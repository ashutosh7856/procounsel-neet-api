"""Student shortlist of institutes: ``mbaShortlists/{userId}`` (one document per student).

Document: ``{ userId, items: { <slug>: { status, deadline, notes, createdAt, updatedAt, checklist? } }, updatedAt }``
(``checklist`` and ``outcome`` are owned by api/mba/applications.py and preserved by PUT; removing an institute
also deletes the documents uploaded for it, see doc_store.py).
Writes use optimistic concurrency (``occ_update``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from . import doc_store
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


COLLEGES_DIR = Path(__file__).resolve().parents[2] / "data" / "mba" / "colleges"


@lru_cache(maxsize=1)
def _bundled_colleges() -> dict[str, Any]:
    """Non-IIM institutes from the bundled official data files (IIMs live in mbaPrograms)."""
    found: dict[str, Any] = {}
    for path in sorted(COLLEGES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug, name = data.get("slug"), data.get("name")
        if isinstance(slug, str) and SLUG_RE.match(slug) and isinstance(name, str) and name.strip():
            found[slug] = SimpleNamespace(name=name, shortName=data.get("shortName") or name)
    return found


def known_institutes(db: SafeFirestore) -> dict[str, Any]:
    """Every institute a student can shortlist: IIMs (Firestore) plus the bundled colleges."""
    return {**_bundled_colleges(), **load_institutes(db)}


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise HTTPException(404, "Institute not found.")


@router.get("/me/shortlist", response_model=ShortlistResponse)
def list_shortlist(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    institutes = known_institutes(db)
    items = [_item(slug, raw, institutes) for slug, raw in _items(get_doc(db, SHORTLISTS, user.user_id)).items()]
    items.sort(key=_sort_key)
    return {"items": items}


@router.get("/me/shortlist/{slug}", response_model=ShortlistItem)
def get_shortlist_item(slug: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    raw = _items(get_doc(db, SHORTLISTS, user.user_id)).get(slug)
    if raw is None:
        raise HTTPException(404, "Not in your shortlist.")
    return _item(slug, raw, known_institutes(db))


@router.put("/me/shortlist/{slug}", response_model=ShortlistItem)
def put_shortlist_item(slug: str, body: ShortlistInput, user: CurrentUser = Depends(student),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    institutes = known_institutes(db)
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
        # The document checklist and admission outcome (api/mba/applications.py) live on the same entry; a PUT keeps them.
        for kept in ("checklist", "outcome"):
            if previous is not None and isinstance(previous.get(kept), dict):
                entry[kept] = previous[kept]
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

    removed = occ_update(db, SHORTLISTS, user.user_id, mutate)
    doc_store.remove_where(db, user.user_id, slug)  # uploaded documents for this institute go with it
    return {"removed": removed}
