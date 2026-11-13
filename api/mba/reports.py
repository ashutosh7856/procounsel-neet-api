"""Question issue reports (contract: docs/mba-api.md → "Question reports").

Students: ``GET/POST /questions/{id}/reports`` — one report per (student, question) in
``mbaQuestionReports/{userId}_{questionId}``, editable. Only after the answer was revealed to
that student (answered in practice / daily, or part of a submitted attempt) and never while
the question is in one of their running mocks. Rate limited per student per India-time day.

Admins (MBA content roles): ``GET /admin/reports`` and ``PATCH /admin/reports/{id}``.
Reporter identity (userId / phone) is never returned.
"""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db

from .admin_roles import reports_admin as content_admin  # "support" or "content" capability (admin_roles.py)
from .attempts import _question_section, user_attempts
from .deps import student
from .models import SECTION_IDS, SectionId
from .questions import get_question_or_404
from .stats import has_answered
from .store import QUESTIONS, STATS, get_bank, get_doc, iso, local_date, occ_update, query_eq, stat_id, stream_all, utcnow

router = APIRouter()
admin_router = APIRouter(prefix="/admin")

REPORTS = "mbaQuestionReports"
REPORTS_PER_DAY = 20          # distinct reports a student may create or edit per day
EDITS_PER_REPORT_PER_DAY = 5  # saves of one report per day

ReportCategory = Literal["wrong_answer", "unclear", "typo", "solution_error", "other"]
ReportStatus = Literal["open", "resolved", "rejected"]
_STATUSES = ("open", "resolved", "rejected")
_CATEGORIES = ("wrong_answer", "unclear", "typo", "solution_error", "other")


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: ReportCategory
    note: str | None = Field(default=None, max_length=1000)


class MyReport(BaseModel):
    questionId: str
    category: ReportCategory
    note: str | None
    status: ReportStatus
    createdAt: str
    updatedAt: str


class MyReportResponse(BaseModel):
    report: MyReport | None


class AdminReportPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReportStatus
    note: str | None = Field(default=None, max_length=2000)


class AdminReport(BaseModel):
    id: str
    questionId: str
    paperId: str | None
    section: SectionId | None
    number: int | None
    stemPreview: str
    category: ReportCategory
    note: str | None
    status: ReportStatus
    adminNote: str | None
    resolvedBy: str | None
    resolvedAt: str | None
    createdAt: str
    updatedAt: str


class ReportCounts(BaseModel):
    open: int
    resolved: int
    rejected: int


class AdminReportsResponse(BaseModel):
    reports: list[AdminReport]
    counts: ReportCounts


def report_id(user_id: str, question_id: str) -> str:
    """Deterministic (one per student per question) but opaque: the id never reveals the userId."""
    return hashlib.sha256(f"mba-report|{user_id}|{question_id}".encode()).hexdigest()[:28]


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _status(doc: dict[str, Any]) -> str:
    return doc.get("status") if doc.get("status") in _STATUSES else "open"


def _category(doc: dict[str, Any]) -> str:
    return doc.get("category") if doc.get("category") in _CATEGORIES else "other"


def _mine(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "questionId": str(doc.get("questionId") or ""), "category": _category(doc), "note": _str(doc.get("note")),
        "status": _status(doc), "createdAt": str(doc.get("createdAt") or ""), "updatedAt": str(doc.get("updatedAt") or ""),
    }


def _check_revealed(db: SafeFirestore, user: CurrentUser, question_id: str) -> dict[str, Any]:
    """404 unknown question; 403 unless the student has seen this question's answer and it is not in a live mock."""
    bank = get_bank(db)
    question = get_question_or_404(bank, question_id)
    attempts = user_attempts(db, bank, user)
    if any(a.get("status") == "in_progress" and question_id in _question_section(a) for a in attempts):
        raise HTTPException(403, "This question is part of your mock in progress. Submit the mock first.")
    seen = has_answered(get_doc(db, STATS, stat_id(user.user_id, question_id))) or any(
        a.get("status") == "submitted" and question_id in _question_section(a) for a in attempts
    )
    if not seen:
        raise HTTPException(403, "You can report a question after you have answered it or seen it in a submitted mock.")
    return question


