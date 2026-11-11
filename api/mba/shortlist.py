"""Student shortlist of institutes: ``mbaShortlists/{userId}`` (one document per student).

Document: ``{ userId, items: { <slug>: { status, deadline, notes, createdAt, updatedAt } }, updatedAt }``.
Writes use optimistic concurrency (``occ_update``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .program_models import SLUG_RE, ShortlistDeleteResponse, ShortlistInput, ShortlistItem, ShortlistResponse
from .programs import load_institutes
from .store import get_doc, iso, occ_update, utcnow

router = APIRouter()

SHORTLISTS = "mbaShortlists"
MAX_ITEMS = 100
_STATUSES = {"interested", "shortlisted", "applied", "interview", "offer", "declined"}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _item(slug: str, raw: Any, institutes: dict[str, Any]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    inst = institutes.get(slug)
    created = _str(raw.get("createdAt")) or ""
    return {
        "slug": slug,
        "name": inst.name if inst else None,
        "shortName": inst.shortName if inst else None,
        "status": raw.get("status") if raw.get("status") in _STATUSES else "interested",
        "deadline": _str(raw.get("deadline")),
        "notes": _str(raw.get("notes")),
        "createdAt": created,
        "updatedAt": _str(raw.get("updatedAt")) or created,
    }


def _items(doc: dict[str, Any] | None) -> dict[str, Any]:
    items = (doc or {}).get("items")
    return items if isinstance(items, dict) else {}


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    # Upcoming deadlines first, then undated, newest update first within each group.
    return (item["deadline"] is None, item["deadline"] or "", "".join(chr(0x10FFFF - ord(c)) for c in item["updatedAt"]))


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise HTTPException(404, "Institute not found.")


@router.get("/me/shortlist", response_model=ShortlistResponse)
def list_shortlist(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    institutes = load_institutes(db)
    items = [_item(slug, raw, institutes) for slug, raw in _items(get_doc(db, SHORTLISTS, user.user_id)).items()]
    items.sort(key=_sort_key)
    return {"items": items}


@router.get("/me/shortlist/{slug}", response_model=ShortlistItem)
def get_shortlist_item(slug: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    raw = _items(get_doc(db, SHORTLISTS, user.user_id)).get(slug)
    if raw is None:
        raise HTTPException(404, "Not in your shortlist.")
    return _item(slug, raw, load_institutes(db))


@router.put("/me/shortlist/{slug}", response_model=ShortlistItem)
def put_shortlist_item(slug: str, body: ShortlistInput, user: CurrentUser = Depends(student),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    institutes = load_institutes(db)
    if slug not in institutes:
        raise HTTPException(404, "Institute not found.")
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        items = dict(_items(current))
        previous = items.get(slug) if isinstance(items.get(slug), dict) else None
        if previous is None and len(items) >= MAX_ITEMS:
            raise HTTPException(409, f"A shortlist can hold at most {MAX_ITEMS} institutes.")
        entry = {
            "status": body.status,
            "deadline": body.deadline,
            "notes": body.notes.strip() if body.notes and body.notes.strip() else None,
            "createdAt": _str((previous or {}).get("createdAt")) or now,
            "updatedAt": now,
        }
        items[slug] = entry
        return {"userId": user.user_id, "items": items, "updatedAt": now}, entry

    entry = occ_update(db, SHORTLISTS, user.user_id, mutate)
    return _item(slug, entry, institutes)


@router.delete("/me/shortlist/{slug}", response_model=ShortlistDeleteResponse)
def delete_shortlist_item(slug: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
        items = dict(_items(current))
        if current is None or slug not in items:
            return None, False
        items.pop(slug)
        return {"items": items, "updatedAt": now}, True

    return {"removed": occ_update(db, SHORTLISTS, user.user_id, mutate)}
