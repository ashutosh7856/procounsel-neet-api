"""Lazy Firebase/Firestore connection.

Configuration (same variable names as the Java backend):
  FIREBASE_CONFIG             service-account JSON as a string (Vercel)
  FIREBASE_CREDENTIALS_PATH   path to a service-account JSON file (local alternative)
  FIREBASE_REALTIME_CONFIG    Realtime Database URL (optional)

Nothing connects at import time, so the API still boots without any of these set.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Literal

from .guard import SafeFirestore

APP_NAME = "procounsel-neet-api"
# Seconds per Firestore call; without it a bad key makes requests hang forever.
DB_TIMEOUT = 10

Mode = Literal["service_account", "disabled"]


class DatabaseConfigError(RuntimeError):
    """Raised when the database is not configured or the configuration is unsafe."""


_lock = threading.Lock()
_db: SafeFirestore | None = None
_app: Any = None


def connection_mode() -> Mode:
    if os.getenv("FIREBASE_CONFIG") or os.getenv("FIREBASE_CREDENTIALS_PATH"):
        return "service_account"
    return "disabled"


def _load_service_account() -> dict[str, Any]:
    raw = os.getenv("FIREBASE_CONFIG")
    if not raw:
        path = os.getenv("FIREBASE_CREDENTIALS_PATH", "")
        try:
            with open(path, "r", encoding="utf-8") as file:
                raw = file.read()
        except OSError as error:
            raise DatabaseConfigError(f"Cannot read FIREBASE_CREDENTIALS_PATH: {error}") from error
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DatabaseConfigError("Firebase service-account JSON is not valid JSON.") from error
    if info.get("type") != "service_account" or not info.get("project_id"):
        raise DatabaseConfigError("Firebase credentials must be a service-account JSON with a project_id.")
    return info


def _connect() -> tuple[SafeFirestore, Any]:
    import firebase_admin
    from firebase_admin import credentials, firestore

    mode = connection_mode()
    options: dict[str, Any] = {}
    if os.getenv("FIREBASE_REALTIME_CONFIG"):
        options["databaseURL"] = os.environ["FIREBASE_REALTIME_CONFIG"]

    if mode == "service_account":
        info = _load_service_account()
        try:
            app = firebase_admin.get_app(APP_NAME)
        except ValueError:
            app = firebase_admin.initialize_app(credentials.Certificate(info), options, name=APP_NAME)
        return SafeFirestore(firestore.client(app)), app

    raise DatabaseConfigError("Database is not configured. See docs/database.md.")


def get_db() -> SafeFirestore:
    """Guarded Firestore handle. Use as a FastAPI dependency: ``db = Depends(get_db)``."""
    global _db, _app
    if _db is None:
        with _lock:
            if _db is None:
                _db, _app = _connect()
    return _db


def get_firebase_app() -> Any:
    """firebase_admin App (e.g. for Firebase Auth or Realtime Database)."""
    get_db()
    return _app


def reset_for_tests() -> None:
    global _db, _app
    _db, _app = None, None
