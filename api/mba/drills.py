"""Practice modes: custom test builder, timed drills, weak-topic and mixed sets
(contract: docs/mba-api.md → "Practice modes").

A built test is an ordinary attempt (``mbaAttempts``) with ``kind: "drill"`` and a generated
``sectionPlan``, so it runs on the attempt engine in attempts.py unchanged: server-owned timer,
autosave with ``seq``, idempotent submit, CAT marking (latest exam version), result, history,
insights and the mock analyst. Its ``testId`` is ``drill-{attemptId}``; ``POST /attempts`` with that
id resumes it (or reopens the submitted one). ``clientToken`` makes ``POST /drills`` idempotent.

Selection (no answer key is ever read here):
* Pool = published questions matching sections / topics / subtopics / difficulty / source, minus every
  question in the student's running attempts (so a built test can never reveal a live mock's answers).
* DILR / RC sets stay together: a unit is a set's pool questions in paper order, or one standalone
  question. Whole units are taken while they fit; if slots remain and only bigger units are left, the
  first questions of the best-ranked set fill them (a coherent subset that shares the passage).
* ``mixed`` / ``timed`` spread the count evenly over the chosen sections (a short section's
  shortfall moves to the next); ``weak`` takes the best-ranked questions wherever they are.
* Units are ranked by tier, randomly within a tier (randomised selection), then shuffled within their
  section (randomised order). Option order is never shuffled: official solutions refer to option letters.
  - ``mixed`` / ``timed``: never answered → last answer wrong → the rest.
  - ``weak``: due mistakes → lucky guesses (right but rated "guess") → weak topics (insights.py rules:
    ≥ MIN_EVIDENCE answers and accuracy < WEAK_BELOW), never answered → last wrong → the rest.
* Sections run in CAT order, one timed block each (a one-section drill is a single timed block).
  ``timed`` mode takes exactly one section. Time = ``timeLimitMinutes`` split by question count, or
  automatic: the official pace of the latest CAT version with announced question counts
  (section minutes / questions, e.g. 40 / 22 ≈ 1.8 min), falling back to 1.8 min per question.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import _question_section, attempt_payload, summary, user_attempts
from .confidence import is_lucky_guess
from .deps import student
from .exams import is_pyq  # same PYQ rule as the practice `source` filter
from .insights import MIN_EVIDENCE, WEAK_BELOW
from .models import SECTION_IDS, Attempt, AttemptSummary, SectionId
from .questions import question_sort_key
from .scoring import pick_version
from .stats import has_answered, is_due
from .store import ATTEMPTS, Bank, get_bank, iso, occ_update, user_stats, utcnow

router = APIRouter()

DEFAULT_PACE_MINUTES = 1.8  # fallback when no CAT version has announced question counts
MAX_COUNT = 50
MAX_MINUTES = 180
SECTION_NAMES = {"VARC": "VARC", "DILR": "DILR", "QA": "Quant"}
MODE_TITLES = {"weak": "Weak topics set", "mixed": "Mixed set"}

Mode = Literal["timed", "weak", "mixed"]
SourceFilter = Literal["all", "pyq", "original"]
Difficulty = Literal["easy", "medium", "hard"]
Label = Annotated[str, Field(min_length=1, max_length=200)]


class DrillCreate(BaseModel):
    model_config = {"extra": "forbid"}

    clientToken: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # one per "Start" click
    mode: Mode
    sections: list[SectionId] = Field(default_factory=list, max_length=3)  # empty = all
    topics: list[Label] = Field(default_factory=list, max_length=50)  # ignored in weak mode
    subtopics: list[Label] = Field(default_factory=list, max_length=100)  # ignored in weak mode
    difficulty: list[Difficulty] = Field(default_factory=list, max_length=3)  # empty = all
    source: SourceFilter = "all"
    count: int = Field(ge=1, le=MAX_COUNT)
    timeLimitMinutes: int | None = Field(default=None, ge=1, le=MAX_MINUTES)  # null = automatic (CAT pace)


class SubtopicOption(BaseModel):
    subtopic: str
    questionCount: int


class TopicOption(BaseModel):
    topic: str
    questionCount: int
    subtopics: list[SubtopicOption]


class SectionOption(BaseModel):
    id: SectionId
    questionCount: int
    minutesPerQuestion: float
    topics: list[TopicOption]


class SourceCounts(BaseModel):
    all: int
    pyq: int
    original: int


class WeakTopicOption(BaseModel):
    section: SectionId
    topic: str
    attempts: int
    accuracy: float


class DrillLimits(BaseModel):
    maxCount: int
    maxMinutes: int


class DrillOptions(BaseModel):
    sections: list[SectionOption]
    sources: SourceCounts
    weakTopics: list[WeakTopicOption]
    mistakesDue: int
    luckyGuesses: int
    inProgress: AttemptSummary | None
    limits: DrillLimits


# ---------------------------------------------------------------- pure helpers
def _norm(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def section_pace(bank: Bank) -> dict[str, float]:
    """Minutes per question by section from the latest CAT version that announced question counts."""
    versions = [v for v in (bank.exams.get("cat") or {}).get("versions") or [] if isinstance(v, dict) and isinstance(v.get("year"), int)]
    pace: dict[str, float] = {}
    for version in sorted(versions, key=lambda v: v["year"], reverse=True):
        for section in version.get("sections") or []:
            if not isinstance(section, dict) or section.get("id") not in SECTION_IDS or section["id"] in pace:
                continue
            count, minutes = section.get("questionCount"), section.get("durationMinutes")
            if isinstance(count, int) and count > 0 and isinstance(minutes, (int, float)) and minutes > 0:
                pace[section["id"]] = minutes / count
    return {sid: round(pace.get(sid, DEFAULT_PACE_MINUTES), 4) for sid in SECTION_IDS}


def weak_topics(bank: Bank, stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Same rule as GET /me/insights: ≥ MIN_EVIDENCE answers and accuracy < WEAK_BELOW. Worst first."""
    rows: dict[tuple[str, str], list[int]] = {}
    for qid, stat in stats.items():
        question = bank.questions.get(qid)
        topic = (question or {}).get("topic")
        if not question or not has_answered(stat) or question.get("section") not in SECTION_IDS or not isinstance(topic, str) or not topic.strip():
            continue
        row = rows.setdefault((question["section"], topic.strip()), [0, 0])
        row[0] += max(0, int(stat.get("attempts") or 0))
        row[1] += max(0, int(stat.get("correct") or 0))
    weak = [
        {"section": s, "topic": t, "attempts": a, "accuracy": round(c / a, 4)}
        for (s, t), (a, c) in rows.items() if a >= MIN_EVIDENCE and c / a < WEAK_BELOW
    ]
    weak.sort(key=lambda w: (w["accuracy"], -w["attempts"]))
    return weak


