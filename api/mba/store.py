"""Firestore access helpers for the MBA feature.

* Clock helpers (UTC timestamps as ISO strings; "days" use India time).
* ``occ_update``: optimistic-concurrency read-modify-write (update-time precondition,
  ``create`` for new docs) so concurrent requests never lose writes.
* ``get_bank``: an in-process, TTL-cached snapshot of the published content
  (exam config, papers, question sets, questions). Content changes only via the
  import scripts and the admin review endpoints (which call ``invalidate_bank``),
  so a short cache keeps request cost low.

Only single-field equality queries are used, so no composite indexes are needed.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, TypeVar
from zoneinfo import ZoneInfo

from google.api_core import exceptions as gexc
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.client import Client as _FirestoreClient

from api.db import SafeFirestore
from api.db.firebase import DB_TIMEOUT

from .schedule import available_from, has_started

EXAMS = "mbaExams"
PAPERS = "mbaPapers"
SETS = "mbaQuestionSets"
QUESTIONS = "mbaQuestions"
ATTEMPTS = "mbaAttempts"
PROFILES = "mbaProfiles"
STATS = "mbaQuestionStats"
AI_USAGE = "mbaAiUsage"

IST = ZoneInfo("Asia/Kolkata")
T = TypeVar("T")


# ---------------------------------------------------------------- clock
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_date(moment: datetime | None = None) -> date:
    """Calendar day in India time (used for daily challenge, quota, streaks)."""
    return (moment or utcnow()).astimezone(IST).date()


def days_later(moment: datetime, days: int) -> datetime:
    return moment + timedelta(days=days)


# ---------------------------------------------------------------- reads
def as_dict(snapshot: Any) -> dict[str, Any] | None:
    if snapshot is None or not getattr(snapshot, "exists", False):
        return None
    data = snapshot.to_dict()
    return data if isinstance(data, dict) else {}


def get_doc(db: SafeFirestore, collection: str, doc_id: str) -> dict[str, Any] | None:
    return as_dict(db.collection(collection).document(doc_id).get(timeout=DB_TIMEOUT))


def query_eq(db: SafeFirestore, collection: str, field_name: str, value: Any) -> list[tuple[str, dict[str, Any]]]:
    query = db.collection(collection).where(filter=FieldFilter(field_name, "==", value))
    return [(snap.id, as_dict(snap) or {}) for snap in query.stream(timeout=DB_TIMEOUT)]


def stream_all(db: SafeFirestore, collection: str) -> list[tuple[str, dict[str, Any]]]:
    return [(snap.id, as_dict(snap) or {}) for snap in db.collection(collection).stream(timeout=DB_TIMEOUT)]


# ---------------------------------------------------------------- writes
class ConcurrentUpdateError(RuntimeError):
    pass


def occ_update(
    db: SafeFirestore,
    collection: str,
    doc_id: str,
    mutate: Callable[[dict[str, Any] | None], tuple[dict[str, Any] | None, T]],
    retries: int = 6,
) -> T:
    """Read the doc, let ``mutate(current)`` return ``(new_fields_or_None, result)``.

    ``None`` means "no write". Existing docs are updated with an update-time
    precondition; missing docs are created with ``create`` (fails if someone else
    created it first). On a conflict the read-modify-write is retried.
    """
    ref = db.collection(collection).document(doc_id)
    for _ in range(retries):
        snapshot = ref.get(timeout=DB_TIMEOUT)
        current = as_dict(snapshot)
        new_fields, result = mutate(None if current is None else dict(current))
        if new_fields is None:
            return result
        try:
            if current is None:
                ref.create(new_fields, timeout=DB_TIMEOUT)
            else:
                option = _FirestoreClient.write_option(last_update_time=snapshot.update_time)
                ref.update(new_fields, option=option, timeout=DB_TIMEOUT)
            return result
        except (gexc.FailedPrecondition, gexc.Conflict, gexc.Aborted):
            continue
    raise ConcurrentUpdateError(f"Too many concurrent updates on {collection}/{doc_id}.")


# ---------------------------------------------------------------- content bank
@dataclass
class Bank:
    exams: dict[str, dict[str, Any]] = field(default_factory=dict)
    papers: dict[str, dict[str, Any]] = field(default_factory=dict)  # published papers
    sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    questions: dict[str, dict[str, Any]] = field(default_factory=dict)  # published only
    loaded_at: float = 0.0
    refresh_at: float | None = None  # epoch seconds when a scheduled paper goes live (reload then)


_bank_lock = threading.Lock()
_bank: Bank | None = None
_bank_db_id: int | None = None


def _bank_ttl() -> float:
    try:
        return float(os.getenv("MBA_BANK_TTL_SECONDS", "300"))
    except ValueError:
        return 300.0


def invalidate_bank() -> None:
    global _bank
    with _bank_lock:
        _bank = None


def _is_published(data: dict[str, Any]) -> bool:
    """Students only ever see content whose status is explicitly "published" (not draft/archived)."""
    return data.get("status") == "published"


def get_bank(db: SafeFirestore) -> Bank:
    global _bank, _bank_db_id
    with _bank_lock:
        fresh = _bank is not None and _bank_db_id == id(db) and time.monotonic() - _bank.loaded_at < _bank_ttl()
        if fresh and (_bank.refresh_at is None or time.time() < _bank.refresh_at):  # type: ignore[union-attr]
            return _bank  # type: ignore[return-value]
    # A published paper scheduled for later (availableFrom, see schedule.py) stays out of the bank until then.
    now = utcnow()
    published = {doc_id: {**data, "id": doc_id} for doc_id, data in stream_all(db, PAPERS) if _is_published(data)}
    papers = {doc_id: paper for doc_id, paper in published.items() if has_started(paper, now)}
    upcoming = [start.timestamp() for paper in published.values() if (start := available_from(paper)) and start > now]
    bank = Bank(
        exams={doc_id: data for doc_id, data in stream_all(db, EXAMS)},
        papers=papers,
        sets={doc_id: {**data, "id": doc_id} for doc_id, data in stream_all(db, SETS)},
        # A question is visible only when it and its paper are published, so a paper still
        # under review never leaks into practice or the daily challenge.
        questions={
            doc_id: {**data, "id": doc_id}
            for doc_id, data in stream_all(db, QUESTIONS)
            if _is_published(data) and (not data.get("paperId") or data["paperId"] in papers)
        },
        loaded_at=time.monotonic(),
        refresh_at=min(upcoming) if upcoming else None,
    )
    with _bank_lock:
        _bank, _bank_db_id = bank, id(db)
    return bank


# ---------------------------------------------------------------- per-user
def stat_id(user_id: str, question_id: str) -> str:
    return f"{user_id}_{question_id}"


def user_stats(db: SafeFirestore, user_id: str) -> dict[str, dict[str, Any]]:
    """questionId -> stats doc for this user."""
    stats: dict[str, dict[str, Any]] = {}
    for _doc_id, data in query_eq(db, STATS, "userId", user_id):
        question_id = data.get("questionId")
        if isinstance(question_id, str):
            stats[question_id] = data
    return stats
