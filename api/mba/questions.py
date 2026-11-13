"""Question bank browsing, bookmarks, mistakes and the daily challenge."""

from __future__ import annotations

import hashlib
import random
from typing import Any, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .exams import is_pyq
from .models import (
    SECTION_IDS,
    BookmarkResponse,
    DailyResponse,
    ExamSectionId,
    MistakeCategory,
    MistakeItem,
    MistakePatch,
    MistakesResponse,
    QuestionsResponse,
)
from .public import public_question
from .stats import has_answered, is_due, new_stat
from .store import STATS, Bank, get_bank, iso, local_date, occ_update, parse_iso, stat_id, user_stats, utcnow

router = APIRouter()

DAILY_MIN, DAILY_MAX = 5, 10
_CATEGORIES = set(get_args(MistakeCategory))


def question_sort_key(question: dict[str, Any]) -> tuple[Any, ...]:
    year = question.get("year") if isinstance(question.get("year"), int) else 0
    slot = question.get("slot") if isinstance(question.get("slot"), int) else 0
    section = SECTION_IDS.index(question["section"]) if question.get("section") in SECTION_IDS else 9
    number = question.get("number") if isinstance(question.get("number"), int) else 0
    return (-year, slot, str(question.get("paperId") or ""), section, number, str(question.get("id")))


def get_question_or_404(bank: Bank, question_id: str) -> dict[str, Any]:
    question = bank.questions.get(question_id)
    if question is None:
        raise HTTPException(404, "Question not found.")
    return question


def exam_of(question: dict[str, Any]) -> str:
    return question.get("examId") or "cat"


@router.get("/questions", response_model=QuestionsResponse)
def list_questions(
    section: ExamSectionId | None = None,
    examId: str = Query(default="cat", max_length=50),  # noqa: N803 - practice is per exam; CAT by default
    topic: str | None = Query(default=None, max_length=200),
    year: int | None = None,
    slot: int | None = None,
    paperId: str | None = Query(default=None, max_length=200),  # noqa: N803
    source: Literal["all", "pyq", "original"] = "all",
    filter: Literal["all", "unsolved", "incorrect", "bookmarked"] = "all",  # noqa: A002
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=200),
    user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    bank = get_bank(db)
    stats = user_stats(db, user.user_id)
    topic_key = topic.strip().lower() if topic else None

    def keep(q: dict[str, Any]) -> bool:
        if exam_of(q) != examId:
            return False
        if section and q.get("section") != section:
            return False
        if topic_key and str(q.get("topic") or "").strip().lower() != topic_key:
            return False
        if year is not None and q.get("year") != year:
            return False
        if slot is not None and q.get("slot") != slot:
            return False
        if paperId and q.get("paperId") != paperId:
            return False
        if source != "all" and is_pyq(q) != (source == "pyq"):
            return False
        stat = stats.get(q["id"])
        if filter == "unsolved":
            return not has_answered(stat)
        if filter == "incorrect":
            return bool(stat) and stat.get("lastCorrect") is False
        if filter == "bookmarked":
            return bool(stat) and bool(stat.get("bookmarked"))
        return True

    ordered = sorted((q for q in bank.questions.values() if keep(q)), key=question_sort_key)
    start = 0
    if cursor:
        ids = [q["id"] for q in ordered]
        if cursor not in ids:
            raise HTTPException(400, "Invalid cursor.")
        start = ids.index(cursor) + 1
    page = ordered[start:start + limit]
    has_more = start + limit < len(ordered)
    return {
        "questions": [
            {**public_question(q, bank.sets), "bookmarked": bool((stats.get(q["id"]) or {}).get("bookmarked"))}
            for q in page
        ],
        "nextCursor": page[-1]["id"] if page and has_more else None,
    }


# ---------------------------------------------------------------- bookmarks
def _set_bookmark(db: SafeFirestore, user: CurrentUser, question_id: str, value: bool) -> dict[str, Any]:
    question = get_question_or_404(get_bank(db), question_id)
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            if not value:
                return None, {"bookmarked": False}
            return {**new_stat(user.user_id, question), "bookmarked": True, "updatedAt": now}, {"bookmarked": True}
        if bool(current.get("bookmarked")) == value:
            return None, {"bookmarked": value}
        return {"bookmarked": value, "updatedAt": now}, {"bookmarked": value}

    return occ_update(db, STATS, stat_id(user.user_id, question_id), mutate)