def filtered_pool(bank: Bank, body: DrillCreate, live: set[str]) -> list[dict[str, Any]]:
    sections = set(body.sections or SECTION_IDS)
    topics = {_norm(t) for t in body.topics} if body.mode != "weak" else set()
    subtopics = {_norm(t) for t in body.subtopics} if body.mode != "weak" else set()
    difficulty = set(body.difficulty)
    pool = []
    for question in bank.questions.values():
        if question["id"] in live or question.get("section") not in sections:
            continue
        if topics and _norm(question.get("topic")) not in topics:
            continue
        if subtopics and _norm(question.get("subtopic")) not in subtopics:
            continue
        if difficulty and question.get("difficulty") not in difficulty:
            continue
        if body.source == "pyq" and not is_pyq(question) or body.source == "original" and is_pyq(question):
            continue
        pool.append(question)
    return pool


def _history_tier(stat: dict[str, Any] | None) -> int:
    if not has_answered(stat):
        return 0
    return 1 if (stat or {}).get("lastCorrect") is False else 2


def rank_tier(question: dict[str, Any], stat: dict[str, Any] | None, mode: str, weak: set[tuple[str, str]], now: Any) -> int | None:
    """Lower = picked first; None = not eligible (weak mode only)."""
    if mode != "weak":
        return _history_tier(stat)
    if stat and is_due(stat, now):
        return 0
    if is_lucky_guess(stat):
        return 1
    topic = question.get("topic").strip() if isinstance(question.get("topic"), str) else ""
    if (question.get("section"), topic) in weak:
        return 2 + _history_tier(stat)
    return None


def select_units(pool: list[dict[str, Any]], tiers: dict[str, int], count: int, rng: random.Random) -> list[list[dict[str, Any]]]:
    """Pick up to ``count`` questions as whole sets where possible (see module doc)."""
    units: list[list[dict[str, Any]]] = []
    by_set: dict[str, list[dict[str, Any]]] = {}
    for question in sorted((q for q in pool if q["id"] in tiers), key=question_sort_key):
        set_id = question.get("setId")
        if isinstance(set_id, str) and set_id:
            if set_id not in by_set:
                by_set[set_id] = []
                units.append(by_set[set_id])
            by_set[set_id].append(question)
        else:
            units.append([question])
    ranked: list[list[dict[str, Any]]] = []
    for tier in sorted({min(tiers[q["id"]] for q in unit) for unit in units}):
        group = [unit for unit in units if min(tiers[q["id"]] for q in unit) == tier]
        rng.shuffle(group)
        ranked.extend(group)

    chosen: list[list[dict[str, Any]]] = []
    left = count
    for unit in ranked:
        if left == 0:
            break
        if len(unit) <= left:
            chosen.append(unit)
            left -= len(unit)
    if left > 0:
        rest = next((unit for unit in ranked if not any(unit is c for c in chosen)), None)
        if rest is not None:
            chosen.append(rest[:left])
    return chosen


