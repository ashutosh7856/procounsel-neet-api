"""Faculty/admin content review: ``/api/v1/mba/admin`` (contract: docs/mba-api.md).

Callers are Admin-panel users (``require_admin``: the Java admin login JWT whose
subject is an ``admins`` doc id) whose role has the needed capability (admin_roles.py:
content = questions/sets, tests = papers/publish; both may read).
Unlike the student endpoints this reads the database directly (all statuses), not
the published-only content bank, and invalidates the bank after every write.
Writes go only to ``mbaQuestions``, ``mbaQuestionSets`` and ``mbaPapers``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentAdmin
from api.db import SafeFirestore, get_db
from scripts.mba.paper_format import (
    DIFFICULTIES,
    SET_KINDS,
    PaperFormatError,
    build_paper_docs,
    check_question,
    check_set,
    content_from_docs,
    exam_versions,
    question_input,
    set_input,
)

from .admin_roles import content_editor, content_reader, test_manager

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
from .public import approaches, public_source
from .schedule import schedule_state
from .store import PAPERS, QUESTIONS, SETS, get_doc, invalidate_bank, iso, occ_update, query_eq, stream_all, utcnow

router = APIRouter(prefix="/admin")

HISTORY_LIMIT = 50
STATUSES = ("draft", "published", "archived")
SHORT_FIELDS = ("correctAnswer", "difficulty", "topic", "subtopic")  # shown as old -> new in history


# Kept for modules that imported it: any admin who may read MBA content (content or tests capability).
content_admin = content_reader


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


def _section_ok(doc: dict[str, Any], section: Any) -> bool:
    """CAT: VARC/DILR/QA; other exams: their own ids (checked against the exam config on import)."""
    if (doc.get("examId") or "cat") == "cat":
        return section in SECTION_IDS
    return isinstance(section, str) and bool(section)


def _paper_sections(paper: dict[str, Any]) -> list[tuple[str, list[str]]]:
    out = []
    for section in paper.get("sections") or []:
        if isinstance(section, dict) and _section_ok(paper, section.get("id")):
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
        "examId": _str(paper.get("examId")) or "cat",
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
        "version": _version(paper),
        "history": _history(paper),
        "availableFrom": _str(paper.get("availableFrom")),
        "availableUntil": _str(paper.get("availableUntil")),
        "schedule": schedule_state(paper, utcnow()),
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
        "key": _str(raw.get("key")),
        "section": raw.get("section") if _section_ok(raw, raw.get("section")) else None,
        "status": _status(raw),
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
        "section": raw.get("section") if _section_ok(raw, raw.get("section")) else "VARC",
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
        "alternativeApproaches": approaches(raw),
        "videoUrl": _str(raw.get("videoUrl")),
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


# ---------------------------------------------------------------- validation (scripts/mba/paper_format.py, not duplicated)
def _paper_context(paper_id: str | None, paper: dict[str, Any] | None) -> dict[str, Any]:
    """The ``check_paper`` context ``check_question`` needs, from a stored paper."""
    paper = paper or {}
    exam_id = paper.get("examId") or "cat"
    version_year = _int(paper.get("examVersionYear")) or _int(paper.get("year"))
    return {
        "id": paper_id or "", "examId": exam_id, "title": paper.get("title"),
        "year": _int(paper.get("year")), "slot": _int(paper.get("slot")),
        "examVersionYear": version_year,
        "source": paper.get("source") if isinstance(paper.get("source"), dict) else {},
        # The pattern version, so check_question also checks the marking rules (e.g. no TITA in XAT).
        "version": (exam_versions(exam_id) or {}).get(version_year) if version_year is not None else None,
    }


def _validate_question(db: SafeFirestore, q: dict[str, Any]) -> list[str]:
    """Problems with a stored (or about-to-be-stored) question, using the importer's own rules."""
    errors: list[str] = []
    set_docs: dict[str, dict[str, Any]] = {}
    set_keys: dict[str, str] = {}
    set_id = _str(q.get("setId"))
    if set_id:
        set_doc = get_doc(db, SETS, set_id)
        if set_doc is None or _status(set_doc) == "archived":
            errors.append(f"set {set_id} does not exist (or was deleted)")
        elif set_doc.get("paperId") != q.get("paperId"):
            errors.append("the set belongs to another paper")
        else:
            key = _str(set_doc.get("key")) or set_id
            set_keys[set_id] = key
            set_docs[key] = {"id": set_id, "section": set_doc.get("section")}
    paper_id = _str(q.get("paperId"))
    paper = get_doc(db, PAPERS, paper_id) if paper_id else None
    check_question(question_input(q, set_keys), "question", errors, [], _paper_context(paper_id, paper), set_docs)
    return errors


