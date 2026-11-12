"""Talk-to-my-counsellor: student requests and the Admin-panel queue (contract: docs/mba-api.md).

Collection ``mbaCounsellorRequests/{id}`` (one doc per request):
``{ userId, studentName, phoneNumber, email, topic, preferredTime, note, slug, status, assignedTo,
adminNote, createdAt, updatedAt, assignedAt, doneAt, updatedBy, history[] }``.
Students create and read their own; admins (same roles as MBA content review) list, assign and close.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .admin import content_admin
from .deps import student
from .program_models import SLUG_RE
from .store import iso, occ_update, query_eq, stream_all, utcnow

router = APIRouter()

REQUESTS = "mbaCounsellorRequests"
MAX_ACTIVE = 3  # open + assigned requests a student may have at once
HISTORY_LIMIT = 30

Topic = Literal["shortlisting", "applications", "wat-pi", "other"]
RequestStatus = Literal["open", "assigned", "done"]
TOPICS = ("shortlisting", "applications", "wat-pi", "other")
STATUSES = ("open", "assigned", "done")


# ---------------------------------------------------------------- models
def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CounsellorRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Topic
    preferredTime: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    slug: str | None = None  # optional institute the request is about

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


class CounsellorRequest(BaseModel):
    id: str
    topic: Topic
    preferredTime: str | None
    note: str | None
    slug: str | None
    status: RequestStatus
    assignedTo: str | None
    createdAt: str
    updatedAt: str
    assignedAt: str | None
    doneAt: str | None


class CounsellorRequestsResponse(BaseModel):
    requests: list[CounsellorRequest]


class RequestHistory(BaseModel):
    at: str
    by: str
    summary: str


class AdminCounsellorRequest(CounsellorRequest):
    userId: str
    studentName: str | None
    phoneNumber: str | None
    email: str | None
    adminNote: str | None
    updatedBy: str | None
    history: list[RequestHistory]


class AdminCounsellorRequestsResponse(BaseModel):
    requests: list[AdminCounsellorRequest]
    counts: dict[str, int]  # {open, assigned, done} over all requests (ignores filters)


class AdminRequestPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RequestStatus | None = None
    assignedTo: str | None = Field(default=None, max_length=200)
    adminNote: str | None = Field(default=None, max_length=2000)

    @field_validator("assignedTo", "adminNote")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _clean(value)


# ---------------------------------------------------------------- shaping
def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _public(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    created = _str(data.get("createdAt")) or ""
    return {
        "id": doc_id,
        "topic": data.get("topic") if data.get("topic") in TOPICS else "other",
        "preferredTime": _str(data.get("preferredTime")),
        "note": _str(data.get("note")),
        "slug": _str(data.get("slug")),
        "status": data.get("status") if data.get("status") in STATUSES else "open",
        "assignedTo": _str(data.get("assignedTo")),
        "createdAt": created,
        "updatedAt": _str(data.get("updatedAt")) or created,
        "assignedAt": _str(data.get("assignedAt")),
        "doneAt": _str(data.get("doneAt")),
    }


def _admin_view(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    history = data.get("history") if isinstance(data.get("history"), list) else []
    return {
        **_public(doc_id, data),
        "userId": _str(data.get("userId")) or "",
        "studentName": _str(data.get("studentName")),
        "phoneNumber": _str(data.get("phoneNumber")),
        "email": _str(data.get("email")),
        "adminNote": _str(data.get("adminNote")),
        "updatedBy": _str(data.get("updatedBy")),
        "history": [
            {"at": h["at"], "by": h["by"], "summary": h["summary"]}
            for h in history
            if isinstance(h, dict) and all(isinstance(h.get(k), str) for k in ("at", "by", "summary"))
        ],
    }


def _student_name(user: CurrentUser) -> str | None:
    profile = user.profile or {}
    parts = [_str(profile.get(k)) for k in ("firstName", "lastName")]
    name = " ".join(p for p in parts if p)
    return name or _str(profile.get("name")) or _str(profile.get("fullName"))


def _newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["createdAt"], r["id"]), reverse=True)


# ---------------------------------------------------------------- student
@router.post("/me/counsellor-requests", response_model=CounsellorRequest, status_code=201)
def create_request(body: CounsellorRequestInput, user: CurrentUser = Depends(student),
                   db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    mine = query_eq(db, REQUESTS, "userId", user.user_id)
    active = sum(1 for _id, data in mine if data.get("status") in ("open", "assigned"))
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
        "note": body.note,
        "slug": body.slug,
        "status": "open",
        "assignedTo": None,
        "adminNote": None,
        "createdAt": now,
        "updatedAt": now,
        "assignedAt": None,
        "doneAt": None,
        "updatedBy": None,
        "history": [{"at": now, "by": "student", "summary": "Request created"}],
    }
    db.collection(REQUESTS).document(doc_id).create(data, timeout=DB_TIMEOUT)
    return _public(doc_id, data)


@router.get("/me/counsellor-requests", response_model=CounsellorRequestsResponse)
def list_my_requests(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    rows = [_public(doc_id, data) for doc_id, data in query_eq(db, REQUESTS, "userId", user.user_id)]
    return {"requests": _newest_first(rows)}


# ---------------------------------------------------------------- admin
@router.get("/admin/counsellor-requests", response_model=AdminCounsellorRequestsResponse)
def admin_list_requests(
    status: RequestStatus | None = Query(default=None),
    topic: Topic | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    _admin: CurrentAdmin = Depends(content_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    rows = [_admin_view(doc_id, data) for doc_id, data in stream_all(db, REQUESTS)]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    needle = (q or "").strip().casefold()
    shown = [
        r for r in rows
        if (status is None or r["status"] == status)
        and (topic is None or r["topic"] == topic)
        and (not needle or any(needle in (r[k] or "").casefold()
                               for k in ("studentName", "phoneNumber", "email", "assignedTo", "note", "slug")))
    ]
    return {"requests": _newest_first(shown), "counts": counts}


@router.patch("/admin/counsellor-requests/{request_id}", response_model=AdminCounsellorRequest)
def admin_update_request(request_id: str, body: AdminRequestPatch, admin: CurrentAdmin = Depends(content_admin),
                         db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "Nothing to update.")
    if "/" in request_id or not request_id.strip():
        raise HTTPException(404, "Request not found.")
    now = iso(utcnow())
    who = admin.email or admin.admin_id

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Request not found.")
        view = _admin_view(request_id, current)
        changes: dict[str, Any] = {}
        summary: list[str] = []
        if "assignedTo" in sent and body.assignedTo != view["assignedTo"]:
            changes["assignedTo"] = body.assignedTo
            summary.append(f"Assigned to {body.assignedTo}" if body.assignedTo else "Unassigned")
        if "adminNote" in sent and body.adminNote != view["adminNote"]:
            changes["adminNote"] = body.adminNote
            summary.append("Note updated")
        assigned_to = changes.get("assignedTo", view["assignedTo"])
        status = body.status if "status" in sent and body.status is not None else view["status"]
        if "status" not in sent or body.status is None:
            # Assigning an open request moves it to "assigned"; clearing the assignee re-opens it.
            if status == "open" and assigned_to:
                status = "assigned"
            elif status == "assigned" and not assigned_to:
                status = "open"
        if status == "assigned" and not assigned_to:
            raise HTTPException(422, "Set assignedTo (counsellor name or email) to mark a request assigned.")
        if status != view["status"]:
            changes["status"] = status
            summary.append(f"Status {view['status']} → {status}")
            if status == "assigned":
                changes["assignedAt"] = now
            if status == "done":
                changes["doneAt"] = now
            elif view["doneAt"]:
                changes["doneAt"] = None
        elif "assignedTo" in changes and status == "assigned":
            changes["assignedAt"] = now
        if not changes:
            return None, view
        history = current.get("history") if isinstance(current.get("history"), list) else []
        changes.update({
            "updatedAt": now,
            "updatedBy": who,
            "history": (history + [{"at": now, "by": who, "summary": "; ".join(summary)}])[-HISTORY_LIMIT:],
        })
        return changes, _admin_view(request_id, {**current, **changes})

    return occ_update(db, REQUESTS, request_id, mutate)
