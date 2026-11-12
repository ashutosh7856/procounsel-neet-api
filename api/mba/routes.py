"""MBA router: ``/api/v1/mba`` (contract: docs/mba-api.md)."""

from __future__ import annotations

from fastapi import APIRouter

from . import admin, ai, attempts, dashboard, exams, practice, profile, questions
from . import programs, shortlist  # Phase D

router = APIRouter(prefix="/api/v1/mba", tags=["MBA"])

# /exams, /papers, /programs and /eligibility are public; every other route declares Depends(student) itself,
# except /admin/* (admin.py), which declares Depends(content_admin).
for module in (exams, profile, dashboard, questions, practice, attempts, ai, admin, programs, shortlist):
    router.include_router(module.router)
from . import applications, counsellor_requests  # noqa: E402 - application tracker + "talk to my counsellor"
for module in (applications, counsellor_requests):
    router.include_router(module.router)
from . import gdpi  # noqa: E402 - WAT / GD / PI preparation + AI mock interview
router.include_router(gdpi.router)
from . import notifications, planner  # noqa: E402 - study planner + in-app notifications
for module in (planner, notifications):
    router.include_router(module.router)
from . import analysis, insights, leaderboard, reports  # noqa: E402 - mock analyst, insights, question reports, daily leaderboard
for module in (analysis, insights, leaderboard, reports):
    router.include_router(module.router)
router.include_router(reports.admin_router)
