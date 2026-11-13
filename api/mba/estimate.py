"""CAT score estimator: ``GET /me/score-estimate`` (contract: docs/mba-api.md → "Score estimator").

Estimates the student's CAT raw score on the current pattern (the latest exam version in
``mbaExams/cat`` whose question counts are announced) from their own answers only:

* Timed evidence — submitted full / sectional tests (previous-year papers and ProCounsel mocks).
  Gives the attempt rate (how many questions they answer under time) and accuracy, per section
  and separately for MCQ and TITA (TITA has no negative marking). Highest weight.
* Practice and daily-challenge answers (``mbaQuestionStats``) — accuracy only, lower weight.
  One observation per question, counted wrong if the student ever got it wrong (retries after
  seeing the solution would flatter the estimate). Questions already seen in a timed test are
  not counted again.

Every observation is weighted by recency (half-life ``HALF_LIFE_DAYS``). Per section and type:
expected marks = questions × attempt rate × (accuracy × correct + (1 − accuracy) × incorrect).
The range is an 80% band combining the uncertainty in the measured rates with the normal
paper-to-paper spread of a score at that accuracy. The MCQ/TITA mix of the current pattern is
taken from the latest previous-year papers in the bank (the official pattern does not state it).

Nothing here is an official CAT score or percentile, and no percentile mapping is ever made.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .analysis import practice_href
from .attempts import _plan, user_attempts
from .deps import student
from .exams import is_pyq, paper_sections
from .models import SECTION_IDS, SectionId
from .questions import daily_question_ids
from .scoring import marking_rule, normalize_answer
from .store import Bank, get_bank, parse_iso, user_stats, utcnow

router = APIRouter()

HALF_LIFE_DAYS = 30.0
W_PYQ, W_MOCK, W_PRACTICE = 1.0, 0.9, 0.35
SHRINK = 6.0  # pseudo-observations pulling a thin MCQ/TITA bucket towards the section as a whole
Z80 = 1.2816  # two-sided 80% band
MIN_TIMED_PER_SECTION = 1  # timed tests covering the section
MIN_ANSWERED_PER_SECTION = 20  # answered questions in the section, any source
TIMED_KINDS = ("full_mock", "sectional")
TYPES = ("MCQ", "TITA")
DISCLAIMER = (
    "An estimate of your CAT raw score from your own ProCounsel tests and practice. "
    "It is not an official score, and it does not predict your CAT percentile."
)


# ---------------------------------------------------------------- models
class EstimateTypeRow(BaseModel):
    type: Literal["MCQ", "TITA"]
    questionCount: int
    attemptRate: float | None
    accuracy: float | None
    answered: int  # observations behind the accuracy (timed + practice)
    expected: float


class EstimateSection(BaseModel):
    id: SectionId
    questionCount: int
    maxScore: float
    expected: float
    low: int
    high: int
    timedTests: int
    answered: int
    types: list[EstimateTypeRow]


class EstimateNeed(BaseModel):
    section: SectionId
    timedTestsNeeded: int
    questionsNeeded: int


class EstimateTip(BaseModel):
    title: str
    detail: str
    href: str


class EstimateInputs(BaseModel):
    pyqAttempts: int
    mockAttempts: int
    fullLength: int  # of those, full-length papers
    timedQuestions: int  # questions seen in timed tests (answered or not)
    timedAnswered: int
    practiceQuestions: int
    dailyQuestions: int
    lastTimedAt: str | None


class EstimatePattern(BaseModel):
    year: int
    totalDurationMinutes: int
    mixBasis: str  # where the MCQ/TITA split comes from


class ScoreEstimate(BaseModel):
    ready: bool
    pattern: EstimatePattern | None
    expected: float | None
    low: int | None
    high: int | None
    maxScore: float | None
    confidence: Literal["low", "medium", "high"] | None
    confidenceReason: str
    sections: list[EstimateSection]
    inputs: EstimateInputs
    needs: list[EstimateNeed]
    progress: float  # 0–1 towards the minimum data
    tips: list[EstimateTip]
    rules: dict[str, float]
    disclaimer: str


# ---------------------------------------------------------------- helpers
def _recency(moment: datetime | None, now: datetime) -> float:
    if moment is None:
        return 0.5
    age = max(0.0, (now - moment).total_seconds() / 86400)
    return 0.5 ** (age / HALF_LIFE_DAYS)


class _Bucket:
    """Weighted observations for one (section, type)."""

    def __init__(self) -> None:
        self.seen_w = self.answered_w = 0.0  # timed: questions shown / answered (attempt rate)
        self.seen_w2 = 0.0
        self.acc_w = self.acc_c = self.acc_w2 = 0.0  # accuracy, all sources
        self.answered = 0

    def timed(self, weight: float, answered: bool, correct: bool | None, source_w: float) -> None:
        self.seen_w += weight
        self.seen_w2 += weight * weight
        if answered:
            self.answered_w += weight
            self.accuracy(weight * source_w, bool(correct))

    def accuracy(self, weight: float, correct: bool) -> None:
        self.acc_w += weight
        self.acc_c += weight if correct else 0.0
        self.acc_w2 += weight * weight
        self.answered += 1

    @staticmethod
    def _neff(w: float, w2: float) -> float:
        return (w * w / w2) if w2 > 0 else 0.0


def target_version(bank: Bank) -> dict[str, Any] | None:
    """Latest CAT version with every section's question count announced."""
    versions = [v for v in (bank.exams.get("cat") or {}).get("versions") or [] if isinstance(v, dict) and isinstance(v.get("year"), int)]
    for version in sorted(versions, key=lambda v: -v["year"]):
        sections = [s for s in version.get("sections") or [] if isinstance(s, dict) and s.get("id") in SECTION_IDS]
        if sections and all(isinstance(s.get("questionCount"), int) and s["questionCount"] > 0 for s in sections):
            return version
    return None


