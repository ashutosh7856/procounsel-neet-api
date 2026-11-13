"""Score distribution per test, for the "ProCounsel percentile" (contract: docs/mba-api.md → "PYQs").

``mbaTestScoreStats/{testId}`` holds a histogram of every student's FIRST submitted attempt of
that test: ``{testId, paperId, count, scores: {"<int score>": n}, updatedAt}``. It is updated once,
right after an attempt is submitted (``attempts.transition``), so reading a percentile is one
small doc read — no scan over attempts. The counted attempt is marked ``scoreStatsCounted``
so the student's own score can be left out when they are compared with the others.

This is a student's standing among ProCounsel students who took the same test. It is NOT an
official CAT percentile; there is no official mapping and none is ever shown.
"""

from __future__ import annotations

import logging
from typing import Any

from api.db import SafeFirestore

from .store import ATTEMPTS, get_doc, iso, occ_update, query_eq, stream_all, utcnow

log = logging.getLogger(__name__)

SCORE_STATS = "mbaTestScoreStats"
MIN_OTHER_STUDENTS = 20
PERCENTILE_NOTE = (
    "Your standing among ProCounsel students' first attempts of this test. "
    "It is not your official CAT percentile."
)


def score_key(score: Any) -> str:
    try:
        return str(int(round(float(score))))
    except (TypeError, ValueError):
        return "0"


def record_first_score(db: SafeFirestore, att: dict[str, Any]) -> bool:
    """Add a just-submitted attempt to its test's histogram if it is the student's first one of that test.

    Returns True when it was counted. Best effort: a failure is logged and never fails the submit.
    """
    try:
        test_id, user_id = att.get("testId"), att.get("userId")
        if not isinstance(test_id, str) or not test_id or not isinstance(user_id, str):
            return False
        earlier = [
            doc_id for doc_id, data in query_eq(db, ATTEMPTS, "userId", user_id)
            if data.get("testId") == test_id and data.get("status") == "submitted" and doc_id != att.get("id")
        ]
        if earlier:
            return False
        key = score_key((att.get("result") or {}).get("score"))
        now = iso(utcnow())

        def bump(current: dict[str, Any] | None) -> tuple[dict[str, Any], None]:
            scores = {k: int(v) for k, v in ((current or {}).get("scores") or {}).items() if isinstance(v, int)}
            scores[key] = scores.get(key, 0) + 1
            return {"testId": test_id, "paperId": att.get("paperId"), "count": sum(scores.values()),
                    "scores": scores, "updatedAt": now}, None

        occ_update(db, SCORE_STATS, test_id, bump)
        db.collection(ATTEMPTS).document(att["id"]).update({"scoreStatsCounted": True})
        return True
    except Exception:  # noqa: BLE001 - the percentile is a nice-to-have; the submit already succeeded
        log.exception("mba score stats: could not record attempt %s", att.get("id"))
        return False


def percentile(stats: dict[str, Any] | None, score: Any, own_counted: Any = None) -> dict[str, Any]:
    """Where ``score`` stands among other students' first attempts (mid-rank percentile, 0–100).

    ``own_counted``: the student's own score already in the histogram (left out), or None.
    """
    scores: dict[str, int] = {}
    for key, value in ((stats or {}).get("scores") or {}).items():
        if isinstance(value, int) and value > 0:
            scores[key] = value
    if own_counted is not None:
        own = score_key(own_counted)
        if scores.get(own, 0) > 0:
            scores[own] -= 1
    others = sum(scores.values())
    value = float(score or 0)
    result: dict[str, Any] = {"percentile": None, "students": others, "minStudents": MIN_OTHER_STUDENTS,
                              "score": value, "basis": "first_attempt", "note": PERCENTILE_NOTE}
    if others >= MIN_OTHER_STUDENTS:
        mine = int(score_key(value))
        below = sum(n for k, n in scores.items() if int(k) < mine)
        equal = scores.get(str(mine), 0)
        result["percentile"] = round(100 * (below + 0.5 * equal) / others, 1)
    return result


def own_counted_score(attempts: list[dict[str, Any]], test_id: str) -> Any:
    """The student's score that is in the test's histogram (their counted first attempt), or None."""
    for att in attempts:
        if att.get("testId") == test_id and att.get("scoreStatsCounted") and att.get("status") == "submitted":
            return (att.get("result") or {}).get("score")
    return None


def test_stats(db: SafeFirestore, test_id: str) -> dict[str, Any] | None:
    return get_doc(db, SCORE_STATS, test_id)


def all_test_stats(db: SafeFirestore) -> dict[str, dict[str, Any]]:
    """Every test's histogram (one small doc per test, so this grows with tests, not students)."""
    return dict(stream_all(db, SCORE_STATS))
