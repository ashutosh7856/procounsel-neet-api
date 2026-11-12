"""In-app notifications, computed on request from the student's real state (no cron, nothing queued).

Read state lives in ``mbaNotificationState/{userId}``: ``{ userId, lastSeenAt, dismissed: [ids], updatedAt }``.
An item is unread when its ``at`` is after ``lastSeenAt`` (and it is not dismissed). Ids are stable for
as long as the condition lasts (day-scoped items get a new id each India-time day).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import user_attempts
from .deps import student
from .planner import _week_tasks, exam_date_for, parse_day, week_start_of
from .profile import load_profile
from .shortlist import known_institutes
from .stats import is_due
from .store import IST, get_bank, get_doc, iso, local_date, occ_update, parse_iso, user_stats, utcnow

router = APIRouter()

STATE = "mbaNotificationState"
SHORTLISTS = "mbaShortlists"
MILESTONES = (30, 14, 7, 1)
DEADLINE_WINDOW_DAYS = 7
NEW_MOCK_WINDOW_DAYS = 14
MAX_DISMISSED = 200

Kind = Literal["plan_today", "plan_overdue", "mistakes_due", "resume_mock", "cat_countdown", "shortlist_deadline", "new_mock"]


class Notification(BaseModel):
    id: str
    kind: Kind
    title: str
    detail: str
    href: str
    at: str
    unread: bool


class NotificationsResponse(BaseModel):
    items: list[Notification]
    unreadCount: int
    lastSeenAt: str | None


class SeenInput(BaseModel):
    model_config = {"extra": "forbid"}
    dismissIds: list[str] = Field(default_factory=list, max_length=50)


class SeenResponse(BaseModel):
    lastSeenAt: str
    dismissed: int


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _countdown(exam: date, today: date, source: str | None) -> dict[str, Any] | None:
    days_left = (exam - today).days
    if days_left < 0:
        return None
    if days_left == 0:
        return {"id": f"cat-{exam.isoformat()}-0", "kind": "cat_countdown", "title": "CAT is today",
                "detail": "All the best. Read every question fully and keep an eye on the section timer.",
                "href": "/mba/dashboard", "at": _day_start(exam)}
    milestone = next((m for m in sorted(MILESTONES) if days_left <= m), None)
    if milestone is None:
        return None
    whose = "" if source == "profile" else " (official date)"
    return {"id": f"cat-{exam.isoformat()}-{milestone}", "kind": "cat_countdown",
            "title": f"{_plural(days_left, 'day')} to CAT",
            "detail": f"CAT is on {exam.strftime('%d %b %Y')}{whose}. Your study plan paces the mocks for the final weeks.",
            "href": "/mba/planner", "at": _day_start(exam - timedelta(days=milestone))}


def compute(db: SafeFirestore, user: CurrentUser) -> list[dict[str, Any]]:
    bank = get_bank(db)
    now = utcnow()
    today = local_date(now)
    today_start = _day_start(today)
    items: list[dict[str, Any]] = []

    attempts = user_attempts(db, bank, user)
    live = next((a for a in attempts if a.get("status") == "in_progress"), None)
    if live:
        items.append({"id": f"resume-{live['id']}", "kind": "resume_mock", "title": f"Resume {live.get('title') or 'your mock'}",
                      "detail": "Your mock is still running; the timer keeps going on the server.",
                      "href": f"/mba/mocks/attempts/{live['id']}", "at": parse_iso(live.get("startedAt")) or today_start})

    # Plan: today's open tasks, and open tasks from earlier days of this week.
    week = week_start_of(today)
    tasks = [t for _, t, _ in _week_tasks(db, user.user_id, week)]
    open_today = [t for t in tasks if t.get("status") == "pending" and t.get("date") == today.isoformat()]
    earlier = [t for t in tasks if t.get("status") == "pending" and (parse_day(t.get("date")) or today) < today]
    if open_today:
        minutes = sum(int(t.get("minutes") or 0) for t in open_today)
        items.append({"id": f"plan-today-{today.isoformat()}", "kind": "plan_today",
                      "title": f"{_plural(len(open_today), 'task')} on today's plan",
                      "detail": f"About {minutes} min. First up: {open_today[0].get('title') or 'study task'}.",
                      "href": "/mba/planner", "at": today_start})
    if earlier:
        items.append({"id": f"plan-earlier-{today.isoformat()}", "kind": "plan_overdue",
                      "title": f"{_plural(len(earlier), 'task')} from earlier this week still open",
                      "detail": "Do them, move them to another day, or skip them. The plan adapts.",
                      "href": "/mba/planner", "at": today_start})

    due = sum(1 for s in user_stats(db, user.user_id).values() if is_due(s, now))
    if due:
        items.append({"id": f"mistakes-{today.isoformat()}", "kind": "mistakes_due", "title": f"{_plural(due, 'mistake')} due for review",
                      "detail": "Spaced review: retry them while they're fresh.", "href": "/mba/mistakes?due=true", "at": today_start})

    exam, source = exam_date_for(load_profile(db, user.user_id))
    if exam:
        countdown = _countdown(exam, today, source)
        if countdown:
            items.append(countdown)

    shortlist = (get_doc(db, SHORTLISTS, user.user_id) or {}).get("items")
    institutes = known_institutes(db) if isinstance(shortlist, dict) and shortlist else {}
    for slug, entry in (shortlist.items() if isinstance(shortlist, dict) else []):
        if not isinstance(entry, dict) or entry.get("status") in ("declined", "offer"):
            continue
        deadline = parse_day(entry.get("deadline"))
        if deadline is None or not 0 <= (deadline - today).days <= DEADLINE_WINDOW_DAYS:
            continue
        inst = institutes.get(slug)
        name = (inst.shortName or inst.name) if inst else slug.replace("-", " ").title()
        left = (deadline - today).days
        when = "today" if left == 0 else ("tomorrow" if left == 1 else f"in {left} days")
        created = parse_iso(entry.get("createdAt")) or today_start
        items.append({"id": f"deadline-{slug}-{deadline.isoformat()}", "kind": "shortlist_deadline",
                      "title": f"{name} deadline {when}", "detail": f"Application deadline {deadline.strftime('%d %b %Y')} on your shortlist.",
                      "href": "/mba/shortlist", "at": max(created, _day_start(deadline - timedelta(days=DEADLINE_WINDOW_DAYS)))})

    attempted_papers = {a.get("paperId") for a in attempts}
    for paper_id, paper in bank.papers.items():
        published = parse_iso(paper.get("publishedAt"))
        if not published or published > now or now - published > timedelta(days=NEW_MOCK_WINDOW_DAYS) or paper_id in attempted_papers:
            continue
        title = paper.get("title") if isinstance(paper.get("title"), str) and paper["title"].strip() else "A new mock"
        items.append({"id": f"new-mock-{paper_id}", "kind": "new_mock", "title": f"New mock: {title.strip()}",
                      "detail": "Full mock and sectionals are ready in Mock Tests.", "href": "/mba/mocks", "at": published})
    return items


def _state(db: SafeFirestore, user_id: str) -> tuple[datetime | None, set[str]]:
    doc = get_doc(db, STATE, user_id) or {}
    dismissed = {d for d in doc.get("dismissed") or [] if isinstance(d, str)}
    return parse_iso(doc.get("lastSeenAt")), dismissed


@router.get("/me/notifications", response_model=NotificationsResponse)
def get_notifications(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    last_seen, dismissed = _state(db, user.user_id)
    rows = []
    for item in compute(db, user):
        if item["id"] in dismissed:
            continue
        at: datetime = item["at"]
        rows.append({**item, "at": iso(at), "unread": last_seen is None or at > last_seen, "_sort": at})
    rows.sort(key=lambda r: (not r["unread"], -r["_sort"].timestamp()))
    for r in rows:
        r.pop("_sort")
    return {"items": rows, "unreadCount": sum(1 for r in rows if r["unread"]), "lastSeenAt": iso(last_seen) if last_seen else None}


@router.patch("/me/notifications/seen", response_model=SeenResponse)
def mark_seen(body: SeenInput | None = Body(default=None), user: CurrentUser = Depends(student),
              db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    stamp = iso(utcnow())
    ids = [i for i in (body.dismissIds if body else []) if isinstance(i, str) and 0 < len(i) <= 200]

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        dismissed = [d for d in (current or {}).get("dismissed") or [] if isinstance(d, str)]
        for i in ids:
            if i not in dismissed:
                dismissed.append(i)
        dismissed = dismissed[-MAX_DISMISSED:]
        doc = {"userId": user.user_id, "lastSeenAt": stamp, "dismissed": dismissed, "updatedAt": stamp}
        return doc, {"lastSeenAt": stamp, "dismissed": len(dismissed)}

    return occ_update(db, STATE, user.user_id, mutate)
