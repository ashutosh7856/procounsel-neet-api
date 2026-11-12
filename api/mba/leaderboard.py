"""Opt-in daily challenge leaderboard (contract: docs/mba-api.md → "Daily leaderboard").

* ``mbaLeaderboardPrefs/{userId}`` — ``{optedIn, displayName}``. Nobody appears until they opt in.
* ``mbaDailyResults/{date}_{userId}`` — the day's daily-challenge results of an opted-in student:
  ``answers: {questionId: correct}``. The FIRST result seen for a question that day is kept, so
  re-answering never improves a rank. Results are recorded from ``mbaQuestionStats`` for the
  current India-time day only (when the board is read), because the daily set is derived from
  the live question bank.

Ranking: daily = accuracy, then how many of the day's questions were answered (participation).
Weekly = days active in the last 7, then improvement in accuracy vs the 7 days before, then accuracy.
Never by volume or study hours. Responses never contain userIds or phone numbers.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .deps import student
from .questions import daily_question_ids
from .store import STATS, get_bank, get_doc, iso, local_date, occ_update, parse_iso, query_eq, user_stats, utcnow

router = APIRouter()

PREFS = "mbaLeaderboardPrefs"
RESULTS = "mbaDailyResults"
TOP_N = 20
HISTORY_DAYS = 30
BOARD_TTL_SECONDS = 60.0
NAME_MAX = 24

# Deliberately short and simple: whole words in this list are dropped from display names.
_BLOCKED = frozenset({
    "fuck", "fucker", "fucking", "shit", "bitch", "bastard", "asshole", "dick", "cunt", "slut", "whore", "porn",
    "sex", "nigger", "nigga", "chutiya", "chutia", "madarchod", "behenchod", "bhenchod", "bhosdike", "gandu",
    "randi", "lund", "lavda", "loda", "harami", "kamina", "mc", "bc",
})


class PrefsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    optedIn: bool
    displayName: str | None = Field(default=None, max_length=60)


class Prefs(BaseModel):
    optedIn: bool
    displayName: str
    suggestedName: str


class DailyEntry(BaseModel):
    rank: int
    displayName: str
    answered: int
    correct: int
    accuracy: float
    isYou: bool


class DailyBoard(BaseModel):
    date: str
    questionCount: int
    participants: int
    optedIn: bool
    entries: list[DailyEntry]
    you: DailyEntry | None
    rule: str


class WeeklyEntry(BaseModel):
    rank: int
    displayName: str
    daysActive: int
    answered: int
    accuracy: float
    previousAccuracy: float | None
    improvement: float | None
    isYou: bool


class WeeklyBoard(BaseModel):
    weekStart: str
    weekEnd: str
    participants: int
    optedIn: bool
    entries: list[WeeklyEntry]
    you: WeeklyEntry | None
    rule: str


# ---------------------------------------------------------------- names
def clean_name(raw: str | None) -> str:
    """Letters, digits, spaces and . - ' only; blocked words dropped; ≤24 chars. May return ''."""
    text = re.sub(r"[^\w .'\-]", " ", raw or "", flags=re.UNICODE).replace("_", " ")
    words = [w for w in text.split() if re.sub(r"[^a-z]", "", w.lower()) not in _BLOCKED]
    return " ".join(words)[:NAME_MAX].strip()


def suggested_name(user: CurrentUser) -> str:
    profile = user.profile or {}
    first = clean_name(str(profile.get("firstName") or "")).split(" ")[0] if profile.get("firstName") else ""
    last = clean_name(str(profile.get("lastName") or ""))
    name = f"{first} {last[0].upper()}." if first and last else first
    return name or "CAT aspirant"


def _prefs(db: SafeFirestore, user: CurrentUser) -> dict[str, Any]:
    doc = get_doc(db, PREFS, user.user_id) or {}
    suggestion = suggested_name(user)
    return {"optedIn": doc.get("optedIn") is True, "displayName": clean_name(doc.get("displayName")) or suggestion,
            "suggestedName": suggestion}


@router.get("/me/leaderboard", response_model=Prefs)
def get_prefs(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _prefs(db, user)


@router.put("/me/leaderboard", response_model=Prefs)
def put_prefs(body: PrefsInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    name = clean_name(body.displayName) if body.displayName is not None else None
    if body.displayName is not None and len(name or "") < 2:
        raise HTTPException(422, "Choose a display name of at least 2 letters or digits.")
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], None]:
        doc = {"userId": user.user_id, "optedIn": body.optedIn, "updatedAt": now,
               "displayName": name or clean_name((current or {}).get("displayName")) or suggested_name(user)}
        if current is None:
            doc["createdAt"] = now
        return doc, None

    occ_update(db, PREFS, user.user_id, mutate)
    _cache_clear()
    if body.optedIn:
        _sync_user(db, user.user_id)
    return _prefs(db, user)


