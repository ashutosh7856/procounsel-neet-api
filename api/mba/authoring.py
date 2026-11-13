"""Test authoring in the Admin panel: ``/api/v1/mba/admin`` (contract: docs/mba-api.md → "Admin authoring").

Builds papers without the JSON importer: create a draft paper, add/edit/archive sets and
questions, reorder, validate, export, schedule, and import a paper JSON from the browser.
Every rule comes from ``scripts/mba/paper_format.py`` (``check_paper`` / ``check_set`` /
``check_question`` / ``build_paper_docs``), so an authored paper is exactly as valid as an
imported one. Nothing is ever deleted: "delete" archives the doc and drops it from the paper.

Roles (admin_roles.py): papers (create, import, schedule, archive) need ``tests``; sets and
questions need ``content``; reading, validating, exporting and reordering need either.
Structural changes (add/remove/reorder questions) are refused on a published paper —
unpublish it first, so a live mock never changes under students.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from google.api_core import exceptions as gexc
from pydantic import BaseModel, Field

from api.auth import CurrentAdmin, require_admin
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT
from scripts.mba.paper_format import (
    EXAMS_CONFIG_DIR,
    KEY_RE,
    PaperFormatError,
    build_paper_docs,
    check_paper,
    check_question,
    check_set,
    exam_config,
    section_ids,
)

from .admin import (
    _admin_set,
    _edit,
    _paper_context,
    _paper_or_404,
    _paper_payload,
    _paper_questions,
    _paper_sections,
    _question_response,
    _status,
    _str,
    paper_content,
    validate_paper,
)
from .admin_roles import capabilities_of, content_editor, content_reader, test_manager
from .exams import _exam_payload
from .models import (
    HTML_MAX,
    AdminPaper,
    AdminQuestion,
    AdminSet,
    ExamId,
    ExamSectionId,
    ExamsResponse,
    QuestionOption,
    SourceInput,
)
from .store import PAPERS, QUESTIONS, SETS, get_doc, invalidate_bank, iso, occ_update, parse_iso, query_eq, utcnow

router = APIRouter(prefix="/admin")

BATCH_LIMIT = 400
SET_KEY_PREFIX = {"passage": "P", "dilr_set": "S", "data": "D"}


# ---------------------------------------------------------------- models
class AdminMe(BaseModel):
    adminId: str
    email: str | None
    role: str | None
    capabilities: list[Literal["content", "tests", "support", "analytics"]]


class PaperCreate(BaseModel):
    model_config = {"extra": "forbid"}

    id: str | None = Field(default=None, max_length=81)  # CAT: default cat-{year}-slot{slot} when both are given
    examId: ExamId = "cat"  # an exam of GET /admin/exams; fixed once created
    title: str | None = Field(default=None, max_length=200)
    examVersionYear: int | None = None
    year: int | None = None
    slot: int | None = None
    source: SourceInput


class PaperEdit(BaseModel):
    """Only sent fields change; ``null`` clears ``year``/``slot``/the schedule."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=200)
    examVersionYear: int | None = None
    year: int | None = None
    slot: int | None = None
    source: SourceInput | None = None
    availableFrom: str | None = Field(default=None, max_length=40)   # ISO 8601 with offset; null = no start
    availableUntil: str | None = Field(default=None, max_length=40)  # ISO 8601 with offset; null = no end
    expectedVersion: int | None = Field(default=None, ge=1)


class ImportInput(BaseModel):
    model_config = {"extra": "forbid"}

    content: dict[str, Any]  # {paper, sets, questions} — docs/mba-content-format.md (single-file form)
    dryRun: bool = False


class ImportResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    paperId: str | None = None
    examId: str | None = None
    questionCount: int = 0
    setCount: int = 0
    paper: AdminPaper | None = None  # set when imported (not on a dry run)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]


class OrderSection(BaseModel):
    id: ExamSectionId
    questionIds: list[str] = Field(max_length=200)


class OrderInput(BaseModel):
    model_config = {"extra": "forbid"}

    sections: list[OrderSection] = Field(max_length=10)
    expectedVersion: int | None = Field(default=None, ge=1)


