"""Success metrics for the Admin panel: ``GET /api/v1/mba/admin/metrics`` (contract: docs/mba-api.md).

Computes the proposal's success metrics (activation, time-to-value, mock completion,
plan adherence, weekly actives, daily challenge participation, counsellor requests)
from the ``mba*`` collections for an India-time date range. Read-only.

Reads are bounded: every query is a single-field range on the date window (no
composite indexes), projects only the fields used and stops at a per-collection
limit (``truncated`` names any collection that hit it). Results are cached in
process for ``MBA_METRICS_TTL_SECONDS`` (default 300) per range.
"""

from __future__ import annotations

import os
import statistics
import threading
import time
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentAdmin
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .admin_roles import analytics_admin as content_admin  # "analytics" capability (admin_roles.py)
from .counsellor_requests import REQUESTS
from .planner import TASKS
from .questions import daily_question_ids
from .store import ATTEMPTS, IST, PROFILES, STATS, get_bank, iso, local_date, parse_iso, utcnow

router = APIRouter(prefix="/admin")

DEFAULT_DAYS = 28
MAX_DAYS = 92
ACTIVATION_DAYS = 7  # "answered >= 10 questions in the first 7 days"
ACTIVATION_QUESTIONS = 10
# Per-collection read caps (documents, projected fields only).
LIMITS = {PROFILES: 5000, STATS: 40000, ATTEMPTS: 20000, TASKS: 50000, REQUESTS: 5000}
CACHE_MAX = 32
PIPELINE_BUCKET = {"open": "open", "assigned": "assigned", "done": "done", "new": "open", "contacted": "assigned",
                   "in_progress": "assigned", "converted": "done", "closed": "done"}


# ---------------------------------------------------------------- response models
class Activation(BaseModel):
    eligible: int  # onboarded in range and at least 7 days ago
    activated: int  # of those, answered >= 10 distinct questions within 7 days of onboarding
    rate: float | None


class TimeToValue(BaseModel):
    students: int  # onboarded in range who reached the milestone (any time up to now)
    medianDays: float | None
    sameDayRate: float | None  # share of those who reached it on their onboarding day (India time)


class MockKind(BaseModel):
    started: int
    submitted: int
    completionRate: float | None


class Mocks(MockKind):
    byKind: dict[str, MockKind]


class Planner(BaseModel):
    scheduled: int
    done: int
    skipped: int
    adherence: float | None  # done / scheduled


class Active(BaseModel):
    distinctStudents: int
    avgWeekly: float | None  # over the full weeks in range


class DailyChallenge(BaseModel):
    days: int
    avgParticipantsPerDay: float | None
    distinctStudents: int


class CounsellorRequests(BaseModel):
    total: int
    avgPerWeek: float | None
    byStatus: dict[str, int]
    conversionRate: float | None  # done / total


class WeekRow(BaseModel):
    weekStart: str  # Monday (India time), or `from` for a partial first week
    weekEnd: str
    fullWeek: bool
    onboarded: int
    activeStudents: int
    mocksStarted: int
    mocksSubmitted: int
    plannerScheduled: int
    plannerDone: int
    dailyChallengeStudents: int
    counsellorRequests: int
    counsellorRequestsDone: int


class MetricsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    generatedAt: str
    onboarded: int
    activation: Activation
    timeToFirstPractice: TimeToValue
    timeToFirstMock: TimeToValue
    mocks: Mocks
    planner: Planner
    weeklyActive: Active
    dailyChallenge: DailyChallenge
    counsellorRequests: CounsellorRequests
    weeks: list[WeekRow]
    truncated: list[str]  # collections whose read cap was hit (numbers are then a lower bound)


# ---------------------------------------------------------------- helpers
def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, dtime.min, tzinfo=IST)


def _range(
    db: SafeFirestore, collection: str, field: str, low: str, high: str | None, fields: list[str], truncated: list[str]
) -> list[dict[str, Any]]:
    query = db.collection(collection).where(filter=FieldFilter(field, ">=", low))
    if high is not None:
        query = query.where(filter=FieldFilter(field, "<", high))
    limit = LIMITS[collection]
    rows = [snap.to_dict() or {} for snap in query.select(fields).limit(limit).stream(timeout=DB_TIMEOUT)]
    if len(rows) >= limit:
        truncated.append(collection)
    return rows


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _local_day(value: Any) -> date | None:
    moment = parse_iso(value)
    return local_date(moment) if moment else None


def _iso_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _ttv(deltas: list[float]) -> dict[str, Any]:
    if not deltas:
        return {"students": 0, "medianDays": None, "sameDayRate": None}
    return {
        "students": len(deltas),
        "medianDays": round(statistics.median(deltas), 2),
        "sameDayRate": _ratio(sum(1 for d in deltas if d < 1), len(deltas)),
    }


