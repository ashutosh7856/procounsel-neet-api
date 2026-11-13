"""Exam-update feed: admin-written announcements per exam (registration, admit card, exam date, answer key, result).

Contract: docs/mba-api.md → "Exam updates". Collection ``mbaExamUpdates/{id}`` = ``{ exam, kind, title, detail,
eventDate, sourceUrl, status: draft | published, publishedAt, createdAt, createdBy, updatedAt, updatedBy }``.
Every update must link the OFFICIAL page it comes from (``sourceUrl``, https). Nothing is seeded: admins enter updates
from the exam bodies' sites. Students see published updates for the exams they target (profile ``targetExams``,
CAT when unset) on the dashboard and as ``exam_update`` in-app notifications (``student_notifications``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .admin_roles import require_mba
from .deps import student
from .models import EXAM_IDS
from .profile import load_profile
from .store import get_doc, iso, parse_iso, query_eq, stream_all, utcnow

router = APIRouter()

UPDATES = "mbaExamUpdates"
NOTIFY_WINDOW_DAYS = 30
STUDENT_LIMIT = 20
ExamId = Literal["cat", "xat", "snap", "nmat", "cmat", "mat", "gmat", "mah-mba-cet"]
UpdateKind = Literal["registration", "admit_card", "exam_date", "answer_key", "result", "other"]
UpdateStatus = Literal["draft", "published"]
KINDS = ("registration", "admit_card", "exam_date", "answer_key", "result", "other")
EXAM_LABEL = {"cat": "CAT", "xat": "XAT", "snap": "SNAP", "nmat": "NMAT", "cmat": "CMAT", "mat": "MAT", "gmat": "GMAT",
              "mah-mba-cet": "MAH MBA CET"}
KIND_LABEL = {"registration": "Registration", "admit_card": "Admit card", "exam_date": "Exam date",
              "answer_key": "Answer key", "result": "Result", "other": "Update"}
assert set(EXAM_LABEL) == set(EXAM_IDS)

updates_admin = require_mba("content", "support")  # faculty or support staff keep the feed current


# ---------------------------------------------------------------- models
def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _clean_day(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if len(value) != 10:
        raise ValueError("eventDate must be YYYY-MM-DD")
    date.fromisoformat(value)  # ValueError -> 422
    return value


def _https(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or " " in value:
        raise ValueError("sourceUrl must be the official https:// page")
    return value


class ExamUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam: ExamId
    kind: UpdateKind
    title: str = Field(min_length=3, max_length=140)
    detail: str | None = Field(default=None, max_length=600)
    eventDate: str | None = None  # YYYY-MM-DD the update is about (e.g. result day), optional
    sourceUrl: str = Field(min_length=10, max_length=500)
    status: UpdateStatus = "draft"

    @field_validator("title", "detail")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("eventDate")
    @classmethod
    def _day(cls, value: str | None) -> str | None:
        return _clean_day(value)

    @field_validator("sourceUrl")
    @classmethod
    def _url(cls, value: str) -> str:
        return _https(value)


class ExamUpdatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam: ExamId | None = None
    kind: UpdateKind | None = None
    title: str | None = Field(default=None, min_length=3, max_length=140)
    detail: str | None = Field(default=None, max_length=600)
    eventDate: str | None = None
    sourceUrl: str | None = Field(default=None, min_length=10, max_length=500)
    status: UpdateStatus | None = None

    @field_validator("title", "detail")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("eventDate")
    @classmethod
    def _day(cls, value: str | None) -> str | None:
        return _clean_day(value)

    @field_validator("sourceUrl")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return None if value is None else _https(value)


class ExamUpdate(BaseModel):
    id: str
    exam: ExamId
    examLabel: str
    kind: UpdateKind
    kindLabel: str
    title: str
    detail: str | None
    eventDate: str | None
    sourceUrl: str
    publishedAt: str | None


class AdminExamUpdate(ExamUpdate):
    status: UpdateStatus
    createdAt: str
    createdBy: str | None
    updatedAt: str
    updatedBy: str | None


class ExamUpdatesResponse(BaseModel):
    exams: list[str]  # the exams the student targets (what the list is filtered by)
    updates: list[ExamUpdate]  # newest published first, up to 20


class AdminExamUpdatesResponse(BaseModel):
    updates: list[AdminExamUpdate]  # newest first (drafts included)


class DeletedResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------- shaping
def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _valid(data: dict[str, Any]) -> bool:
    return (data.get("exam") in EXAM_LABEL and data.get("kind") in KIND_LABEL and bool(_str(data.get("title")))
            and bool(_str(data.get("sourceUrl"))))


def _public(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc_id, "exam": data["exam"], "examLabel": EXAM_LABEL[data["exam"]], "kind": data["kind"],
        "kindLabel": KIND_LABEL[data["kind"]], "title": _str(data.get("title")) or "", "detail": _str(data.get("detail")),
        "eventDate": _str(data.get("eventDate")), "sourceUrl": _str(data.get("sourceUrl")) or "",
        "publishedAt": _str(data.get("publishedAt")) if data.get("status") == "published" else None,
    }


def _admin(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    created = _str(data.get("createdAt")) or ""
    return {**_public(doc_id, data), "status": "published" if data.get("status") == "published" else "draft",
            "createdAt": created, "createdBy": _str(data.get("createdBy")),
            "updatedAt": _str(data.get("updatedAt")) or created, "updatedBy": _str(data.get("updatedBy"))}


def target_exams(profile: dict[str, Any] | None) -> list[str]:
    exams = (profile or {}).get("targetExams")
    return [e for e in exams if e in EXAM_LABEL] if isinstance(exams, list) and exams else ["cat"]


def published_for(db: SafeFirestore, exams: list[str]) -> list[dict[str, Any]]:
    rows = [_public(doc_id, data) for doc_id, data in query_eq(db, UPDATES, "status", "published")
            if _valid(data) and data["exam"] in exams and _str(data.get("publishedAt"))]
    rows.sort(key=lambda r: (r["publishedAt"], r["id"]), reverse=True)
    return rows


def student_notifications(db: SafeFirestore, profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """In-app notifications (api/mba/notifications.py): updates published in the last 30 days for the student's exams."""
    cutoff = utcnow() - timedelta(days=NOTIFY_WINDOW_DAYS)
    items = []
    for row in published_for(db, target_exams(profile)):
        at = parse_iso(row["publishedAt"])
        if at is None or at < cutoff:
            continue
        items.append({"id": f"exam-update-{row['id']}", "kind": "exam_update", "title": f"{row['examLabel']}: {row['title']}",
                      "detail": row["detail"] or f"{row['kindLabel']} · see the official notice",
                      "href": "/mba/dashboard#exam-updates", "at": at})
    return items


