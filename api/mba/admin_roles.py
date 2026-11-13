"""Admin-panel roles for the MBA endpoints (contract: docs/mba-api.md → "Admin roles").

The caller's role is the ``role`` field of the Java ``admins/{email}`` doc (read-only; the
Java app stores any string, the Admin panel offers superAdmin, COURSE, blogger, ... and the
four MBA roles below). Each capability maps to a set of roles:

=============  ========================================  ===============================
capability     what it unlocks                           extra role (env to override)
=============  ========================================  ===============================
content        write/edit/review questions and sets      mbaFaculty      MBA_ADMIN_ROLES_CONTENT
tests          create/import papers, order, schedule,    mbaTestManager  MBA_ADMIN_ROLES_TESTS
               publish
support        question reports, counsellor requests     mbaSupport      MBA_ADMIN_ROLES_SUPPORT
analytics      MBA ops panel (AI usage, counts)          mbaAnalyst      MBA_ADMIN_ROLES_ANALYTICS
=============  ========================================  ===============================

Every capability also includes the roles in ``MBA_CONTENT_ADMIN_ROLES`` (default
``superAdmin,COURSE`` — the single setting used before, so existing admins keep full
access), and ``superAdmin`` can always do everything. ``*`` in any of these = every admin.
"""

from __future__ import annotations

import os
from typing import Callable

from api.auth import CurrentAdmin, require_admin_roles

CAPABILITIES = ("content", "tests", "support", "analytics")
DEFAULT_BASE_ROLES = "superAdmin,COURSE"
DEFAULT_ROLES = {"content": "mbaFaculty", "tests": "mbaTestManager", "support": "mbaSupport", "analytics": "mbaAnalyst"}


def _parse(raw: str) -> frozenset[str] | None:
    roles = {role.strip() for role in raw.split(",") if role.strip()}
    return None if "*" in roles else frozenset(roles)


def capability_roles(capability: str) -> frozenset[str] | None:
    """Roles allowed for one capability (``None`` = every admin)."""
    base = _parse(os.getenv("MBA_CONTENT_ADMIN_ROLES", DEFAULT_BASE_ROLES))
    extra = _parse(os.getenv(f"MBA_ADMIN_ROLES_{capability.upper()}", DEFAULT_ROLES[capability]))
    if base is None or extra is None:
        return None
    return base | extra | {"superAdmin"}


def allowed_roles(*capabilities: str) -> Callable[[], frozenset[str] | None]:
    """Roles allowed for ANY of ``capabilities`` (evaluated per request, so env changes apply)."""

    def roles() -> frozenset[str] | None:
        out: set[str] = set()
        for capability in capabilities:
            allowed = capability_roles(capability)
            if allowed is None:
                return None
            out |= allowed
        return frozenset(out)

    return roles


def capabilities_of(role: str | None) -> list[str]:
    out = []
    for capability in CAPABILITIES:
        allowed = capability_roles(capability)
        if allowed is None or role in allowed:
            out.append(capability)
    return out


def require_mba(*capabilities: str) -> Callable[..., CurrentAdmin]:
    """Dependency: an admin whose role has at least one of ``capabilities``."""
    return require_admin_roles(allowed_roles(*capabilities))


content_editor = require_mba("content")             # questions + sets
test_manager = require_mba("tests")                 # papers: create, import, schedule, publish
content_reader = require_mba("content", "tests")    # read papers/questions, validate, export, reorder
support_admin = require_mba("support")              # counsellor requests
reports_admin = require_mba("support", "content")   # question reports (support triages, faculty fixes)
analytics_admin = require_mba("analytics")          # MBA ops panel
