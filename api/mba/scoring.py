"""Pure, deterministic scoring (no I/O).

* MCQ: the answer is an option id; compared exactly after trimming.
* TITA: trimmed strings compared exactly; when both sides are plain decimal numbers
  (ASCII digits, optional sign and point — no exponents, separators or other digit
  scripts) they are compared numerically ("12" == "12.0" == "012", "1e1" != "10").
* Marks per question type come from the exam version's ``marking`` rules.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


def normalize_answer(answer: Any) -> str | None:
    if answer is None:
        return None
    text = str(answer).strip()
    return text or None


_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)")


def _number(text: str) -> Decimal | None:
    if not _DECIMAL_RE.fullmatch(text):
        return None
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def answers_match(qtype: str, given: Any, official: Any) -> bool:
    given_text, official_text = normalize_answer(given), normalize_answer(official)
    if given_text is None or official_text is None:
        return False
    if qtype == "TITA":
        given_num, official_num = _number(given_text), _number(official_text)
        if given_num is not None and official_num is not None:
            return given_num == official_num
    return given_text == official_text


def is_correct(question: dict[str, Any], answer: Any) -> bool | None:
    """True/False for an answer, None when unanswered."""
    if normalize_answer(answer) is None:
        return None
    return answers_match(str(question.get("type") or "MCQ"), answer, question.get("correctAnswer"))


def pick_version(exam: dict[str, Any] | None, year: int | None) -> dict[str, Any] | None:
    """Version for the paper's year; else the latest version not after it; else the latest."""
    versions = [v for v in (exam or {}).get("versions") or [] if isinstance(v, dict) and isinstance(v.get("year"), int)]
    if not versions:
        return None
    versions.sort(key=lambda v: v["year"])
    if year is not None:
        for version in versions:
            if version["year"] == year:
                return version
        earlier = [v for v in versions if v["year"] <= year]
        if earlier:
            return earlier[-1]
    return versions[-1]


def marking_rule(version: dict[str, Any] | None, qtype: str) -> dict[str, float]:
    for rule in (version or {}).get("marking") or []:
        if isinstance(rule, dict) and rule.get("type") == qtype:
            return {
                "correct": float(rule.get("correct") or 0),
                "incorrect": float(rule.get("incorrect") or 0),
                "unanswered": float(rule.get("unanswered") or 0),
            }
    raise ValueError(f"Exam version has no marking rule for {qtype} questions.")


def question_marks(question: dict[str, Any], answer: Any, version: dict[str, Any] | None) -> tuple[float, bool | None]:
    rule = marking_rule(version, str(question.get("type") or "MCQ"))
    correct = is_correct(question, answer)
    if correct is None:
        return rule["unanswered"], None
    return (rule["correct"] if correct else rule["incorrect"]), correct


def _clean(number: float) -> float:
    return int(number) if float(number).is_integer() else round(number, 4)


def score_attempt(
    sections: Iterable[tuple[str, list[dict[str, Any]]]],
    responses: dict[str, dict[str, Any]],
    version: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score responses.

    ``sections``: ordered ``(sectionId, [stored question dicts])``.
    ``responses``: questionId -> ``{answer, timeSpentMs, ...}``.
    Returns ``{score, maxScore, sections: [...], perQuestion: {qid: {marks, isCorrect}}}``.
    """
    total = total_max = 0.0
    section_rows: list[dict[str, Any]] = []
    per_question: dict[str, dict[str, Any]] = {}
    for section_id, questions in sections:
        score = max_score = 0.0
        correct_n = incorrect_n = unanswered_n = time_ms = 0
        for question in questions:
            qid = str(question.get("id"))
            response = responses.get(qid) or {}
            marks, correct = question_marks(question, response.get("answer"), version)
            max_score += marking_rule(version, str(question.get("type") or "MCQ"))["correct"]
            score += marks
            time_ms += int(response.get("timeSpentMs") or 0)
            if correct is None:
                unanswered_n += 1
            elif correct:
                correct_n += 1
            else:
                incorrect_n += 1
            per_question[qid] = {"marks": _clean(marks), "isCorrect": correct}
        attempted = correct_n + incorrect_n
        section_rows.append({
            "id": section_id,
            "score": _clean(score),
            "maxScore": _clean(max_score),
            "attempted": attempted,
            "correct": correct_n,
            "incorrect": incorrect_n,
            "unanswered": unanswered_n,
            "accuracy": round(correct_n / attempted, 4) if attempted else None,
            "timeSpentMs": time_ms,
        })
        total += score
        total_max += max_score
    return {"score": _clean(total), "maxScore": _clean(total_max), "sections": section_rows, "perQuestion": per_question}
