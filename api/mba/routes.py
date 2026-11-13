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
from . import metrics  # noqa: E402 - admin success metrics
router.include_router(metrics.router)
from . import colleges  # noqa: E402 - in-app college list (IIMs + bundled colleges)
router.include_router(colleges.router)
from . import confidence, drills  # noqa: E402 - practice modes (test builder, drills) + self-rated confidence
for module in (drills, confidence):
    router.include_router(module.router)
from . import estimate, pyq  # noqa: E402 - previous-year papers + CAT score estimator
for module in (pyq, estimate):
    router.include_router(module.router)
from . import authoring, ops, privacy  # noqa: E402 - admin test authoring + MBA ops panel + student "delete my MBA data"
for module in (authoring, ops, privacy):
    router.include_router(module.router)
from . import community, support  # noqa: E402 - doubts, study groups, events, help-centre tickets
for module in (community, support):
    router.include_router(module.router)
from . import exam_updates  # noqa: E402 - admin-managed exam-update feed (dashboard + notifications)
router.include_router(exam_updates.router)
router.include_router(applications.admin_router)  # anonymous admission-outcome counts
from . import coach, syllabus  # noqa: E402 - AI section coaches + "explain my plan", CAT syllabus with lesson progress
for module in (coach, syllabus):
    router.include_router(module.router)
