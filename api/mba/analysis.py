"""Mock analyst: a deterministic "question selection" analysis of a submitted attempt,
optionally explained by an AI layer (contract: docs/mba-api.md → "Mock analyst").

* ``GET  /me/attempts/{id}/analysis`` — the deterministic analysis (always available once
  the attempt is submitted) plus the cached AI explanation if one was generated.
* ``POST /me/attempts/{id}/analysis`` — generates the AI explanation once and caches it in
  ``mbaAttemptAnalyses/{attemptId}``; later calls return the cached copy (no quota used).
  503 when the model is not configured / fails, 429 when the daily AI quota (shared with the
  tutor, ``mbaAiUsage``) is used up. The deterministic analysis never depends on the model.

The model only sees recorded facts computed here (per-section counts and time, per-question
correctness / time / difficulty / topic). It never sees answer keys or solutions, and every
link it may suggest comes from a fixed list built here, so it cannot invent a destination.
"""

from __future__ import annotations

import json
import os
import re
from statistics import median
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .ai import DEFAULT_MODEL, OPENAI_TIMEOUT_SECONDS, _daily_limit
from .attempts import _plan, transition
from .deps import student
from .models import SECTION_IDS, SectionId
from .scoring import normalize_answer
from .store import AI_USAGE, Bank, get_bank, get_doc, iso, local_date, occ_update, utcnow

router = APIRouter()

ANALYSES = "mbaAttemptAnalyses"
LOW_EVIDENCE_ATTEMPTED = 10
TIME_SINK_FACTOR = 2.0
MIN_TIMED_FOR_MEDIAN = 3
MAX_LISTED = 8
SUMMARY_MAX_WORDS = 120
DIFFICULTIES = ("easy", "medium", "hard")
SECTION_NAMES = {"VARC": "VARC", "DILR": "DILR", "QA": "Quant"}

Outcome = Literal["correct", "incorrect", "skipped"]


# ---------------------------------------------------------------- response models
class SectionFacts(BaseModel):
    id: SectionId
    questionCount: int
    score: float
    maxScore: float
    attempted: int
    correct: int
    incorrect: int
    unanswered: int
    accuracy: float | None
    timeSpentMs: int
    medianTimeMs: int | None


class Bucket(BaseModel):
    total: int
    attempted: int
    correct: int
    incorrect: int
    skipped: int
    accuracy: float | None


class DifficultyFacts(Bucket):
    difficulty: Literal["easy", "medium", "hard", "unrated"]


class TopicFacts(Bucket):
    section: SectionId
    topic: str
    timeSpentMs: int


class QuestionRef(BaseModel):
    questionId: str
    section: SectionId
    number: int
    topic: str | None
    difficulty: Literal["easy", "medium", "hard"] | None
    outcome: Outcome
    timeSpentMs: int


class TimeSink(QuestionRef):
    sectionMedianMs: int
    ratio: float


class SelectionFacts(BaseModel):
    easySkipped: int
    easyIncorrect: int
    hardAttempted: int
    hardCorrect: int
    timeOnIncorrectMs: int
    timeOnHardIncorrectMs: int
    timeSinkCount: int


class PracticeLink(BaseModel):
    id: str
    label: str
    href: str


class DeterministicAnalysis(BaseModel):
    attemptId: str
    title: str
    submittedAt: str
    score: float
    maxScore: float
    questionCount: int
    attempted: int
    lowEvidence: bool
    evidenceNote: str | None
    sections: list[SectionFacts]
    byDifficulty: list[DifficultyFacts]
    byTopic: list[TopicFacts]
    missedEasy: list[QuestionRef]
    timeSinks: list[TimeSink]
    selection: SelectionFacts
    links: list[PracticeLink]


class AiPriority(BaseModel):
    title: str
    detail: str
    nextSteps: list[str]
    link: PracticeLink


class AiAnalysis(BaseModel):
    summary: str
    strengths: list[str]
    priorities: list[AiPriority]
    selectionAdvice: str
    generatedAt: str
    model: str


class AttemptAnalysisResponse(BaseModel):
    attemptId: str
    analysis: DeterministicAnalysis
    ai: AiAnalysis | None
    remainingToday: int | None


# ---------------------------------------------------------------- deterministic analysis
def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    incorrect = sum(1 for r in rows if r["outcome"] == "incorrect")
    attempted = correct + incorrect
    return {"total": len(rows), "attempted": attempted, "correct": correct, "incorrect": incorrect,
            "skipped": len(rows) - attempted, "accuracy": _ratio(correct, attempted)}