@router.put("/me/bookmarks/{question_id}", response_model=BookmarkResponse)
def add_bookmark(question_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _set_bookmark(db, user, question_id, True)


@router.delete("/me/bookmarks/{question_id}", response_model=BookmarkResponse)
def remove_bookmark(question_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _set_bookmark(db, user, question_id, False)


# ---------------------------------------------------------------- mistakes
def mistake_item(stat: dict[str, Any], bank: Bank) -> dict[str, Any] | None:
    question = bank.questions.get(str(stat.get("questionId")))
    if question is None:
        return None
    return {
        "question": public_question(question, bank.sets),
        "lastAnswer": str(stat.get("lastAnswer") or ""),
        "category": stat.get("mistakeCategory") if stat.get("mistakeCategory") in _CATEGORIES else None,
        "note": stat.get("note") if isinstance(stat.get("note"), str) else None,
        "nextReviewAt": stat.get("nextReviewAt") if isinstance(stat.get("nextReviewAt"), str) else None,
        "retries": int(stat.get("retries") or 0),
    }


@router.get("/me/mistakes", response_model=MistakesResponse)
def list_mistakes(
    section: ExamSectionId | None = None,
    examId: str | None = Query(default=None, max_length=50),  # noqa: N803 - null = every exam
    due: bool = False,
    user: CurrentUser = Depends(student),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    bank = get_bank(db)
    now = utcnow()
    stats = [s for s in user_stats(db, user.user_id).values() if s.get("isMistake")]
    if section:
        stats = [s for s in stats if s.get("section") == section]
    if examId:
        stats = [s for s in stats if exam_of(bank.questions.get(str(s.get("questionId"))) or {}) == examId]
    if due:
        stats = [s for s in stats if is_due(s, now)]
    stats.sort(key=lambda s: parse_iso(s.get("nextReviewAt")) or now)
    return {"items": [item for s in stats if (item := mistake_item(s, bank))]}


@router.patch("/me/mistakes/{question_id}", response_model=MistakeItem)
def patch_mistake(
    question_id: str, body: MistakePatch, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)
) -> dict[str, Any]:
    bank = get_bank(db)
    get_question_or_404(bank, question_id)
    changes: dict[str, Any] = {}
    if "category" in body.model_fields_set:
        changes["mistakeCategory"] = body.category
    if "note" in body.model_fields_set:
        changes["note"] = body.note.strip() if body.note else None

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if not current or not current.get("isMistake"):
            raise HTTPException(404, "This question is not in your mistakes.")
        if not changes:
            return None, current
        update = {**changes, "updatedAt": iso(utcnow())}
        return update, {**current, **update}

    stat = occ_update(db, STATS, stat_id(user.user_id, question_id), mutate)
    item = mistake_item(stat, bank)
    if item is None:
        raise HTTPException(404, "Question not found.")
    return item


# ---------------------------------------------------------------- daily challenge
def daily_question_ids(bank: Bank, day: str) -> list[str]:
    """Deterministic 5–10 published questions for a calendar day (same for everyone).

    Prefers standalone questions (no shared passage/set) when there are enough.
    """
    published = [q for q in bank.questions.values() if exam_of(q) == "cat"]  # the daily challenge is CAT
    standalone = [q for q in published if not q.get("setId")]
    pool = sorted(q["id"] for q in (standalone if len(standalone) >= DAILY_MIN else published))
    if not pool:
        return []
    seed = int.from_bytes(hashlib.sha256(f"mba-daily|{day}".encode()).digest()[:8], "big")
    count = min(len(pool), DAILY_MIN + seed % (DAILY_MAX - DAILY_MIN + 1))
    return random.Random(seed).sample(pool, count)


@router.get("/daily", response_model=DailyResponse)
def daily(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    day = local_date().isoformat()
    ids = daily_question_ids(bank, day)
    stats = user_stats(db, user.user_id)
    completed = sum(1 for qid in ids if day in ((stats.get(qid) or {}).get("answeredDates") or []))
    return {"date": day, "questions": [public_question(bank.questions[qid], bank.sets) for qid in ids], "completed": completed}