def _validate_set(s: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    check_set(set_input(s), "set", errors, _str(s.get("paperId")) or "", _str(s.get("examId")) or "cat")
    return errors


def paper_content(db: SafeFirestore, paper_id: str, paper: dict[str, Any]) -> dict[str, Any]:
    """The paper as importable content JSON (scripts/mba/paper_format.py): its sections' questions in order."""
    questions = _paper_questions(db, paper_id)
    ordered = [questions[qid] for _, ids in _paper_sections(paper) for qid in ids if qid in questions]
    used = {q.get("setId") for q in ordered}
    sets = [
        {**doc, "id": sid}
        for sid, doc in query_eq(db, SETS, "paperId", paper_id)
        if _status(doc) != "archived" or sid in used
    ]
    return content_from_docs({**paper, "id": paper_id}, sets, ordered)


def validate_paper(db: SafeFirestore, paper_id: str, paper: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) of the whole paper, exactly as the importer would report them."""
    try:
        _, _, _, warnings = build_paper_docs(paper_content(db, paper_id, paper))
    except PaperFormatError as error:
        return error.errors, []
    return [], warnings


def _describe(field: str, old: Any, new: Any) -> str:
    if field in SHORT_FIELDS:
        return f"{field}: {old if old not in (None, '') else '—'} → {new if new not in (None, '') else '—'}"
    if field == "options" and isinstance(old, list) and isinstance(new, list):
        old_ids = [o.get("id") for o in old if isinstance(o, dict)]
        new_ids = [o.get("id") for o in new if isinstance(o, dict)]
        return f"options edited ({', '.join(map(str, new_ids))})" if old_ids == new_ids else f"options {old_ids} → {new_ids}"
    return f"{field} edited"


def _edit(
    current: dict[str, Any], changes: dict[str, Any], admin: CurrentAdmin, expected: int | None, summary: str | None = None
) -> dict[str, Any] | None:
    """Fields to write for an edit (version + history), or None when nothing changed.

    ``summary`` replaces the generated per-field summary (e.g. "added VARC-05")."""
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
        "summary": summary or "; ".join(_describe(field, current.get(field), changes[field]) for field in changed),
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
def admin_list_papers(
    examId: str | None = Query(default=None, max_length=50),  # noqa: N803 - None = every exam
    _admin: CurrentAdmin = Depends(content_reader),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    questions = dict(stream_all(db, QUESTIONS))
    papers = {pid: doc for pid, doc in stream_all(db, PAPERS) if examId is None or (doc.get("examId") or "cat") == examId}
    ordered = sorted(papers, key=lambda pid: _paper_sort({**papers[pid], "id": pid}))
    return {"papers": [_paper_payload(pid, papers[pid], questions) for pid in ordered]}


@router.get("/papers/{paper_id}/questions", response_model=AdminPaperQuestionsResponse)
def admin_paper_questions(paper_id: str, _admin: CurrentAdmin = Depends(content_reader), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    questions = _paper_questions(db, paper_id)
    sets = dict(query_eq(db, SETS, "paperId", paper_id))
    ordered = [qid for _, ids in _paper_sections(paper) for qid in ids if qid in questions]
    return {
        "paper": _paper_payload(paper_id, paper, questions),
        "questions": [_admin_question(qid, questions[qid], sets) for qid in ordered],
        "sets": [_admin_set(sid, sets[sid]) for sid in sorted(sets) if _status(sets[sid]) != "archived"],
    }


@router.patch("/questions/{question_id}", response_model=AdminQuestion)
def admin_edit_question(
    question_id: str, body: QuestionEdit, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)
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
    if "alternativeApproaches" in sent:
        changes["alternativeApproaches"] = [a for a in body.alternativeApproaches or [] if _str(a)] or None
    if "videoUrl" in sent:
        changes["videoUrl"] = _clean_text(body.videoUrl)
    for field in ("topic", "subtopic"):
        if field in sent:
            changes[field] = _clean_text(getattr(body, field))
    if "difficulty" in sent:
        changes["difficulty"] = body.difficulty
    if "type" in sent:
        if body.type is None:
            raise HTTPException(422, "type cannot be null")
        changes["type"] = body.type
    if "setId" in sent:
        changes["setId"] = _clean_text(body.setId)
    if "source" in sent:
        if body.source is None:
            raise HTTPException(422, "source cannot be null")
        changes["source"] = body.source.model_dump(exclude_none=True)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Question not found.")
        merged = {**current, **changes}
        if merged.get("type") == "TITA" and "options" not in sent:
            merged["options"] = changes["options"] = None  # switching to TITA drops the options
        errors = _validate_question(db, merged)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        fields = _edit(current, changes, admin, body.expectedVersion)
        return fields, {**current, **(fields or {})}

    updated = occ_update(db, QUESTIONS, question_id, mutate)
    invalidate_bank()
    return _question_response(db, question_id, updated)


@router.patch("/sets/{set_id}", response_model=AdminSet)
def admin_edit_set(set_id: str, body: SetEdit, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
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
    if "kind" in sent:
        if body.kind is None:
            raise HTTPException(422, "kind cannot be null")
        changes["kind"] = body.kind
    if "images" in sent:
        changes["images"] = [img.strip() for img in body.images or [] if img.strip()]

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Question set not found.")
        errors = _validate_set({**current, **changes})
        if errors:
            raise HTTPException(422, "; ".join(errors))
        fields = _edit(current, changes, admin, body.expectedVersion)
        return fields, {**current, **(fields or {})}

    updated = occ_update(db, SETS, set_id, mutate)
    invalidate_bank()
    return _admin_set(set_id, updated)  # type: ignore[return-value]


@router.post("/questions/{question_id}/review", response_model=AdminQuestion)
def admin_review_question(
    question_id: str, body: ReviewInput, admin: CurrentAdmin = Depends(content_editor), db: SafeFirestore = Depends(get_db)
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
            errors = _validate_question(db, current)
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
def admin_publish_paper(paper_id: str, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _paper_or_404(db, paper_id)
    questions = _paper_questions(db, paper_id)
    payload = _paper_payload(paper_id, paper, questions)
    if not payload["readyToPublish"]:
        pending = payload["questionCount"] - payload["counts"]["published"]
        detail = "The paper has no questions." if not payload["questionCount"] else (
            f"{pending} of {payload['questionCount']} questions are not published yet."
        )
        raise HTTPException(409, detail)
    errors, _warnings = validate_paper(db, paper_id, paper)
    if errors:
        raise HTTPException(422, "Fix the paper before publishing: " + "; ".join(errors[:20]))
    paper = _set_paper_status(db, paper_id, admin, publish=True)
    return _paper_payload(paper_id, paper, questions)


@router.post("/papers/{paper_id}/unpublish", response_model=AdminPaper)
def admin_unpublish_paper(paper_id: str, admin: CurrentAdmin = Depends(test_manager), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    paper = _set_paper_status(db, paper_id, admin, publish=False)
    return _paper_payload(paper_id, paper, _paper_questions(db, paper_id))