def type_mix(bank: Bank, year: int) -> tuple[dict[str, float], str]:
    """Share of TITA questions per section, from the bank's previous-year papers closest to ``year``."""
    cat_papers = [p for p in bank.papers.values() if (p.get("examId") or "cat") == "cat"]  # other exams: not CAT's mix
    pyqs = [p for p in cat_papers if is_pyq(p) and paper_sections(bank, p)]
    if pyqs:
        best = max(p["year"] for p in pyqs if p["year"] <= year) if any(p["year"] <= year for p in pyqs) else max(p["year"] for p in pyqs)
        chosen = [p for p in pyqs if p["year"] == best]
        basis = f"CAT {best} papers ({len(chosen)} slot{'s' if len(chosen) != 1 else ''})"
    else:
        chosen = [p for p in cat_papers if paper_sections(bank, p)]
        basis = "ProCounsel mocks in the CAT pattern"
    counts: dict[str, list[int]] = {sid: [0, 0] for sid in SECTION_IDS}
    for paper in chosen:
        for sid, ids in paper_sections(bank, paper) or []:
            for qid in ids:
                counts[sid][0] += 1
                counts[sid][1] += 1 if bank.questions[qid].get("type") == "TITA" else 0
    if not any(total for total, _ in counts.values()):
        return {sid: 0.0 for sid in SECTION_IDS}, "no papers yet (all questions treated as MCQ)"
    return {sid: (tita / total if total else 0.0) for sid, (total, tita) in counts.items()}, basis


def _round(value: float) -> float:
    return round(value, 1)


