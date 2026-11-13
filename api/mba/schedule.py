"""Optional schedule window of a paper: ``availableFrom`` / ``availableUntil`` (ISO UTC strings).

* Before ``availableFrom`` a published paper is not in the content bank at all (no tests,
  no practice/daily questions), so a scheduled mock cannot leak before it goes live.
* From ``availableUntil`` on, its tests are no longer listed and cannot be started
  (an attempt already in progress can still be resumed and submitted; results stay).

Self-contained (no store import) because ``store.get_bank`` uses it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

Schedule = Literal["always", "upcoming", "live", "ended"]


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def available_from(paper: dict[str, Any]) -> datetime | None:
    return _moment(paper.get("availableFrom"))


def available_until(paper: dict[str, Any]) -> datetime | None:
    return _moment(paper.get("availableUntil"))


def has_started(paper: dict[str, Any], now: datetime) -> bool:
    start = available_from(paper)
    return start is None or start <= now


def is_open(paper: dict[str, Any], now: datetime) -> bool:
    """Tests of this paper may be listed and started now."""
    end = available_until(paper)
    return has_started(paper, now) and (end is None or now < end)


def schedule_state(paper: dict[str, Any], now: datetime) -> Schedule:
    start, end = available_from(paper), available_until(paper)
    if start is None and end is None:
        return "always"
    if start is not None and now < start:
        return "upcoming"
    if end is not None and now >= end:
        return "ended"
    return "live"
