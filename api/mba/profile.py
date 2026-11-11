"""Onboarding profile: ``mbaProfiles/{userId}``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .models import MbaProfile, MbaProfileInput
from .store import PROFILES, get_doc, iso, occ_update, utcnow

router = APIRouter()


def load_profile(db: SafeFirestore, user_id: str) -> dict[str, Any] | None:
    data = get_doc(db, PROFILES, user_id)
    if not data:
        return None
    try:
        return MbaProfile.model_validate({**data, "userId": user_id}).model_dump()
    except Exception:  # noqa: BLE001 - unreadable profile == not onboarded
        return None


@router.get("/me/profile", response_model=MbaProfile)
def get_profile(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    profile = load_profile(db, user.user_id)
    if profile is None:
        raise HTTPException(404, "MBA profile not found; onboarding is not complete.")
    return profile


@router.put("/me/profile", response_model=MbaProfile)
def put_profile(body: MbaProfileInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        created = (current or {}).get("createdAt") if isinstance((current or {}).get("createdAt"), str) else now
        doc = {**body.model_dump(), "userId": user.user_id, "createdAt": created, "updatedAt": now}
        return doc, doc

    return occ_update(db, PROFILES, user.user_id, mutate)
