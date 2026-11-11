from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .deps import CurrentUser, get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Who the bearer token belongs to (same JWT the Java backend issues at login)."""
    return {"userId": user.user_id, "phoneNumber": user.phone_number, "role": user.role}
