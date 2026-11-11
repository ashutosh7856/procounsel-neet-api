"""Per-student question stats (``mbaQuestionStats/{userId}_{questionId}``).

One doc per (student, question) holds practice history, the bookmark flag and the
mistake-review state. Pure functions here; callers do the writes.

Mistake schedule: a wrong answer (practice or submitted mock) makes the question a
mistake due again in 1 day. Each later answer is a retry: a correct retry moves it
along the 1 → 3 → 7 → 14 day ladder; the 4th correct retry in a row clears it; a
wrong retry puts it back to 1 day.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .store import days_later, iso, local_date, parse_iso

REVIEW_SCHEDULE_DAYS = (1, 3, 7, 14)
MAX_ACTIVITY_DATES = 60


def new_stat(user_id: str, question: dict[str, Any]) -> dict[str, Any]:
    return {
        "userId": user_id,
        "questionId": str(question.get("id")),
        "section": question.get("section"),
        "paperId": question.get("paperId"),
        "attempts": 0,
        "correct": 0,
        "bookmarked": False,
        "isMistake": False,
        "retries": 0,
        "reviewStep": 0,
    }


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def apply_answer(
    stat: dict[str, Any] | None,
    user_id: str,
    question: dict[str, Any],
    answer: str,
    correct: bool,
    now: datetime,
    via: str,
) -> dict[str, Any]:
    """Return the full updated stats doc after one answered question."""
    doc = {**new_stat(user_id, question), **(stat or {})}
    doc["attempts"] = _int(doc.get("attempts")) + 1
    doc["correct"] = _int(doc.get("correct")) + (1 if correct else 0)
    doc["lastAnswer"] = answer
    doc["lastCorrect"] = correct
    doc["lastAnsweredAt"] = iso(now)
    doc["answeredVia"] = sorted({*(doc.get("answeredVia") or []), via})
    today = local_date(now).isoformat()
    dates = [d for d in doc.get("answeredDates") or [] if isinstance(d, str)]
    if today not in dates:
        dates.append(today)
    doc["answeredDates"] = sorted(dates)[-MAX_ACTIVITY_DATES:]

    was_mistake = bool(doc.get("isMistake"))
    if not correct:
        if was_mistake:
            doc["retries"] = _int(doc.get("retries")) + 1
        else:
            doc["isMistake"] = True
            doc["retries"] = 0
            doc["mistakeAt"] = iso(now)
        doc["reviewStep"] = 0
        doc["nextReviewAt"] = iso(days_later(now, REVIEW_SCHEDULE_DAYS[0]))
    elif was_mistake:
        doc["retries"] = _int(doc.get("retries")) + 1
        step = _int(doc.get("reviewStep")) + 1
        doc["reviewStep"] = step
        if step >= len(REVIEW_SCHEDULE_DAYS):
            doc["isMistake"] = False
            doc["nextReviewAt"] = None
            doc["resolvedAt"] = iso(now)
        else:
            doc["nextReviewAt"] = iso(days_later(now, REVIEW_SCHEDULE_DAYS[step]))
    doc["updatedAt"] = iso(now)
    return doc


def has_answered(stat: dict[str, Any] | None) -> bool:
    return bool(stat) and _int(stat.get("attempts")) > 0


def is_due(stat: dict[str, Any], now: datetime) -> bool:
    if not stat.get("isMistake"):
        return False
    due_at = parse_iso(stat.get("nextReviewAt"))
    return due_at is None or due_at <= now
