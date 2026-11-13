"""AI section coaches (VARC / DILR / Quant) and "Explain my plan" (contract: docs/mba-api.md → "AI section coaches").

Each coach is a short chat scoped to one CAT section, with a section-specific system prompt.
The model sees only this student's own data for that section: topic accuracy (same rules as
insights.py), the topics of their recent mistakes and, when there is enough data, the section's
score estimate (estimate.py). Never other students' data.

Guardrails:
* Off-topic requests and official facts (dates, pattern, cut-offs, fees) are refused by the
  prompt, which points to the app's official pages instead of letting the model guess.
* Questions of a running test: while a test is in progress the prompt forbids solving or
  hinting any specific question, and a message that quotes a live question (8+ consecutive
  words of its stem, options or passage) is refused before any model call (no quota used).

Chats live in ``mbaCoachChats/{userId}_{coach}``: only the last ``MAX_STORED_TURNS`` turns, and
turns older than ``CHAT_TTL_DAYS`` are dropped; the student can delete a chat at any time.
``{userId}_plan`` caches the last plan explanation (re-used while the week's plan is unchanged).

Every model call counts against the shared daily AI quota (``mbaAiUsage``, ``MBA_AI_DAILY_LIMIT``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .ai import DEFAULT_MODEL, OPENAI_TIMEOUT_SECONDS, _daily_limit, _text
from .attempts import _question_section, user_attempts
from .deps import student
from .estimate import estimate
from .insights import _status
from .planner import _week_param, build_week_response
from .stats import has_answered
from .store import AI_USAGE, Bank, get_bank, get_doc, iso, local_date, occ_update, parse_iso, user_stats, utcnow

router = APIRouter()

CHATS = "mbaCoachChats"
CoachId = Literal["varc", "dilr", "quant"]
COACHES: dict[str, dict[str, str]] = {
    "varc": {"section": "VARC", "name": "VARC coach", "full": "Verbal Ability & Reading Comprehension"},
    "dilr": {"section": "DILR", "name": "DILR coach", "full": "Data Interpretation & Logical Reasoning"},
    "quant": {"section": "QA", "name": "Quant coach", "full": "Quantitative Ability"},
}
MAX_STORED_TURNS = 20      # 10 exchanges kept per student per coach
MODEL_TURNS = 12           # history sent to the model
CHAT_TTL_DAYS = 7          # older turns are dropped
MAX_MESSAGE_CHARS = 1500
REPLY_TOKENS = 700
PLAN_TOKENS = 500
LIVE_SHINGLE_WORDS = 8     # a message sharing this many consecutive words with a live question is refused
MAX_TOPICS = 15
MAX_MISTAKE_TOPICS = 6

# App pages the coaches point to instead of stating official facts (Website routes).
OFFICIAL_PAGES = (
    "CAT exam pattern and dates: /mba-entrance-exams/cat",
    "IIM cut-offs (official): /mba-colleges/iim-cutoffs",
    "Admission deadlines: /mba-admission-deadlines",
    "College details and eligibility: /mba/colleges",
)

FOCUS = {
    "varc": (
        "Your focus: reading-comprehension strategy (reading for structure and the author's view, choosing passages, "
        "and the question types: main idea, inference, specific detail and EXCEPT, tone, strengthen/weaken, application, "
        "function of examples); verbal-ability methods (para-jumbles via mandatory pairs and the opening sentence, "
        "odd sentence out, para summary, sentence placement); vocabulary in context; reading habits."
    ),
    "dilr": (
        "Your focus: set selection (scan the sets first, judge each by data volume, number of conditions and familiarity, "
        "and leave a set that does not open up), building grids and tables from the clues, splitting into cases, and "
        "approaches for arrangements, scheduling, distributions, tournaments, Venn-based sets, networks and data "
        "interpretation (tables and charts, quick percentage and ratio estimation)."
    ),
    "quant": (
        "Your focus: clear concept explanations (arithmetic, algebra, number system, geometry, modern maths), "
        "shortcuts together with when they do and do not apply, checking the student's working step by step and naming "
        "the exact step that went wrong, and question selection (easy ones first, skipping time sinks)."
    ),
}


# ---------------------------------------------------------------- models
class CoachTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    at: str


class CoachTopic(BaseModel):
    topic: str
    attempts: int
    correct: int
    accuracy: float | None
    status: Literal["weak", "ok", "strong", "low_evidence"]


class CoachEstimate(BaseModel):
    expected: float
    low: int
    high: int
    maxScore: float
    confidence: Literal["low", "medium", "high"] | None


class CoachContext(BaseModel):
    """Exactly what the coach is told about the student (shown in the app as "What your coach sees")."""

    topics: list[CoachTopic]
    recentMistakeTopics: list[str]
    estimate: CoachEstimate | None
    inRunningTest: bool


class CoachChat(BaseModel):
    coach: CoachId
    section: Literal["VARC", "DILR", "QA"]
    title: str
    turns: list[CoachTurn]
    context: CoachContext
    dailyLimit: int
    remainingToday: int
    configured: bool  # False: OPENAI_API_KEY missing, sending returns 503


class CoachMessageInput(BaseModel):
    model_config = {"extra": "forbid"}

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class DeletedResponse(BaseModel):
    deleted: bool


class PlanExplanation(BaseModel):
    weekStart: str
    text: str
    generatedAt: str
    cached: bool
    remainingToday: int | None


class PlanExplanationResponse(BaseModel):
    explanation: PlanExplanation | None


# ---------------------------------------------------------------- helpers
def chat_id(user_id: str, coach: str) -> str:
    return f"{user_id}_{coach}"


def _fresh_turns(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Stored turns minus the ones older than CHAT_TTL_DAYS (short-lived chats)."""
    cutoff = utcnow() - timedelta(days=CHAT_TTL_DAYS)
    turns = []
    for turn in (doc or {}).get("turns") or []:
        if not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant") or not isinstance(turn.get("text"), str):
            continue
        at = parse_iso(turn.get("at"))
        if at is None or at < cutoff:
            continue
        turns.append({"role": turn["role"], "text": turn["text"], "at": turn["at"]})
    return turns[-MAX_STORED_TURNS:]