class SetCreate(BaseModel):
    model_config = {"extra": "forbid"}

    key: str | None = Field(default=None, max_length=61)  # default {section}-{P|S|D}{n}
    kind: Literal["passage", "dilr_set", "data"]
    section: ExamSectionId  # one of the paper's exam sections (checked by check_set)
    title: str | None = Field(default=None, max_length=300)
    contentHtml: str = Field(max_length=HTML_MAX)
    images: list[str] | None = Field(default=None, max_length=20)


class QuestionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    key: str | None = Field(default=None, max_length=61)  # default {section}-{nn}
    section: ExamSectionId  # one of the paper's exam sections (checked by check_question)
    type: Literal["MCQ", "TITA"]
    setId: str | None = None
    stemHtml: str = Field(max_length=HTML_MAX)
    options: list[QuestionOption] | None = Field(default=None, max_length=10)
    answer: str | int | float | None = None
    solutionHtml: str | None = Field(default=None, max_length=HTML_MAX)
    alternativeApproaches: list[str] | None = Field(default=None, max_length=5)  # extra solution methods (HTML)
    videoUrl: str | None = Field(default=None, max_length=500)  # https only
    topic: str | None = Field(default=None, max_length=200)
    subtopic: str | None = Field(default=None, max_length=200)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    source: SourceInput | None = None  # default: the paper's source
    position: int | None = Field(default=None, ge=1)  # 1-based place in the section; default last


# ---------------------------------------------------------------- helpers
def _who(admin: CurrentAdmin) -> str:
    return admin.admin_id


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _answer(value: Any) -> str | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() if value is not None and str(value).strip() else None


def _draft_paper_or_409(db: SafeFirestore, paper_id: str) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    if _status(paper) == "published":
        raise HTTPException(409, "Unpublish the paper before adding, removing or reordering questions.")
    return paper


def _renumber(db: SafeFirestore, sections: list[dict[str, Any]], questions: dict[str, dict[str, Any]]) -> None:
    """Store number = 1-based position within the section for every question whose number changed."""
    now = iso(utcnow())
    batch, pending = db.batch(), 0
    for section in sections:
        for position, qid in enumerate(section["questionIds"], start=1):
            doc = questions.get(qid)
            if doc is None or doc.get("number") == position:
                continue
            batch.update(db.collection(QUESTIONS).document(qid), {"number": position, "updatedAt": now})
            pending += 1
            if pending >= BATCH_LIMIT:
                batch.commit(timeout=DB_TIMEOUT)
                batch, pending = db.batch(), 0
    if pending:
        batch.commit(timeout=DB_TIMEOUT)


def _section_order(paper: dict[str, Any]) -> tuple[str, ...]:
    """The exam's section order (CAT: VARC, DILR, QA; others from their config)."""
    return section_ids(paper.get("examId") or "cat")


def _sort_sections(sections: list[dict[str, Any]], order: tuple[str, ...]) -> list[dict[str, Any]]:
    rank = {sid: i for i, sid in enumerate(order)}
    return sorted(sections, key=lambda s: rank.get(s["id"], len(rank)))


def _sections_with(paper: dict[str, Any]) -> list[dict[str, Any]]:
    """Mutable copy of the paper's sections in the exam's canonical order."""
    current = {sid: ids for sid, ids in _paper_sections(paper)}
    return _sort_sections([{"id": sid, "questionIds": list(ids)} for sid, ids in current.items()], _section_order(paper))


def _set_section(
    sections: list[dict[str, Any]], section_id: str, ids: list[str], order: tuple[str, ...]
) -> list[dict[str, Any]]:
    out = [s for s in sections if s["id"] != section_id]
    if ids:
        out.append({"id": section_id, "questionIds": ids})
    return _sort_sections(out, order)


def _update_paper_sections(
    db: SafeFirestore, paper_id: str, admin: CurrentAdmin, change: Any, summary: str, expected: int | None = None
) -> dict[str, Any]:
    """OCC update of the paper's sections: ``change(sections) -> sections``; versioned with history."""

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Paper not found.")
        if _status(current) == "published":
            raise HTTPException(409, "Unpublish the paper before adding, removing or reordering questions.")
        sections = change(_sections_with(current))
        count = sum(len(s["questionIds"]) for s in sections)
        fields = _edit(current, {"sections": sections, "questionCount": count}, admin, expected, summary)
        return fields, {**current, **(fields or {})}

    paper = occ_update(db, PAPERS, paper_id, mutate)
    invalidate_bank()
    return paper


