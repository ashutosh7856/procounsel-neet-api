"""Public exam/paper endpoints and test definitions derived from papers.

Tests are not stored: every offered paper yields one full mock (``{paperId}-full``)
and one sectional test per section (``{paperId}-{section}``). A paper is offered only
when the paper and ALL of its questions have status "published". Durations and
marking come from the exam version named by the paper's ``examVersionYear``
(falling back to its ``year`` for papers without one), so older patterns (60-minute
sections in 2017–19, 76 questions in 2020) need no special casing.

A paper is a previous-year paper (PYQ) when it has an integer ``year`` and ``slot`` and an
official source; everything else is a ProCounsel original.

Every exam (``paper.examId``: cat, xat, snap, nmat, cmat, mat, gmat, mah-mba-cet) is timed by
its version's ``timerBlocks``: sections in one block share one timer and the student moves
freely between them (SNAP: one 60-minute block; XAT: Part 1 = 170 minutes for three sections,
then GK). Without ``timerBlocks`` every section is its own block with its own
``durationMinutes`` (CAT, NMAT, GMAT). Sectional tests exist only for sections that are a block
on their own, since an exam with one shared timer states no per-section time.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .models import SECTION_IDS, Exam, ExamsResponse, PapersResponse, TestsResponse
from .scoring import marking_rule
from .public import public_source
from .schedule import is_open
from .scoring import pick_version
from .store import Bank, get_bank, utcnow

router = APIRouter()


def _exam_payload(exam_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return Exam.model_validate({**data, "id": exam_id}).model_dump()
    except Exception:  # noqa: BLE001 - malformed config is treated as missing
        return None


def exam_section_ids(bank: Bank, exam_id: str) -> tuple[str, ...]:
    """Every section id of the exam's config (CAT: always VARC/DILR/QA)."""
    if exam_id == "cat":
        return SECTION_IDS
    out: list[str] = []
    for version in (bank.exams.get(exam_id) or {}).get("versions") or []:
        for section in (version or {}).get("sections") or [] if isinstance(version, dict) else []:
            if isinstance(section, dict) and isinstance(section.get("id"), str) and section["id"] not in out:
                out.append(section["id"])
    return tuple(out)


def paper_sections(bank: Bank, paper: dict[str, Any]) -> list[tuple[str, list[str]]] | None:
    """Ordered (sectionId, [question ids]) for an offered paper; None unless every question is published."""
    out: list[tuple[str, list[str]]] = []
    valid = exam_section_ids(bank, paper.get("examId") or "cat")
    for section in paper.get("sections") or []:
        if not isinstance(section, dict) or section.get("id") not in valid:
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


def is_pyq(paper: dict[str, Any] | None) -> bool:
    """An actual past CAT paper: year + slot set and an official source."""
    paper = paper or {}
    source = paper.get("source") if isinstance(paper.get("source"), dict) else {}
    return _int_or_none(paper.get("year")) is not None and _int_or_none(paper.get("slot")) is not None \
        and source.get("kind") == "official"


TestSource = Literal["all", "pyq", "original"]


def source_matches(wanted: str, pyq: bool) -> bool:
    return wanted == "all" or (wanted == "pyq") == pyq


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


def timer_blocks(version: dict[str, Any], section_ids: list[str]) -> list[dict[str, Any]] | None:
    """The version's timer blocks restricted to ``section_ids`` (in block order), or None if any
    present section has no timer. Without ``timerBlocks`` each section is its own block."""
    durations = {s.get("id"): s.get("durationMinutes") for s in version.get("sections") or [] if isinstance(s, dict)}
    raw = version.get("timerBlocks")
    if not raw:
        raw = [{"id": sid, "sectionIds": [sid], "durationMinutes": durations.get(sid)} for sid in section_ids]
    present, blocks = set(section_ids), []
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            continue
        ids = [sid for sid in block.get("sectionIds") or [] if sid in present]
        minutes = _int_or_none(block.get("durationMinutes"))
        if not ids:
            continue
        if minutes is None or minutes <= 0:
            return None
        blocks.append({"id": str(block.get("id") or ids[0]), "name": block.get("name"), "sectionIds": ids, "durationMinutes": minutes})
    covered = [sid for block in blocks for sid in block["sectionIds"]]
    if sorted(covered) != sorted(section_ids):
        return None
    return blocks