def split_minutes(counts: list[int], total: int | None, pace: list[float]) -> list[int]:
    """Minutes per section: ``total`` split by question count (≥ 1 each), or automatic from ``pace``."""
    if total is None:
        return [max(1, math.ceil(n * p - 1e-9)) for n, p in zip(counts, pace)]
    if total < len(counts):
        raise HTTPException(422, f"Give at least {len(counts)} minutes: each section needs at least 1 minute.")
    n_all = sum(counts)
    minutes = [max(1, math.floor(total * n / n_all)) for n in counts]
    i = 0
    while sum(minutes) < total:  # hand out the rounding remainder, biggest sections first
        order = sorted(range(len(counts)), key=lambda k: -counts[k])
        minutes[order[i % len(order)]] += 1
        i += 1
    while sum(minutes) > total:
        k = max((k for k in range(len(minutes)) if minutes[k] > 1), key=lambda k: minutes[k])
        minutes[k] -= 1
    return minutes


def build_plan(
    bank: Bank, body: DrillCreate, stats: dict[str, dict[str, Any]], live: set[str], rng: random.Random
) -> list[dict[str, Any]]:
    if body.mode == "timed" and len(body.sections) != 1:
        raise HTTPException(422, "A timed drill covers one section. Pick VARC, DILR or Quant.")
    pool = filtered_pool(bank, body, live)
    now = utcnow()
    weak = {(w["section"], w["topic"]) for w in weak_topics(bank, stats)} if body.mode == "weak" else set()
    tiers = {}
    for question in pool:
        tier = rank_tier(question, stats.get(question["id"]), body.mode, weak, now)
        if tier is not None:
            tiers[question["id"]] = tier
    if not tiers:
        if body.mode == "weak":
            raise HTTPException(422, (
                f"Nothing to revise yet: no mistakes are due and no topic is weak (a topic is weak after {MIN_EVIDENCE} "
                f"answers under {round(WEAK_BELOW * 100)}% accuracy). Build a mixed set instead."
            ))
        raise HTTPException(422, "No questions match these choices. Try fewer filters.")
    if body.mode == "weak":  # priority decides: due mistakes may all sit in one section
        units = select_units(pool, tiers, body.count, rng)
    else:  # spread the count over the chosen sections that have questions
        present = [sid for sid in SECTION_IDS if any(q["section"] == sid for q in pool if q["id"] in tiers)]
        units, left = [], body.count
        for i, sid in enumerate(present):
            part = select_units([q for q in pool if q["section"] == sid], tiers, math.ceil(left / (len(present) - i)), rng)
            units += part
            left -= sum(len(unit) for unit in part)

    by_section: dict[str, list[list[dict[str, Any]]]] = {}
    for unit in units:
        by_section.setdefault(unit[0]["section"], []).append(unit)
    order = [sid for sid in SECTION_IDS if sid in by_section]
    pace = section_pace(bank)
    counts = [sum(len(u) for u in by_section[sid]) for sid in order]
    minutes = split_minutes(counts, body.timeLimitMinutes, [pace[sid] for sid in order])
    plan = []
    for sid, mins in zip(order, minutes):
        section_units = by_section[sid]
        rng.shuffle(section_units)
        plan.append({"id": sid, "durationMinutes": mins, "questionIds": [q["id"] for unit in section_units for q in unit]})
    return plan


def drill_title(mode: str, plan: list[dict[str, Any]]) -> str:
    n = sum(len(s["questionIds"]) for s in plan)
    minutes = sum(int(s["durationMinutes"]) for s in plan)
    name = f"{SECTION_NAMES[plan[0]['id']]} drill" if mode == "timed" else MODE_TITLES[mode]
    return f"{name} — {n} question{'s' if n != 1 else ''}, {minutes} min"


def _drill_doc_id(user_id: str, token: str) -> str:
    return hashlib.sha256(f"{user_id}|drill|{token}".encode()).hexdigest()[:24]


def _live_ids(attempts: list[dict[str, Any]]) -> set[str]:
    return {qid for a in attempts if a.get("status") == "in_progress" for qid in _question_section(a)}