# ---------------------------------------------------------------- results
def _opted(db: SafeFirestore) -> dict[str, str]:
    """userId -> display name of every opted-in student."""
    out = {}
    for doc_id, doc in query_eq(db, PREFS, "optedIn", True):
        uid = str(doc.get("userId") or doc_id)
        out[uid] = clean_name(doc.get("displayName")) or "CAT aspirant"
    return out


def _day_answers(stat: dict[str, Any], day: str) -> bool | None:
    """The stat's correctness for ``day`` if its last answer was given that day, else None."""
    if day not in (stat.get("answeredDates") or []):
        return None
    moment = parse_iso(stat.get("lastAnsweredAt"))
    if moment is None or local_date(moment).isoformat() != day or not isinstance(stat.get("lastCorrect"), bool):
        return None
    return stat["lastCorrect"]


def _record(db: SafeFirestore, day: str, found: dict[str, dict[str, bool]], existing: dict[str, dict[str, Any]]) -> None:
    """Merge newly seen answers into mbaDailyResults (first result per question wins)."""
    batch, pending = db.batch(), 0
    now = iso(utcnow())
    for uid, answers in found.items():
        current = existing.get(uid) or {}
        kept = {k: v for k, v in (current.get("answers") or {}).items() if isinstance(v, bool)}
        merged = {**answers, **kept}
        if merged == kept:
            continue
        doc = {"date": day, "userId": uid, "answers": merged, "answered": len(merged),
               "correct": sum(1 for v in merged.values() if v), "createdAt": current.get("createdAt") or now, "updatedAt": now}
        batch.set(db.collection(RESULTS).document(f"{day}_{uid}"), doc)
        existing[uid] = doc
        pending += 1
    if pending:
        batch.commit(timeout=DB_TIMEOUT)


def _existing(db: SafeFirestore, day: str) -> dict[str, dict[str, Any]]:
    return {str(d.get("userId")): d for _, d in query_eq(db, RESULTS, "date", day) if d.get("userId")}


def _sync_today(db: SafeFirestore, opted: dict[str, str]) -> None:
    day = local_date().isoformat()
    ids = daily_question_ids(get_bank(db), day)
    found: dict[str, dict[str, bool]] = {}
    for qid in ids:
        for _, stat in query_eq(db, STATS, "questionId", qid):
            uid = stat.get("userId")
            if uid in opted and (correct := _day_answers(stat, day)) is not None:
                found.setdefault(uid, {})[qid] = correct
    if found:
        _record(db, day, found, _existing(db, day))


def _sync_user(db: SafeFirestore, user_id: str) -> None:
    day = local_date().isoformat()
    ids = set(daily_question_ids(get_bank(db), day))
    stats = user_stats(db, user_id)
    answers = {qid: c for qid in ids if (c := _day_answers(stats.get(qid) or {}, day)) is not None}
    if answers:
        current = get_doc(db, RESULTS, f"{day}_{user_id}")
        _record(db, day, {user_id: answers}, {user_id: current} if current else {})


# ---------------------------------------------------------------- boards (cached briefly per instance)
_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, int], tuple[float, Any]] = {}


def _cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


def _cached(key: tuple[str, str], db: SafeFirestore, build: Any) -> Any:
    full = (*key, id(db))
    with _cache_lock:
        hit = _cache.get(full)
        if hit and time.monotonic() - hit[0] < BOARD_TTL_SECONDS:
            return hit[1]
    value = build()
    with _cache_lock:
        _cache[full] = (time.monotonic(), value)
    return value


def _rank(rows: list[dict[str, Any]], key: Any) -> list[dict[str, Any]]:
    """Competition ranking (1, 1, 3) on ``key``; ties keep a stable name order."""
    rows.sort(key=lambda r: r["displayName"].lower())
    rows.sort(key=key)
    previous, rank = None, 0
    for i, row in enumerate(rows, start=1):
        k = key(row)
        if k != previous:
            rank, previous = i, k
        row["rank"] = rank
    return rows