def _check_id(update_id: str) -> None:
    if "/" in update_id or not update_id.strip() or len(update_id) > 64:
        raise HTTPException(404, "Update not found.")


# ---------------------------------------------------------------- student
@router.get("/me/exam-updates", response_model=ExamUpdatesResponse)
def my_exam_updates(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    exams = target_exams(load_profile(db, user.user_id))
    return {"exams": exams, "updates": published_for(db, exams)[:STUDENT_LIMIT]}


# ---------------------------------------------------------------- admin
@router.get("/admin/exam-updates", response_model=AdminExamUpdatesResponse)
def admin_list_updates(exam: ExamId | None = Query(default=None), _admin_user: CurrentAdmin = Depends(updates_admin),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    rows = [_admin(doc_id, data) for doc_id, data in stream_all(db, UPDATES)
            if _valid(data) and (exam is None or data["exam"] == exam)]
    rows.sort(key=lambda r: (r["publishedAt"] or r["createdAt"], r["id"]), reverse=True)
    return {"updates": rows}


@router.post("/admin/exam-updates", response_model=AdminExamUpdate, status_code=201)
def admin_create_update(body: ExamUpdateInput, admin: CurrentAdmin = Depends(updates_admin),
                        db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    now = iso(utcnow())
    who = admin.email or admin.admin_id
    data = {**body.model_dump(), "publishedAt": now if body.status == "published" else None,
            "createdAt": now, "createdBy": who, "updatedAt": now, "updatedBy": who}
    doc_id = uuid.uuid4().hex
    db.collection(UPDATES).document(doc_id).create(data, timeout=DB_TIMEOUT)
    return _admin(doc_id, data)


@router.patch("/admin/exam-updates/{update_id}", response_model=AdminExamUpdate)
def admin_update_update(update_id: str, body: ExamUpdatePatch, admin: CurrentAdmin = Depends(updates_admin),
                        db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_id(update_id)
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "Nothing to update.")
    for required in ("exam", "kind", "title", "sourceUrl", "status"):
        if required in sent and getattr(body, required) is None:
            raise HTTPException(422, f"{required} can't be empty.")
    current = get_doc(db, UPDATES, update_id)
    if current is None:
        raise HTTPException(404, "Update not found.")
    now = iso(utcnow())
    changes: dict[str, Any] = {k: getattr(body, k) for k in sent}
    if changes.get("status") == "published" and current.get("status") != "published":
        changes["publishedAt"] = now  # (re)publishing puts it on top and notifies again
    elif changes.get("status") == "draft":
        changes["publishedAt"] = None
    changes |= {"updatedAt": now, "updatedBy": admin.email or admin.admin_id}
    db.collection(UPDATES).document(update_id).update(changes, timeout=DB_TIMEOUT)
    return _admin(update_id, {**current, **changes})


@router.delete("/admin/exam-updates/{update_id}", response_model=DeletedResponse)
def admin_delete_update(update_id: str, _admin_user: CurrentAdmin = Depends(updates_admin),
                        db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_id(update_id)
    if get_doc(db, UPDATES, update_id) is None:
        raise HTTPException(404, "Update not found.")
    db.collection(UPDATES).document(update_id).delete(timeout=DB_TIMEOUT)
    return {"deleted": True}
