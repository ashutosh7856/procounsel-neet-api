"""Weakness detector: ``GET /me/insights`` (contract: docs/mba-api.md → "Insights").

Topic accuracy comes from ``mbaQuestionStats`` (every practice, daily and submitted-mock answer
is counted there); average time per question comes from the student's submitted attempts (the
only place time per question is recorded). A topic is called weak only with enough evidence
(``MIN_EVIDENCE`` answers); below that it is labelled low-confidence and never flagged.

``examId`` (default ``cat``) limits topics and the score trend to one exam.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .analysis import practice_href
from .attempts import _plan, user_attempts
from .deps import student
from .exams import exam_section_ids
from .models import ExamSectionId
from .scoring import normalize_answer
from .stats import has_answered
from .store import get_bank, user_stats

router = APIRouter()

MIN_EVIDENCE = 8
WEAK_BELOW = 0.6
STRONG_FROM = 0.8
TREND_ATTEMPTS = 5
MAX_WEAK = 5


class TopicInsight(BaseModel):
    section: ExamSectionId
    topic: str
    questions: int
    attempts: int
    correct: int
    accuracy: float | None
    avgTimeMs: int | None
    timedAnswers: int
    confidence: Literal["sufficient", "low"]
    status: Literal["weak", "ok", "strong", "low_evidence"]
    href: str


class TrendSection(BaseModel):
    id: ExamSectionId
    score: float
    maxScore: float
    accuracy: float | None


class TrendPoint(BaseModel):
    attemptId: str
    title: str
    kind: str
    submittedAt: str
    score: float
    maxScore: float
    sections: list[TrendSection]


class InsightsRules(BaseModel):
    minAttempts: int
    weakBelow: float
    strongFrom: float


class InsightsResponse(BaseModel):
    topics: list[TopicInsight]
    weakTopics: list[TopicInsight]
    lowEvidenceCount: int
    trend: list[TrendPoint]
    rules: InsightsRules


def _status(attempts: int, accuracy: float | None) -> str:
    if attempts < MIN_EVIDENCE or accuracy is None:
        return "low_evidence"
    if accuracy < WEAK_BELOW:
        return "weak"
    return "strong" if accuracy >= STRONG_FROM else "ok"


@router.get("/me/insights", response_model=InsightsResponse)
def insights(
    examId: str = Query(default="cat", max_length=50),  # noqa: N803
    user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    bank = get_bank(db)
    stats = user_stats(db, user.user_id)
    section_ids = exam_section_ids(bank, examId)
    submitted = [a for a in user_attempts(db, bank, user)
                 if a.get("status") == "submitted" and (a.get("examId") or "cat") == examId]

    def key_of(question: dict[str, Any]) -> tuple[str, str] | None:
        topic = question.get("topic")
        if (question.get("examId") or "cat") != examId or question.get("section") not in section_ids \
                or not isinstance(topic, str) or not topic.strip():
            return None
        return question["section"], topic.strip()

    rows: dict[tuple[str, str], dict[str, int]] = {}
    for qid, stat in stats.items():
        question = bank.questions.get(qid)
        key = key_of(question) if question and has_answered(stat) else None
        if key is None:
            continue
        row = rows.setdefault(key, {"questions": 0, "attempts": 0, "correct": 0, "timeMs": 0, "timed": 0})
        row["questions"] += 1
        row["attempts"] += max(0, int(stat.get("attempts") or 0))
        row["correct"] += max(0, int(stat.get("correct") or 0))

    for att in submitted:
        responses = att.get("responses") or {}
        for section in _plan(att):
            for qid in section.get("questionIds") or []:
                response = responses.get(qid)
                question = bank.questions.get(qid)
                if not isinstance(response, dict) or question is None or normalize_answer(response.get("answer")) is None:
                    continue
                key = key_of(question)
                time_ms = int(response.get("timeSpentMs") or 0)
                if key in rows and time_ms > 0:
                    rows[key]["timeMs"] += time_ms
                    rows[key]["timed"] += 1

    topics = []
    for (section, topic), row in rows.items():
        accuracy = round(row["correct"] / row["attempts"], 4) if row["attempts"] else None
        topics.append({
            "section": section, "topic": topic, "questions": row["questions"], "attempts": row["attempts"],
            "correct": row["correct"], "accuracy": accuracy,
            "avgTimeMs": row["timeMs"] // row["timed"] if row["timed"] else None, "timedAnswers": row["timed"],
            "confidence": "sufficient" if row["attempts"] >= MIN_EVIDENCE else "low",
            "status": _status(row["attempts"], accuracy), "href": practice_href(section, topic, exam=examId),
        })
    topics.sort(key=lambda t: (section_ids.index(t["section"]), t["topic"].lower()))
    weak = sorted((t for t in topics if t["status"] == "weak"), key=lambda t: (t["accuracy"] or 0, -t["attempts"]))

    trend = []
    for att in sorted(submitted, key=lambda a: (str(a.get("submittedAt") or ""), str(a.get("startedAt") or "")))[-TREND_ATTEMPTS:]:
        result = att.get("result") or {}
        trend.append({
            "attemptId": att["id"], "title": att.get("title") or "", "kind": att.get("kind") or "",
            "submittedAt": att.get("submittedAt") or "", "score": result.get("score", 0), "maxScore": result.get("maxScore", 0),
            "sections": [
                {"id": s["id"], "score": s.get("score", 0), "maxScore": s.get("maxScore", 0), "accuracy": s.get("accuracy")}
                for s in result.get("sections") or [] if isinstance(s, dict) and s.get("id") in section_ids
            ],
        })

    return {
        "topics": topics,
        "weakTopics": weak[:MAX_WEAK],
        "lowEvidenceCount": sum(1 for t in topics if t["status"] == "low_evidence"),
        "trend": trend,
        "rules": {"minAttempts": MIN_EVIDENCE, "weakBelow": WEAK_BELOW, "strongFrom": STRONG_FROM},
    }
