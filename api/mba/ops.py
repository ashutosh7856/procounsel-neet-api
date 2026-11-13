"""MBA ops panel for the Admin panel: ``GET /api/v1/mba/admin/ops`` (contract: docs/mba-api.md → "MBA ops").

AI usage per India-time day from ``mbaAiUsage`` (``{userId}_{date}`` docs with a call count,
queried by ``date`` — single-field equality, no composite index), with an ESTIMATED cost
from ai_pricing.py; content counts by status; question-report and counsellor-request counts.
Read-only. Role: ``analytics`` (admin_roles.py).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import CurrentAdmin
from api.db import SafeFirestore, get_db

from .admin import _paper_sections, _state, _status
from .admin_roles import analytics_admin
from .ai_pricing import ai_pricing
from .counsellor_requests import REQUESTS
from .reports import REPORTS
from .schedule import schedule_state
from .store import AI_USAGE, PAPERS, QUESTIONS, SETS, iso, local_date, parse_iso, query_eq, stream_all, utcnow

router = APIRouter(prefix="/admin")

TOP_USERS = 10


class AiDay(BaseModel):
    date: str
    calls: int
    students: int
    estCostUsd: float


class AiTopUser(BaseModel):
    userId: str
    calls: int
    days: int
    estCostUsd: float


class AiPricingOut(BaseModel):
    model: str
    inputPerMTokUsd: float
    outputPerMTokUsd: float
    estInputTokensPerCall: float
    estOutputTokensPerCall: float
    sourceUrl: str


class AiUsage(BaseModel):
    days: list[AiDay]  # oldest first, one entry per day (zeros included)
    totalCalls: int
    totalStudents: int
    estCostUsd: float
    topUsers: list[AiTopUser]
    pricing: AiPricingOut


class ContentCounts(BaseModel):
    papers: dict[str, int]     # draft / published / archived, plus upcoming / live / ended for scheduled published papers
    questions: dict[str, int]  # draft / flagged / published / archived (questions listed in a paper) + unlisted
    sets: dict[str, int]       # draft / published / archived


class SupportCounts(BaseModel):
    reports: dict[str, int]        # open / resolved / rejected / last7Days
    counsellorRequests: dict[str, int]  # open / assigned / done


class OpsSummary(BaseModel):
    generatedAt: str
    ai: AiUsage
    content: ContentCounts
    support: SupportCounts


def _ai_usage(db: SafeFirestore, days: int) -> dict[str, Any]:
    pricing = ai_pricing()
    today = local_date()
    per_day, per_user, user_days = [], {}, {}
    students: set[str] = set()
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        calls, users = 0, set()
        for doc_id, doc in query_eq(db, AI_USAGE, "date", day):
            count = int(doc.get("count") or 0) if isinstance(doc.get("count"), (int, float)) else 0
            user_id = str(doc.get("userId") or doc_id.rsplit("_", 1)[0])
            calls += count
            users.add(user_id)
            per_user[user_id] = per_user.get(user_id, 0) + count
            user_days[user_id] = user_days.get(user_id, 0) + 1
        students |= users
        per_day.append({"date": day, "calls": calls, "students": len(users), "estCostUsd": pricing.cost_usd(calls)})
    total = sum(d["calls"] for d in per_day)
    top = sorted(per_user.items(), key=lambda item: (-item[1], item[0]))[:TOP_USERS]
    return {
        "days": per_day,
        "totalCalls": total,
        "totalStudents": len(students),
        "estCostUsd": pricing.cost_usd(total),
        "topUsers": [{"userId": uid, "calls": n, "days": user_days[uid], "estCostUsd": pricing.cost_usd(n)} for uid, n in top],
        "pricing": {
            "model": pricing.model, "inputPerMTokUsd": pricing.input_per_mtok_usd, "outputPerMTokUsd": pricing.output_per_mtok_usd,
            "estInputTokensPerCall": pricing.est_input_tokens, "estOutputTokensPerCall": pricing.est_output_tokens,
            "sourceUrl": pricing.source_url,
        },
    }


def _content(db: SafeFirestore) -> dict[str, Any]:
    now = utcnow()
    papers = dict(stream_all(db, PAPERS))
    paper_counts = {"draft": 0, "published": 0, "archived": 0, "upcoming": 0, "live": 0, "ended": 0}
    listed: set[str] = set()
    for paper in papers.values():
        status = _status(paper)
        paper_counts[status] += 1
        if status == "published" and (state := schedule_state(paper, now)) != "always":
            paper_counts[state] += 1
        listed |= {qid for _, ids in _paper_sections(paper) for qid in ids}
    question_counts = {"draft": 0, "flagged": 0, "published": 0, "archived": 0, "unlisted": 0}
    for qid, doc in stream_all(db, QUESTIONS):
        if qid in listed:
            question_counts[_state(doc)] += 1
        else:
            question_counts["unlisted"] += 1  # archived from a paper (Admin delete / re-import)
    set_counts = {"draft": 0, "published": 0, "archived": 0}
    for _, doc in stream_all(db, SETS):
        set_counts[_status(doc)] += 1
    return {"papers": paper_counts, "questions": question_counts, "sets": set_counts}


def _support(db: SafeFirestore) -> dict[str, Any]:
    since = utcnow() - timedelta(days=7)
    reports = {"open": 0, "resolved": 0, "rejected": 0, "last7Days": 0}
    for _, doc in stream_all(db, REPORTS):
        status = doc.get("status") if doc.get("status") in ("resolved", "rejected") else "open"
        reports[status] += 1
        created = parse_iso(doc.get("createdAt"))
        if created and created >= since:
            reports["last7Days"] += 1
    requests = {"open": 0, "assigned": 0, "done": 0}
    for _, doc in stream_all(db, REQUESTS):
        if doc.get("status") in requests:
            requests[doc["status"]] += 1
    return {"reports": reports, "counsellorRequests": requests}


@router.get("/ops", response_model=OpsSummary)
def ops_summary(
    days: int = Query(default=14, ge=1, le=60),
    _admin: CurrentAdmin = Depends(analytics_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    return {"generatedAt": iso(utcnow()), "ai": _ai_usage(db, days), "content": _content(db), "support": _support(db)}