def practice_href(section: str | None = None, topic: str | None = None) -> str:
    params = {k: v for k, v in (("section", section), ("topic", topic)) if v}
    return "/mba/practice" + (f"?{urlencode(params)}" if params else "")


def _ref(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in ("questionId", "section", "number", "topic", "difficulty", "outcome", "timeSpentMs")}


def question_rows(att: dict[str, Any], bank: Bank) -> list[dict[str, Any]]:
    """One row per question of the attempt, in paper order: recorded facts only (no answer key)."""
    per_question = (att.get("result") or {}).get("perQuestion") or {}
    responses = att.get("responses") or {}
    rows = []
    for section in _plan(att):
        number = 0
        for qid in section.get("questionIds") or []:
            question = bank.questions.get(qid)
            if question is None:
                continue
            number += 1
            response = responses.get(qid) if isinstance(responses.get(qid), dict) else {}
            answered = normalize_answer(response.get("answer")) is not None
            is_correct = (per_question.get(qid) or {}).get("isCorrect")
            outcome = "skipped" if not answered or is_correct is None else ("correct" if is_correct else "incorrect")
            difficulty = question.get("difficulty") if question.get("difficulty") in DIFFICULTIES else None
            topic = question.get("topic").strip() if isinstance(question.get("topic"), str) and question["topic"].strip() else None
            rows.append({
                "questionId": qid, "section": section["id"], "number": number, "topic": topic, "difficulty": difficulty,
                "outcome": outcome, "timeSpentMs": max(0, int(response.get("timeSpentMs") or 0)),
            })
    return rows


def deterministic_analysis(att: dict[str, Any], bank: Bank) -> dict[str, Any]:
    rows = question_rows(att, bank)
    result = att.get("result") or {}
    stored_sections = {s.get("id"): s for s in result.get("sections") or [] if isinstance(s, dict)}

    sections, medians = [], {}
    for section in _plan(att):
        sid = section["id"]
        srows = [r for r in rows if r["section"] == sid]
        timed = [r["timeSpentMs"] for r in srows if r["timeSpentMs"] > 0]
        med = int(median(timed)) if len(timed) >= MIN_TIMED_FOR_MEDIAN else None
        medians[sid] = med
        b = _bucket(srows)
        stored = stored_sections.get(sid) or {}
        sections.append({
            "id": sid, "questionCount": len(srows), "score": stored.get("score", 0), "maxScore": stored.get("maxScore", 0),
            "attempted": b["attempted"], "correct": b["correct"], "incorrect": b["incorrect"], "unanswered": b["skipped"],
            "accuracy": b["accuracy"], "timeSpentMs": sum(r["timeSpentMs"] for r in srows), "medianTimeMs": med,
        })

    by_difficulty = []
    for difficulty in (*DIFFICULTIES, None):
        drows = [r for r in rows if r["difficulty"] == difficulty]
        if drows:
            by_difficulty.append({"difficulty": difficulty or "unrated", **_bucket(drows)})

    topics: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if r["topic"]:
            topics.setdefault((r["section"], r["topic"]), []).append(r)
    by_topic = [
        {"section": sid, "topic": topic, **_bucket(trows), "timeSpentMs": sum(r["timeSpentMs"] for r in trows)}
        for (sid, topic), trows in topics.items()
    ]
    by_topic.sort(key=lambda t: (SECTION_IDS.index(t["section"]), -t["total"], t["topic"].lower()))

    missed_easy = [_ref(r) for r in rows if r["difficulty"] == "easy" and r["outcome"] != "correct"]
    sinks = []
    for r in rows:
        med = medians.get(r["section"])
        if med and r["outcome"] != "correct" and r["timeSpentMs"] > TIME_SINK_FACTOR * med:
            sinks.append({**_ref(r), "sectionMedianMs": med, "ratio": round(r["timeSpentMs"] / med, 2)})
    sinks.sort(key=lambda s: -s["timeSpentMs"])

    attempted = sum(1 for r in rows if r["outcome"] != "skipped")
    selection = {
        "easySkipped": sum(1 for r in rows if r["difficulty"] == "easy" and r["outcome"] == "skipped"),
        "easyIncorrect": sum(1 for r in rows if r["difficulty"] == "easy" and r["outcome"] == "incorrect"),
        "hardAttempted": sum(1 for r in rows if r["difficulty"] == "hard" and r["outcome"] != "skipped"),
        "hardCorrect": sum(1 for r in rows if r["difficulty"] == "hard" and r["outcome"] == "correct"),
        "timeOnIncorrectMs": sum(r["timeSpentMs"] for r in rows if r["outcome"] == "incorrect"),
        "timeOnHardIncorrectMs": sum(r["timeSpentMs"] for r in rows if r["difficulty"] == "hard" and r["outcome"] == "incorrect"),
        "timeSinkCount": len(sinks),
    }

    links = [{"id": f"section:{s['id']}", "label": f"Practise {SECTION_NAMES[s['id']]}", "href": practice_href(s["id"])} for s in sections]
    for t in by_topic:
        links.append({"id": f"topic:{t['section']}:{t['topic']}", "label": f"Practise {t['topic']} ({SECTION_NAMES[t['section']]})",
                      "href": practice_href(t["section"], t["topic"])})
    links.append({"id": "mistakes", "label": "Review your mistakes", "href": "/mba/mistakes"})

    low = attempted < LOW_EVIDENCE_ATTEMPTED
    return {
        "attemptId": att["id"],
        "title": att.get("title") or "",
        "submittedAt": att.get("submittedAt") or "",
        "score": result.get("score", 0),
        "maxScore": result.get("maxScore", 0),
        "questionCount": len(rows),
        "attempted": attempted,
        "lowEvidence": low,
        "evidenceNote": (
            f"Only {attempted} question{'s' if attempted != 1 else ''} attempted — patterns below are tentative. "
            f"Attempt at least {LOW_EVIDENCE_ATTEMPTED} for a reliable read."
        ) if low else None,
        "sections": sections,
        "byDifficulty": by_difficulty,
        "byTopic": by_topic,
        "missedEasy": missed_easy[:MAX_LISTED],
        "timeSinks": sinks[:MAX_LISTED],
        "selection": selection,
        "links": links,
    }