# ---------------------------------------------------------------- routes
@router.get("/drills/options", response_model=DrillOptions)
def drill_options(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    attempts = user_attempts(db, bank, user)
    live = _live_ids(attempts)
    stats = user_stats(db, user.user_id)
    pace = section_pace(bank)
    available = [q for q in bank.questions.values() if q["id"] not in live and q.get("section") in SECTION_IDS]

    sections = []
    for sid in SECTION_IDS:
        topics: dict[str, dict[str, Any]] = {}
        for question in available:
            if question["section"] != sid or not isinstance(question.get("topic"), str) or not question["topic"].strip():
                continue
            row = topics.setdefault(question["topic"].strip(), {"count": 0, "subtopics": {}})
            row["count"] += 1
            sub = question.get("subtopic")
            if isinstance(sub, str) and sub.strip():
                row["subtopics"][sub.strip()] = row["subtopics"].get(sub.strip(), 0) + 1
        sections.append({
            "id": sid,
            "questionCount": sum(1 for q in available if q["section"] == sid),
            "minutesPerQuestion": pace[sid],
            "topics": [
                {"topic": t, "questionCount": row["count"],
                 "subtopics": [{"subtopic": s, "questionCount": c} for s, c in sorted(row["subtopics"].items(), key=lambda x: x[0].lower())]}
                for t, row in sorted(topics.items(), key=lambda x: x[0].lower())
            ],
        })
    now = utcnow()
    in_progress = next((a for a in attempts if a.get("status") == "in_progress" and a.get("kind") == "drill"), None)
    pyq = sum(1 for q in available if is_pyq(q))
    return {
        "sections": sections,
        "sources": {"all": len(available), "pyq": pyq, "original": len(available) - pyq},
        "weakTopics": weak_topics(bank, stats),
        "mistakesDue": sum(1 for qid, s in stats.items() if qid in bank.questions and qid not in live and is_due(s, now)),
        "luckyGuesses": sum(1 for qid, s in stats.items() if qid in bank.questions and qid not in live and is_lucky_guess(s)),
        "inProgress": summary(in_progress) if in_progress else None,
        "limits": {"maxCount": MAX_COUNT, "maxMinutes": MAX_MINUTES},
    }


@router.post("/drills", response_model=Attempt)
def create_drill(body: DrillCreate, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    attempt_id = _drill_doc_id(user.user_id, body.clientToken)
    attempts = user_attempts(db, bank, user)
    mine = next((a for a in attempts if a["id"] == attempt_id), None)
    if mine is not None:  # the same Start click again (double tap / retry): same test
        return attempt_payload(mine, bank)
    running = next((a for a in attempts if a.get("status") == "in_progress" and a.get("kind") == "drill"), None)
    if running is not None:
        raise HTTPException(409, "Finish or submit the test you built earlier first.")

    exam = bank.exams.get("cat")
    version = pick_version(exam, None)
    marking = (version or {}).get("marking") or []
    if not {rule.get("type") for rule in marking if isinstance(rule, dict)} >= {"MCQ", "TITA"}:
        raise HTTPException(503, "The CAT exam pattern is not configured yet.")
    plan = build_plan(bank, body, user_stats(db, user.user_id), _live_ids(attempts), random.Random())

    now = utcnow()
    doc = {
        "userId": user.user_id,
        "testId": f"drill-{attempt_id}",
        "title": drill_title(body.mode, plan),
        "kind": "drill",
        "paperId": None,
        "examId": "cat",
        "year": None,
        "examVersionYear": version.get("year"),
        "marking": marking,
        "sectionOrderLocked": True,
        "sectionPlan": plan,
        "drill": {
            "mode": body.mode, "sections": list(body.sections), "topics": list(body.topics), "subtopics": list(body.subtopics),
            "difficulty": list(body.difficulty), "source": body.source, "count": body.count,
            "timeLimitMinutes": body.timeLimitMinutes, "clientToken": body.clientToken,
        },
        "status": "in_progress",
        "currentSectionIndex": 0,
        "currentSectionStartedAt": iso(now),
        "sectionLog": [{"id": plan[0]["id"], "startedAt": iso(now), "endedAt": None}],
        "startedAt": iso(now),
        "submittedAt": None,
        "responses": {},
        "savedSeq": 0,
        "result": None,
        "updatedAt": iso(now),
    }

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            return doc, {**doc, "id": attempt_id}
        if current.get("userId") != user.user_id:
            raise HTTPException(409, "Could not start this test; please retry.")
        return None, {**current, "id": attempt_id}  # a concurrent request with the same token created it

    return attempt_payload(occ_update(db, ATTEMPTS, attempt_id, mutate), bank)
