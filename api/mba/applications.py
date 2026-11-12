"""Application tracker: the shortlist plus a per-institute document checklist (contract: docs/mba-api.md).

Stored on the shortlist entry, ``mbaShortlists/{userId}.items.<slug>.checklist``:
``{ <itemId>: { done, notApplicable, doneAt, updatedAt, custom?, label?, createdAt? } }``.
Default items are defined here (only their state is stored); custom items carry their own label.
Official application dates come from the bundled data files (``data/mba/{colleges,programs}/<slug>.json``
``keyDates``), never from the student.
"""

from __future__ import annotations

import json
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db

from .deps import student
from .program_models import DATE_RE, SLUG_RE, ShortlistStatus
from .shortlist import known_institutes
from .shortlist import SHORTLISTS, _item, _items, _sort_key
from .store import get_doc, iso, occ_update, utcnow

log = logging.getLogger(__name__)
router = APIRouter()

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "mba"
MAX_CUSTOM = 20
LABEL_MAX = 120

# (id, label, hint, optional). Optional items can be marked "not applicable".
DEFAULT_ITEMS: tuple[tuple[str, str, str | None, bool], ...] = (
    ("cat-scorecard", "CAT scorecard", "Download it from iimcat.ac.in when results are out.", False),
    ("graduation", "Graduation marksheets / degree certificate",
     "Final-year students: marksheets up to the latest semester.", False),
    ("class-10-12", "Class 10 and Class 12 marksheets", None, False),
    ("id-proof", "Photo ID proof", "Aadhaar, passport, PAN card or driving licence.", False),
    ("category-certificate", "Category / EWS / PwD certificate",
     "Only if you apply under a reserved category; check the validity date the institute asks for.", True),
    ("work-experience", "Work-experience letters", "Offer, relieving and current-employer letters, if you have work experience.", True),
    ("sop-essays", "SOP / essays", "Only if the institute asks for them.", True),
    ("fee-receipt", "Application fee receipt", None, False),
)
_DEFAULTS = {item[0]: item for item in DEFAULT_ITEMS}


# ---------------------------------------------------------------- models
class ChecklistItem(BaseModel):
    id: str
    label: str
    hint: str | None
    custom: bool
    optional: bool  # may be marked not applicable
    done: bool
    notApplicable: bool
    doneAt: str | None


class ChecklistProgress(BaseModel):
    done: int
    total: int  # items that apply (not-applicable items are excluded)


class OfficialDates(BaseModel):
    applicationOpens: str | None  # YYYY-MM-DD or YYYY-MM
    applicationDeadline: str | None
    examDate: str | None
    notes: str | None
    sourceUrl: str | None


class Application(BaseModel):
    slug: str
    name: str | None
    shortName: str | None
    status: ShortlistStatus
    deadline: str | None  # entered by the student
    officialDates: OfficialDates | None
    effectiveDeadline: str | None  # student deadline, else the official application deadline
    deadlineSource: Literal["student", "official"] | None
    notes: str | None
    checklist: list[ChecklistItem]
    progress: ChecklistProgress
    createdAt: str
    updatedAt: str


class ApplicationsResponse(BaseModel):
    items: list[Application]


class ChecklistPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool | None = None
    notApplicable: bool | None = None


class ChecklistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=LABEL_MAX)

    @field_validator("label")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("label must not be blank")
        return value


# ---------------------------------------------------------------- official dates (bundled data)
def _date(value: Any, month_ok: bool = True) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if DATE_RE.match(value) or (month_ok and len(value) == 7 and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit()):
        return value
    return None


def _source_url(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.startswith("http"):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("url"), str) and raw["url"].startswith("http"):
        return raw["url"]
    return None