# ---------------------------------------------------------------- AI explanation layer
SYSTEM_PROMPT = (
    "You are a CAT (IIM Common Admission Test) mock-test analyst. You receive a JSON object of facts "
    "computed from ONE submitted mock: section scores, counts, time, accuracy by difficulty and topic, easy "
    "questions that were skipped or wrong, and time sinks (wrong or skipped questions that took more than twice "
    "the section's median time). Use ONLY these facts. Never invent numbers, topics, percentiles, ranks, cut-offs "
    "or study history that are not in the facts, and never claim anything about questions' content. When a fact "
    "is missing say so plainly. If lowEvidence is true, say early in the summary that the evidence is thin and "
    "keep conclusions tentative. Quote numbers exactly as given (times are milliseconds; convert to minutes/"
    "seconds). Reply with a single JSON object and nothing else, of the form: "
    '{"summary": string (at most 120 words), "strengths": [3 short strings], '
    '"priorities": [3 objects {"title": string, "detail": string, "nextSteps": [1-3 concrete action strings], '
    '"linkId": one of the ids in the facts\' links list}], "selectionAdvice": string (2-4 sentences on which '
    "questions to pick or leave next time, based on missedEasy, timeSinks and accuracy by difficulty)}. "
    "If fewer than 3 genuine strengths exist in the facts, give fewer rather than inventing any."
)


def ai_facts(analysis: dict[str, Any]) -> dict[str, Any]:
    """What the model sees: the deterministic analysis minus ids/hrefs it does not need."""
    def strip(ref: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in ref.items() if k != "questionId"}

    return {
        "title": analysis["title"],
        "score": analysis["score"], "maxScore": analysis["maxScore"],
        "questionCount": analysis["questionCount"], "attempted": analysis["attempted"],
        "lowEvidence": analysis["lowEvidence"],
        "sections": analysis["sections"],
        "byDifficulty": analysis["byDifficulty"],
        "byTopic": analysis["byTopic"],
        "missedEasy": [strip(r) for r in analysis["missedEasy"]],
        "timeSinks": [strip(r) for r in analysis["timeSinks"]],
        "selection": analysis["selection"],
        "links": [{"id": link["id"], "label": link["label"]} for link in analysis["links"]],
    }


def build_messages(analysis: dict[str, Any]) -> list[dict[str, str]]:
    facts = json.dumps(ai_facts(analysis), separators=(",", ":"), ensure_ascii=False)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"Facts:\n{facts}"}]


def call_model(messages: list[dict[str, str]]) -> str:
    """One JSON-mode Chat Completions call; isolated so tests can replace it."""
    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=OPENAI_TIMEOUT_SECONDS, max_retries=1)
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            max_completion_tokens=1200,
            response_format={"type": "json_object"},
        )
    except OpenAIError as error:
        raise HTTPException(503, "The mock analyst is unavailable right now. Please try again.") from error
    return (response.choices[0].message.content or "").strip() if response.choices else ""