def _usage_id(user: CurrentUser) -> str:
    return f"{user.user_id}_{local_date().isoformat()}"


def _used_today(db: SafeFirestore, user: CurrentUser) -> int:
    return int((get_doc(db, AI_USAGE, _usage_id(user)) or {}).get("count") or 0)


def _check_quota(db: SafeFirestore, user: CurrentUser) -> int:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "The AI coach is not configured.")
    limit = _daily_limit()
    if _used_today(db, user) >= limit:
        raise HTTPException(429, f"Daily AI limit reached ({limit}). It resets at midnight IST.")
    return limit


def _count_usage(db: SafeFirestore, user: CurrentUser) -> int:
    """Count one AI call in the shared daily quota; returns today's total."""
    usage_id, now = _usage_id(user), iso(utcnow())

    def bump(current: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
        n = int((current or {}).get("count") or 0) + 1
        return {"userId": user.user_id, "date": usage_id.rsplit("_", 1)[1], "count": n, "updatedAt": now}, n

    return occ_update(db, AI_USAGE, usage_id, bump)


def call_model(messages: list[dict[str, str]], max_tokens: int) -> str:
    """Single Chat Completions call; isolated so it can be replaced in tests."""
    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            max_completion_tokens=max_tokens,
        )
    except OpenAIError as error:
        raise HTTPException(503, "The AI coach is unavailable right now. Please try again.") from error
    text = (response.choices[0].message.content or "").strip() if response.choices else ""
    if not text:
        raise HTTPException(503, "The AI coach returned no answer. Please try again.")
    return text


# ---------------------------------------------------------------- student context
def _live_ids(attempts: list[dict[str, Any]]) -> set[str]:
    return {qid for a in attempts if a.get("status") == "in_progress" for qid in _question_section(a)}


