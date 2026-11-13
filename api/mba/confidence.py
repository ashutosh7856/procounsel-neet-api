"""Self-rated confidence (contract: docs/mba-api.md → "Practice modes").

A student may rate any practice or attempt answer ``sure`` / ``unsure`` / ``guess`` (optional).
The rating is stored with the answer (attempt ``responses[qid].confidence``) and counted into the
student's ``mbaQuestionStats`` doc (``confidenceCounts.{level}.{answers,correct}`` +
``lastConfidence``) whenever the answer itself is counted there (practice answers, submitted attempts).

``GET /me/confidence`` turns those counters into a calibration summary: how often "sure" answers
were right, lucky guesses (right answers rated "guess") and "sure but wrong" answers by topic.
Questions whose latest answer was a lucky guess are offered again by the weak-topic set (drills.py).
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .models import SECTION_IDS, ConfidenceBucket, SectionId
from .stats import has_answered
from .store import get_bank, user_stats

router = APIRouter()

LEVELS: tuple[str, ...] = ("sure", "unsure", "guess")
MAX_TOPICS = 5


def clean_confidence(value: Any) -> str | None:
    return value if value in LEVELS else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def apply_confidence(doc: dict[str, Any], confidence: Any, correct: bool) -> dict[str, Any]:
    """Count one rated answer into a stats doc (after ``stats.apply_answer``). Unrated answers only reset ``lastConfidence``."""
    level = clean_confidence(confidence)
    doc["lastConfidence"] = level
    if level is None:
        return doc
    counts = {k: dict(v) for k, v in (doc.get("confidenceCounts") or {}).items() if k in LEVELS and isinstance(v, dict)}
    row = counts.setdefault(level, {})
    row["answers"] = _int(row.get("answers")) + 1
    row["correct"] = _int(row.get("correct")) + (1 if correct else 0)
    counts[level] = row
    doc["confidenceCounts"] = counts
    return doc


def is_lucky_guess(stat: dict[str, Any] | None) -> bool:
    """The latest answer was right but rated "guess"."""
    return bool(stat) and stat.get("lastConfidence") == "guess" and stat.get("lastCorrect") is True


def breakdown(rows: Iterable[tuple[Any, bool | None]]) -> dict[str, dict[str, int]]:
    """ConfidenceBreakdown from (confidence, isCorrect) of ANSWERED questions (isCorrect None = skipped, ignored)."""
    out = {key: {"answered": 0, "correct": 0, "incorrect": 0} for key in (*LEVELS, "unrated")}
    for confidence, correct in rows:
        if correct is None:
            continue
        row = out[clean_confidence(confidence) or "unrated"]
        row["answered"] += 1
        row["correct" if correct else "incorrect"] += 1
    return out


# ---------------------------------------------------------------- GET /me/confidence
class LevelSummary(BaseModel):
    level: Literal["sure", "unsure", "guess"]
    answers: int
    correct: int
    accuracy: float | None


class ConfidenceTopic(BaseModel):
    section: SectionId
    topic: str
    sureButWrong: int
    luckyGuesses: int
    href: str


class ConfidenceSummary(BaseModel):
    levels: list[LevelSummary]
    ratedAnswers: int
    unratedAnswers: int
    sureButWrong: int  # answers rated "sure" that were wrong
    luckyGuesses: int  # answers rated "guess" that were right
    luckyGuessQuestions: int  # questions whose latest answer was a lucky guess (offered again in weak-topic sets)
    topics: list[ConfidenceTopic]  # most "sure but wrong" first, max 5
    totals: ConfidenceBucket


@router.get("/me/confidence", response_model=ConfidenceSummary)
def my_confidence(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    from .analysis import practice_href  # local: analysis imports attempts, which imports this module

    bank = get_bank(db)
    levels = {level: {"answers": 0, "correct": 0} for level in LEVELS}
    total_answers = total_correct = lucky_questions = 0
    topics: dict[tuple[str, str], dict[str, int]] = {}
    for qid, stat in user_stats(db, user.user_id).items():
        if not has_answered(stat):
            continue
        total_answers += _int(stat.get("attempts"))
        total_correct += _int(stat.get("correct"))
        lucky_questions += 1 if is_lucky_guess(stat) else 0
        counts = stat.get("confidenceCounts") if isinstance(stat.get("confidenceCounts"), dict) else {}
        question = bank.questions.get(qid) or {}
        topic = question.get("topic")
        key = (question["section"], topic.strip()) if question.get("section") in SECTION_IDS and isinstance(topic, str) and topic.strip() else None
        for level in LEVELS:
            row = counts.get(level) if isinstance(counts.get(level), dict) else {}
            answers, correct = _int(row.get("answers")), _int(row.get("correct"))
            correct = min(correct, answers)
            levels[level]["answers"] += answers
            levels[level]["correct"] += correct
            if key and level in ("sure", "guess"):
                t = topics.setdefault(key, {"sureButWrong": 0, "luckyGuesses": 0})
                t["sureButWrong" if level == "sure" else "luckyGuesses"] += (answers - correct) if level == "sure" else correct

    rated = sum(v["answers"] for v in levels.values())
    topic_rows = [
        {"section": s, "topic": t, **row, "href": practice_href(s, t)}
        for (s, t), row in topics.items() if row["sureButWrong"] or row["luckyGuesses"]
    ]
    topic_rows.sort(key=lambda r: (-r["sureButWrong"], -r["luckyGuesses"], SECTION_IDS.index(r["section"]), r["topic"].lower()))
    return {
        "levels": [
            {"level": level, **v, "accuracy": round(v["correct"] / v["answers"], 4) if v["answers"] else None}
            for level, v in levels.items()
        ],
        "ratedAnswers": rated,
        "unratedAnswers": max(0, total_answers - rated),
        "sureButWrong": levels["sure"]["answers"] - levels["sure"]["correct"],
        "luckyGuesses": levels["guess"]["correct"],
        "luckyGuessQuestions": lucky_questions,
        "topics": topic_rows[:MAX_TOPICS],
        "totals": {"answered": total_answers, "correct": total_correct, "incorrect": max(0, total_answers - total_correct)},
    }
