"""Help centre tickets and MBA events (contract: docs/mba-api.md → "Community: doubts, study groups, events, help").

* ``mbaSupportTickets/{id}`` — a student's ticket: ``{ userId, studentName, phoneNumber, category, subject, attemptId,
  questionId, status, messages: [{by, authorName, text, at}], createdAt, updatedAt, lastStudentAt, lastSupportAt }``.
  Status: ``open`` (waiting for support) → ``answered`` (support replied) → ``closed``. A student message reopens it.
  Private between the student and support, so contact details are allowed in tickets (unlike doubts).
* ``mbaEvents/{id}`` — admin-managed doubt hours and webinars (the Java live sessions have no exam tag, so they can't
  be filtered for MBA): ``{ title, description, kind, startsAt, endsAt, link, host, exams, status, createdBy, ... }``.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .admin_roles import require_mba, support_admin
from .community import consume, faculty_name, text_problem
from .counsellor_requests import _student_name
from .deps import student
from .models import EXAM_IDS
from .profile import load_profile
from .store import ATTEMPTS, get_bank, get_doc, iso, occ_update, parse_iso, query_eq, stream_all, utcnow

router = APIRouter()

TICKETS = "mbaSupportTickets"
EVENTS = "mbaEvents"
MAX_MESSAGES = 60
NOTIFY_WINDOW_DAYS = 30
EVENT_PAST_HOURS = 2          # an event stays listed this long after it ends
EVENT_AHEAD_DAYS = 90

TicketCategory = Literal["account", "mocks", "questions", "technical", "data", "feedback", "other"]
TicketStatus = Literal["open", "answered", "closed"]
EventKind = Literal["doubt_hour", "webinar"]
EventStatus = Literal["scheduled", "cancelled"]
_CATEGORIES = ("account", "mocks", "questions", "technical", "data", "feedback", "other")
_STATUSES = ("open", "answered", "closed")

events_admin = require_mba("content", "support")  # faculty host doubt hours, support runs webinars


# ---------------------------------------------------------------- models
class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: TicketCategory
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=10, max_length=3000)
    attemptId: str | None = Field(default=None, max_length=200)
    questionId: str | None = Field(default=None, max_length=300)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3000)


class StudentTicketPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["closed"]


class AdminMessageInput(MessageInput):
    status: TicketStatus | None = None  # default after a support reply: "answered"


class AdminTicketPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TicketStatus


class TicketMessage(BaseModel):
    by: Literal["student", "support"]
    authorName: str
    text: str
    at: str


class Ticket(BaseModel):
    id: str
    category: TicketCategory
    subject: str
    status: TicketStatus
    attemptId: str | None
    questionId: str | None
    messages: list[TicketMessage]
    createdAt: str
    updatedAt: str


class TicketsResponse(BaseModel):
    tickets: list[Ticket]


class AdminTicket(Ticket):
    userId: str | None
    studentName: str | None
    phoneNumber: str | None


class TicketCounts(BaseModel):
    open: int
    answered: int
    closed: int


class AdminTicketsResponse(BaseModel):
    tickets: list[AdminTicket]
    counts: TicketCounts


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    kind: EventKind
    startsAt: str = Field(max_length=40)
    endsAt: str = Field(max_length=40)
    link: str | None = Field(default=None, max_length=500)
    host: str | None = Field(default=None, max_length=80)
    exams: list[str] = Field(default_factory=list, max_length=len(EXAM_IDS))  # [] = every MBA student
    status: EventStatus = "scheduled"

    @field_validator("exams")
    @classmethod
    def _exams(cls, value: list[str]) -> list[str]:
        if any(e not in EXAM_IDS for e in value):
            raise ValueError(f"exams must be among {list(EXAM_IDS)}.")
        return [e for e in EXAM_IDS if e in value]

    @field_validator("link")
    @classmethod
    def _link(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if not re.match(r"^https://[^\s/$.?#][^\s]*$", value):
            raise ValueError("link must be an https:// URL.")
        return value


class Event(BaseModel):
    id: str
    title: str
    description: str | None
    kind: EventKind
    startsAt: str
    endsAt: str
    link: str | None
    host: str | None
    exams: list[str]
    status: EventStatus


class EventsResponse(BaseModel):
    events: list[Event]


class AdminEvent(Event):
    createdBy: str | None
    createdAt: str
    updatedAt: str


class AdminEventsResponse(BaseModel):
    events: list[AdminEvent]


# ---------------------------------------------------------------- tickets: helpers
def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").replace("\r\n", "\n")).strip()
    if not text:
        raise HTTPException(422, "Write a message.")
    problem = text_problem(text, allow_links=True)  # abuse only; contact details are fine in a private ticket
    if problem:
        raise HTTPException(422, problem)
    return text


def _messages(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"by": "support" if m.get("by") == "support" else "student", "authorName": str(m.get("authorName") or ""),
         "text": str(m.get("text") or ""), "at": str(m.get("at") or "")}
        for m in doc.get("messages") or [] if isinstance(m, dict)
    ]


def _ticket(doc_id: str, doc: dict[str, Any], admin: bool = False) -> dict[str, Any]:
    out = {
        "id": doc_id, "category": doc.get("category") if doc.get("category") in _CATEGORIES else "other",
        "subject": str(doc.get("subject") or ""), "status": doc.get("status") if doc.get("status") in _STATUSES else "open",
        "attemptId": _str(doc.get("attemptId")), "questionId": _str(doc.get("questionId")), "messages": _messages(doc),
        "createdAt": str(doc.get("createdAt") or ""), "updatedAt": str(doc.get("updatedAt") or ""),
    }
    if admin:
        out.update({"userId": _str(doc.get("userId")), "studentName": _str(doc.get("studentName")),
                    "phoneNumber": _str(doc.get("phoneNumber"))})
    return out


def _own(db: SafeFirestore, user: CurrentUser, ticket_id: str) -> dict[str, Any]:
    doc = get_doc(db, TICKETS, ticket_id)
    if doc is None or doc.get("userId") != user.user_id:
        raise HTTPException(404, "Ticket not found.")
    return doc


# ---------------------------------------------------------------- tickets: student
@router.get("/me/tickets", response_model=TicketsResponse)
def my_tickets(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    rows = [_ticket(i, d) for i, d in query_eq(db, TICKETS, "userId", user.user_id)]
    rows.sort(key=lambda t: t["updatedAt"], reverse=True)
    return {"tickets": rows}


@router.post("/me/tickets", response_model=Ticket, status_code=201)
def create_ticket(body: TicketInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    subject = _clean(body.subject)
    message = _clean(body.message)
    attempt_id = _str(body.attemptId)
    question_id = _str(body.questionId)
    if attempt_id and (get_doc(db, ATTEMPTS, attempt_id) or {}).get("userId") != user.user_id:
        raise HTTPException(422, "That mock attempt was not found in your account.")
    if question_id and question_id not in get_bank(db).questions:
        raise HTTPException(422, "That question was not found.")
    consume(db, user.user_id, "tickets")
    stamp = iso(utcnow())
    name = _student_name(user)
    doc = {
        "userId": user.user_id, "studentName": name, "phoneNumber": user.phone_number or None,
        "category": body.category, "subject": subject, "attemptId": attempt_id, "questionId": question_id, "status": "open",
        "messages": [{"by": "student", "authorName": name or "You", "text": message, "at": stamp}],
        "createdAt": stamp, "updatedAt": stamp, "lastStudentAt": stamp, "lastSupportAt": None,
    }
    doc_id = uuid.uuid4().hex
    db.collection(TICKETS).document(doc_id).create(doc, timeout=DB_TIMEOUT)
    return _ticket(doc_id, doc)


@router.get("/me/tickets/{ticket_id}", response_model=Ticket)
def my_ticket(ticket_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _ticket(ticket_id, _own(db, user, ticket_id))


@router.post("/me/tickets/{ticket_id}/messages", response_model=Ticket)
def student_message(ticket_id: str, body: MessageInput, user: CurrentUser = Depends(student),
                    db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _own(db, user, ticket_id)
    text = _clean(body.text)
    consume(db, user.user_id, "ticketMessages")

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None or current.get("userId") != user.user_id:
            raise HTTPException(404, "Ticket not found.")
        messages = [m for m in current.get("messages") or [] if isinstance(m, dict)]
        if len(messages) >= MAX_MESSAGES:
            raise HTTPException(409, "This ticket is very long. Please raise a new one.")
        stamp = iso(utcnow())
        messages.append({"by": "student", "authorName": _str(current.get("studentName")) or "You", "text": text, "at": stamp})
        fields = {"messages": messages, "status": "open", "updatedAt": stamp, "lastStudentAt": stamp}
        return fields, {**current, **fields}

    return _ticket(ticket_id, occ_update(db, TICKETS, ticket_id, mutate))


@router.patch("/me/tickets/{ticket_id}", response_model=Ticket)
def close_ticket(ticket_id: str, body: StudentTicketPatch, user: CurrentUser = Depends(student),
                 db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _own(db, user, ticket_id)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None or current.get("userId") != user.user_id:
            raise HTTPException(404, "Ticket not found.")
        if current.get("status") == body.status:
            return None, current
        fields = {"status": body.status, "updatedAt": iso(utcnow()), "closedBy": "student"}
        return fields, {**current, **fields}

    return _ticket(ticket_id, occ_update(db, TICKETS, ticket_id, mutate))


def student_notifications(db: SafeFirestore, user_id: str) -> list[dict[str, Any]]:
    """In-app notifications (api/mba/notifications.py): the latest support reply on each ticket (last 30 days)."""
    items = []
    cutoff = utcnow() - timedelta(days=NOTIFY_WINDOW_DAYS)
    for doc_id, doc in query_eq(db, TICKETS, "userId", user_id):
        at = parse_iso(doc.get("lastSupportAt"))
        if at is None or at < cutoff:
            continue
        subject = str(doc.get("subject") or "your ticket")
        items.append({"id": f"ticket-{doc_id}-{re.sub(r'[^0-9]', '', doc['lastSupportAt'])}", "kind": "support_reply",
                      "title": "Support replied to your ticket", "detail": subject[:100],
                      "href": f"/mba/help?ticket={doc_id}", "at": at})
    return items


# ---------------------------------------------------------------- tickets: admin
@router.get("/admin/support/tickets", response_model=AdminTicketsResponse)
def admin_tickets(
    status: TicketStatus | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    _admin: CurrentAdmin = Depends(support_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    rows = [_ticket(i, d, admin=True) for i, d in stream_all(db, TICKETS)]
    needle = (q or "").strip().casefold()
    if category:
        rows = [r for r in rows if r["category"] == category]
    if needle:
        rows = [r for r in rows if any(needle in (r[k] or "").casefold() for k in ("subject", "studentName", "phoneNumber", "id"))]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in _STATUSES}
    rows = [r for r in rows if status is None or r["status"] == status]
    rows.sort(key=lambda r: r["updatedAt"], reverse=True)
    rows.sort(key=lambda r: _STATUSES.index(r["status"]))  # waiting on support first
    return {"tickets": rows, "counts": counts}


@router.get("/admin/support/tickets/{ticket_id}", response_model=AdminTicket)
def admin_ticket(ticket_id: str, _admin: CurrentAdmin = Depends(support_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    doc = get_doc(db, TICKETS, ticket_id)
    if doc is None:
        raise HTTPException(404, "Ticket not found.")
    return _ticket(ticket_id, doc, admin=True)


@router.post("/admin/support/tickets/{ticket_id}/messages", response_model=AdminTicket)
def admin_message(ticket_id: str, body: AdminMessageInput, admin: CurrentAdmin = Depends(support_admin),
                  db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    text = _clean(body.text)
    first = faculty_name(admin)
    name = "ProCounsel support" if first == "ProCounsel faculty" else f"{first} · ProCounsel support"

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Ticket not found.")
        messages = [m for m in current.get("messages") or [] if isinstance(m, dict)]
        stamp = iso(utcnow())
        messages.append({"by": "support", "authorName": name, "adminId": admin.admin_id, "text": text, "at": stamp})
        fields = {"messages": messages, "status": body.status or "answered", "updatedAt": stamp, "lastSupportAt": stamp}
        return fields, {**current, **fields}

    return _ticket(ticket_id, occ_update(db, TICKETS, ticket_id, mutate), admin=True)


@router.patch("/admin/support/tickets/{ticket_id}", response_model=AdminTicket)
def admin_patch_ticket(ticket_id: str, body: AdminTicketPatch, admin: CurrentAdmin = Depends(support_admin),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Ticket not found.")
        if current.get("status") == body.status:
            return None, current
        fields = {"status": body.status, "updatedAt": iso(utcnow()), "closedBy": admin.admin_id if body.status == "closed" else None}
        return fields, {**current, **fields}

    return _ticket(ticket_id, occ_update(db, TICKETS, ticket_id, mutate), admin=True)


# ---------------------------------------------------------------- events
def _event(doc_id: str, doc: dict[str, Any], admin: bool = False) -> dict[str, Any]:
    out = {
        "id": doc_id, "title": str(doc.get("title") or ""), "description": _str(doc.get("description")),
        "kind": "webinar" if doc.get("kind") == "webinar" else "doubt_hour",
        "startsAt": str(doc.get("startsAt") or ""), "endsAt": str(doc.get("endsAt") or ""),
        "link": _str(doc.get("link")), "host": _str(doc.get("host")),
        "exams": [e for e in doc.get("exams") or [] if e in EXAM_IDS],
        "status": "cancelled" if doc.get("status") == "cancelled" else "scheduled",
    }
    if admin:
        out.update({"createdBy": _str(doc.get("createdBy")), "createdAt": str(doc.get("createdAt") or ""),
                    "updatedAt": str(doc.get("updatedAt") or "")})
    return out


def _event_fields(body: EventInput) -> dict[str, Any]:
    starts, ends = parse_iso(body.startsAt), parse_iso(body.endsAt)
    if starts is None or ends is None or "T" not in body.startsAt or "T" not in body.endsAt:
        raise HTTPException(422, "startsAt and endsAt must be ISO date-times with a time zone (e.g. 2026-11-20T18:30:00+05:30).")
    if ends <= starts or ends - starts > timedelta(hours=12):
        raise HTTPException(422, "endsAt must be after startsAt, at most 12 hours later.")
    return {"title": body.title.strip(), "description": _str(body.description), "kind": body.kind, "startsAt": iso(starts),
            "endsAt": iso(ends), "link": body.link, "host": _str(body.host), "exams": body.exams, "status": body.status}


@router.get("/events", response_model=EventsResponse)
def list_events(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Upcoming (and just-ended) doubt hours and webinars for the student's target exams, soonest first."""
    now = utcnow()
    profile = load_profile(db, user.user_id) or {}
    targets = set(profile.get("targetExams") or ["cat"])
    rows = []
    for doc_id, doc in stream_all(db, EVENTS):
        event = _event(doc_id, doc)
        starts, ends = parse_iso(event["startsAt"]), parse_iso(event["endsAt"])
        if starts is None or ends is None or ends < now - timedelta(hours=EVENT_PAST_HOURS) or starts > now + timedelta(days=EVENT_AHEAD_DAYS):
            continue
        if event["exams"] and not targets & set(event["exams"]):
            continue
        rows.append(event)
    rows.sort(key=lambda e: e["startsAt"])
    return {"events": rows[:50]}


