"""Mock/sectional test attempts with server-owned timers.

Timing: each section runs ``durationMinutes`` from ``currentSectionStartedAt``.
Every read/write first "advances" the attempt: sections whose time is over are
closed and the next one starts at the previous deadline; when the last section's
time is over the attempt is scored and submitted. Advancing is deterministic, so
it does not matter which request applies it.

Exams other than CAT store ``timerBlocks`` on the attempt: the timed unit is then a block
of sections sharing one timer (SNAP: all four sections, 60 min; XAT: Part 1 then GK) and
answers may change in any section of the current block. ``currentSectionIndex`` /
``currentSectionStartedAt`` / ``sectionLog`` then refer to blocks. ``sectionPlan`` stays one
entry per section, so analysis/insights read it unchanged. CAT attempts have no
``timerBlocks`` and every section is its own unit, exactly as before.

All state changes go through ``store.occ_update`` (update-time precondition), so
two concurrent requests can never both submit an attempt; only the request that
actually submitted it records the student's question stats.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .confidence import apply_confidence, breakdown, clean_confidence
from .deps import student
from .exams import derive_tests, is_pyq
from .models import Attempt, AttemptCreate, AttemptResult, AttemptsResponse, ResponsesPatch, SavedSeq
from .public import public_question, reveal
from .schedule import is_open
from .score_stats import own_counted_score, percentile, record_first_score, test_stats
from .scoring import normalize_answer, score_attempt
from .stats import apply_answer
from .store import ATTEMPTS, STATS, Bank, get_bank, iso, occ_update, parse_iso, query_eq, stat_id, user_stats, utcnow

router = APIRouter()

# An action mutates the attempt in place and returns True (submit it now), False (changed,
# keep going) or None (nothing changed). It may raise HTTPException to reject the request.
Action = Callable[[dict[str, Any], datetime], "bool | None"]


# ---------------------------------------------------------------- pure state helpers
def _plan(att: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in att.get("sectionPlan") or [] if isinstance(s, dict)]


def _units(att: dict[str, Any]) -> list[dict[str, Any]]:
    """Timed units: the attempt's ``timerBlocks`` when present, else one per plan section (CAT)."""
    blocks = [b for b in att.get("timerBlocks") or [] if isinstance(b, dict) and b.get("sectionIds")]
    if blocks:
        return blocks
    return [{"id": s["id"], "sectionIds": [s["id"]], "durationMinutes": s.get("durationMinutes")} for s in _plan(att)]


def section_deadline(att: dict[str, Any]) -> datetime:
    plan = _units(att)
    index = min(int(att.get("currentSectionIndex") or 0), len(plan) - 1)
    started = parse_iso(att.get("currentSectionStartedAt")) or parse_iso(att.get("startedAt")) or utcnow()
    return started + timedelta(minutes=int(plan[index].get("durationMinutes") or 0))


def advance(att: dict[str, Any], now: datetime) -> tuple[bool, bool]:
    """Close sections (timer blocks) whose time is over. Returns (changed, timeIsUp)."""
    changed = False
    plan = _units(att)
    while att.get("status") == "in_progress":
        deadline = section_deadline(att)
        if now < deadline:
            return changed, False
        index = int(att.get("currentSectionIndex") or 0)
        _close_section(att, index, deadline)
        changed = True
        if index >= len(plan) - 1:
            return changed, True
        _open_section(att, index + 1, deadline)
    return changed, False


def _close_section(att: dict[str, Any], index: int, at: datetime) -> None:
    log = att.setdefault("sectionLog", [])
    if index < len(log) and not log[index].get("endedAt"):
        log[index]["endedAt"] = iso(at)


def _open_section(att: dict[str, Any], index: int, at: datetime) -> None:
    att["currentSectionIndex"] = index
    att["currentSectionStartedAt"] = iso(at)
    att.setdefault("sectionLog", []).append({"id": _units(att)[index]["id"], "startedAt": iso(at), "endedAt": None})


def _question_section(att: dict[str, Any]) -> dict[str, int]:
    """questionId -> index of its timed unit (the section for CAT, the timer block otherwise)."""
    if not att.get("timerBlocks"):
        return {qid: i for i, section in enumerate(_plan(att)) for qid in section.get("questionIds") or []}
    unit_of = {sid: i for i, unit in enumerate(_units(att)) for sid in unit.get("sectionIds") or []}
    return {
        qid: unit_of.get(section["id"], i)
        for i, section in enumerate(_plan(att)) for qid in section.get("questionIds") or []
    }


