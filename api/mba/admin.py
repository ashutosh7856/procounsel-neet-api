"""Faculty/admin content review: ``/api/v1/mba/admin`` (contract: docs/mba-api.md).

Callers are Admin-panel users (``require_admin``: the Java admin login JWT whose
subject is an ``admins`` doc id) whose role is allowed by ``MBA_CONTENT_ADMIN_ROLES``.
Unlike the student endpoints this reads the database directly (all statuses), not
the published-only content bank, and invalidates the bank after every write.
Writes go only to ``mbaQuestions``, ``mbaQuestionSets`` and ``mbaPapers``.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentAdmin, require_admin_roles
from api.db import SafeFirestore, get_db
from scripts.mba.paper_format import DIFFICULTIES, OPTION_ID_RE, SET_KINDS

from .exams import _paper_label, _paper_sort
from .models import (
    SECTION_IDS,
    AdminPaper,
    AdminPaperQuestionsResponse,
    AdminPapersResponse,
    AdminQuestion,
    AdminSet,
    QuestionEdit,
    ReviewInput,
    SetEdit,
)
from .public import public_source
from .store import PAPERS, QUESTIONS, SETS, get_doc, invalidate_bank, iso, occ_update, query_eq, stream_all, utcnow

router = APIRouter(prefix="/admin")

DEFAULT_ROLES = "superAdmin,COURSE"
HISTORY_LIMIT = 50
STATUSES = ("draft", "published", "archived")
SHORT_FIELDS = ("correctAnswer", "difficulty", "topic", "subtopic")  # shown as old -> new in history


def content_admin_roles() -> frozenset[str] | None:
    """Admin roles allowed to review MBA content (``*`` = every admin)."""
    raw = os.getenv("MBA_CONTENT_ADMIN_ROLES", DEFAULT_ROLES).strip()
    if raw == "*":
        return None
    return frozenset(role.strip() for role in raw.split(",") if role.strip())


content_admin = require_admin_roles(content_admin_roles)


# ---------------------------------------------------------------- reading helpers
def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _version(doc: dict[str, Any]) -> int:
    version = _int(doc.get("version"))
    return version if version and version > 0 else 1


def _status(doc: dict[str, Any] | None) -> str:
    status = (doc or {}).get("status")
    return status if status in STATUSES else "draft"


def _state(doc: dict[str, Any] | None) -> str:
    """Review bucket: missing | archived | published | flagged | draft."""
    if doc is None:
        return "missing"
    status = _status(doc)
    if status == "draft" and doc.get("flagged") is True:
        return "flagged"
    return status


def _counts(docs: list[dict[str, Any] | None]) -> dict[str, int]:
    counts = {"draft": 0, "flagged": 0, "published": 0, "archived": 0, "missing": 0}
    for doc in docs:
        counts[_state(doc)] += 1
    return counts


def _paper_sections(paper: dict[str, Any]) -> list[tuple[str, list[str]]]:
    out = []
    for section in paper.get("sections") or []:
        if isinstance(section, dict) and section.get("id") in SECTION_IDS:
            out.append((section["id"], [qid for qid in section.get("questionIds") or [] if isinstance(qid, str)]))
    return out


def _paper_payload(paper_id: str, paper: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sections = _paper_sections(paper)
    all_docs = [questions.get(qid) for _, ids in sections for qid in ids]
    counts = _counts(all_docs)
    return {
        "id": paper_id,
        "title": _paper_label(paper),
        "status": _status(paper),
        "examVersionYear": _int(paper.get("examVersionYear")),
        "year": _int(paper.get("year")),
        "slot": _int(paper.get("slot")),
        "questionCount": len(all_docs),
        "counts": counts,
        "sections": [
            {"id": sid, "questionCount": len(ids), "counts": _counts([questions.get(qid) for qid in ids])}
            for sid, ids in sections
        ],
        "readyToPublish": bool(all_docs) and counts["published"] == len(all_docs),
        "source": public_source(paper.get("source")) if isinstance(paper.get("source"), dict) else None,
        "updatedAt": _str(paper.get("updatedAt")),
        "publishedAt": _str(paper.get("publishedAt")),
        "publishedBy": _str(paper.get("publishedBy")),
    }


def _history(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for entry in doc.get("history") or []:
        if isinstance(entry, dict) and _int(entry.get("version")) is not None:
            out.append({
                "version": entry["version"],
                "editedBy": str(entry.get("editedBy") or ""),
                "editedAt": str(entry.get("editedAt") or ""),
                "changes": [str(c) for c in entry.get("changes") or []],
                "summary": str(entry.get("summary") or ""),
            })
    return out


def _admin_set(set_id: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    images = raw.get("images")
    return {
        "id": set_id,
        "kind": raw.get("kind") if raw.get("kind") in SET_KINDS else "passage",
        "title": _str(raw.get("title")),
        "contentHtml": raw.get("contentHtml") if isinstance(raw.get("contentHtml"), str) else "",
        "images": [img for img in images if isinstance(img, str)] if isinstance(images, list) else None,
        "version": _version(raw),
        "updatedAt": _str(raw.get("updatedAt")),
    }


def _admin_question(question_id: str, raw: dict[str, Any], sets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Full stored question for reviewers (includes the answer key and solution)."""
    qtype = "TITA" if raw.get("type") == "TITA" else "MCQ"
    options = None
    if qtype == "MCQ" and isinstance(raw.get("options"), list):
        options = [
            {"id": str(opt.get("id")), "textHtml": opt.get("textHtml") if isinstance(opt.get("textHtml"), str) else ""}
            for opt in raw["options"]
            if isinstance(opt, dict) and opt.get("id") is not None
        ]
    set_id = _str(raw.get("setId"))
    action = raw.get("reviewAction")
    return {
        "id": question_id,
        "key": _str(raw.get("key")),
        "paperId": _str(raw.get("paperId")),
        "section": raw.get("section") if raw.get("section") in SECTION_IDS else "VARC",
        "number": _int(raw.get("number")),
        "type": qtype,
        "stemHtml": raw.get("stemHtml") if isinstance(raw.get("stemHtml"), str) else "",
        "options": options,
        "setId": set_id,
        "set": _admin_set(set_id, sets.get(set_id)) if set_id else None,
        "topic": _str(raw.get("topic")),
        "subtopic": _str(raw.get("subtopic")),
        "difficulty": raw.get("difficulty") if raw.get("difficulty") in DIFFICULTIES else None,
        "correctAnswer": str(raw.get("correctAnswer") or ""),
        "solutionHtml": raw.get("solutionHtml") if isinstance(raw.get("solutionHtml"), str) else None,
        "source": public_source(raw.get("source")),
        "status": _status(raw),
        "flagged": _state(raw) == "flagged",
        "reviewAction": action if action in ("approved", "rejected", "flagged") else None,
        "reviewNote": _str(raw.get("reviewNote")),
        "reviewedBy": _str(raw.get("reviewedBy")),
        "reviewedAt": _str(raw.get("reviewedAt")),
        "version": _version(raw),
        "history": _history(raw),
        "updatedAt": _str(raw.get("updatedAt")),
    }