@router.get("/admin/events", response_model=AdminEventsResponse)
def admin_events(
    include_past: bool = Query(default=False, alias="includePast"),
    _admin: CurrentAdmin = Depends(events_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    cutoff = iso(utcnow() - timedelta(days=1))
    rows = [_event(i, d, admin=True) for i, d in stream_all(db, EVENTS)]
    rows = [r for r in rows if include_past or r["endsAt"] >= cutoff]
    rows.sort(key=lambda e: e["startsAt"], reverse=include_past)
    return {"events": rows}


@router.post("/admin/events", response_model=AdminEvent, status_code=201)
def admin_create_event(body: EventInput, admin: CurrentAdmin = Depends(events_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    stamp = iso(utcnow())
    doc = {**_event_fields(body), "createdBy": admin.admin_id, "createdAt": stamp, "updatedAt": stamp}
    doc_id = uuid.uuid4().hex
    db.collection(EVENTS).document(doc_id).create(doc, timeout=DB_TIMEOUT)
    return _event(doc_id, doc, admin=True)


@router.put("/admin/events/{event_id}", response_model=AdminEvent)
def admin_update_event(event_id: str, body: EventInput, admin: CurrentAdmin = Depends(events_admin),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    fields = _event_fields(body)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Event not found.")
        update = {**fields, "updatedAt": iso(utcnow()), "updatedBy": admin.admin_id}
        return update, {**current, **update}

    return _event(event_id, occ_update(db, EVENTS, event_id, mutate), admin=True)


@router.delete("/admin/events/{event_id}", status_code=204)
def admin_delete_event(event_id: str, _admin: CurrentAdmin = Depends(events_admin), db: SafeFirestore = Depends(get_db)) -> None:
    """Removes an event entirely (to tell students it is off, set ``status: "cancelled"`` instead)."""
    if get_doc(db, EVENTS, event_id) is None:
        raise HTTPException(404, "Event not found.")
    db.collection(EVENTS).document(event_id).delete(timeout=DB_TIMEOUT)
