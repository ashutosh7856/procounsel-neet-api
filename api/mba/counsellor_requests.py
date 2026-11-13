"""Talk-to-my-counsellor: student requests (MBA leads) and the Admin-panel pipeline (contract: docs/mba-api.md).

Collection ``mbaCounsellorRequests/{id}`` (one doc per request):
``{ userId, studentName, phoneNumber, email, topic, preferredTime, preferredSlots, note, slug, status, counsellorId, counsellorName,
closeReason, nextFollowUpAt, shareWithCounsellor, shareUpdatedAt, notes[], history[], createdAt, updatedAt,
assignedAt, statusChangedAt, closedAt, updatedBy }``.

Pipeline: new -> contacted -> in_progress -> converted | closed (closed needs a reason). Counsellors are the Java
``counsellors`` collection, read-only here; a request stores the counsellor's id plus a name snapshot for the student.
Legacy docs (status open/assigned/done, free-text ``assignedTo``, single ``adminNote``) are mapped on read.

Students create and read their own requests and choose whether the counsellor may see their MBA profile, shortlist
and mock summary (``shareWithCounsellor``); admins (same roles as MBA content review) see that data only when shared.
Assignment and status changes reach the student as in-app notifications (``student_notifications``).
Topic ``mock_interview`` = "book a mock interview with a counsellor": it carries 1-3 ``preferredSlots``
(``{date, time: morning|afternoon|evening}``, India time). Application documents are shared per document by the student
(``mbaApplicationDocs.shareWithCounsellor``, doc_store.py); the admin detail lists only those, with signed download links.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from . import doc_store
from .admin_roles import support_admin as content_admin  # MBA "support" capability (admin_roles.py)
from .deps import student
from .profile import load_profile
from .program_models import SLUG_RE
from .store import ATTEMPTS, get_doc, iso, local_date, occ_update, parse_iso, query_eq, stream_all, utcnow

router = APIRouter()

REQUESTS = "mbaCounsellorRequests"
COUNSELLORS = "counsellors"  # Java-owned, read-only
SHORTLISTS = "mbaShortlists"
MAX_ACTIVE = 3  # requests not yet converted/closed a student may have at once
HISTORY_LIMIT = 50
NOTES_LIMIT = 200
NOTIFY_WINDOW_DAYS = 30
COUNSELLOR_CACHE_SECONDS = 300.0
COUNSELLOR_FIELDS = ("firstName", "lastName", "phoneNumber", "email", "verified", "organisationName", "photoUrlSmall")

Topic = Literal["shortlisting", "applications", "wat-pi", "mock_interview", "other"]
SlotTime = Literal["morning", "afternoon", "evening"]  # India time: 9-12, 12-4, 4-8
RequestStatus = Literal["new", "contacted", "in_progress", "converted", "closed"]
TOPICS = ("shortlisting", "applications", "wat-pi", "mock_interview", "other")
MAX_SLOTS = 3
SLOT_DAYS_AHEAD = 60
STATUSES = ("new", "contacted", "in_progress", "converted", "closed")
TERMINAL = ("converted", "closed")
LEGACY_STATUS = {"open": "new", "assigned": "new", "done": "closed"}
TOPIC_LABEL = {"shortlisting": "Shortlisting colleges", "applications": "Applications & documents",
               "wat-pi": "WAT / GD / PI prep", "mock_interview": "Mock interview", "other": "Something else"}
STATUS_LABEL = {"new": "New", "contacted": "Contacted", "in_progress": "In progress", "converted": "Converted",
                "closed": "Closed"}
# What the student is told when the request moves to a status (shown in their timeline + a notification).
STUDENT_STATUS_TEXT = {"new": "Your request was reopened", "contacted": "Your counsellor reached out to you",
                       "in_progress": "Your counsellor is working on your request",
                       "converted": "Your request is complete", "closed": "Your request was closed"}
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- models
def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class PreferredSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str  # YYYY-MM-DD, today .. +60 days (India time)
    time: SlotTime

    @field_validator("date")
    @classmethod
    def _day(cls, value: str) -> str:
        if not DAY_RE.match(value):
            raise ValueError("date must be YYYY-MM-DD")
        day = date.fromisoformat(value)
        today = local_date()
        if not today <= day <= today + timedelta(days=SLOT_DAYS_AHEAD):
            raise ValueError(f"pick a date in the next {SLOT_DAYS_AHEAD} days")
        return value


class CounsellorRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Topic
    preferredTime: str | None = Field(default=None, max_length=120)
    preferredSlots: list[PreferredSlot] | None = Field(default=None, max_length=MAX_SLOTS)  # mock_interview only
    note: str | None = Field(default=None, max_length=1000)
    slug: str | None = None  # optional institute the request is about
    shareWithCounsellor: bool = False

    @field_validator("preferredTime", "note")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        value = _clean(value)
        if value is not None and not SLUG_RE.match(value):
            raise ValueError("invalid institute slug")
        return value


class StudentRequestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareWithCounsellor: bool


class TimelineEntry(BaseModel):
    at: str
    text: str


class SlotOut(BaseModel):
    date: str
    time: SlotTime


class CounsellorRequest(BaseModel):
    id: str
    topic: Topic
    preferredTime: str | None
    preferredSlots: list[SlotOut]  # mock_interview: 1-3 preferred slots; else empty
    note: str | None
    slug: str | None
    status: RequestStatus
    counsellorName: str | None
    shareWithCounsellor: bool
    createdAt: str
    updatedAt: str
    assignedAt: str | None
    closedAt: str | None  # converted or closed
    timeline: list[TimelineEntry]  # oldest first; student-facing events only


class CounsellorRequestsResponse(BaseModel):
    requests: list[CounsellorRequest]


class RequestHistory(BaseModel):
    at: str
    by: str
    summary: str


class FollowUpNote(BaseModel):
    id: str
    at: str
    by: str  # admin email
    text: str


class AssignedCounsellor(BaseModel):
    id: str | None  # None for a legacy free-text assignment
    name: str
    phoneNumber: str | None
    email: str | None


class AdminCounsellorRequest(CounsellorRequest):
    userId: str
    studentName: str | None
    phoneNumber: str | None
    email: str | None
    counsellor: AssignedCounsellor | None
    closeReason: str | None
    nextFollowUpAt: str | None  # YYYY-MM-DD
    overdue: bool  # follow-up date before today (India time) on an open request
    notes: list[FollowUpNote]  # newest first
    updatedBy: str | None
    history: list[RequestHistory]


class SharedProfile(BaseModel):
    targetExam: str
    examDate: str | None
    targetPercentile: float | None
    currentLevel: str
    weeklyStudyHours: float
    targetPrograms: list[str] | None


class SharedShortlistItem(BaseModel):
    slug: str
    status: str
    deadline: str | None


class SharedSection(BaseModel):
    id: str
    score: float | None
    maxScore: float | None
    accuracy: float | None


class SharedMock(BaseModel):
    title: str
    submittedAt: str | None
    score: float | None
    maxScore: float | None
    sections: list[SharedSection]


class SharedStudentData(BaseModel):
    profile: SharedProfile | None
    shortlist: list[SharedShortlistItem]
    mocksSubmitted: int
    recentMocks: list[SharedMock]  # newest first, up to 5


class SharedDocument(BaseModel):
    id: str
    slug: str
    institute: str | None  # short name, when the institute is still listed
    itemId: str
    itemLabel: str
    fileName: str
    contentType: str
    size: int
    uploadedAt: str | None


class AdminCounsellorRequestDetail(AdminCounsellorRequest):
    shared: SharedStudentData | None  # None unless the student chose to share
    sharedDocuments: list[SharedDocument]  # application documents the student shared, each by its own toggle


class DownloadLink(BaseModel):
    url: str
    expiresAt: str


class CounsellorLoad(BaseModel):
    counsellorId: str | None  # None = legacy free-text assignee
    name: str
    active: int  # not converted / closed
    overdue: int
    total: int


class AdminCounsellorRequestsResponse(BaseModel):
    requests: list[AdminCounsellorRequest]
    counts: dict[str, int]  # per status over all requests (ignores filters)
    overdue: int  # over all requests
    unassigned: int  # open requests without a counsellor, over all requests
    byCounsellor: list[CounsellorLoad]  # over all requests, most active first


class AdminRequestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RequestStatus | None = None
    closeReason: str | None = Field(default=None, max_length=300)
    counsellorId: str | None = Field(default=None, max_length=128)
    nextFollowUpAt: str | None = None

    @field_validator("closeReason", "counsellorId")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("nextFollowUpAt")
    @classmethod
    def _day(cls, value: str | None) -> str | None:
        value = _clean(value)
        if value is not None:
            if not DAY_RE.match(value):
                raise ValueError("nextFollowUpAt must be YYYY-MM-DD")
            date.fromisoformat(value)  # raises ValueError -> 422
        return value


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note is empty")
        return value


class CounsellorOption(BaseModel):
    id: str
    name: str
    phoneNumber: str | None
    email: str | None
    organisationName: str | None
    photoUrl: str | None
    verified: bool


class CounsellorsResponse(BaseModel):
    counsellors: list[CounsellorOption]
    total: int  # matching the search, before the limit


# ---------------------------------------------------------------- counsellors (Java collection, read-only)
_counsellor_lock = threading.Lock()
_counsellor_cache: tuple[int, float, dict[str, dict[str, Any]]] | None = None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _counsellor_option(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(p for p in (_str(data.get("firstName")), _str(data.get("lastName"))) if p)
    return {
        "id": doc_id,
        "name": name or _str(data.get("email")) or _str(data.get("phoneNumber")) or doc_id,
        "phoneNumber": _str(data.get("phoneNumber")),
        "email": _str(data.get("email")),
        "organisationName": _str(data.get("organisationName")),
        "photoUrl": _str(data.get("photoUrlSmall")),
        "verified": data.get("verified") is True,
    }


def counsellor_directory(db: SafeFirestore) -> dict[str, dict[str, Any]]:
    """id -> CounsellorOption for every doc in ``counsellors`` (only the fields we need; cached briefly)."""
    global _counsellor_cache
    with _counsellor_lock:
        cache = _counsellor_cache
        if cache is not None and cache[0] == id(db) and time.monotonic() - cache[1] < COUNSELLOR_CACHE_SECONDS:
            return cache[2]
    query = db.collection(COUNSELLORS).select(list(COUNSELLOR_FIELDS))
    found = {snap.id: _counsellor_option(snap.id, snap.to_dict() or {}) for snap in query.stream(timeout=DB_TIMEOUT)}
    with _counsellor_lock:
        _counsellor_cache = (id(db), time.monotonic(), found)
    return found


def _lookup_counsellor(db: SafeFirestore, counsellor_id: str) -> dict[str, Any] | None:
    if "/" in counsellor_id:
        return None
    cached = counsellor_directory(db).get(counsellor_id)
    if cached is not None:
        return cached
    data = get_doc(db, COUNSELLORS, counsellor_id)  # newer than the cache
    return _counsellor_option(counsellor_id, data) if data is not None else None


# ---------------------------------------------------------------- shaping
def _status(data: dict[str, Any]) -> str:
    raw = data.get("status")
    return raw if raw in STATUSES else LEGACY_STATUS.get(raw, "new")


def _history(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("history") if isinstance(data.get("history"), list) else []
    return [h for h in raw if isinstance(h, dict) and all(isinstance(h.get(k), str) for k in ("at", "by", "summary"))]


def _timeline(data: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for h in _history(data):
        text = h.get("studentText")
        if isinstance(text, str) and text:
            out.append({"at": h["at"], "text": text})
        elif h["by"] == "student" and h["summary"] == "Request created":  # legacy creation entry
            out.append({"at": h["at"], "text": "You asked for a call"})
    return out


def _counsellor_name(data: dict[str, Any]) -> str | None:
    return _str(data.get("counsellorName")) or _str(data.get("assignedTo"))


def _slots(raw: Any) -> list[dict[str, str]]:
    return [{"date": s["date"], "time": s["time"]} for s in (raw if isinstance(raw, list) else [])
            if isinstance(s, dict) and isinstance(s.get("date"), str) and DAY_RE.match(s["date"])
            and s.get("time") in ("morning", "afternoon", "evening")][:MAX_SLOTS]


def _public(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    created = _str(data.get("createdAt")) or ""
    return {
        "id": doc_id,
        "topic": data.get("topic") if data.get("topic") in TOPICS else "other",
        "preferredTime": _str(data.get("preferredTime")),
        "preferredSlots": _slots(data.get("preferredSlots")),
        "note": _str(data.get("note")),
        "slug": _str(data.get("slug")),
        "status": _status(data),
        "counsellorName": _counsellor_name(data),
        "shareWithCounsellor": data.get("shareWithCounsellor") is True,
        "createdAt": created,
        "updatedAt": _str(data.get("updatedAt")) or created,
        "assignedAt": _str(data.get("assignedAt")),
        "closedAt": _str(data.get("closedAt")) or _str(data.get("doneAt")),
        "timeline": _timeline(data),
    }


def _notes(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("notes") if isinstance(data.get("notes"), list) else []
    notes = [{"id": n["id"], "at": n["at"], "by": n["by"], "text": n["text"]} for n in raw
             if isinstance(n, dict) and all(isinstance(n.get(k), str) for k in ("id", "at", "by", "text"))]
    legacy = _str(data.get("adminNote"))
    if legacy and not notes:
        notes.append({"id": "legacy", "at": _str(data.get("updatedAt")) or _str(data.get("createdAt")) or "",
                      "by": _str(data.get("updatedBy")) or "admin", "text": legacy})
    return sorted(notes, key=lambda n: n["at"], reverse=True)


def _is_overdue(status: str, follow_up: str | None, today: date) -> bool:
    if status in TERMINAL or not follow_up:
        return False
    try:
        return date.fromisoformat(follow_up) < today
    except ValueError:
        return False


def _admin_view(doc_id: str, data: dict[str, Any], directory: dict[str, dict[str, Any]], today: date) -> dict[str, Any]:
    view = _public(doc_id, data)
    counsellor_id = _str(data.get("counsellorId"))
    counsellor = None
    if counsellor_id:
        live = directory.get(counsellor_id) or {}
        counsellor = {"id": counsellor_id, "name": view["counsellorName"] or live.get("name") or counsellor_id,
                      "phoneNumber": live.get("phoneNumber"), "email": live.get("email")}
    elif view["counsellorName"]:
        counsellor = {"id": None, "name": view["counsellorName"], "phoneNumber": None, "email": None}
    follow_up = _str(data.get("nextFollowUpAt"))
    return {
        **view,
        "userId": _str(data.get("userId")) or "",
        "studentName": _str(data.get("studentName")),
        "phoneNumber": _str(data.get("phoneNumber")),
        "email": _str(data.get("email")),
        "counsellor": counsellor,
        "closeReason": _str(data.get("closeReason")),
        "nextFollowUpAt": follow_up,
        "overdue": _is_overdue(view["status"], follow_up, today),
        "notes": _notes(data),
        "updatedBy": _str(data.get("updatedBy")),
        "history": [{"at": h["at"], "by": h["by"], "summary": h["summary"]} for h in _history(data)],
    }


def _student_name(user: CurrentUser) -> str | None:
    profile = user.profile or {}
    parts = [_str(profile.get(k)) for k in ("firstName", "lastName")]
    name = " ".join(p for p in parts if p)
    return name or _str(profile.get("name")) or _str(profile.get("fullName"))


def _newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["createdAt"], r["id"]), reverse=True)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def shared_data(db: SafeFirestore, user_id: str) -> dict[str, Any]:
    """What a student who opted in shares with their counsellor: profile, shortlist, mock summary (read-only)."""
    profile = load_profile(db, user_id)
    items = (get_doc(db, SHORTLISTS, user_id) or {}).get("items")
    shortlist = [
        {"slug": slug, "status": entry.get("status") if isinstance(entry.get("status"), str) else "interested",
         "deadline": _str(entry.get("deadline"))}
        for slug, entry in (items.items() if isinstance(items, dict) else []) if isinstance(entry, dict)
    ]
    shortlist.sort(key=lambda i: (i["deadline"] is None, i["deadline"] or "", i["slug"]))
    submitted = [a for _id, a in query_eq(db, ATTEMPTS, "userId", user_id) if a.get("status") == "submitted"]
    submitted.sort(key=lambda a: str(a.get("submittedAt") or ""), reverse=True)
    recent = []
    for att in submitted[:5]:
        result = att.get("result") if isinstance(att.get("result"), dict) else {}
        sections = [
            {"id": str(s.get("id")), "score": _num(s.get("score")), "maxScore": _num(s.get("maxScore")),
             "accuracy": _num(s.get("accuracy"))}
            for s in result.get("sections") or [] if isinstance(s, dict) and s.get("id")
        ]
        recent.append({"title": _str(att.get("title")) or "Mock", "submittedAt": _str(att.get("submittedAt")),
                       "score": _num(result.get("score")), "maxScore": _num(result.get("maxScore")), "sections": sections})
    return {
        "profile": {k: profile.get(k) for k in SharedProfile.model_fields} if profile else None,
        "shortlist": shortlist,
        "mocksSubmitted": len(submitted),
        "recentMocks": recent,
    }


def _detail(db: SafeFirestore, doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    view = _admin_view(doc_id, data, counsellor_directory(db), local_date())
    shared = shared_data(db, view["userId"]) if view["shareWithCounsellor"] and view["userId"] else None
    documents = []
    if view["userId"]:
        from .shortlist import known_institutes  # local import: shortlist -> doc_store, keeps imports one-way

        institutes = known_institutes(db)
        for d in doc_store.shared_docs(db, view["userId"]):
            inst = institutes.get(d["slug"])
            documents.append({"id": d["id"], "slug": d["slug"], "institute": (inst.shortName or inst.name) if inst else None,
                              "itemId": d["itemId"], "itemLabel": d["itemLabel"], "fileName": d["fileName"],
                              "contentType": d["contentType"], "size": d["size"], "uploadedAt": d["uploadedAt"]})
    return {**view, "shared": shared, "sharedDocuments": documents}


def _check_id(request_id: str) -> None:
    if "/" in request_id or not request_id.strip():
        raise HTTPException(404, "Request not found.")


def _with_history(current: dict[str, Any], changes: dict[str, Any], who: str, now: str, summary: str,
                  student_text: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"at": now, "by": who, "summary": summary}
    if student_text:
        entry["studentText"] = student_text
    return {**changes, "updatedAt": now, "updatedBy": who,
            "history": (_history(current) + [entry])[-HISTORY_LIMIT:]}


# ---------------------------------------------------------------- student
@router.post("/me/counsellor-requests", response_model=CounsellorRequest, status_code=201)
def create_request(body: CounsellorRequestInput, user: CurrentUser = Depends(student),
                   db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    if body.topic == "mock_interview" and not body.preferredSlots:
        raise HTTPException(422, "Pick at least one preferred slot for the mock interview.")
    if body.topic != "mock_interview" and body.preferredSlots:
        raise HTTPException(422, "Preferred slots are only for mock interview requests.")
    slots = sorted({(s.date, s.time) for s in body.preferredSlots or []},
                   key=lambda s: (s[0], ("morning", "afternoon", "evening").index(s[1])))
    mine = query_eq(db, REQUESTS, "userId", user.user_id)
    active = sum(1 for _id, data in mine if _status(data) not in TERMINAL)
    if active >= MAX_ACTIVE:
        raise HTTPException(409, f"You already have {active} open requests. A counsellor will reach out soon.")
    now = iso(utcnow())
    doc_id = uuid.uuid4().hex
    data = {
        "userId": user.user_id,
        "studentName": _student_name(user),
        "phoneNumber": user.phone_number or None,
        "email": _str((user.profile or {}).get("email")),
        "topic": body.topic,
        "preferredTime": body.preferredTime,
        "preferredSlots": [{"date": d, "time": t} for d, t in slots],
        "note": body.note,
        "slug": body.slug,
        "status": "new",
        "counsellorId": None,
        "counsellorName": None,
        "closeReason": None,
        "nextFollowUpAt": None,
        "shareWithCounsellor": body.shareWithCounsellor,
        "shareUpdatedAt": now,
        "notes": [],
        "createdAt": now,
        "updatedAt": now,
        "assignedAt": None,
        "statusChangedAt": now,
        "closedAt": None,
        "updatedBy": None,
        "history": [{"at": now, "by": "student", "summary": "Request created",
                     "studentText": "You asked for a mock interview" if body.topic == "mock_interview" else "You asked for a call"}],
    }
    db.collection(REQUESTS).document(doc_id).create(data, timeout=DB_TIMEOUT)
    return _public(doc_id, data)


@router.get("/me/counsellor-requests", response_model=CounsellorRequestsResponse)
def list_my_requests(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    rows = [_public(doc_id, data) for doc_id, data in query_eq(db, REQUESTS, "userId", user.user_id)]
    return {"requests": _newest_first(rows)}


@router.patch("/me/counsellor-requests/{request_id}", response_model=CounsellorRequest)
def update_my_request(request_id: str, body: StudentRequestPatch, user: CurrentUser = Depends(student),
                      db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_id(request_id)
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None or current.get("userId") != user.user_id:
            raise HTTPException(404, "Request not found.")
        if (current.get("shareWithCounsellor") is True) == body.shareWithCounsellor:
            return None, _public(request_id, current)
        text = ("You shared your MBA profile, shortlist and mock scores with your counsellor"
                if body.shareWithCounsellor else "You stopped sharing your MBA data with your counsellor")
        changes = {"shareWithCounsellor": body.shareWithCounsellor, "shareUpdatedAt": now,
                   "history": (_history(current) + [{"at": now, "by": "student", "summary":
                               "Sharing turned on" if body.shareWithCounsellor else "Sharing turned off",
                               "studentText": text}])[-HISTORY_LIMIT:],
                   "updatedAt": now}
        return changes, _public(request_id, {**current, **changes})

    return occ_update(db, REQUESTS, request_id, mutate)


def student_notifications(db: SafeFirestore, user_id: str) -> list[dict[str, Any]]:
    """In-app notifications (api/mba/notifications.py): the latest admin-made update on each request."""
    items = []
    cutoff = utcnow() - timedelta(days=NOTIFY_WINDOW_DAYS)
    for doc_id, data in query_eq(db, REQUESTS, "userId", user_id):
        latest = next((h for h in reversed(_history(data)) if h["by"] != "student" and h.get("studentText")), None)
        at = parse_iso(latest["at"]) if latest else None
        if latest is None or at is None or at < cutoff:
            continue
        topic = TOPIC_LABEL.get(data.get("topic"), "Something else")  # type: ignore[arg-type]
        items.append({"id": f"counsellor-{doc_id}-{re.sub(r'[^0-9]', '', latest['at'])}", "kind": "counsellor_update",
                      "title": latest["studentText"], "detail": f"Talk to my counsellor · {topic}",
                      "href": "/mba/shortlist#counsellor", "at": at})
    return items


# ---------------------------------------------------------------- admin
@router.get("/admin/counsellors", response_model=CounsellorsResponse)
def admin_list_counsellors(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    _admin: CurrentAdmin = Depends(content_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    needle = (q or "").strip().casefold()
    rows = [
        c for c in counsellor_directory(db).values()
        if not needle or any(needle in (c[k] or "").casefold() for k in ("name", "phoneNumber", "email", "organisationName", "id"))
    ]
    rows.sort(key=lambda c: (not c["verified"], c["name"].casefold()))
    return {"counsellors": rows[:limit], "total": len(rows)}


@router.get("/admin/counsellor-requests", response_model=AdminCounsellorRequestsResponse)
def admin_list_requests(
    status: RequestStatus | None = Query(default=None),
    topic: Topic | None = Query(default=None),
    counsellorId: str | None = Query(default=None, max_length=128, description='"none" = unassigned'),
    overdue: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=100),
    _admin: CurrentAdmin = Depends(content_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    directory = counsellor_directory(db)
    today = local_date()
    rows = [_admin_view(doc_id, data, directory, today) for doc_id, data in stream_all(db, REQUESTS)]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    loads: dict[tuple[str | None, str], dict[str, Any]] = {}
    for r in rows:
        c = r["counsellor"]
        if c is None:
            continue
        load = loads.setdefault((c["id"], c["id"] or c["name"]), {"counsellorId": c["id"], "name": c["name"],
                                                                  "active": 0, "overdue": 0, "total": 0})
        load["total"] += 1
        load["active"] += r["status"] not in TERMINAL
        load["overdue"] += r["overdue"]
    needle = (q or "").strip().casefold()
    want = (counsellorId or "").strip()
    shown = [
        r for r in rows
        if (status is None or r["status"] == status)
        and (topic is None or r["topic"] == topic)
        and (not want or (r["counsellor"] is None if want == "none" else (r["counsellor"] or {}).get("id") == want))
        and (not overdue or r["overdue"])
        and (not needle or any(needle in (r[k] or "").casefold()
                               for k in ("studentName", "phoneNumber", "email", "counsellorName", "note", "slug")))
    ]
    return {
        "requests": _newest_first(shown),
        "counts": counts,
        "overdue": sum(1 for r in rows if r["overdue"]),
        "unassigned": sum(1 for r in rows if r["counsellor"] is None and r["status"] not in TERMINAL),
        "byCounsellor": sorted(loads.values(), key=lambda x: (-x["active"], x["name"].casefold())),
    }


@router.get("/admin/counsellor-requests/{request_id}", response_model=AdminCounsellorRequestDetail)
def admin_get_request(request_id: str, _admin: CurrentAdmin = Depends(content_admin),
                      db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_id(request_id)
    data = get_doc(db, REQUESTS, request_id)
    if data is None:
        raise HTTPException(404, "Request not found.")
    return _detail(db, request_id, data)


@router.patch("/admin/counsellor-requests/{request_id}", response_model=AdminCounsellorRequestDetail)
def admin_update_request(request_id: str, body: AdminRequestPatch, admin: CurrentAdmin = Depends(content_admin),
                         db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "Nothing to update.")
    _check_id(request_id)
    counsellor = None
    if "counsellorId" in sent and body.counsellorId:
        counsellor = _lookup_counsellor(db, body.counsellorId)
        if counsellor is None:
            raise HTTPException(422, "Unknown counsellor.")
    now = iso(utcnow())
    who = admin.email or admin.admin_id

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Request not found.")
        old_status = _status(current)
        changes: dict[str, Any] = {}
        summary: list[str] = []
        student_text: list[str] = []
        if "counsellorId" in sent:
            if counsellor is not None and counsellor["id"] != _str(current.get("counsellorId")):
                changes.update({"counsellorId": counsellor["id"], "counsellorName": counsellor["name"], "assignedAt": now,
                                "assignedTo": None})
                summary.append(f"Assigned to {counsellor['name']}")
                student_text.append(f"{counsellor['name']} is your counsellor")
            elif counsellor is None and (_str(current.get("counsellorId")) or _counsellor_name(current)):
                changes.update({"counsellorId": None, "counsellorName": None, "assignedAt": None, "assignedTo": None})
                summary.append("Unassigned")
        status = body.status if "status" in sent and body.status is not None else old_status
        if status != old_status:
            changes.update({"status": status, "statusChangedAt": now,
                            "closedAt": now if status in TERMINAL else None})
            summary.append(f"Status {STATUS_LABEL[old_status]} → {STATUS_LABEL[status]}")
            has_counsellor = changes.get("counsellorName", _counsellor_name(current))
            student_text.append("Our team reached out to you" if status == "contacted" and not has_counsellor
                                else STUDENT_STATUS_TEXT[status])
        # Closed needs a reason; converted may carry an outcome note; open statuses have none.
        old_reason = _str(current.get("closeReason"))
        reason = None
        if status in TERMINAL:
            reason = body.closeReason if "closeReason" in sent else (old_reason if status == old_status else None)
            if status == "closed" and not reason:
                raise HTTPException(422, "Give a reason to close the request.")
        if reason != old_reason:
            changes["closeReason"] = reason
            if reason:
                summary.append(f"Reason: {reason}")
        if "nextFollowUpAt" in sent and body.nextFollowUpAt != _str(current.get("nextFollowUpAt")):
            changes["nextFollowUpAt"] = body.nextFollowUpAt
            summary.append(f"Next follow-up {body.nextFollowUpAt}" if body.nextFollowUpAt else "Follow-up cleared")
        if not changes:
            return None, current
        changes = _with_history(current, changes, who, now, "; ".join(summary), "; ".join(student_text) or None)
        return changes, {**current, **changes}

    return _detail(db, request_id, occ_update(db, REQUESTS, request_id, mutate))


@router.post("/admin/counsellor-requests/{request_id}/notes", response_model=AdminCounsellorRequestDetail, status_code=201)
def admin_add_note(request_id: str, body: NoteInput, admin: CurrentAdmin = Depends(content_admin),
                   db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_id(request_id)
    now = iso(utcnow())
    who = admin.email or admin.admin_id

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Request not found.")
        raw = current.get("notes") if isinstance(current.get("notes"), list) else []
        notes = [n for n in raw if isinstance(n, dict)]
        legacy = _str(current.get("adminNote"))
        if legacy and not notes:  # keep the pre-pipeline single note as the first timeline entry
            notes.append({"id": "legacy", "at": _str(current.get("updatedAt")) or now,
                          "by": _str(current.get("updatedBy")) or "admin", "text": legacy})
        notes.append({"id": uuid.uuid4().hex[:12], "at": now, "by": who, "text": body.text})
        changes = {"notes": notes[-NOTES_LIMIT:], "updatedAt": now, "updatedBy": who}
        return changes, {**current, **changes}

    return _detail(db, request_id, occ_update(db, REQUESTS, request_id, mutate))


@router.get("/admin/counsellor-requests/{request_id}/documents/{doc_id}/download", response_model=DownloadLink)
def admin_download_document(request_id: str, doc_id: str, _admin: CurrentAdmin = Depends(content_admin),
                            db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Short-lived link to a document the request's student shared; 404 for anything not shared."""
    _check_id(request_id)
    data = get_doc(db, REQUESTS, request_id)
    user_id = _str((data or {}).get("userId"))
    if data is None or not user_id:
        raise HTTPException(404, "Request not found.")
    doc = doc_store.own_doc(db, user_id, doc_id)
    if doc.get("shareWithCounsellor") is not True:
        raise HTTPException(404, "Document not found.")
    if not doc_store.enabled():
        raise HTTPException(503, "Document storage is not configured.")
    return doc_store.download_link(doc)