def coach_context(bank: Bank, section: str, stats: dict[str, dict[str, Any]], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """This student's own data for one section (never anyone else's)."""
    rows: dict[str, dict[str, int]] = {}
    mistakes: list[tuple[str, str]] = []
    for qid, stat in stats.items():
        question = bank.questions.get(qid)
        if not question or (question.get("examId") or "cat") != "cat" or question.get("section") != section:
            continue
        topic = question.get("topic").strip() if isinstance(question.get("topic"), str) else ""
        if not topic or not has_answered(stat):
            continue
        row = rows.setdefault(topic, {"attempts": 0, "correct": 0})
        row["attempts"] += max(0, int(stat.get("attempts") or 0))
        row["correct"] += max(0, int(stat.get("correct") or 0))
        if stat.get("isMistake") or stat.get("lastCorrect") is False:
            sub = question.get("subtopic").strip() if isinstance(question.get("subtopic"), str) else ""
            mistakes.append((str(stat.get("mistakeAt") or stat.get("lastAnsweredAt") or ""), f"{topic} · {sub}" if sub else topic))
    topics = []
    for topic, row in rows.items():
        accuracy = round(row["correct"] / row["attempts"], 4) if row["attempts"] else None
        topics.append({"topic": topic, "attempts": row["attempts"], "correct": row["correct"], "accuracy": accuracy,
                       "status": _status(row["attempts"], accuracy)})
    topics.sort(key=lambda t: (-t["attempts"], t["topic"].lower()))
    recent: list[str] = []
    for _, label in sorted(mistakes, reverse=True):
        if label not in recent:
            recent.append(label)
    est = None
    result = estimate(bank, attempts, stats, utcnow())
    if result.get("ready"):
        for row in result.get("sections") or []:
            if row.get("id") == section:
                est = {"expected": row["expected"], "low": row["low"], "high": row["high"], "maxScore": row["maxScore"],
                       "confidence": result.get("confidence")}
    return {
        "topics": topics[:MAX_TOPICS],
        "recentMistakeTopics": recent[:MAX_MISTAKE_TOPICS],
        "estimate": est,
        "inRunningTest": any(a.get("status") == "in_progress" for a in attempts),
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def context_text(coach: str, context: dict[str, Any]) -> str:
    lines = [f"Student's own {COACHES[coach]['full']} data from ProCounsel (practice, daily challenge and submitted tests):"]
    if context["topics"]:
        lines.append("Accuracy by topic (status 'low_evidence' = too few answers to judge):")
        lines += [f"- {t['topic']}: {t['correct']}/{t['attempts']} correct ({_pct(t['accuracy'])}), {t['status']}" for t in context["topics"]]
    else:
        lines.append("No answered questions in this section yet.")
    if context["recentMistakeTopics"]:
        lines.append("Topics of recent mistakes (latest first): " + "; ".join(context["recentMistakeTopics"]))
    est = context["estimate"]
    if est:
        lines.append(f"ProCounsel score estimate for this section (not official): about {est['expected']} "
                     f"(range {est['low']} to {est['high']}) out of {est['maxScore']}, confidence {est['confidence']}.")
    else:
        lines.append("Score estimate: not enough data yet.")
    lines.append("Timed test in progress right now: " + ("YES" if context["inRunningTest"] else "no"))
    return "\n".join(lines)


def system_prompt(coach: str) -> str:
    info = COACHES[coach]
    others = ", ".join(c["name"] for k, c in COACHES.items() if k != coach)
    pages = "; ".join(OFFICIAL_PAGES)
    return (
        f"You are the ProCounsel {info['name']}: a friendly, precise CAT (IIM Common Admission Test) coach for the "
        f"{info['full']} section, chatting with one student inside the ProCounsel MBA app. {FOCUS[coach]}\n"
        "Rules you must always follow:\n"
        f"1. Scope: only {info['full']} preparation for CAT and this student's own data below. If asked about anything "
        f"else (another CAT section, other subjects, personal matters, coding, general chat), decline in one sentence and "
        f"suggest the right place ({others} for other sections).\n"
        "2. Official facts: never state exam dates, registration or admission deadlines, the exam pattern, number of "
        "questions, marking scheme, cut-offs, percentiles, fees or admission criteria from memory, and never convert a "
        f"score into a percentile. Say you cannot confirm it and point to the app's pages: {pages}.\n"
        "3. Running tests: if the data says a timed test is in progress, do not solve, check, or hint at any specific "
        "question the student shares; say you will help once the test is submitted, and offer only general method.\n"
        "4. Data: use only the student's own data given to you. Never claim to know other students' results or rank "
        "the student against others. If the data is thin, say so instead of guessing.\n"
        "5. Accuracy: do not invent facts, formulas or passage content. If you are not sure, say so.\n"
        "6. Style: plain text (no HTML, no tables), short paragraphs or numbered steps, normally under 200 words unless "
        "the student asks for a full worked solution. Be specific and encouraging."
    )


def build_messages(coach: str, context: dict[str, Any], history: list[dict[str, Any]], message: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt(coach)},
                {"role": "system", "content": context_text(coach, context)}]
    messages += [{"role": t["role"], "content": t["text"]} for t in history[-MODEL_TURNS:]]
    messages.append({"role": "user", "content": message})
    return messages


_WORD_RE = re.compile(r"[a-z0-9]+")


def _shingles(text: str, n: int = LIVE_SHINGLE_WORDS) -> set[tuple[str, ...]]:
    words = _WORD_RE.findall(text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def quotes_live_question(bank: Bank, live_ids: set[str], message: str) -> bool:
    """True when the message shares ``LIVE_SHINGLE_WORDS`` consecutive words with a question of a running test."""
    said = _shingles(message)
    if not said or not live_ids:
        return False
    for qid in live_ids:
        question = bank.questions.get(qid)
        if not question:
            continue
        parts = [_text(question.get("stemHtml"))]
        parts += [_text(o.get("textHtml")) for o in question.get("options") or [] if isinstance(o, dict)]
        qset = bank.sets.get(question.get("setId") or "") if question.get("setId") else None
        if qset:
            parts.append(_text(qset.get("contentHtml")))
        if any(said & _shingles(part) for part in parts if part):
            return True
    return False


def _chat_payload(coach: str, turns: list[dict[str, Any]], context: dict[str, Any], used: int) -> dict[str, Any]:
    limit = _daily_limit()
    info = COACHES[coach]
    return {
        "coach": coach, "section": info["section"], "title": info["name"], "turns": turns, "context": context,
        "dailyLimit": limit, "remainingToday": max(0, limit - used), "configured": bool(os.getenv("OPENAI_API_KEY")),
    }


def _load(db: SafeFirestore, user: CurrentUser, coach: str) -> tuple[Bank, dict[str, Any], list[dict[str, Any]]]:
    bank = get_bank(db)
    attempts = user_attempts(db, bank, user)
    context = coach_context(bank, COACHES[coach]["section"], user_stats(db, user.user_id), attempts)
    return bank, context, attempts


# ---------------------------------------------------------------- coach routes
@router.get("/me/coach/{coach}", response_model=CoachChat)
def get_coach(coach: CoachId, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _bank, context, _attempts = _load(db, user, coach)
    turns = _fresh_turns(get_doc(db, CHATS, chat_id(user.user_id, coach)))
    return _chat_payload(coach, turns, context, _used_today(db, user))


@router.post("/me/coach/{coach}/messages", response_model=CoachChat)
def send_coach_message(coach: CoachId, body: CoachMessageInput, user: CurrentUser = Depends(student),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Type a message.")
    bank, context, attempts = _load(db, user, coach)
    if quotes_live_question(bank, _live_ids(attempts), message):
        raise HTTPException(409, "That looks like a question from your test in progress. Submit the test first, then ask about it.")
    _check_quota(db, user)
    doc_id = chat_id(user.user_id, coach)
    history = _fresh_turns(get_doc(db, CHATS, doc_id))
    reply = call_model(build_messages(coach, context, history, message), REPLY_TOKENS)
    now = iso(utcnow())

    def save(current: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        turns = [*_fresh_turns(current), {"role": "user", "text": message, "at": now},
                 {"role": "assistant", "text": reply, "at": now}][-MAX_STORED_TURNS:]
        doc = {"userId": user.user_id, "coach": coach, "turns": turns, "updatedAt": now}
        if current is None:
            doc["createdAt"] = now
        return doc, turns

    turns = occ_update(db, CHATS, doc_id, save)
    used = _count_usage(db, user)
    return _chat_payload(coach, turns, context, used)


@router.delete("/me/coach/{coach}", response_model=DeletedResponse)
def delete_coach_chat(coach: CoachId, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    ref = db.collection(CHATS).document(chat_id(user.user_id, coach))
    existed = ref.get(timeout=DB_TIMEOUT).exists
    if existed:
        ref.delete(timeout=DB_TIMEOUT)
    return {"deleted": bool(existed)}


# ---------------------------------------------------------------- explain my plan
PLAN_PROMPT = (
    "You explain a student's weekly CAT study plan inside the ProCounsel MBA app. The plan was built by fixed rules "
    "(listed below) from the student's own profile and results. Explain in plain language why these tasks are in the "
    "plan, using ONLY the rules, the section figures and the tasks given. Do not invent tasks, numbers, dates or exam "
    "facts, do not change the plan, and do not mention other students. Write 120-220 words of plain text: one or two "
    "sentences of overview, then 3-5 short lines starting with '- ' on the biggest choices (mocks, which section gets "
    "most time and why, revision, rest days, daily challenge), then one encouraging line on how to follow the plan."
)


def plan_hash(plan: dict[str, Any]) -> str:
    tasks = [(t["date"], t["type"], t["title"], t.get("detail"), t.get("minutes"), t.get("status"))
             for d in plan["days"] for t in d["tasks"]]
    raw = json.dumps({"tasks": tasks, "rules": plan["basis"].get("rules")}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def plan_messages(plan: dict[str, Any]) -> list[dict[str, str]]:
    basis = plan["basis"]
    lines = [
        f"Week: {plan['weekStart']} to {plan['weekEnd']}",
        f"Exam date: {basis.get('examDate') or 'not set'}; weeks to exam: {basis.get('weeksToExam') if basis.get('weeksToExam') is not None else 'unknown'}",
        f"Weekly study hours: {basis.get('weeklyStudyHours')}; minutes per study day: {basis.get('minutesPerStudyDay')}; level: {basis.get('level')}",
        f"Mocks this week: {basis.get('mocksThisWeek')}; mistakes due for revision: {basis.get('mistakesDue')}",
        "Sections: " + "; ".join(
            f"{s['id']} answered {s['attempted']}, accuracy {_pct(s.get('accuracy'))}, time weight {s['weight']}"
            for s in basis.get("sections") or []),
        "Rules applied:", *[f"- {rule}" for rule in basis.get("rules") or []],
        "Tasks:",
    ]
    for day in plan["days"]:
        if day["rest"] and not day["tasks"]:
            lines.append(f"{day['date']}: rest day")
        for task in day["tasks"]:
            detail = f" ({task['detail']})" if task.get("detail") else ""
            lines.append(f"{day['date']}: {task['title']}{detail}, {task['minutes']} min, {task['status']}")
    return [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


def _plan_doc_id(user: CurrentUser) -> str:
    return chat_id(user.user_id, "plan")


def _cached_plan(db: SafeFirestore, user: CurrentUser, week: str, digest: str) -> dict[str, Any] | None:
    doc = get_doc(db, CHATS, _plan_doc_id(user))
    if not doc or doc.get("userId") != user.user_id or doc.get("weekStart") != week or doc.get("planHash") != digest:
        return None
    return {"weekStart": week, "text": str(doc.get("text") or ""), "generatedAt": str(doc.get("generatedAt") or ""),
            "cached": True, "remainingToday": None}


@router.get("/me/plan/explain", response_model=PlanExplanationResponse)
def get_plan_explanation(week: str | None = Query(default=None), user: CurrentUser = Depends(student),
                         db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    plan = build_week_response(db, user, _week_param(week, local_date(utcnow())))
    return {"explanation": _cached_plan(db, user, plan["weekStart"], plan_hash(plan))}


@router.post("/me/plan/explain", response_model=PlanExplanation)
def explain_plan(week: str | None = Query(default=None), user: CurrentUser = Depends(student),
                 db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    plan = build_week_response(db, user, _week_param(week, local_date(utcnow())))
    if not any(d["tasks"] for d in plan["days"]):
        raise HTTPException(409, "Build this week's plan first, then ask for an explanation.")
    digest = plan_hash(plan)
    cached = _cached_plan(db, user, plan["weekStart"], digest)
    if cached:
        return cached
    limit = _check_quota(db, user)
    text = call_model(plan_messages(plan), PLAN_TOKENS)
    now = iso(utcnow())
    db.collection(CHATS).document(_plan_doc_id(user)).set(
        {"userId": user.user_id, "coach": "plan", "weekStart": plan["weekStart"], "planHash": digest, "text": text,
         "generatedAt": now, "updatedAt": now},
        timeout=DB_TIMEOUT,
    )
    used = _count_usage(db, user)
    return {"weekStart": plan["weekStart"], "text": text, "generatedAt": now, "cached": False,
            "remainingToday": max(0, limit - used)}
