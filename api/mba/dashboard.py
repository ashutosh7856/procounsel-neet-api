"""Student dashboard aggregated from mbaQuestionStats + mbaAttempts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import summary, user_attempts
from .deps import student
from .models import SECTION_IDS, Dashboard
from .profile import load_profile
from .questions import daily_question_ids
from .stats import has_answered, is_due
from .store import get_bank, local_date, parse_iso, user_stats, utcnow

router = APIRouter()

WEAK_SECTION_MIN_ATTEMPTED = 5
WEAK_SECTION_ACCURACY = 0.6
SECTION_NAMES = {"VARC": "Verbal Ability & Reading Comprehension", "DILR": "Data Interpretation & Logical Reasoning", "QA": "Quantitative Ability"}


def streak(active_days: set[str], today: date) -> dict[str, Any]:
    """Consecutive active days ending today (or yesterday, if today isn't done yet)."""
    if not active_days:
        return {"current": 0, "lastActiveDate": None}
    last = max(active_days)
    day = today if today.isoformat() in active_days else today - timedelta(days=1)
    current = 0
    while day.isoformat() in active_days:
        current += 1
        day -= timedelta(days=1)
    return {"current": current, "lastActiveDate": last}


@router.get("/me/dashboard", response_model=Dashboard)
def dashboard(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    now = utcnow()
    today = local_date(now)
    profile = load_profile(db, user.user_id)
    stats = user_stats(db, user.user_id)
    attempts = user_attempts(db, bank, user)

    days_to_exam = None
    if profile and profile.get("examDate"):
        days_to_exam = max(0, (date.fromisoformat(profile["examDate"]) - today).days)

    # Per section: distinct questions answered, and how many of those were last answered correctly.
    sections = []
    for section_id in SECTION_IDS:
        answered = [s for s in stats.values() if s.get("section") == section_id and has_answered(s)]
        correct = sum(1 for s in answered if s.get("lastCorrect") is True)
        sections.append({
            "id": section_id,
            "attempted": len(answered),
            "correct": correct,
            "accuracy": round(correct / len(answered), 4) if answered else None,
        })

    submitted = [a for a in attempts if a.get("status") == "submitted"]
    in_progress = next((a for a in attempts if a.get("status") == "in_progress"), None)
    mistakes_due = sum(1 for s in stats.values() if is_due(s, now))
    totals = {
        "questionsAttempted": sum(1 for s in stats.values() if has_answered(s)),
        "correct": sum(1 for s in stats.values() if has_answered(s) and s.get("lastCorrect") is True),
        "bookmarked": sum(1 for s in stats.values() if s.get("bookmarked")),
        "mistakesDue": mistakes_due,
        "mocksCompleted": len(submitted),
    }

    active_days: set[str] = set()
    for s in stats.values():
        active_days.update(d for d in s.get("answeredDates") or [] if isinstance(d, str))
    for a in attempts:
        for key in ("startedAt", "submittedAt"):
            moment = parse_iso(a.get(key))
            if moment:
                active_days.add(local_date(moment).isoformat())

    priorities: list[dict[str, str]] = []
    if in_progress:
        priorities.append({
            "kind": "resume_mock", "title": f"Resume {in_progress.get('title') or 'your mock'}",
            "detail": "Your timer is running on the server.", "href": f"/mba/mocks/attempts/{in_progress['id']}",
        })
    if not submitted and not in_progress:
        priorities.append({
            "kind": "take_diagnostic", "title": "Take a diagnostic mock",
            "detail": "One full past CAT paper shows where you stand in each section.", "href": "/mba/mocks",
        })
    if mistakes_due:
        priorities.append({
            "kind": "review_mistakes", "title": f"Review {mistakes_due} mistake{'s' if mistakes_due != 1 else ''}",
            "detail": "Spaced review of questions you got wrong.", "href": "/mba/mistakes?due=true",
        })
    weak = [s for s in sections if s["attempted"] >= WEAK_SECTION_MIN_ATTEMPTED and (s["accuracy"] or 0) < WEAK_SECTION_ACCURACY]
    if weak:
        worst = min(weak, key=lambda s: s["accuracy"] or 0)
        priorities.append({
            "kind": "practice_weak_section", "title": f"Practise {worst['id']}",
            "detail": f"{SECTION_NAMES[worst['id']]} accuracy is {round((worst['accuracy'] or 0) * 100)}% over {worst['attempted']} questions.",
            "href": f"/mba/practice?section={worst['id']}",
        })
    daily_ids = daily_question_ids(bank, today.isoformat())
    daily_done = sum(1 for qid in daily_ids if today.isoformat() in ((stats.get(qid) or {}).get("answeredDates") or []))
    if daily_ids and daily_done < len(daily_ids):
        priorities.append({
            "kind": "daily_challenge", "title": "Today's challenge",
            "detail": f"{daily_done} of {len(daily_ids)} questions done.", "href": "/mba/daily",
        })

    return {
        "profile": profile,
        "daysToExam": days_to_exam,
        "sections": sections,
        "totals": totals,
        "recentAttempts": [summary(a) for a in attempts[:5]],
        "inProgressAttempt": summary(in_progress) if in_progress else None,
        "priorities": priorities[:3],
        "streak": streak(active_days, today),
    }