@lru_cache(maxsize=1)
def official_dates() -> dict[str, dict[str, Any]]:
    """slug -> OfficialDates payload, from every bundled data file that has ``keyDates``."""
    out: dict[str, dict[str, Any]] = {}
    for folder in ("programs", "colleges"):
        for path in sorted((DATA_DIR / folder).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                log.warning("Skipping %s: %s", path, error)
                continue
            key_dates = data.get("keyDates") if isinstance(data, dict) else None
            slug = data.get("slug") if isinstance(data, dict) and isinstance(data.get("slug"), str) else path.stem
            if not isinstance(key_dates, dict) or slug in out:
                continue
            payload = {
                "applicationOpens": _date(key_dates.get("applicationOpens")),
                "applicationDeadline": _date(key_dates.get("applicationDeadline")),
                "examDate": _date(key_dates.get("examDate")),
                "notes": key_dates["notes"].strip() if isinstance(key_dates.get("notes"), str) and key_dates["notes"].strip() else None,
                "sourceUrl": _source_url(key_dates.get("source")),
            }
            if any(payload[k] for k in ("applicationOpens", "applicationDeadline", "examDate", "notes")):
                out[slug] = payload
    return out


# ---------------------------------------------------------------- shaping
def _checklist(raw_entry: dict[str, Any]) -> list[dict[str, Any]]:
    stored = raw_entry.get("checklist") if isinstance(raw_entry.get("checklist"), dict) else {}
    items: list[dict[str, Any]] = []

    def state(raw: Any) -> dict[str, Any]:
        raw = raw if isinstance(raw, dict) else {}
        done = raw.get("done") is True
        doneAt = raw.get("doneAt")
        return {"done": done, "notApplicable": raw.get("notApplicable") is True,
                "doneAt": doneAt if done and isinstance(doneAt, str) else None}

    for item_id, label, hint, optional in DEFAULT_ITEMS:
        st = state(stored.get(item_id))
        if not optional:
            st["notApplicable"] = False
        items.append({"id": item_id, "label": label, "hint": hint, "custom": False, "optional": optional, **st})

    customs = [
        (item_id, raw) for item_id, raw in stored.items()
        if item_id not in _DEFAULTS and isinstance(raw, dict) and raw.get("custom") is True
        and isinstance(raw.get("label"), str) and raw["label"].strip()
    ]
    customs.sort(key=lambda pair: (str(pair[1].get("createdAt") or ""), pair[0]))
    for item_id, raw in customs:
        items.append({"id": item_id, "label": raw["label"].strip(), "hint": None, "custom": True, "optional": True,
                      **{**state(raw), "notApplicable": False}})
    return items


def _application(slug: str, raw: Any, institutes: dict[str, Any]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    base = _item(slug, raw, institutes)
    official = official_dates().get(slug)
    official_deadline = _date(official.get("applicationDeadline"), month_ok=False) if official else None
    if base["deadline"]:
        effective, source = base["deadline"], "student"
    elif official_deadline:
        effective, source = official_deadline, "official"
    else:
        effective, source = None, None
    checklist = _checklist(raw)
    applicable = [c for c in checklist if not c["notApplicable"]]
    return {
        **base,
        "officialDates": official,
        "effectiveDeadline": effective,
        "deadlineSource": source,
        "checklist": checklist,
        "progress": {"done": sum(1 for c in applicable if c["done"]), "total": len(applicable)},
    }


def _sorted(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(apps, key=lambda a: _sort_key({**a, "deadline": a["effectiveDeadline"]}))


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise HTTPException(404, "Not in your shortlist.")


def _mutate_checklist(db: SafeFirestore, user: CurrentUser, slug: str, change) -> dict[str, Any]:
    """Apply ``change(checklist_dict, now)`` to the entry's checklist with OCC; returns the new entry."""
    _check_slug(slug)
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        items = dict(_items(current))
        entry = items.get(slug)
        if not isinstance(entry, dict):
            raise HTTPException(404, "Not in your shortlist.")
        entry = dict(entry)
        checklist = dict(entry["checklist"]) if isinstance(entry.get("checklist"), dict) else {}
        change(checklist, now)
        entry["checklist"] = checklist
        entry["updatedAt"] = now
        items[slug] = entry
        return {"items": items, "updatedAt": now}, entry

    entry = occ_update(db, SHORTLISTS, user.user_id, mutate)
    return _application(slug, entry, known_institutes(db))


# ---------------------------------------------------------------- endpoints
@router.get("/me/applications", response_model=ApplicationsResponse)
def list_applications(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    institutes = known_institutes(db)
    apps = [_application(slug, raw, institutes) for slug, raw in _items(get_doc(db, SHORTLISTS, user.user_id)).items()]
    return {"items": _sorted(apps)}


@router.get("/me/applications/{slug}", response_model=Application)
def get_application(slug: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    raw = _items(get_doc(db, SHORTLISTS, user.user_id)).get(slug)
    if raw is None:
        raise HTTPException(404, "Not in your shortlist.")
    return _application(slug, raw, known_institutes(db))


@router.patch("/me/applications/{slug}/checklist/{item_id}", response_model=Application)
def patch_checklist_item(slug: str, item_id: str, body: ChecklistPatch, user: CurrentUser = Depends(student),
                         db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    if body.done is None and body.notApplicable is None:
        raise HTTPException(422, "Send done and/or notApplicable.")

    def change(checklist: dict[str, Any], now: str) -> None:
        default = _DEFAULTS.get(item_id)
        raw = checklist.get(item_id)
        if default is None and not (isinstance(raw, dict) and raw.get("custom") is True):
            raise HTTPException(404, "Checklist item not found.")
        if body.notApplicable is not None and (default is None or not default[3]):
            raise HTTPException(422, "Only optional items can be marked not applicable.")
        new = dict(raw) if isinstance(raw, dict) else {}
        if body.done is not None:
            new["done"] = body.done
            new["doneAt"] = now if body.done else None
        if body.notApplicable is not None:
            new["notApplicable"] = body.notApplicable
            if body.notApplicable:
                new["done"], new["doneAt"] = False, None
        new["updatedAt"] = now
        checklist[item_id] = new

    return _mutate_checklist(db, user, slug, change)


@router.post("/me/applications/{slug}/checklist", response_model=Application, status_code=201)
def add_checklist_item(slug: str, body: ChecklistCreate, user: CurrentUser = Depends(student),
                       db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    def change(checklist: dict[str, Any], now: str) -> None:
        customs = [raw for raw in checklist.values() if isinstance(raw, dict) and raw.get("custom") is True]
        if len(customs) >= MAX_CUSTOM:
            raise HTTPException(409, f"An application can have at most {MAX_CUSTOM} custom items.")
        if any(str(raw.get("label", "")).casefold() == body.label.casefold() for raw in customs):
            raise HTTPException(409, "That item is already on the checklist.")
        item_id = f"c-{secrets.token_hex(4)}"
        while item_id in checklist:
            item_id = f"c-{secrets.token_hex(4)}"
        checklist[item_id] = {"custom": True, "label": body.label, "done": False, "doneAt": None,
                              "createdAt": now, "updatedAt": now}

    return _mutate_checklist(db, user, slug, change)


@router.delete("/me/applications/{slug}/checklist/{item_id}", response_model=Application)
def delete_checklist_item(slug: str, item_id: str, user: CurrentUser = Depends(student),
                          db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    def change(checklist: dict[str, Any], now: str) -> None:
        if item_id in _DEFAULTS:
            raise HTTPException(422, "Default items can't be removed; mark an optional one not applicable instead.")
        raw = checklist.get(item_id)
        if not (isinstance(raw, dict) and raw.get("custom") is True):
            raise HTTPException(404, "Checklist item not found.")
        checklist.pop(item_id)

    return _mutate_checklist(db, user, slug, change)
