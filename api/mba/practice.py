"""Practice answers: check, reveal, record stats/mistakes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .attempts import live_question_ids
from .confidence import apply_confidence
from .deps import student
from .models import PracticeAnswerInput, PracticeAnswerResponse
from .public import reveal
from .questions import get_question_or_404
from .scoring import is_correct, normalize_answer
from .stats import apply_answer
from .store import STATS, get_bank, occ_update, stat_id, utcnow

router = APIRouter()


@router.post("/practice/answers", response_model=PracticeAnswerResponse)
def answer_practice(body: PracticeAnswerInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    question = get_question_or_404(bank, body.questionId)
    answer = normalize_answer(body.answer)
    if answer is None:
        raise HTTPException(422, "Answer is required.")
    if question.get("type") != "TITA":
        option_ids = {str(o.get("id")) for o in question.get("options") or [] if isinstance(o, dict)}
        if answer not in option_ids:
            raise HTTPException(422, "Answer must be one of the question's option ids.")
    if body.questionId in live_question_ids(db, bank, user):
        raise HTTPException(403, "This question is part of your mock in progress. Submit the mock first.")

    correct = bool(is_correct(question, answer))
    now = utcnow()

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        doc = apply_confidence(apply_answer(current, user.user_id, question, answer, correct, now, "practice"), body.confidence, correct)
        return doc, doc

    stat = occ_update(db, STATS, stat_id(user.user_id, body.questionId), mutate)
    return {**reveal(question, correct), "stats": {"attempts": stat["attempts"], "correct": stat["correct"]}}