def _moment(value: str | None, name: str) -> str | None:
    if value is None or not value.strip():
        return None
    moment = parse_iso(value.strip())
    if moment is None or "T" not in value:
        raise HTTPException(422, f"{name} must be an ISO date-time like 2026-11-30T10:00:00+05:30")
    return iso(moment)


def _paper_out(db: SafeFirestore, paper_id: str, paper: dict[str, Any]) -> dict[str, Any]:
    return _paper_payload(paper_id, paper, _paper_questions(db, paper_id))


# ---------------------------------------------------------------- who am I
@router.get("/me", response_model=AdminMe)
def admin_me(admin: CurrentAdmin = Depends(require_admin)) -> dict[str, Any]:
    """The caller's MBA capabilities (an empty list for admins without MBA access)."""
    return {"adminId": admin.admin_id, "email": admin.email, "role": admin.role, "capabilities": capabilities_of(admin.role)}


# ---------------------------------------------------------------- exams
@router.get("/exams", response_model=ExamsResponse)
def admin_exams(_admin: CurrentAdmin = Depends(content_reader)) -> dict[str, Any]:
    """Every exam a paper can follow: the same config files the importer validates against
    (CAT first, then data/mba/exams-config/*.json by id), including draft-only exams."""
    ids = ["cat", *sorted(path.stem for path in EXAMS_CONFIG_DIR.glob("*.json"))]
    exams = [payload for exam_id in ids if (data := exam_config(exam_id)) and (payload := _exam_payload(exam_id, data))]
    return {"exams": exams}