def _scoring_version(att: dict[str, Any]) -> dict[str, Any]:
    """What ``score_attempt`` needs, as stored on the attempt (extras only for non-CAT exams)."""
    version: dict[str, Any] = {"marking": att.get("marking") or []}
    if att.get("unansweredPenalty"):
        version["unansweredPenalty"] = att["unansweredPenalty"]
    if att.get("excludedSections"):
        version["sections"] = [{"id": sid, "countsInTotal": False} for sid in att["excludedSections"]]
    return version


def _finalize(att: dict[str, Any], bank: Bank, now: datetime) -> None:
    deadline = section_deadline(att)
    submitted_at = min(now, deadline)
    _close_section(att, int(att.get("currentSectionIndex") or 0), submitted_at)
    sections = [
        (section["id"], [bank.questions[qid] for qid in section.get("questionIds") or [] if qid in bank.questions])
        for section in _plan(att)
    ]
    scored = score_attempt(sections, att.get("responses") or {}, _scoring_version(att))
    att["status"] = "submitted"
    att["submittedAt"] = iso(submitted_at)
    att["result"] = scored


# ---------------------------------------------------------------- persistence
def _check_owner(att: dict[str, Any] | None, user: CurrentUser) -> dict[str, Any]:
    if att is None or att.get("userId") != user.user_id:
        raise HTTPException(404, "Attempt not found.")
    return att


def transition(
    db: SafeFirestore, bank: Bank, attempt_id: str, user: CurrentUser, action: Action | None = None
) -> dict[str, Any]:
    """Advance timers, apply ``action``, submit when due — atomically. Returns the attempt."""
    now = utcnow()

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, tuple[dict[str, Any], bool]]:
        att = copy.deepcopy(_check_owner(current, user))
        if att.get("status") != "in_progress":
            if action is not None:
                action(att, now)  # lets actions reject (409) on submitted attempts
            return None, (att, False)
        changed, time_up = advance(att, now)
        finish = time_up
        if not time_up and action is not None:
            outcome = action(att, now)
            if outcome is not None:
                changed, finish = True, bool(outcome)
        if finish:
            _finalize(att, bank, now)
            changed = True
        if not changed:
            return None, (att, False)
        att["updatedAt"] = iso(now)
        return att, (att, finish)

    att, submitted_now = occ_update(db, ATTEMPTS, attempt_id, mutate)
    if submitted_now:
        record_attempt_stats(db, bank, att, now)
        # Built tests (drills.py) are one-off question mixes: no shared score histogram.
        if att.get("kind") != "drill" and record_first_score(db, {**att, "id": attempt_id}):
            att["scoreStatsCounted"] = True
    return att


def record_attempt_stats(db: SafeFirestore, bank: Bank, att: dict[str, Any], now: datetime) -> None:
    """Count every answered question of a just-submitted attempt into mbaQuestionStats."""
    stats = user_stats(db, att["userId"])
    per_question = (att.get("result") or {}).get("perQuestion") or {}
    batch, pending = db.batch(), 0
    for qid, response in (att.get("responses") or {}).items():
        answer = normalize_answer((response or {}).get("answer"))
        question = bank.questions.get(qid)
        if answer is None or question is None or qid not in per_question:
            continue
        correct = bool(per_question[qid].get("isCorrect"))
        doc = apply_answer(stats.get(qid), att["userId"], question, answer, correct, now, "attempt")
        doc = apply_confidence(doc, (response or {}).get("confidence"), correct)
        batch.set(db.collection(STATS).document(stat_id(att["userId"], qid)), doc)
        pending += 1
        if pending >= 400:
            batch.commit(timeout=DB_TIMEOUT)
            batch, pending = db.batch(), 0
    if pending:
        batch.commit(timeout=DB_TIMEOUT)


def user_attempts(db: SafeFirestore, bank: Bank, user: CurrentUser) -> list[dict[str, Any]]:
    """All attempts of the user (newest first), with timed-out ones submitted."""
    now = utcnow()
    attempts = []
    for doc_id, data in query_eq(db, ATTEMPTS, "userId", user.user_id):
        data = {**data, "id": doc_id}
        if data.get("status") == "in_progress" and _plan(data) and now >= section_deadline(data):
            data = {**transition(db, bank, doc_id, user), "id": doc_id}
        attempts.append(data)
    attempts.sort(key=lambda a: str(a.get("startedAt") or ""), reverse=True)
    return attempts