# ---------------------------------------------------------------- core
def estimate(bank: Bank, attempts: list[dict[str, Any]], stats: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
    version = target_version(bank)
    buckets = {(sid, t): _Bucket() for sid in SECTION_IDS for t in TYPES}
    timed_tests = {sid: 0 for sid in SECTION_IDS}
    inputs = {"pyqAttempts": 0, "mockAttempts": 0, "fullLength": 0, "timedQuestions": 0, "timedAnswered": 0,
              "practiceQuestions": 0, "dailyQuestions": 0, "lastTimedAt": None}
    in_tests: set[str] = set()
    last_timed: datetime | None = None

    for att in attempts:
        if att.get("status") != "submitted":
            continue
        plan = _plan(att)
        in_tests.update(qid for section in plan for qid in section.get("questionIds") or [])
        if att.get("kind") not in TIMED_KINDS:
            continue
        submitted = parse_iso(att.get("submittedAt"))
        weight = _recency(submitted, now)
        pyq = is_pyq(bank.papers.get(att.get("paperId") or ""))
        source_w = W_PYQ if pyq else W_MOCK
        inputs["pyqAttempts" if pyq else "mockAttempts"] += 1
        inputs["fullLength"] += 1 if att.get("kind") == "full_mock" else 0
        if submitted and (last_timed is None or submitted > last_timed):
            last_timed = submitted
        per_question = (att.get("result") or {}).get("perQuestion") or {}
        responses = att.get("responses") or {}
        for section in plan:
            sid = section.get("id")
            if sid not in SECTION_IDS:
                continue
            timed_tests[sid] += 1
            for qid in section.get("questionIds") or []:
                question = bank.questions.get(qid)
                if question is None:
                    continue
                qtype = "TITA" if question.get("type") == "TITA" else "MCQ"
                answered = normalize_answer((responses.get(qid) or {}).get("answer")) is not None
                correct = (per_question.get(qid) or {}).get("isCorrect")
                buckets[(sid, qtype)].timed(weight, answered, correct, source_w)
                inputs["timedQuestions"] += 1
                inputs["timedAnswered"] += 1 if answered else 0
    inputs["lastTimedAt"] = last_timed.isoformat().replace("+00:00", "Z") if last_timed else None

    daily_cache: dict[str, set[str]] = {}

    def is_daily(qid: str, dates: list[str]) -> bool:
        for day in dates:
            if day not in daily_cache:
                daily_cache[day] = set(daily_question_ids(bank, day))
            if qid in daily_cache[day]:
                return True
        return False

    for qid, stat in stats.items():
        question = bank.questions.get(qid)
        if question is None or qid in in_tests or int(stat.get("attempts") or 0) <= 0:
            continue
        sid = question.get("section")
        if sid not in SECTION_IDS:
            continue
        dates = sorted(d for d in stat.get("answeredDates") or [] if isinstance(d, str))
        first = parse_iso(f"{dates[0]}T12:00:00+05:30") if dates else parse_iso(stat.get("lastAnsweredAt"))
        correct = int(stat.get("correct") or 0) > 0 and not stat.get("mistakeAt") and not stat.get("isMistake")
        qtype = "TITA" if question.get("type") == "TITA" else "MCQ"
        buckets[(sid, qtype)].accuracy(_recency(first, now) * W_PRACTICE, correct)
        inputs["dailyQuestions" if is_daily(qid, dates) else "practiceQuestions"] += 1

    answered_by_section = {sid: buckets[(sid, "MCQ")].answered + buckets[(sid, "TITA")].answered for sid in SECTION_IDS}
    needs = []
    progress_parts = []
    for sid in SECTION_IDS:
        timed_need = max(0, MIN_TIMED_PER_SECTION - timed_tests[sid])
        answer_need = max(0, MIN_ANSWERED_PER_SECTION - answered_by_section[sid])
        progress_parts.append(min(1.0, timed_tests[sid] / MIN_TIMED_PER_SECTION))
        progress_parts.append(min(1.0, answered_by_section[sid] / MIN_ANSWERED_PER_SECTION))
        if timed_need or answer_need:
            needs.append({"section": sid, "timedTestsNeeded": timed_need, "questionsNeeded": answer_need})
    progress = round(sum(progress_parts) / len(progress_parts), 3)
    rules = {"halfLifeDays": HALF_LIFE_DAYS, "weightPyq": W_PYQ, "weightMock": W_MOCK, "weightPractice": W_PRACTICE,
             "minTimedPerSection": MIN_TIMED_PER_SECTION, "minAnsweredPerSection": MIN_ANSWERED_PER_SECTION, "band": 0.8}
    base = {"inputs": inputs, "needs": needs, "progress": progress, "rules": rules, "disclaimer": DISCLAIMER}
    tips = _tips(timed_tests, buckets, inputs, last_timed, now, needs)

    if version is None or needs:
        reason = ("The current CAT pattern is not loaded yet." if version is None
                  else "Not enough of your own answers yet to estimate a score.")
        return {**base, "ready": False, "pattern": None, "expected": None, "low": None, "high": None, "maxScore": None,
                "confidence": None, "confidenceReason": reason, "sections": [], "tips": tips}

    mix, mix_basis = type_mix(bank, version["year"])
    sections_out = []
    total_expected = total_var = total_max = total_min = 0.0
    for spec in version.get("sections") or []:
        sid = spec.get("id")
        if sid not in SECTION_IDS:
            continue
        n_total = int(spec["questionCount"])
        n_tita = int(round(n_total * mix.get(sid, 0.0)))
        counts = {"MCQ": n_total - n_tita, "TITA": n_tita}
        both = [buckets[(sid, t)] for t in TYPES]
        sec_rate = sum(b.answered_w for b in both) / sum(b.seen_w for b in both) if sum(b.seen_w for b in both) else 0.0
        sec_acc = sum(b.acc_c for b in both) / sum(b.acc_w for b in both) if sum(b.acc_w for b in both) else 0.0
        expected = var = 0.0
        sec_max = sec_min = 0.0
        rows = []
        for qtype in TYPES:
            bucket, n = buckets[(sid, qtype)], counts[qtype]
            rule = marking_rule(version, qtype)
            n_rate = _Bucket._neff(bucket.seen_w, bucket.seen_w2)
            n_acc = _Bucket._neff(bucket.acc_w, bucket.acc_w2)
            # Shrink thin buckets towards the section as a whole (by effective sample size).
            rate = (n_rate * (bucket.answered_w / bucket.seen_w if bucket.seen_w else sec_rate) + SHRINK * sec_rate) / (n_rate + SHRINK)
            acc = (n_acc * (bucket.acc_c / bucket.acc_w if bucket.acc_w else sec_acc) + SHRINK * sec_acc) / (n_acc + SHRINK)
            per_attempt = acc * rule["correct"] + (1 - acc) * rule["incorrect"]
            spread = rule["correct"] - rule["incorrect"]
            attempted = n * rate
            row_expected = attempted * per_attempt
            # Paper-to-paper spread at this accuracy + uncertainty in the measured accuracy and attempt rate.
            var += attempted * acc * (1 - acc) * spread ** 2
            var += (attempted * spread) ** 2 * acc * (1 - acc) / (n_acc + SHRINK)
            var += (n * per_attempt) ** 2 * rate * (1 - rate) / (n_rate + SHRINK)
            expected += row_expected
            sec_max += n * rule["correct"]
            sec_min += n * min(0.0, rule["incorrect"])
            rows.append({"type": qtype, "questionCount": n, "attemptRate": round(rate, 3) if n_rate or sec_rate else None,
                         "accuracy": round(acc, 3) if bucket.acc_w or sec_acc else None, "answered": bucket.answered,
                         "expected": _round(row_expected)})
        sd = math.sqrt(var)
        sections_out.append({
            "id": sid, "questionCount": n_total, "maxScore": sec_max, "expected": _round(expected),
            "low": int(math.floor(max(sec_min, expected - Z80 * sd))), "high": int(math.ceil(min(sec_max, expected + Z80 * sd))),
            "timedTests": timed_tests[sid], "answered": answered_by_section[sid], "types": rows,
        })
        total_expected += expected
        total_var += var
        total_max += sec_max
        total_min += sec_min
    total_sd = math.sqrt(total_var)
    confidence, reason = _confidence(timed_tests, sum(answered_by_section.values()), last_timed, now)
    return {
        **base, "ready": True,
        "pattern": {"year": version["year"], "totalDurationMinutes": int(version.get("totalDurationMinutes") or 0), "mixBasis": mix_basis},
        "expected": _round(total_expected),
        "low": int(math.floor(max(total_min, total_expected - Z80 * total_sd))),
        "high": int(math.ceil(min(total_max, total_expected + Z80 * total_sd))),
        "maxScore": total_max, "confidence": confidence, "confidenceReason": reason,
        "sections": sections_out, "tips": tips,
    }


def _confidence(timed: dict[str, int], answered: int, last_timed: datetime | None, now: datetime) -> tuple[str, str]:
    fewest = min(timed.values())
    stale = last_timed is None or (now - last_timed).days > 30
    if fewest >= 3 and answered >= 300 and not stale:
        return "high", f"At least 3 timed tests per section and {answered} answered questions, the latest within 30 days."
    if fewest >= 2 and answered >= 120:
        return "medium", f"{fewest}+ timed tests per section and {answered} answered questions."
    return "low", f"Based on {fewest} timed test{'s' if fewest != 1 else ''} in your thinnest section and {answered} answered questions."


def _tips(timed: dict[str, int], buckets: dict[tuple[str, str], _Bucket], inputs: dict[str, Any],
          last_timed: datetime | None, now: datetime, needs: list[dict[str, Any]]) -> list[dict[str, str]]:
    tips: list[dict[str, str]] = []
    if inputs["fullLength"] < 3:
        tips.append({"title": "Take a full previous-year paper",
                     "detail": "A full timed CAT paper measures all three sections under real conditions — the strongest input.",
                     "href": "/mba/pyq"})
    thinnest = min(SECTION_IDS, key=lambda sid: (timed[sid], SECTION_IDS.index(sid)))
    if timed[thinnest] < 3:
        tips.append({"title": f"Take a timed {thinnest} sectional",
                     "detail": f"{thinnest} has the fewest timed tests behind it ({timed[thinnest]}).", "href": "/mba/pyq"})
    for need in needs:
        if need["questionsNeeded"]:
            tips.append({"title": f"Answer {need['questionsNeeded']} more {need['section']} questions",
                         "detail": "Practice questions sharpen the accuracy part of the estimate.",
                         "href": practice_href(need["section"])})
    thin_tita = [sid for sid in SECTION_IDS if buckets[(sid, "TITA")].answered < SHRINK]
    if thin_tita and not needs:
        sid = thin_tita[0]
        tips.append({"title": f"Answer more type-in (TITA) questions in {sid}",
                     "detail": "TITA has no negative marking, so it is estimated separately; you have few TITA answers there.",
                     "href": practice_href(sid)})
    if last_timed is not None and (now - last_timed).days > 21:
        tips.append({"title": "Take a fresh timed test",
                     "detail": f"Your last timed test was {(now - last_timed).days} days ago; older results count for less.",
                     "href": "/mba/pyq"})
    return tips[:4]


@router.get("/me/score-estimate", response_model=ScoreEstimate)
def score_estimate(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    bank = get_bank(db)
    return estimate(bank, user_attempts(db, bank, user), user_stats(db, user.user_id), utcnow())