# ---------------------------------------------------------------- papers
@router.post("/papers", response_model=AdminPaper, status_code=201)
def create_paper(body: PaperCreate, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    errors: list[str] = []
    header = body.model_dump(exclude_none=True)
    header["source"] = body.source.model_dump(exclude_none=True)
    paper = check_paper(header, errors, [])
    if paper is None or errors:
        raise HTTPException(422, "; ".join(errors))
    now = iso(utcnow())
    doc = {
        "id": paper["id"], "examId": paper["examId"], "title": paper["title"], "examVersionYear": paper["examVersionYear"],
        "year": paper["year"], "slot": paper["slot"], "source": paper["source"], "sections": [], "questionCount": 0,
        "status": "draft", "version": 1, "history": [], "createdBy": _who(admin), "createdAt": now, "updatedAt": now,
        "updatedBy": _who(admin),
    }
    try:
        db.collection(PAPERS).document(paper["id"]).create(doc, timeout=DB_TIMEOUT)
    except gexc.Conflict as error:
        raise HTTPException(409, f"A paper with id {paper['id']} already exists.") from error
    invalidate_bank()
    return _paper_payload(paper["id"], doc, {})


@router.patch("/papers/{paper_id}", response_model=AdminPaper)
def edit_paper(
    paper_id: str, body: PaperEdit, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    sent = body.model_fields_set - {"expectedVersion"}
    if not sent:
        raise HTTPException(422, "Nothing to change.")
    changes: dict[str, Any] = {}
    for field in ("examVersionYear", "year", "slot"):
        if field in sent:
            changes[field] = getattr(body, field)
    if "title" in sent:
        if not _clean(body.title):
            raise HTTPException(422, "title is required")
        changes["title"] = _clean(body.title)
    if "source" in sent:
        if body.source is None:
            raise HTTPException(422, "source cannot be null")
        changes["source"] = body.source.model_dump(exclude_none=True)
    if "availableFrom" in sent:
        changes["availableFrom"] = _moment(body.availableFrom, "availableFrom")
    if "availableUntil" in sent:
        changes["availableUntil"] = _moment(body.availableUntil, "availableUntil")

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Paper not found.")
        merged = {**current, **changes}
        errors: list[str] = []
        header = {k: merged.get(k) for k in ("examId", "title", "examVersionYear", "year", "slot", "source")}
        checked = check_paper({**{k: v for k, v in header.items() if v is not None}, "id": paper_id}, errors, [])
        start, end = parse_iso(merged.get("availableFrom")), parse_iso(merged.get("availableUntil"))
        if start and end and end <= start:
            errors.append("availableUntil must be after availableFrom")
        if errors:
            raise HTTPException(422, "; ".join(errors))
        if checked is not None and "source" in changes:
            changes["source"] = merged["source"] = checked["source"]
        fields = _edit(current, changes, admin, body.expectedVersion)
        return fields, {**current, **(fields or {})}

    paper = occ_update(db, PAPERS, paper_id, mutate)
    # Questions carry copies of the paper's years (filters / PYQ labels): keep them in step.
    copied = {k: paper.get(k) for k in ("examVersionYear", "year", "slot") if k in changes}
    questions = _paper_questions(db, paper_id)
    if copied:
        batch, pending = db.batch(), 0
        for qid in questions:
            batch.update(db.collection(QUESTIONS).document(qid), copied)
            pending += 1
            if pending >= BATCH_LIMIT:
                batch.commit(timeout=DB_TIMEOUT)
                batch, pending = db.batch(), 0
        if pending:
            batch.commit(timeout=DB_TIMEOUT)
    invalidate_bank()
    return _paper_payload(paper_id, paper, questions)


@router.post("/papers/{paper_id}/archive", response_model=AdminPaper)
def archive_paper(paper_id: str, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Hide a draft paper from the list's active work (unpublish restores it to draft)."""

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Paper not found.")
        if _status(current) == "published":
            raise HTTPException(409, "Unpublish the paper before archiving it.")
        if current.get("status") == "archived":
            return None, current
        now = iso(utcnow())
        fields = {"status": "archived", "archivedAt": now, "archivedBy": _who(admin), "updatedAt": now}
        return fields, {**current, **fields}

    paper = occ_update(db, PAPERS, paper_id, mutate)
    invalidate_bank()
    return _paper_out(db, paper_id, paper)


@router.get("/papers/{paper_id}/export")
def export_paper(paper_id: str, _admin: CurrentAdmin = Depends(content_reader), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """The paper as content JSON (docs/mba-content-format.md); re-importable under another id."""
    return paper_content(db, paper_id, _paper_or_404(db, paper_id))


@router.post("/papers/{paper_id}/validate", response_model=ValidationResult)
def validate(paper_id: str, _admin: CurrentAdmin = Depends(content_reader), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    errors, warnings = validate_paper(db, paper_id, _paper_or_404(db, paper_id))
    return {"valid": not errors, "errors": errors, "warnings": warnings}


@router.post("/papers/import", response_model=ImportResult)
def import_paper(body: ImportInput, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Import a paper JSON (same format as scripts/mba/import_paper.py) as a NEW draft paper."""
    try:
        paper, sets, questions, warnings = build_paper_docs(body.content, publish=False)
    except PaperFormatError as error:
        if body.dryRun:
            return {"valid": False, "errors": error.errors, "warnings": []}
        raise HTTPException(422, "; ".join(error.errors[:20])) from error
    summary = {"paperId": paper["id"], "examId": paper["examId"], "questionCount": len(questions), "setCount": len(sets)}
    exists = get_doc(db, PAPERS, paper["id"]) is not None or bool(query_eq(db, QUESTIONS, "paperId", paper["id"]))
    conflict = f"A paper with id {paper['id']} already exists. Change paper.id to import it as a new paper."
    if body.dryRun:
        return {"valid": not exists, "errors": [conflict] if exists else [], "warnings": warnings, **summary}
    if exists:
        raise HTTPException(409, conflict)

    now = iso(utcnow())
    stamp = {"version": 1, "history": [], "createdBy": _who(admin), "createdAt": now, "updatedAt": now}
    writes = [(SETS, doc) for doc in sets] + [(QUESTIONS, doc) for doc in questions]
    batch, pending = db.batch(), 0
    for collection, doc in writes:
        batch.set(db.collection(collection).document(doc["id"]), {**doc, **stamp})
        pending += 1
        if pending >= BATCH_LIMIT:
            batch.commit(timeout=DB_TIMEOUT)
            batch, pending = db.batch(), 0
    if pending:
        batch.commit(timeout=DB_TIMEOUT)
    paper_doc = {**paper, **stamp, "importedBy": _who(admin), "importedAt": now}
    try:  # paper last: it appears in the list only once its questions exist
        db.collection(PAPERS).document(paper["id"]).create(paper_doc, timeout=DB_TIMEOUT)
    except gexc.Conflict as error:
        raise HTTPException(409, conflict) from error
    invalidate_bank()
    return {"valid": True, "errors": [], "warnings": warnings, **summary, "paper": _paper_out(db, paper["id"], paper_doc)}


@router.put("/papers/{paper_id}/order", response_model=AdminPaper)
def reorder(paper_id: str, body: OrderInput, admin: CurrentAdmin = Depends(content_reader), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Reorder questions within their sections (same questions, same sections; numbers follow)."""
    current = _draft_paper_or_409(db, paper_id)
    before = {sid: ids for sid, ids in _paper_sections(current)}
    after = {s.id: list(s.questionIds) for s in body.sections if s.questionIds}
    if set(after) != {sid for sid, ids in before.items() if ids} or any(
        sorted(after[sid]) != sorted(before[sid]) or len(set(after[sid])) != len(after[sid]) for sid in after
    ):
        raise HTTPException(422, "The new order must list exactly the paper's current questions, each in its own section.")
    paper = _update_paper_sections(
        db, paper_id, admin, lambda _sections: _sort_sections([{"id": sid, "questionIds": ids} for sid, ids in after.items()], _section_order(current)),
        "question order changed", body.expectedVersion,
    )
    questions = _paper_questions(db, paper_id)
    _renumber(db, _sections_with(paper), questions)
    return _paper_out(db, paper_id, paper)


# ---------------------------------------------------------------- sets
@router.post("/papers/{paper_id}/sets", response_model=AdminSet, status_code=201)
def create_set(
    paper_id: str, body: SetCreate, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    existing = {doc_id for doc_id, _ in query_eq(db, SETS, "paperId", paper_id)}
    key = _clean(body.key)
    if key is None:
        prefix = f"{body.section}-{SET_KEY_PREFIX[body.kind]}"
        n = 1
        while f"{paper_id}-{prefix}{n}".lower() in existing:
            n += 1
        key = f"{prefix}{n}"
    item = {"key": key, "kind": body.kind, "section": body.section, "contentHtml": body.contentHtml}
    if _clean(body.title):
        item["title"] = _clean(body.title)
    if body.images:
        item["images"] = [img.strip() for img in body.images if img.strip()]
    errors: list[str] = []
    doc = check_set(item, "set", errors, paper_id, paper.get("examId") or "cat")
    if doc is None or errors:
        raise HTTPException(422, "; ".join(errors))
    now = iso(utcnow())
    doc = {**doc, "status": "draft", "version": 1, "history": [], "createdBy": _who(admin), "createdAt": now, "updatedAt": now}
    try:
        db.collection(SETS).document(doc["id"]).create(doc, timeout=DB_TIMEOUT)
    except gexc.Conflict as error:
        raise HTTPException(409, f"Set key {key} is already used in this paper.") from error
    return _admin_set(doc["id"], doc)  # type: ignore[return-value]


@router.delete("/sets/{set_id}", response_model=AdminSet)
def archive_set(set_id: str, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Archive a set. 409 while a question still in its paper uses it."""
    current = get_doc(db, SETS, set_id)
    if current is None:
        raise HTTPException(404, "Question set not found.")
    paper = get_doc(db, PAPERS, current.get("paperId") or "") or {}
    listed = {qid for _, ids in _paper_sections(paper) for qid in ids}
    users = [qid for qid, q in query_eq(db, QUESTIONS, "setId", set_id) if qid in listed and _status(q) != "archived"]
    if users:
        raise HTTPException(409, f"{len(users)} question(s) still use this set. Move or delete them first.")

    def mutate(doc: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if doc is None:
            raise HTTPException(404, "Question set not found.")
        if doc.get("status") == "archived":
            return None, doc
        now = iso(utcnow())
        fields = {"status": "archived", "archivedAt": now, "archivedBy": _who(admin), "updatedAt": now}
        return fields, {**doc, **fields}

    updated = occ_update(db, SETS, set_id, mutate)
    invalidate_bank()
    return _admin_set(set_id, updated)  # type: ignore[return-value]


# ---------------------------------------------------------------- questions
@router.post("/papers/{paper_id}/questions", response_model=AdminQuestion, status_code=201)
def create_question(
    paper_id: str, body: QuestionCreate, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    paper = _draft_paper_or_409(db, paper_id)
    taken = {qid for qid, _ in query_eq(db, QUESTIONS, "paperId", paper_id)}
    key = _clean(body.key)
    if key is None:
        n = 1
        while f"{paper_id}-{body.section}-{n:02d}".lower() in taken:
            n += 1
        key = f"{body.section}-{n:02d}"
    if not KEY_RE.match(key):
        raise HTTPException(422, f"key must match {KEY_RE.pattern} (e.g. 'QA-01')")
    set_docs: dict[str, dict[str, Any]] = {}
    item: dict[str, Any] = {
        "key": key, "section": body.section, "type": body.type, "stemHtml": body.stemHtml,
        "answer": _answer(body.answer),
        "source": body.source.model_dump(exclude_none=True) if body.source else paper.get("source"),
    }
    if body.options is not None:
        item["options"] = [{"id": opt.id.strip(), "textHtml": opt.textHtml} for opt in body.options]
    for name in ("solutionHtml", "topic", "subtopic"):
        if _clean(getattr(body, name)):
            item[name] = getattr(body, name).strip() if name != "solutionHtml" else getattr(body, name)
    approaches = [a for a in body.alternativeApproaches or [] if _clean(a)]
    if approaches:
        item["alternativeApproaches"] = approaches
    if _clean(body.videoUrl):
        item["videoUrl"] = body.videoUrl.strip()  # type: ignore[union-attr]
    if body.difficulty:
        item["difficulty"] = body.difficulty
    if _clean(body.setId):
        set_doc = get_doc(db, SETS, body.setId.strip())  # type: ignore[union-attr]
        if set_doc is None or set_doc.get("paperId") != paper_id or _status(set_doc) == "archived":
            raise HTTPException(422, "setId is not a set of this paper")
        set_key = _str(set_doc.get("key")) or body.setId.strip()  # type: ignore[union-attr]
        set_docs[set_key] = {"id": body.setId.strip(), "section": set_doc.get("section")}  # type: ignore[union-attr]
        item["setKey"] = set_key
    errors: list[str] = []
    doc = check_question(item, "question", errors, [], _paper_context(paper_id, paper), set_docs)
    if doc is None or errors:
        raise HTTPException(422, "; ".join(errors))

    now = iso(utcnow())
    doc = {**doc, "number": None, "status": "draft", "version": 1, "history": [], "createdBy": _who(admin),
           "createdAt": now, "updatedAt": now, "updatedBy": _who(admin)}
    try:
        db.collection(QUESTIONS).document(doc["id"]).create(doc, timeout=DB_TIMEOUT)
    except gexc.Conflict as error:
        raise HTTPException(409, f"Question key {key} is already used in this paper.") from error

    def add(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = next((s["questionIds"] for s in sections if s["id"] == body.section), [])
        at = min(body.position - 1, len(ids)) if body.position else len(ids)
        return _set_section(sections, body.section, [*ids[:at], doc["id"], *ids[at:]], _section_order(paper))

    updated = _update_paper_sections(db, paper_id, admin, add, f"added {key}")
    questions = _paper_questions(db, paper_id)
    _renumber(db, _sections_with(updated), questions)
    return _question_response(db, doc["id"], get_doc(db, QUESTIONS, doc["id"]) or doc)


@router.delete("/questions/{question_id}", response_model=AdminQuestion)
def archive_question(question_id: str, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Archive a question and take it out of its paper (the rest are renumbered)."""
    current = get_doc(db, QUESTIONS, question_id)
    if current is None:
        raise HTTPException(404, "Question not found.")
    paper_id = _str(current.get("paperId"))
    if paper_id:
        _draft_paper_or_409(db, paper_id)

    def mutate(doc: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if doc is None:
            raise HTTPException(404, "Question not found.")
        now = iso(utcnow())
        fields = {"status": "archived", "flagged": False, "archivedAt": now, "archivedBy": _who(admin), "updatedAt": now}
        return fields, {**doc, **fields}

    updated = occ_update(db, QUESTIONS, question_id, mutate)
    if paper_id:
        label = _str(current.get("key")) or question_id

        def remove(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = [{"id": s["id"], "questionIds": [q for q in s["questionIds"] if q != question_id]} for s in sections]
            return [s for s in out if s["questionIds"]]

        paper = _update_paper_sections(db, paper_id, admin, remove, f"removed {label}")
        _renumber(db, _sections_with(paper), _paper_questions(db, paper_id))
    invalidate_bank()
    return _question_response(db, question_id, updated)