def live_question_ids(db: SafeFirestore, bank: Bank, user: CurrentUser) -> set[str]:
    """Question ids in the user's in-progress (still running) attempts."""
    ids: set[str] = set()
    for att in user_attempts(db, bank, user):
        if att.get("status") == "in_progress":
            ids.update(_question_section(att))
    return ids


# ---------------------------------------------------------------- payloads
def summary(att: dict[str, Any]) -> dict[str, Any]:
    result = att.get("result") or {}
    submitted = att.get("status") == "submitted"
    return {
        "id": att["id"],
        "testId": att.get("testId") or "",
        "title": att.get("title") or "",
        "status": "submitted" if submitted else "in_progress",
        "startedAt": att.get("startedAt") or "",
        "submittedAt": att.get("submittedAt") if submitted else None,
        "score": result.get("score") if submitted else None,
        "maxScore": result.get("maxScore") if submitted else None,
    }


def attempt_payload(att: dict[str, Any], bank: Bank) -> dict[str, Any]:
    plan = _plan(att)
    units = _units(att)
    index = min(int(att.get("currentSectionIndex") or 0), len(units) - 1)
    submitted = att.get("status") == "submitted"
    ends_at = att.get("submittedAt") if submitted else iso(section_deadline(att))
    questions = [
        {**public_question(bank.questions[qid], bank.sets), "sectionIndex": i}
        for i, section in enumerate(plan)
        for qid in section.get("questionIds") or []
        if qid in bank.questions
    ]
    responses = {
        qid: {
            "answer": r.get("answer"),
            "markedForReview": bool(r.get("markedForReview")),
            "timeSpentMs": int(r.get("timeSpentMs") or 0),
            "confidence": clean_confidence(r.get("confidence")),
        }
        for qid, r in (att.get("responses") or {}).items()
        if isinstance(r, dict)
    }
    return {
        "id": att["id"],
        "testId": att.get("testId") or "",
        "title": att.get("title") or "",
        "status": "submitted" if submitted else "in_progress",
        "currentSection": units[index]["sectionIds"][0],
        "sectionOrder": [section["id"] for section in plan],
        "sectionEndsAt": ends_at or iso(utcnow()),
        "serverNow": iso(utcnow()),
        "questions": questions,
        "responses": responses,
        "savedSeq": int(att.get("savedSeq") or 0),
        "examId": att.get("examId") or "cat",
        "timerBlocks": [
            {"id": u["id"], "name": u.get("name"), "sectionIds": list(u["sectionIds"]),
             "durationMinutes": int(u.get("durationMinutes") or 1)}
            for u in units
        ],
        "currentBlock": units[index]["id"],
    }


def procounsel_percentile(db: SafeFirestore, att: dict[str, Any]) -> dict[str, Any]:
    """The attempt's standing among other ProCounsel students' first attempts of the same test."""
    test_id = att.get("testId") or ""
    score = (att.get("result") or {}).get("score", 0)
    if att.get("scoreStatsCounted"):
        own = score
    else:
        own = own_counted_score(
            [{**data, "id": doc_id} for doc_id, data in query_eq(db, ATTEMPTS, "userId", att.get("userId"))], test_id
        )
    return percentile(test_stats(db, test_id), score, own)