# ---------------------------------------------------------------- computation
def compute_metrics(db: SafeFirestore, start: date, end: date) -> dict[str, Any]:
    """Metrics for India-time days ``start``..``end`` (inclusive)."""
    now = utcnow()
    today = local_date(now)
    low, high = iso(_start_of_day(start)), iso(_start_of_day(end + timedelta(days=1)))
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    in_range = set(days)
    truncated: list[str] = []

    profiles = _range(db, PROFILES, "createdAt", low, high, ["userId", "createdAt"], truncated)
    # Stats answered on/after `from` (lastAnsweredAt >= from covers every answer given in the
    # window and every first-7-days answer of students onboarded in it).
    stats = _range(db, STATS, "lastAnsweredAt", low, None, ["userId", "questionId", "answeredDates", "answeredVia"], truncated)
    # Attempts started on/after `from` (open-ended, so time-to-first-mock sees later starts).
    attempts = _range(db, ATTEMPTS, "startedAt", low, None, ["userId", "kind", "status", "startedAt"], truncated)
    tasks = _range(db, TASKS, "date", start.isoformat(), (end + timedelta(days=1)).isoformat(), ["status", "date"], truncated)
    requests = _range(db, REQUESTS, "createdAt", low, high, ["status", "createdAt"], truncated)

    # Weeks (Monday-based, clipped to the range).
    weeks: dict[date, dict[str, Any]] = {}
    for day in days:
        key = _week_start(day)
        row = weeks.setdefault(key, {
            "weekStart": max(key, start).isoformat(), "weekEnd": min(key + timedelta(days=6), end).isoformat(),
            "fullWeek": key >= start and key + timedelta(days=6) <= end,
            "onboarded": 0, "active": set(), "mocksStarted": 0, "mocksSubmitted": 0, "plannerScheduled": 0,
            "plannerDone": 0, "daily": set(), "counsellorRequests": 0, "counsellorRequestsDone": 0,
        })

    def week(day: date) -> dict[str, Any]:
        return weeks[_week_start(day)]

    # Onboarded cohort.
    cohort: dict[str, date] = {}
    cohort_at: dict[str, datetime] = {}
    for doc in profiles:
        uid, created = doc.get("userId"), parse_iso(doc.get("createdAt"))
        if not isinstance(uid, str) or created is None or local_date(created) not in in_range:
            continue
        cohort[uid], cohort_at[uid] = local_date(created), created
        week(local_date(created))["onboarded"] += 1

    # Answers: weekly actives, daily challenge, activation, first practice day.
    active_all: set[str] = set()
    first_seven: dict[str, int] = defaultdict(int)
    first_practice: dict[str, date] = {}
    by_question: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for doc in stats:
        uid = doc.get("userId")
        if not isinstance(uid, str):
            continue
        answered = [d for raw in doc.get("answeredDates") or [] if (d := _iso_day(raw))]
        for day in answered:
            if day in in_range:
                week(day)["active"].add(uid)
                active_all.add(uid)
        if isinstance(doc.get("questionId"), str):
            by_question[doc["questionId"]].append((uid, doc.get("answeredDates") or []))
        onboarded = cohort.get(uid)
        if onboarded is None:
            continue
        if any(onboarded <= d < onboarded + timedelta(days=ACTIVATION_DAYS) for d in answered):
            first_seven[uid] += 1
        if "practice" in (doc.get("answeredVia") or []):
            after = [d for d in answered if d >= onboarded]
            if after and (uid not in first_practice or min(after) < first_practice[uid]):
                first_practice[uid] = min(after)

    # Daily challenge: the day's (deterministic) question ids answered on that day.
    bank = get_bank(db)
    daily_counts: list[int] = []
    daily_all: set[str] = set()
    for day in days:
        if day > today:
            break
        stamp = day.isoformat()
        people = {uid for qid in daily_question_ids(bank, stamp) for uid, dates in by_question.get(qid, []) if stamp in dates}
        daily_counts.append(len(people))
        daily_all |= people
        week(day)["daily"] |= people

    # Mocks (attempts started in range), plus every student's first attempt for time-to-value.
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"started": 0, "submitted": 0})
    first_mock: dict[str, datetime] = {}
    for doc in attempts:
        uid, started = doc.get("userId"), parse_iso(doc.get("startedAt"))
        if started is None:
            continue
        if isinstance(uid, str) and uid in cohort_at and started >= cohort_at[uid]:
            if uid not in first_mock or started < first_mock[uid]:
                first_mock[uid] = started
        day = local_date(started)
        if day not in in_range:
            continue
        kind = doc.get("kind") if isinstance(doc.get("kind"), str) else "unknown"
        submitted = doc.get("status") == "submitted"
        by_kind[kind]["started"] += 1
        by_kind[kind]["submitted"] += int(submitted)
        week(day)["mocksStarted"] += 1
        week(day)["mocksSubmitted"] += int(submitted)
        if isinstance(uid, str):
            week(day)["active"].add(uid)
            active_all.add(uid)

    # Planner tasks scheduled in range.
    planner = {"scheduled": 0, "done": 0, "skipped": 0}
    for doc in tasks:
        day = _iso_day(doc.get("date"))
        if day not in in_range:
            continue
        planner["scheduled"] += 1
        status = doc.get("status")
        if status in ("done", "skipped"):
            planner[status] += 1
        week(day)["plannerScheduled"] += 1
        week(day)["plannerDone"] += int(status == "done")

    # Counsellor requests raised in range.
    req_status: dict[str, int] = defaultdict(int)
    for doc in requests:
        day = _local_day(doc.get("createdAt"))
        if day not in in_range:
            continue
        # Pipeline statuses (counsellor_requests.py) folded into these buckets: new -> open,
        # contacted / in_progress -> assigned (being worked), converted / closed -> done.
        status = PIPELINE_BUCKET.get(doc.get("status"), "open")
        req_status[status] += 1
        week(day)["counsellorRequests"] += 1
        week(day)["counsellorRequestsDone"] += int(status == "done")

    eligible = [uid for uid, day in cohort.items() if day + timedelta(days=ACTIVATION_DAYS) <= today]
    activated = sum(1 for uid in eligible if first_seven.get(uid, 0) >= ACTIVATION_QUESTIONS)
    started_total = sum(k["started"] for k in by_kind.values())
    submitted_total = sum(k["submitted"] for k in by_kind.values())
    full_weeks = [w for w in weeks.values() if w["fullWeek"]]
    req_total = sum(req_status.values())

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "generatedAt": iso(now),
        "onboarded": len(cohort),
        "activation": {"eligible": len(eligible), "activated": activated, "rate": _ratio(activated, len(eligible))},
        "timeToFirstPractice": _ttv([float((d - cohort[uid]).days) for uid, d in first_practice.items()]),
        "timeToFirstMock": _ttv([(t - cohort_at[uid]).total_seconds() / 86400 for uid, t in first_mock.items()]),
        "mocks": {
            "started": started_total, "submitted": submitted_total, "completionRate": _ratio(submitted_total, started_total),
            "byKind": {k: {**v, "completionRate": _ratio(v["submitted"], v["started"])} for k, v in sorted(by_kind.items())},
        },
        "planner": {**planner, "adherence": _ratio(planner["done"], planner["scheduled"])},
        "weeklyActive": {
            "distinctStudents": len(active_all),
            "avgWeekly": round(sum(len(w["active"]) for w in full_weeks) / len(full_weeks), 1) if full_weeks else None,
        },
        "dailyChallenge": {
            "days": len(daily_counts),
            "avgParticipantsPerDay": round(sum(daily_counts) / len(daily_counts), 1) if daily_counts else None,
            "distinctStudents": len(daily_all),
        },
        "counsellorRequests": {
            "total": req_total,
            "avgPerWeek": round(req_total / (len(days) / 7), 1) if days else None,
            "byStatus": {s: req_status.get(s, 0) for s in ("open", "assigned", "done")},
            "conversionRate": _ratio(req_status.get("done", 0), req_total),
        },
        "weeks": [
            {
                **{k: v for k, v in w.items() if k not in ("active", "daily")},
                "activeStudents": len(w["active"]), "dailyChallengeStudents": len(w["daily"]),
            }
            for _, w in sorted(weeks.items())
        ],
        "truncated": sorted(set(truncated)),
    }


# ---------------------------------------------------------------- cache + route
_cache_lock = threading.Lock()
_cache: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}


def _ttl() -> float:
    try:
        return float(os.getenv("MBA_METRICS_TTL_SECONDS", "300"))
    except ValueError:
        return 300.0


def _parse_day(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"`{name}` must be a date (YYYY-MM-DD).") from None


@router.get("/metrics", response_model=MetricsResponse, response_model_by_alias=True)
def admin_metrics(
    from_: str | None = Query(default=None, alias="from", max_length=10),
    to: str | None = Query(default=None, max_length=10),
    _admin: CurrentAdmin = Depends(content_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    today = local_date()
    end = min(_parse_day(to, "to") or today, today)
    start = _parse_day(from_, "from") or end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise HTTPException(422, "`from` must be on or before `to`.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"The range can be at most {MAX_DAYS} days.")

    key = (id(db), start.isoformat(), end.isoformat())
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _ttl():
            return hit[1]
    result = compute_metrics(db, start, end)
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.monotonic(), result)
    return result