def _day(value: str | None) -> date:
    today = local_date()
    if not value:
        return today
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(422, "date must be YYYY-MM-DD.") from error
    if day > today or day < today - timedelta(days=HISTORY_DAYS):
        raise HTTPException(422, f"date must be within the last {HISTORY_DAYS} days.")
    return day


def _public(rows: list[dict[str, Any]], user_id: str, fields: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    def out(row: dict[str, Any]) -> dict[str, Any]:
        return {**{f: row[f] for f in fields}, "isYou": row["userId"] == user_id}

    you = next((out(r) for r in rows if r["userId"] == user_id), None)
    return [out(r) for r in rows[:TOP_N]], you


DAILY_FIELDS = ("rank", "displayName", "answered", "correct", "accuracy")
WEEKLY_FIELDS = ("rank", "displayName", "daysActive", "answered", "accuracy", "previousAccuracy", "improvement")


@router.get("/leaderboard/daily", response_model=DailyBoard)
def daily_board(
    date_: str | None = Query(default=None, alias="date", max_length=10),
    user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    day = _day(date_)
    today = day == local_date()
    prefs = _prefs(db, user)
    if today and prefs["optedIn"]:
        _sync_user(db, user.user_id)

    def build() -> list[dict[str, Any]]:
        opted = _opted(db)
        if today:
            _sync_today(db, opted)
        rows = []
        for uid, doc in _existing(db, day.isoformat()).items():
            answered = int(doc.get("answered") or 0)
            if uid not in opted or answered <= 0:
                continue
            correct = int(doc.get("correct") or 0)
            rows.append({"userId": uid, "displayName": opted[uid], "answered": answered, "correct": correct,
                         "accuracy": round(correct / answered, 4)})
        return _rank(rows, lambda r: (-r["accuracy"], -r["answered"]))

    if today and prefs["optedIn"]:
        _cache_clear()  # the student's own result was just recorded
    rows = _cached(("daily", day.isoformat()), db, build)
    entries, you = _public(rows, user.user_id, DAILY_FIELDS)
    return {
        "date": day.isoformat(),
        "questionCount": len(daily_question_ids(get_bank(db), day.isoformat())) if today else max((r["answered"] for r in rows), default=0),
        "participants": len(rows), "optedIn": prefs["optedIn"], "entries": entries, "you": you,
        "rule": "Ranked by accuracy on the day's challenge (first answer to each question counts), then by how many of the day's questions were answered.",
    }


@router.get("/leaderboard/weekly", response_model=WeeklyBoard)
def weekly_board(
    date_: str | None = Query(default=None, alias="date", max_length=10),
    user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    end = _day(date_)
    start = end - timedelta(days=6)
    prefs = _prefs(db, user)
    if end == local_date() and prefs["optedIn"]:
        _sync_user(db, user.user_id)
        _cache_clear()

    def build() -> list[dict[str, Any]]:
        opted = _opted(db)
        if end == local_date():
            _sync_today(db, opted)
        week: dict[str, dict[str, int]] = {}
        prev: dict[str, dict[str, int]] = {}
        for offset in range(14):
            day = end - timedelta(days=offset)
            bucket = week if offset < 7 else prev
            for uid, doc in _existing(db, day.isoformat()).items():
                answered = int(doc.get("answered") or 0)
                if uid not in opted or answered <= 0:
                    continue
                row = bucket.setdefault(uid, {"days": 0, "answered": 0, "correct": 0})
                row["days"] += 1
                row["answered"] += answered
                row["correct"] += int(doc.get("correct") or 0)
        rows = []
        for uid, w in week.items():
            acc = round(w["correct"] / w["answered"], 4)
            p = prev.get(uid)
            prev_acc = round(p["correct"] / p["answered"], 4) if p else None
            rows.append({"userId": uid, "displayName": opted[uid], "daysActive": w["days"], "answered": w["answered"],
                         "accuracy": acc, "previousAccuracy": prev_acc,
                         "improvement": round(acc - prev_acc, 4) if prev_acc is not None else None})
        return _rank(rows, lambda r: (-r["daysActive"], -(r["improvement"] if r["improvement"] is not None else -9), -r["accuracy"]))

    rows = _cached(("weekly", end.isoformat()), db, build)
    entries, you = _public(rows, user.user_id, WEEKLY_FIELDS)
    return {
        "weekStart": start.isoformat(), "weekEnd": end.isoformat(), "participants": len(rows), "optedIn": prefs["optedIn"],
        "entries": entries, "you": you,
        "rule": "Ranked by days you took the daily challenge this week, then by how much your accuracy improved on the week before, then by accuracy.",
    }