def result_payload(att: dict[str, Any], bank: Bank, db: SafeFirestore | None = None) -> dict[str, Any]:
    result = att.get("result") or {}
    per_question = result.get("perQuestion") or {}
    responses = att.get("responses") or {}
    paper = bank.papers.get(att.get("paperId") or "") or {}
    questions = []
    for section in _plan(att):
        for qid in section.get("questionIds") or []:
            question = bank.questions.get(qid)
            if question is None:
                continue
            response = responses.get(qid) or {}
            marks = per_question.get(qid) or {}
            questions.append({
                **public_question(question, bank.sets),
                **reveal(question, marks.get("isCorrect")),
                "yourAnswer": normalize_answer(response.get("answer")),
                "timeSpentMs": int(response.get("timeSpentMs") or 0),
                "marks": marks.get("marks", 0),
                "confidence": clean_confidence(response.get("confidence")),
            })
    return {
        "id": att["id"],
        "testId": att.get("testId") or "",
        "title": att.get("title") or "",
        "submittedAt": att.get("submittedAt") or "",
        "score": result.get("score", 0),
        "maxScore": result.get("maxScore", 0),
        "sections": result.get("sections") or [],
        "questions": questions,
        "confidence": breakdown((q["confidence"], q["isCorrect"]) for q in questions),
        "isPyq": is_pyq(paper),
        "year": paper.get("year") if isinstance(paper.get("year"), int) else None,
        "slot": paper.get("slot") if isinstance(paper.get("slot"), int) else None,
        "procounselPercentile": procounsel_percentile(db, att) if db is not None else None,
        "examId": att.get("examId") or "cat",
    }


# ---------------------------------------------------------------- routes
def _attempt_doc_id(user_id: str, test_id: str, n: int) -> str:
    return hashlib.sha256(f"{user_id}|{test_id}|{n}".encode()).hexdigest()[:24]


