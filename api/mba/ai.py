"""AI tutor hints grounded in the stored question, its answer key and solution.

Env: OPENAI_API_KEY (required, else 503), OPENAI_MODEL (default gpt-4o-mini),
MBA_AI_DAILY_LIMIT (default 30 hints per student per India-time day, in mbaAiUsage).
"""

from __future__ import annotations

import html
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import live_question_ids
from .deps import student
from .models import HintInput, HintResponse
from .questions import get_question_or_404
from .stats import has_answered
from .store import AI_USAGE, STATS, get_bank, get_doc, iso, local_date, occ_update, stat_id, utcnow

router = APIRouter()

OPENAI_TIMEOUT_SECONDS = 30
DEFAULT_MODEL = "gpt-4o-mini"
LEVEL_GUIDE = {
    1: "Give a short NUDGE (1-3 sentences): point at the key idea or the first thing to notice. "
       "Do not reveal the answer, the correct option or the final computation.",
    2: "Explain the APPROACH (a short list of steps) the student should take, stopping before the final "
       "answer. Do not state the correct option or final value.",
    3: "Give the FULL worked explanation step by step, ending with the answer from the answer key. If the student's "
       "answer is wrong, explain briefly where that reasoning likely went wrong.",
}
MAX_TOKENS = {1: 200, 2: 450, 3: 900}

SYSTEM_PROMPT = (
    "You are a careful CAT (IIM Common Admission Test) tutor helping a student review a question they "
    "have already answered. Use ONLY the question, passage/set, options, answer key and reference "
    "solution provided. The answer key is authoritative: never contradict it, never suggest another "
    "answer is correct, and if your own working disagrees, follow the reference solution. Do not invent "
    "facts, data, formulas or passage content that are not given. If the material is not enough to "
    "explain something, say so plainly. Write plain text (no HTML), concise and encouraging."
)


def _daily_limit() -> int:
    try:
        return max(0, int(os.getenv("MBA_AI_DAILY_LIMIT", "30")))
    except ValueError:
        return 30


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<\s*br\s*/?>|</p>|</li>|</div>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", value)).strip()


def build_messages(question: dict[str, Any], question_set: dict[str, Any] | None, level: int, student_answer: str | None) -> list[dict[str, str]]:
    parts = [f"Section: {question.get('section')}  Type: {question.get('type')}"]
    if question.get("topic"):
        parts.append(f"Topic: {question.get('topic')}")
    if question_set:
        parts.append(f"Shared passage / set:\n{_text(question_set.get('contentHtml'))}")
    parts.append(f"Question:\n{_text(question.get('stemHtml'))}")
    if question.get("type") != "TITA":
        options = "\n".join(f"({o.get('id')}) {_text(o.get('textHtml'))}" for o in question.get("options") or [] if isinstance(o, dict))
        parts.append(f"Options:\n{options}")
    else:
        parts.append("This is a TITA (type-in-the-answer) question with no options.")
    parts.append(f"Answer key (authoritative): {question.get('correctAnswer')}")
    solution = _text(question.get("solutionHtml"))
    parts.append(f"Reference solution:\n{solution}" if solution else "Reference solution: (not available — rely only on the answer key and the question).")
    parts.append(f"Student's answer: {student_answer}" if student_answer else "Student's answer: (not given)")
    parts.append(f"Task (hint level {level} of 3): {LEVEL_GUIDE[level]}")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


def call_openai(messages: list[dict[str, str]], level: int) -> str:
    """Single Chat Completions call; isolated so it can be replaced in tests."""
    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            max_completion_tokens=MAX_TOKENS[level],
        )
    except OpenAIError as error:
        raise HTTPException(503, "The AI tutor is unavailable right now. Please try again.") from error
    text = (response.choices[0].message.content or "").strip() if response.choices else ""
    if not text:
        raise HTTPException(503, "The AI tutor returned no answer. Please try again.")
    return text


@router.post("/ai/hint", response_model=HintResponse)
def hint(body: HintInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "The AI tutor is not configured.")
    bank = get_bank(db)
    question = get_question_or_404(bank, body.questionId)
    stat = get_doc(db, STATS, stat_id(user.user_id, body.questionId))
    if not has_answered(stat) or body.questionId in live_question_ids(db, bank, user):
        raise HTTPException(403, "Hints are available only for questions you have already answered in practice or a submitted mock.")

    limit = _daily_limit()
    usage_id = f"{user.user_id}_{local_date().isoformat()}"
    used = int((get_doc(db, AI_USAGE, usage_id) or {}).get("count") or 0)
    if used >= limit:
        raise HTTPException(429, f"Daily AI hint limit reached ({limit}). It resets at midnight IST.")

    question_set = bank.sets.get(question["setId"]) if question.get("setId") else None
    student_answer = body.studentAnswer or (stat or {}).get("lastAnswer")
    text = call_openai(build_messages(question, question_set, body.level, student_answer), body.level)

    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
        count = int((current or {}).get("count") or 0) + 1
        doc = {"userId": user.user_id, "date": usage_id.rsplit("_", 1)[1], "count": count, "updatedAt": now}
        return doc, count

    count = occ_update(db, AI_USAGE, usage_id, mutate)
    return {"text": text, "level": body.level, "remainingToday": max(0, limit - count), "grounded": True}
