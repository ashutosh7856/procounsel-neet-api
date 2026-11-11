"""Shared dependencies for the MBA routes."""

from __future__ import annotations

from api.auth import require_roles

# Every 🔒 endpoint in docs/mba-api.md: a logged-in user whose role is mbaStudent.
student = require_roles("mbaStudent")