def _marking_complete(bank: Bank, version: dict[str, Any], sections: list[tuple[str, list[str]]]) -> bool:
    """Every question type in every section has a marking rule (else the paper cannot be scored)."""
    for sid, ids in sections:
        for qtype in {str(bank.questions[qid].get("type") or "MCQ") for qid in ids}:
            try:
                marking_rule(version, qtype, sid)
            except ValueError:
                return False
    return True


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
        blocks = timer_blocks(version, [sid for sid, _ in sections])
        if not blocks or (exam_id != "cat" and not _marking_complete(bank, version, sections)):
            continue
        # Plan in block order (a block's sections in config order).
        by_id = dict(sections)
        sections = [(sid, by_id[sid]) for block in blocks for sid in block["sectionIds"]]
        label = _paper_label(paper)
        common = {"paperId": paper_id, "paperTitle": label, "examId": exam_id, "year": _int_or_none(paper.get("year")),
                  "slot": _int_or_none(paper.get("slot")), "isPyq": is_pyq(paper), "examVersionYear": version.get("year"),
                  "version": version, "locked": bool(version.get("sectionOrderLocked", True)),
                  "sectionOrderLocked": bool(version.get("sectionOrderLocked", True))}
        tests[f"{paper_id}-full"] = {
            **common,
            "id": f"{paper_id}-full",
            "title": f"{label} — Full mock",
            "kind": "full_mock",
            "sections": [sid for sid, _ in sections],
            "sectionPlan": [{"id": sid, "durationMinutes": durations.get(sid) or None, "questionIds": ids} for sid, ids in sections],
            "timerBlocks": blocks,
            "durationMinutes": sum(block["durationMinutes"] for block in blocks),
            "questionCount": sum(len(ids) for _, ids in sections),
        }
        for block in blocks:
            if len(block["sectionIds"]) != 1:
                continue  # shared timer: no official per-section time, so no sectional test
            sid = block["sectionIds"][0]
            ids = by_id[sid]
            tests[f"{paper_id}-{sid.lower()}"] = {
                **common,
                "id": f"{paper_id}-{sid.lower()}",
                "title": f"{label} — {sid} sectional",
                "kind": "sectional",
                "sections": [sid],
                "sectionPlan": [{"id": sid, "durationMinutes": block["durationMinutes"], "questionIds": ids}],
                "timerBlocks": [block],
                "durationMinutes": block["durationMinutes"],
                "questionCount": len(ids),
                "locked": True,
                "sectionOrderLocked": True,
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
    now = utcnow()
    papers = []
    for paper_id, paper in bank.papers.items():
        if (paper.get("examId") or "cat") != examId or not is_open(paper, now):  # schedule window (schedule.py)
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
            "isPyq": is_pyq(paper),
        })
    papers.sort(key=lambda p: _paper_sort(bank.papers[p["id"]]))
    return {"papers": papers}


def open_tests(bank: Bank) -> dict[str, dict[str, Any]]:
    """``derive_tests`` minus papers outside their schedule window (listing and starting a test)."""
    now = utcnow()
    return {tid: test for tid, test in derive_tests(bank).items() if is_open(bank.papers.get(test["paperId"]) or {}, now)}


TEST_SUMMARY_KEYS = ("id", "title", "kind", "paperId", "paperTitle", "sections", "durationMinutes", "questionCount",
                     "isPyq", "year", "slot", "examVersionYear", "examId", "timerBlocks", "sectionOrderLocked")


@router.get("/tests", response_model=TestsResponse)
def list_tests(
    source: TestSource = "all",
    examId: str = Query(default="cat", max_length=50),  # noqa: N803
    _user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    tests = open_tests(get_bank(db))
    return {"tests": [
        {key: test[key] for key in TEST_SUMMARY_KEYS} for test in tests.values()
        if source_matches(source, test["isPyq"]) and test["examId"] == examId
    ]}
