"""Previous-year CAT papers with the student's progress: ``GET /me/pyq`` (contract: docs/mba-api.md → "PYQs").

Lists every offered previous-year paper (``exams.is_pyq``) newest year first, with its full paper
and sectional tests (the same derived tests ``POST /attempts`` starts), and per test the student's
attempts, best score and standing among ProCounsel students (``score_stats``).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import user_attempts
from .deps import student
from .exams import derive_tests
from .models import ProcounselPercentile, SectionId, Source
from .public import public_source
from .score_stats import MIN_OTHER_STUDENTS, PERCENTILE_NOTE, all_test_stats, own_counted_score, percentile
from .store import get_bank

router = APIRouter()


class PyqTest(BaseModel):
    testId: str
    kind: Literal["full_mock", "sectional"]
    title: str
    sections: list[SectionId]
    durationMinutes: int
    questionCount: int
    attempts: int  # submitted attempts
    inProgressAttemptId: str | None
    lastAttemptId: str | None  # latest submitted attempt (for the result link)
    bestScore: float | None
    firstScore: float | None
    maxScore: float | None
    takenBy: int  # ProCounsel students with a first attempt of this test
    procounselPercentile: ProcounselPercentile | None  # of the student's first attempt


class PyqSection(BaseModel):
    id: SectionId
    questionCount: int
    durationMinutes: int


class PyqPaper(BaseModel):
    paperId: str
    title: str
    year: int
    slot: int
    examVersionYear: int | None
    questionCount: int
    durationMinutes: int
    sections: list[PyqSection]
    source: Source | None
    tests: list[PyqTest]


class PyqResponse(BaseModel):
    papers: list[PyqPaper]
    minStudents: int
    percentileNote: str


@router.get("/me/pyq", response_model=PyqResponse)
def my_pyq(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    tests = [t for t in derive_tests(bank).values() if t["isPyq"]]
    attempts = user_attempts(db, bank, user)
    stats = all_test_stats(db) if tests else {}
    by_test: dict[str, list[dict[str, Any]]] = {}
    for att in attempts:
        by_test.setdefault(att.get("testId") or "", []).append(att)

    papers: dict[str, dict[str, Any]] = {}
    for test in tests:  # derive_tests is already sorted newest year first, then slot
        paper = papers.get(test["paperId"])
        if paper is None:
            raw = bank.papers[test["paperId"]]
            paper = papers[test["paperId"]] = {
                "paperId": test["paperId"], "title": test["paperTitle"], "year": test["year"], "slot": test["slot"],
                "examVersionYear": test["examVersionYear"], "questionCount": 0, "durationMinutes": 0, "sections": [],
                "source": public_source(raw.get("source")) if isinstance(raw.get("source"), dict) else None, "tests": [],
            }
        if test["kind"] == "full_mock":
            paper["questionCount"] = test["questionCount"]
            paper["durationMinutes"] = test["durationMinutes"]
            paper["sections"] = [
                {"id": s["id"], "questionCount": len(s["questionIds"]), "durationMinutes": s["durationMinutes"]}
                for s in test["sectionPlan"]
            ]
        own = by_test.get(test["id"], [])
        submitted = sorted((a for a in own if a.get("status") == "submitted"), key=lambda a: str(a.get("submittedAt") or ""))
        running = next((a for a in own if a.get("status") == "in_progress"), None)
        scores = [float((a.get("result") or {}).get("score") or 0) for a in submitted]
        first = scores[0] if scores else None
        test_doc = stats.get(test["id"])
        paper["tests"].append({
            "testId": test["id"], "kind": test["kind"], "title": test["title"], "sections": test["sections"],
            "durationMinutes": test["durationMinutes"], "questionCount": test["questionCount"],
            "attempts": len(submitted), "inProgressAttemptId": running["id"] if running else None,
            "lastAttemptId": submitted[-1]["id"] if submitted else None,
            "bestScore": max(scores) if scores else None, "firstScore": first,
            "maxScore": (submitted[0].get("result") or {}).get("maxScore") if submitted else None,
            "takenBy": int((test_doc or {}).get("count") or 0),
            "procounselPercentile": percentile(test_doc, first, own_counted_score(own, test["id"])) if first is not None else None,
        })
    return {"papers": list(papers.values()), "minStudents": MIN_OTHER_STUDENTS, "percentileNote": PERCENTILE_NOTE}