@router.get("/questions/{question_id}/reports", response_model=MyReportResponse)
def my_report(question_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    doc = get_doc(db, REPORTS, report_id(user.user_id, question_id))
    return {"report": _mine(doc) if doc and doc.get("userId") == user.user_id else None}


@router.post("/questions/{question_id}/reports", response_model=MyReport)
def submit_report(
    question_id: str, body: ReportInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    question = _check_revealed(db, user, question_id)
    now = utcnow()
    today = local_date(now).isoformat()
    doc_id = report_id(user.user_id, question_id)
    written_today = {d for d, data in query_eq(db, REPORTS, "userId", user.user_id) if data.get("lastWriteDate") == today}
    if doc_id not in written_today and len(written_today) >= REPORTS_PER_DAY:
        raise HTTPException(429, f"You can send up to {REPORTS_PER_DAY} reports a day. Please try again tomorrow.")
    note = _str(body.note)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        stamp = iso(now)
        if current is None:
            doc = {
                "userId": user.user_id, "questionId": question_id, "paperId": question.get("paperId"),
                "section": question.get("section"), "number": question.get("number"),
                "category": body.category, "note": note, "status": "open", "adminNote": None,
                "resolvedBy": None, "resolvedAt": None, "createdAt": stamp, "updatedAt": stamp,
                "lastWriteDate": today, "writesToday": 1,
            }
            return doc, doc
        if current.get("category") == body.category and _str(current.get("note")) == note:
            return None, current  # unchanged: no write, no rate-limit use
        writes = int(current.get("writesToday") or 0) if current.get("lastWriteDate") == today else 0
        if writes >= EDITS_PER_REPORT_PER_DAY:
            raise HTTPException(429, "You have edited this report too often today. Please try again tomorrow.")
        fields = {"category": body.category, "note": note, "updatedAt": stamp, "lastWriteDate": today, "writesToday": writes + 1}
        if _status(current) != "open":  # an edit after review reopens it
            fields.update({"status": "open", "reopenedAt": stamp})
        return fields, {**current, **fields}

    return _mine(occ_update(db, REPORTS, doc_id, mutate))


# ---------------------------------------------------------------- admin
def _preview(value: Any) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value if isinstance(value, str) else ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= 160 else text[:157].rstrip() + "…"


def _admin_report(doc_id: str, doc: dict[str, Any], question: dict[str, Any] | None) -> dict[str, Any]:
    q = question or {}
    number = q.get("number", doc.get("number"))
    section = q.get("section", doc.get("section"))
    return {
        "id": doc_id, "questionId": str(doc.get("questionId") or ""),
        "paperId": _str(q.get("paperId")) or _str(doc.get("paperId")),
        "section": section if section in SECTION_IDS else None,
        "number": number if isinstance(number, int) and not isinstance(number, bool) else None,
        "stemPreview": _preview(q.get("stemHtml")),
        "category": _category(doc), "note": _str(doc.get("note")), "status": _status(doc),
        "adminNote": _str(doc.get("adminNote")), "resolvedBy": _str(doc.get("resolvedBy")), "resolvedAt": _str(doc.get("resolvedAt")),
        "createdAt": str(doc.get("createdAt") or ""), "updatedAt": str(doc.get("updatedAt") or ""),
    }


@admin_router.get("/reports", response_model=AdminReportsResponse)
def admin_reports(
    status: ReportStatus | None = None,
    paperId: str | None = Query(default=None, max_length=200),  # noqa: N803
    questionId: str | None = Query(default=None, max_length=300),  # noqa: N803
    _admin: CurrentAdmin = Depends(content_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    if questionId:
        docs = query_eq(db, REPORTS, "questionId", questionId)
    elif paperId:
        docs = query_eq(db, REPORTS, "paperId", paperId)
    else:
        docs = stream_all(db, REPORTS)
    counts = {s: 0 for s in _STATUSES}
    for _, doc in docs:
        counts[_status(doc)] += 1
    docs = [(i, d) for i, d in docs if status is None or _status(d) == status]
    question_ids = {str(d.get("questionId") or "") for _, d in docs}
    if paperId:
        questions = dict(query_eq(db, QUESTIONS, "paperId", paperId))
    elif len(question_ids) <= 30:
        questions = {qid: q for qid in question_ids if qid and (q := get_doc(db, QUESTIONS, qid)) is not None}
    else:
        questions = dict(stream_all(db, QUESTIONS))
    reports = [_admin_report(i, d, questions.get(str(d.get("questionId") or ""))) for i, d in docs]
    reports.sort(key=lambda r: r["updatedAt"], reverse=True)
    reports.sort(key=lambda r: _STATUSES.index(r["status"]))
    return {"reports": reports, "counts": counts}


@admin_router.patch("/reports/{report_id}", response_model=AdminReport)
def admin_update_report(
    report_id: str, body: AdminReportPatch, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    note = _str(body.note)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Report not found.")
        stamp = iso(utcnow())
        fields: dict[str, Any] = {"status": body.status, "adminNote": note, "updatedAt": stamp}
        if body.status == "open":
            fields.update({"resolvedBy": None, "resolvedAt": None})
        else:
            fields.update({"resolvedBy": admin.admin_id, "resolvedAt": stamp})
        return fields, {**current, **fields}

    doc = occ_update(db, REPORTS, report_id, mutate)
    return _admin_report(report_id, doc, get_doc(db, QUESTIONS, str(doc.get("questionId") or "")))
