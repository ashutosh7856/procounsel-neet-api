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