@router.post("/attempts", response_model=Attempt)
def create_attempt(body: AttemptCreate, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    test = derive_tests(bank).get(body.testId)
    attempts = user_attempts(db, bank, user)
    if test is None:
        # Built tests (drills.py) are created by POST /drills; here they can only be resumed / reopened.
        own = sorted((a for a in attempts if a.get("testId") == body.testId), key=lambda a: a.get("status") != "in_progress")
        if not own:
            raise HTTPException(404, "Test not found.")
        return attempt_payload(own[0], bank)
    existing = [a for a in attempts if a.get("testId") == body.testId]
    for att in existing:
        if att.get("status") == "in_progress":
            return attempt_payload(att, bank)
    if not is_open(bank.papers.get(test["paperId"]) or {}, utcnow()):  # schedule window over (schedule.py)
        raise HTTPException(409, "This mock is no longer available.")
    # A second live attempt sharing questions (e.g. a sectional of the paper whose full mock is running)
    # could be submitted at once and reveal the answer keys of the running mock.
    wanted = {qid for section in test["sectionPlan"] for qid in section["questionIds"]}
    if any(a.get("status") == "in_progress" and wanted & set(_question_section(a)) for a in attempts):
        raise HTTPException(409, "Submit your test in progress first; it shares questions with this one.")

    now = utcnow()
    plan, blocks = test["sectionPlan"], test.get("timerBlocks") or []
    if body.sectionOrder and not test["locked"] and len(blocks) > 1:
        # NMAT / GMAT: the student picks the block order once, before the first timer starts.
        if sorted(body.sectionOrder) != sorted(b["id"] for b in blocks):
            raise HTTPException(422, "sectionOrder must list every section of this test exactly once.")
        blocks = sorted(blocks, key=lambda b: body.sectionOrder.index(b["id"]))  # type: ignore[union-attr]
        rank = {sid: i for i, b in enumerate(blocks) for sid in b["sectionIds"]}
        plan = sorted(plan, key=lambda s: rank[s["id"]])
    first = plan[0]["id"] if test["examId"] == "cat" else blocks[0]["id"]
    doc = {
        "userId": user.user_id,
        "testId": test["id"],
        "title": test["title"],
        "kind": test["kind"],
        "paperId": test["paperId"],
        "examId": test["examId"],
        "year": test["year"],
        "examVersionYear": test["version"].get("year"),
        "marking": test["version"].get("marking") or [],
        "sectionOrderLocked": test["locked"],
        "sectionPlan": plan,
        "status": "in_progress",
        "currentSectionIndex": 0,
        "currentSectionStartedAt": iso(now),
        "sectionLog": [{"id": first, "startedAt": iso(now), "endedAt": None}],
        "startedAt": iso(now),
        "submittedAt": None,
        "responses": {},
        "savedSeq": 0,
        "result": None,
        "updatedAt": iso(now),
    }
    if test["examId"] != "cat":  # CAT attempt docs keep their original shape (one timer per section)
        version = test["version"]
        doc["timerBlocks"] = blocks
        doc["unansweredPenalty"] = version.get("unansweredPenalty")
        doc["excludedSections"] = [s["id"] for s in version.get("sections") or [] if isinstance(s, dict) and s.get("countsInTotal") is False]
    for n in range(len(existing), len(existing) + 5):
        attempt_id = _attempt_doc_id(user.user_id, body.testId, n)

        def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            if current is None:
                return doc, {**doc, "id": attempt_id}
            return None, ({**current, "id": attempt_id} if current.get("status") == "in_progress" else None)

        att = occ_update(db, ATTEMPTS, attempt_id, mutate)
        if att is not None:  # created, or a concurrent request created it first (resume)
            return attempt_payload(att, bank)
    raise HTTPException(409, "Could not start the attempt; please retry.")


@router.get("/attempts/{attempt_id}", response_model=Attempt)
def get_attempt(attempt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    return attempt_payload({**transition(db, bank, attempt_id, user), "id": attempt_id}, bank)


@router.patch("/attempts/{attempt_id}/responses", response_model=SavedSeq)
def save_responses(
    attempt_id: str, body: ResponsesPatch, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    bank = get_bank(db)
    outcome: dict[str, Any] = {}

    def action(att: dict[str, Any], _now: datetime) -> bool | None:
        if att.get("status") != "in_progress":
            raise HTTPException(409, "This attempt has already been submitted.")
        saved = int(att.get("savedSeq") or 0)
        if body.seq <= saved:
            outcome["stale"] = saved
            return None
        where = _question_section(att)
        current = int(att.get("currentSectionIndex") or 0)
        responses = dict(att.get("responses") or {})
        for item in body.responses:
            if item.questionId not in where:
                raise HTTPException(400, f"Question {item.questionId} is not part of this attempt.")
            if where[item.questionId] != current:
                raise HTTPException(409, "That section is closed; answers can no longer be changed.")
            answer = normalize_answer(item.answer)
            question = bank.questions.get(item.questionId) or {}
            if answer is not None and question.get("type") != "TITA":
                option_ids = {str(o.get("id")) for o in question.get("options") or [] if isinstance(o, dict)}
                if answer not in option_ids:
                    raise HTTPException(422, f"Answer for {item.questionId} must be one of its option ids.")
            responses[item.questionId] = {
                "answer": answer,
                "markedForReview": item.markedForReview,
                "timeSpentMs": item.timeSpentMs,
                "confidence": item.confidence if answer is not None else None,
            }
        att["responses"] = responses
        att["savedSeq"] = body.seq
        return False

    att = transition(db, bank, attempt_id, user, action)
    if "stale" in outcome:
        return {"savedSeq": outcome["stale"]}
    if att.get("status") != "in_progress":  # time ran out before this write
        raise HTTPException(409, "Time is up for this attempt; it has been submitted.")
    return {"savedSeq": int(att.get("savedSeq") or 0)}


@router.post("/attempts/{attempt_id}/sections/{section_id}/submit", response_model=Attempt)
def submit_section(
    attempt_id: str, section_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    bank = get_bank(db)

    def action(att: dict[str, Any], now: datetime) -> bool:
        if att.get("status") != "in_progress":
            raise HTTPException(409, "This attempt has already been submitted.")
        plan = _units(att)
        index = int(att.get("currentSectionIndex") or 0)
        if section_id != plan[index]["id"] and section_id not in plan[index]["sectionIds"]:
            raise HTTPException(409, f"{section_id} is not the current section.")
        if index >= len(plan) - 1:
            return True  # last section: submit the attempt
        _close_section(att, index, now)
        _open_section(att, index + 1, now)
        return False

    return attempt_payload({**transition(db, bank, attempt_id, user, action), "id": attempt_id}, bank)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptResult)
def submit_attempt(attempt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)

    def action(att: dict[str, Any], _now: datetime) -> bool | None:
        return True if att.get("status") == "in_progress" else None  # submitted: same stored result

    return result_payload({**transition(db, bank, attempt_id, user, action), "id": attempt_id}, bank, db)


@router.get("/attempts/{attempt_id}/result", response_model=AttemptResult)
def get_result(attempt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    att = {**transition(db, bank, attempt_id, user), "id": attempt_id}
    if att.get("status") != "submitted":
        raise HTTPException(404, "Result is available after the attempt is submitted.")
    return result_payload(att, bank, db)


@router.get("/me/attempts", response_model=AttemptsResponse)
def my_attempts(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return {"attempts": [summary(att) for att in user_attempts(db, get_bank(db), user)]}
