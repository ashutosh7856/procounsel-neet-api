from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from .firebase import DB_TIMEOUT, DatabaseConfigError, connection_mode, get_db

router = APIRouter(prefix="/api/v1/db", tags=["System"])


@router.get("/health")
def db_health() -> dict[str, Any]:
    """Checks the Firestore connection with a single read of a non-existent document."""
    mode = connection_mode()
    if mode == "disabled":
        # Which settings this deployment can see (presence only, never values) — makes a
        # missing/unattached Vercel variable obvious.
        seen = {name: bool(os.getenv(name)) for name in (
            "FIREBASE_CONFIG", "FIREBASE_CREDENTIALS_PATH", "PROCOUNSEL_JWT_SECRET", "OPENAI_API_KEY")}
        return {"ok": False, "mode": mode, "error": "Database is not configured.",
                "vercelEnv": os.getenv("VERCEL_ENV"), "envPresent": seen}
    try:
        db = get_db()
        db.collection("users").document("neet-api-healthcheck").get(timeout=DB_TIMEOUT)
    except DatabaseConfigError as error:
        return {"ok": False, "mode": mode, "error": str(error)}
    except Exception as error:  # surface connectivity/permission problems without crashing
        return {"ok": False, "mode": mode, "error": f"{type(error).__name__}: {error}"[:300]}
    return {"ok": True, "mode": mode, "project": db.project}
