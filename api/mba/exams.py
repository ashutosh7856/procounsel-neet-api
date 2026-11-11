"""Public exam/paper endpoints and test definitions derived from papers.

Tests are not stored: every offered paper yields one full mock (``{paperId}-full``)
and one sectional test per section (``{paperId}-{section}``). A paper is offered only
when the paper and ALL of its questions have status "published". Durations and
marking come from the exam version named by the paper's ``examVersionYear``
(falling back to its ``year`` for papers without one).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .models import SECTION_IDS, Exam, ExamsResponse, PapersResponse, TestsResponse
from .public import public_source
from .scoring import pick_version
from .store import Bank, get_bank

router = APIRouter()


def _exam_payload(exam_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return Exam.model_validate({**data, "id": exam_id}).model_dump()
    except Exception:  # noqa: BLE001 - malformed config is treated as missing
        return None


def paper_sections(bank: Bank, paper: dict[str, Any]) -> list[tuple[str, list[str]]] | None:
    """Ordered (sectionId, [question ids]) for an offered paper; None unless every question is published."""
    out: list[tuple[str, list[str]]] = []
    for section in paper.get("sections") or []:
        if not isinstance(section, dict) or section.get("id") not in SECTION_IDS:
            continue
        ids = [qid for qid in section.get("questionIds") or [] if isinstance(qid, str)]
        if any(qid not in bank.questions for qid in ids):
            return None
        if ids:
            out.append((section["id"], ids))
    return out or None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def paper_version(bank: Bank, paper: dict[str, Any]) -> dict[str, Any] | None:
    exam = bank.exams.get(paper.get("examId") or "cat")
    wanted = _int_or_none(paper.get("examVersionYear"))
    if wanted is not None:  # explicit pattern year must exist exactly
        return next((v for v in (exam or {}).get("versions") or [] if isinstance(v, dict) and v.get("year") == wanted), None)
    return pick_version(exam, _int_or_none(paper.get("year")))


def _paper_sort(paper: dict[str, Any]) -> tuple[Any, ...]:
    year = _int_or_none(paper.get("year")) or _int_or_none(paper.get("examVersionYear")) or 0
    return (-year, _int_or_none(paper.get("slot")) or 0, str(paper.get("id")))


def _paper_label(paper: dict[str, Any]) -> str:
    if isinstance(paper.get("title"), str) and paper["title"].strip():
        return paper["title"].strip()
    parts = ["CAT", str(paper.get("year") or "Mock")]
    if paper.get("slot"):
        parts.append(f"Slot {paper['slot']}")
    return " ".join(part for part in parts if part)


def derive_tests(bank: Bank) -> dict[str, dict[str, Any]]:
    tests: dict[str, dict[str, Any]] = {}
    for paper_id in sorted(bank.papers, key=lambda pid: _paper_sort(bank.papers[pid])):
        paper = bank.papers[paper_id]
        exam_id = paper.get("examId") or "cat"
        version = paper_version(bank, paper)
        sections = paper_sections(bank, paper)
        if not version or not sections:
            continue
        durations = {s.get("id"): int(s.get("durationMinutes") or 0) for s in version.get("sections") or [] if isinstance(s, dict)}
        if any(durations.get(sid, 0) <= 0 for sid, _ in sections):
            continue
        common = {"paperId": paper_id, "examId": exam_id, "year": _int_or_none(paper.get("year")), "version": version,
                  "locked": bool(version.get("sectionOrderLocked", True))}
        label = _paper_label(paper)
        tests[f"{paper_id}-full"] = {
            **common,
            "id": f"{paper_id}-full",
            "title": f"{label} — Full mock",
            "kind": "full_mock",
            "sections": [sid for sid, _ in sections],
            "sectionPlan": [{"id": sid, "durationMinutes": durations[sid], "questionIds": ids} for sid, ids in sections],
            "durationMinutes": sum(durations[sid] for sid, _ in sections),
            "questionCount": sum(len(ids) for _, ids in sections),
        }
        for sid, ids in sections:
            tests[f"{paper_id}-{sid.lower()}"] = {
                **common,
                "id": f"{paper_id}-{sid.lower()}",
                "title": f"{label} — {sid} sectional",
                "kind": "sectional",
                "sections": [sid],
                "sectionPlan": [{"id": sid, "durationMinutes": durations[sid], "questionIds": ids}],
                "durationMinutes": durations[sid],
                "questionCount": len(ids),
            }
    return tests


@router.get("/exams", response_model=ExamsResponse)
def list_exams(db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    exams = [payload for exam_id, data in sorted(bank.exams.items()) if (payload := _exam_payload(exam_id, data))]
    return {"exams": exams}


@router.get("/exams/{exam_id}", response_model=Exam)
def get_exam(exam_id: str, db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    data = get_bank(db).exams.get(exam_id)
    payload = _exam_payload(exam_id, data) if data is not None else None
    if payload is None:
        raise HTTPException(404, "Exam not found.")
    return payload


@router.get("/papers", response_model=PapersResponse)
def list_papers(examId: str = Query(default="cat", max_length=50), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:  # noqa: N803
    bank = get_bank(db)
    papers = []
    for paper_id, paper in bank.papers.items():
        if (paper.get("examId") or "cat") != examId:
            continue
        sections = paper_sections(bank, paper)
        if not sections:
            continue
        version = paper_version(bank, paper)
        papers.append({
            "id": paper_id,
            "title": _paper_label(paper),
            "examVersionYear": version.get("year") if version else None,
            "year": _int_or_none(paper.get("year")),
            "slot": _int_or_none(paper.get("slot")),
            "questionCount": sum(len(ids) for _, ids in sections),
            "sections": [{"id": sid, "questionCount": len(ids)} for sid, ids in sections],
            "source": public_source(paper.get("source")) if isinstance(paper.get("source"), dict) else None,
        })
    papers.sort(key=lambda p: _paper_sort(bank.papers[p["id"]]))
    return {"papers": papers}


@router.get("/tests", response_model=TestsResponse)
def list_tests(_user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    tests = derive_tests(get_bank(db))
    return {"tests": [
        {key: test[key] for key in ("id", "title", "kind", "paperId", "sections", "durationMinutes", "questionCount")}
        for test in tests.values()
    ]}