def _question_response(db: SafeFirestore, question_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    set_id = _str(raw.get("setId"))
    sets = {}
    if set_id:
        set_doc = get_doc(db, SETS, set_id)
        if set_doc is not None:
            sets[set_id] = set_doc
    return _admin_question(question_id, raw, sets)


def _paper_or_404(db: SafeFirestore, paper_id: str) -> dict[str, Any]:
    paper = get_doc(db, PAPERS, paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found.")
    return paper


def _paper_questions(db: SafeFirestore, paper_id: str) -> dict[str, dict[str, Any]]:
    return dict(query_eq(db, QUESTIONS, "paperId", paper_id))


# ---------------------------------------------------------------- validation (same rules as scripts/mba/paper_format.py)
def _validate_question(q: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not _str(q.get("stemHtml")):
        errors.append("stemHtml is required")
    answer = q.get("correctAnswer")
    if q.get("type") == "TITA":
        if q.get("options"):
            errors.append("TITA questions must not have options")
        if not _str(answer):
            errors.append("TITA answer is required")
        elif len(answer.strip()) > 50:
            errors.append("TITA answer is too long (max 50 characters)")
    else:
        options = q.get("options")
        if not isinstance(options, list) or len(options) < 2:
            errors.append("MCQ needs at least 2 options")
            options = []
        ids = []
        for j, opt in enumerate(options):
            opt_id = opt.get("id") if isinstance(opt, dict) else None
            if not isinstance(opt_id, str) or not OPTION_ID_RE.match(opt_id):
                errors.append(f"options[{j}].id must be a short alphanumeric id like 'A'")
                continue
            if not _str(opt.get("textHtml")):
                errors.append(f"options[{j}].textHtml is required")
            ids.append(opt_id)
        if len(ids) != len(set(ids)):
            errors.append("option ids must be unique")
        if not isinstance(answer, str) or answer.strip() not in ids:
            errors.append(f"answer must be one of the option ids {ids}")
    if q.get("difficulty") is not None and q.get("difficulty") not in DIFFICULTIES:
        errors.append(f"difficulty must be one of {sorted(DIFFICULTIES)}")
    return errors


def _describe(field: str, old: Any, new: Any) -> str:
    if field in SHORT_FIELDS:
        return f"{field}: {old if old not in (None, '') else '—'} → {new if new not in (None, '') else '—'}"
    if field == "options" and isinstance(old, list) and isinstance(new, list):
        old_ids = [o.get("id") for o in old if isinstance(o, dict)]
        new_ids = [o.get("id") for o in new if isinstance(o, dict)]
        return f"options edited ({', '.join(map(str, new_ids))})" if old_ids == new_ids else f"options {old_ids} → {new_ids}"
    return f"{field} edited"


def _edit(current: dict[str, Any], changes: dict[str, Any], admin: CurrentAdmin, expected: int | None) -> dict[str, Any] | None:
    """Fields to write for an edit (version + history), or None when nothing changed."""
    version = _version(current)
    if expected is not None and expected != version:
        raise HTTPException(409, f"This item was changed by someone else (now version {version}). Reload and try again.")
    changed = [field for field, value in changes.items() if current.get(field) != value]
    if not changed:
        return None
    now = iso(utcnow())
    entry = {
        "version": version + 1,
        "editedBy": admin.admin_id,
        "editedAt": now,
        "changes": changed,
        "summary": "; ".join(_describe(field, current.get(field), changes[field]) for field in changed),
    }
    history = [h for h in current.get("history") or [] if isinstance(h, dict)]
    return {
        **{field: changes[field] for field in changed},
        "version": version + 1,
        "history": [*history, entry][-HISTORY_LIMIT:],
        "updatedAt": now,
        "updatedBy": admin.admin_id,
    }


def _clean_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------- endpoints
@router.get("/papers", response_model=AdminPapersResponse)
def admin_list_papers(_admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    questions = dict(stream_all(db, QUESTIONS))
    papers = dict(stream_all(db, PAPERS))
    ordered = sorted(papers, key=lambda pid: _paper_sort({**papers[pid], "id": pid}))
    return {"papers": [_paper_payload(pid, papers[pid], questions) for pid in ordered]}


@router.get("/papers/{paper_id}/questions", response_model=AdminPaperQuestionsResponse)
def admin_paper_questions(paper_id: str, _admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    questions = _paper_questions(db, paper_id)
    sets = dict(query_eq(db, SETS, "paperId", paper_id))
    ordered = [qid for _, ids in _paper_sections(paper) for qid in ids if qid in questions]
    return {
        "paper": _paper_payload(paper_id, paper, questions),
        "questions": [_admin_question(qid, questions[qid], sets) for qid in ordered],
    }


@router.patch("/questions/{question_id}", response_model=AdminQuestion)
def admin_edit_question(
    question_id: str, body: QuestionEdit, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    sent = body.model_fields_set - {"expectedVersion"}
    if not sent:
        raise HTTPException(422, "Nothing to change.")
    changes: dict[str, Any] = {}
    if "stemHtml" in sent:
        changes["stemHtml"] = body.stemHtml
    if "options" in sent:
        changes["options"] = [{"id": opt.id.strip(), "textHtml": opt.textHtml} for opt in body.options] if body.options else None
    if "answer" in sent:
        answer = body.answer
        if isinstance(answer, float) and answer.is_integer():
            answer = int(answer)
        changes["correctAnswer"] = str(answer).strip() if answer is not None else None
    if "solutionHtml" in sent:
        changes["solutionHtml"] = body.solutionHtml if _str(body.solutionHtml) else None
    for field in ("topic", "subtopic"):
        if field in sent:
            changes[field] = _clean_text(getattr(body, field))
    if "difficulty" in sent:
        changes["difficulty"] = body.difficulty

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Question not found.")
        merged = {**current, **changes}
        errors = _validate_question(merged)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        fields = _edit(current, changes, admin, body.expectedVersion)
        return fields, {**current, **(fields or {})}

    updated = occ_update(db, QUESTIONS, question_id, mutate)
    invalidate_bank()
    return _question_response(db, question_id, updated)


@router.patch("/sets/{set_id}", response_model=AdminSet)
def admin_edit_set(set_id: str, body: SetEdit, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    sent = body.model_fields_set - {"expectedVersion"}
    if not sent:
        raise HTTPException(422, "Nothing to change.")
    changes: dict[str, Any] = {}
    if "contentHtml" in sent:
        if not _str(body.contentHtml):
            raise HTTPException(422, "contentHtml is required")
        changes["contentHtml"] = body.contentHtml
    if "title" in sent:
        changes["title"] = _clean_text(body.title)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Question set not found.")
        fields = _edit(current, changes, admin, body.expectedVersion)
        return fields, {**current, **(fields or {})}

    updated = occ_update(db, SETS, set_id, mutate)
    invalidate_bank()
    return _admin_set(set_id, updated)  # type: ignore[return-value]


@router.post("/questions/{question_id}/review", response_model=AdminQuestion)
def admin_review_question(
    question_id: str, body: ReviewInput, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    note = _clean_text(body.note)
    if body.action == "flag" and not note:
        raise HTTPException(422, "A note is required when flagging a question.")
    status, flagged, action = {
        "approve": ("published", False, "approved"),
        "reject": ("archived", False, "rejected"),
        "flag": ("draft", True, "flagged"),
    }[body.action]

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Question not found.")
        if body.action == "approve":
            errors = _validate_question(current)
            if errors:
                raise HTTPException(422, "Fix the question before approving: " + "; ".join(errors))
        now = iso(utcnow())
        fields = {
            "status": status, "flagged": flagged, "reviewAction": action, "reviewNote": note,
            "reviewedBy": admin.admin_id, "reviewedAt": now, "updatedAt": now,
        }
        return fields, {**current, **fields}

    updated = occ_update(db, QUESTIONS, question_id, mutate)
    invalidate_bank()
    return _question_response(db, question_id, updated)


def _set_paper_status(db: SafeFirestore, paper_id: str, admin: CurrentAdmin, publish: bool) -> dict[str, Any]:
    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Paper not found.")
        if _status(current) == ("published" if publish else "draft") and current.get("status") is not None:
            return None, current  # already in that state
        now = iso(utcnow())
        if publish:
            fields = {"status": "published", "publishedAt": now, "publishedBy": admin.admin_id, "updatedAt": now}
        else:
            fields = {"status": "draft", "unpublishedAt": now, "unpublishedBy": admin.admin_id, "updatedAt": now}
        return fields, {**current, **fields}

    paper = occ_update(db, PAPERS, paper_id, mutate)
    invalidate_bank()
    return paper


@router.post("/papers/{paper_id}/publish", response_model=AdminPaper)
def admin_publish_paper(paper_id: str, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    questions = _paper_questions(db, paper_id)
    payload = _paper_payload(paper_id, paper, questions)
    if not payload["readyToPublish"]:
        pending = payload["questionCount"] - payload["counts"]["published"]
        detail = "The paper has no questions." if not payload["questionCount"] else (
            f"{pending} of {payload['questionCount']} questions are not published yet."
        )
        raise HTTPException(409, detail)
    paper = _set_paper_status(db, paper_id, admin, publish=True)
    return _paper_payload(paper_id, paper, questions)


@router.post("/papers/{paper_id}/unpublish", response_model=AdminPaper)
def admin_unpublish_paper(paper_id: str, admin: CurrentAdmin = Depends(content_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _set_paper_status(db, paper_id, admin, publish=False)
    return _paper_payload(paper_id, paper, _paper_questions(db, paper_id))
