"""Authenticate requests with the login JWT issued by the Java backend.

The Java app signs an HS256 JWT whose subject is the user's phone number
(see JwtKeyProvider / UserService in ProcounsellorApp). We verify it with the
same key (``PROCOUNSEL_JWT_SECRET``, base64) and resolve the caller from
Firestore exactly like the Java ``getRole`` logic — read-only.

Admin-panel logins (``POST /api/auth/adminSignin`` in AuthController) are signed with
the same key; their subject is the admin's login email, which is the ``admins`` doc
id (Java ``JwtUtil.getAuthenticatedAdmin``). ``require_admin`` checks exactly that.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import jwt
from fastapi import Depends, Header, HTTPException, status

from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    phone_number: str
    role: str
    profile: dict[str, Any] = field(default_factory=dict, repr=False)


def _signing_key() -> bytes:
    secret = os.getenv("PROCOUNSEL_JWT_SECRET")
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured.")
    return base64.b64decode(secret)


def decode_phone_number(token: str) -> str:
    """JWT subject: the phone number for app users, the admin email for Admin-panel logins."""
    try:
        claims = jwt.decode(token, _signing_key(), algorithms=["HS256"], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from error
    return str(claims["sub"])


def resolve_user(db: SafeFirestore, phone_number: str) -> CurrentUser:
    """Mirror of the Java role resolution: users -> counsellors -> schoolStudents."""
    users = list(db.collection("users").where("phoneNumber", "==", phone_number).limit(1).stream(timeout=DB_TIMEOUT))
    if users:
        data = users[0].to_dict() or {}
        role = "mbaStudent" if str(data.get("interestedCourse") or "").lower() == "mba" else "user"
        return CurrentUser(data.get("userId") or users[0].id, phone_number, role, data)

    for collection, role in (("counsellors", "counsellor"), ("schoolStudents", "schoolStudent")):
        snap = db.collection(collection).document(phone_number).get(timeout=DB_TIMEOUT)
        if snap.exists:
            return CurrentUser(phone_number, phone_number, role, snap.to_dict() or {})

    raise HTTPException(status.HTTP_403_FORBIDDEN, "No ProCounsellor account for this token.")


def get_current_user(
    authorization: str | None = Header(default=None),
    db: SafeFirestore = Depends(get_db),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    return resolve_user(db, decode_phone_number(authorization[7:].strip()))


@dataclass(frozen=True)
class CurrentAdmin:
    """An Admin-panel user: ``admins/{adminId}`` where adminId is the login email (JWT subject)."""

    admin_id: str
    email: str | None
    role: str | None
    profile: dict[str, Any] = field(default_factory=dict, repr=False)


def resolve_admin(db: SafeFirestore, subject: str) -> CurrentAdmin:
    """Mirror of Java ``JwtUtil.getAuthenticatedAdmin``: the subject must be an ``admins`` doc id (read-only)."""
    if not subject or "/" in subject:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This token does not belong to an admin.")
    snap = db.collection("admins").document(subject).get(timeout=DB_TIMEOUT)
    if not snap.exists:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This token does not belong to an admin.")
    data = snap.to_dict() or {}
    role = data.get("role") if isinstance(data.get("role"), str) and data.get("role").strip() else None
    email = data.get("email") if isinstance(data.get("email"), str) else None
    return CurrentAdmin(subject, email, role, data)


def require_admin(
    authorization: str | None = Header(default=None),
    db: SafeFirestore = Depends(get_db),
) -> CurrentAdmin:
    """Dependency: a valid Admin-panel login JWT (``/api/auth/adminSignin``) whose subject is in ``admins``."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    return resolve_admin(db, decode_phone_number(authorization[7:].strip()))


def require_admin_roles(roles: Callable[[], frozenset[str] | None]) -> Callable[..., CurrentAdmin]:
    """Dependency factory: an admin whose stored ``role`` is in ``roles()`` (``None`` = any admin)."""

    def dependency(admin: CurrentAdmin = Depends(require_admin)) -> CurrentAdmin:
        allowed = roles()
        if allowed is not None and admin.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This admin role cannot access this resource.")
        return admin

    return dependency


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    """Dependency factory: ``user: CurrentUser = Depends(require_roles("mbaStudent"))``."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account's role cannot access this resource.")
        return user

    return dependency