def _plain(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def _words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]).rstrip(",;:") + "…"


def parse_ai(raw: str, analysis: dict[str, Any]) -> dict[str, Any]:
    """Validate the model's JSON; links are resolved against the fixed list (unknown → section/mistakes)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(503, "The mock analyst returned an unreadable answer. Please try again.") from error
    if not isinstance(data, dict):
        raise HTTPException(503, "The mock analyst returned an unreadable answer. Please try again.")
    links = {link["id"]: link for link in analysis["links"]}
    fallback = links.get("mistakes") or analysis["links"][-1]
    summary = _words(_plain(data.get("summary"), 1500), SUMMARY_MAX_WORDS)
    strengths = [s for s in (_plain(x, 300) for x in data.get("strengths") or [] if isinstance(data.get("strengths"), list)) if s][:3]
    priorities = []
    for item in data.get("priorities") if isinstance(data.get("priorities"), list) else []:
        if not isinstance(item, dict):
            continue
        title = _plain(item.get("title"), 140)
        if not title:
            continue
        steps = [s for s in (_plain(x, 300) for x in item.get("nextSteps") or [] if isinstance(item.get("nextSteps"), list)) if s][:3]
        priorities.append({
            "title": title,
            "detail": _plain(item.get("detail"), 600),
            "nextSteps": steps,
            "link": links.get(str(item.get("linkId") or "")) or fallback,
        })
        if len(priorities) == 3:
            break
    advice = _plain(data.get("selectionAdvice"), 1200)
    if not summary or not priorities:
        raise HTTPException(503, "The mock analyst returned an incomplete answer. Please try again.")
    return {"summary": summary, "strengths": strengths, "priorities": priorities, "selectionAdvice": advice}


# ---------------------------------------------------------------- routes
def _submitted(db: SafeFirestore, bank: Bank, attempt_id: str, user: CurrentUser) -> dict[str, Any]:
    att = {**transition(db, bank, attempt_id, user), "id": attempt_id}
    if att.get("status") != "submitted":
        raise HTTPException(404, "The analysis is available after the attempt is submitted.")
    return att


def _cached_ai(db: SafeFirestore, attempt_id: str, user: CurrentUser) -> dict[str, Any] | None:
    doc = get_doc(db, ANALYSES, attempt_id)
    if not doc or doc.get("userId") != user.user_id or not isinstance(doc.get("ai"), dict):
        return None
    return doc["ai"]


def _payload(analysis: dict[str, Any], ai: dict[str, Any] | None, remaining: int | None) -> dict[str, Any]:
    return {"attemptId": analysis["attemptId"], "analysis": analysis, "ai": ai, "remainingToday": remaining}


@router.get("/me/attempts/{attempt_id}/analysis", response_model=AttemptAnalysisResponse)
def get_analysis(attempt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    att = _submitted(db, bank, attempt_id, user)
    return _payload(deterministic_analysis(att, bank), _cached_ai(db, attempt_id, user), None)


@router.post("/me/attempts/{attempt_id}/analysis", response_model=AttemptAnalysisResponse)
def create_analysis(attempt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    att = _submitted(db, bank, attempt_id, user)
    analysis = deterministic_analysis(att, bank)
    cached = _cached_ai(db, attempt_id, user)
    if cached is not None:
        return _payload(analysis, cached, None)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "The mock analyst is not configured.")
    limit = _daily_limit()
    usage_id = f"{user.user_id}_{local_date().isoformat()}"
    if int((get_doc(db, AI_USAGE, usage_id) or {}).get("count") or 0) >= limit:
        raise HTTPException(429, f"Daily AI limit reached ({limit}). It resets at midnight IST.")

    parsed = parse_ai(call_model(build_messages(analysis)), analysis)
    now = iso(utcnow())
    ai = {**parsed, "generatedAt": now, "model": os.getenv("OPENAI_MODEL") or DEFAULT_MODEL}

    def save(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is not None and isinstance(current.get("ai"), dict):
            return None, current["ai"]  # a concurrent request cached one first: keep that one
        doc = {"attemptId": attempt_id, "userId": user.user_id, "testId": att.get("testId"), "ai": ai, "createdAt": now}
        return doc, ai

    stored = occ_update(db, ANALYSES, attempt_id, save)

    def count(current: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
        n = int((current or {}).get("count") or 0) + 1
        return {"userId": user.user_id, "date": usage_id.rsplit("_", 1)[1], "count": n, "updatedAt": now}, n

    used = occ_update(db, AI_USAGE, usage_id, count)
    return _payload(analysis, stored, max(0, limit - used))
