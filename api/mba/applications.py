"""Application tracker: the shortlist plus a per-institute document checklist (contract: docs/mba-api.md).

Stored on the shortlist entry, ``mbaShortlists/{userId}.items.<slug>.checklist``:
``{ <itemId>: { done, notApplicable, doneAt, updatedAt, custom?, label?, createdAt? } }``.
Default items are defined here (only their state is stored); custom items carry their own label.
Official application dates come from the bundled data files (``data/mba/{colleges,programs}/<slug>.json``
``keyDates``), never from the student.

Documents uploaded against a checklist item live in Storage + ``mbaApplicationDocs`` (doc_store.py); every document
write answers with the refreshed ``Application``. Admission outcomes (applied → WAT/PI call → interview → admit /
waitlist / reject → accepted / declined, each with an optional date) are stored on the entry as ``outcome``; Admin
gets anonymous per-institute counts only (``GET /admin/application-outcomes``).
"""

from __future__ import annotations

import json
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from . import doc_store
from .admin_roles import analytics_admin
from .deps import student
from .program_models import DATE_RE, SLUG_RE, ShortlistStatus
from .shortlist import known_institutes
from .shortlist import SHORTLISTS, _item, _items, _sort_key
from .store import get_doc, iso, local_date, occ_update, stream_all, utcnow

log = logging.getLogger(__name__)
router = APIRouter()
admin_router = APIRouter(prefix="/admin")

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
class ApplicationDocument(BaseModel):
    id: str
    itemId: str
    fileName: str
    contentType: str
    size: int  # bytes
    status: Literal["pending", "ready"]
    shareWithCounsellor: bool
    uploadedAt: str | None
    createdAt: str


class ChecklistItem(BaseModel):
    id: str
    label: str
    hint: str | None
    custom: bool
    optional: bool  # may be marked not applicable
    done: bool
    notApplicable: bool
    doneAt: str | None
    documents: list[ApplicationDocument]  # uploaded files, oldest first (ready ones only)


OutcomeResult = Literal["admit", "waitlist", "reject"]
OutcomeDecision = Literal["accepted", "declined"]
STAGES = ("applied", "shortlisted", "interviewDone")


class StageMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str | None = None  # YYYY-MM-DD, optional

    @field_validator("date")
    @classmethod
    def _day(cls, value: str | None) -> str | None:
        return _outcome_day(value)


class ResultMark(StageMark):
    value: OutcomeResult


class DecisionMark(StageMark):
    value: OutcomeDecision


class Outcome(BaseModel):
    """Where the application stands. A stage that is null has not been reached (or not recorded)."""

    model_config = ConfigDict(extra="forbid")

    applied: StageMark | None = None
    shortlisted: StageMark | None = None    # called for WAT / GD / PI
    interviewDone: StageMark | None = None  # WAT / GD / PI done
    result: ResultMark | None = None        # admit / waitlist / reject
    decision: DecisionMark | None = None    # student accepted / declined an admit


class OutcomeOut(Outcome):
    updatedAt: str | None = None


class OutcomeFunnel(BaseModel):
    applications: int  # institutes on the shortlist
    applied: int
    shortlisted: int
    interviewDone: int
    admit: int
    waitlist: int
    reject: int
    accepted: int
    declined: int


class DocumentsConfig(BaseModel):
    enabled: bool  # false = uploads are not configured on this server
    maxBytes: int
    allowedTypes: list[str]


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
    outcome: OutcomeOut
    createdAt: str
    updatedAt: str


class ApplicationsResponse(BaseModel):
    items: list[Application]
    funnel: OutcomeFunnel
    documents: DocumentsConfig


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


class UploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1, max_length=100)
    size: int = Field(ge=1)


class UploadTarget(BaseModel):
    url: str  # POST a multipart form here: every entry of ``fields`` first, then the file as ``file``
    fields: dict[str, str]
    expiresAt: str


class UploadStart(BaseModel):
    document: ApplicationDocument  # status "pending" until /complete
    upload: UploadTarget
    maxBytes: int


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareWithCounsellor: bool


class DownloadLink(BaseModel):
    url: str  # short-lived signed URL
    expiresAt: str


class CollegeOutcomeCounts(BaseModel):
    slug: str
    name: str | None
    shortName: str | None
    applied: int
    shortlisted: int
    interviewDone: int
    admit: int
    waitlist: int
    reject: int
    accepted: int
    declined: int


class OutcomesAggregate(BaseModel):
    colleges: list[CollegeOutcomeCounts]  # most applications first
    totals: CollegeOutcomeCounts  # slug "all"
    generatedAt: str


def _outcome_day(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not DATE_RE.match(value):
        raise ValueError("dates must be YYYY-MM-DD")
    day = date.fromisoformat(value)
    if day > local_date():
        raise ValueError("dates can't be in the future")
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
DocsMap = dict[tuple[str, str], list[dict[str, Any]]]
FUNNEL_KEYS = ("applied", "shortlisted", "interviewDone", "admit", "waitlist", "reject", "accepted", "declined")


def _mark(raw: Any, values: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    day = raw.get("date") if isinstance(raw.get("date"), str) and DATE_RE.match(raw["date"]) else None
    if values is None:
        return {"date": day}
    return {"value": raw["value"], "date": day} if raw.get("value") in values else None


def _outcome(raw_entry: dict[str, Any]) -> dict[str, Any]:
    raw = raw_entry.get("outcome") if isinstance(raw_entry.get("outcome"), dict) else {}
    out = {stage: _mark(raw.get(stage)) for stage in STAGES}
    out["result"] = _mark(raw.get("result"), ("admit", "waitlist", "reject"))
    out["decision"] = _mark(raw.get("decision"), ("accepted", "declined"))
    out["updatedAt"] = raw.get("updatedAt") if isinstance(raw.get("updatedAt"), str) else None
    return out


def _funnel_flags(outcome: dict[str, Any]) -> dict[str, bool]:
    result = (outcome.get("result") or {}).get("value")
    decision = (outcome.get("decision") or {}).get("value")
    return {"applied": outcome.get("applied") is not None, "shortlisted": outcome.get("shortlisted") is not None,
            "interviewDone": outcome.get("interviewDone") is not None, "admit": result == "admit",
            "waitlist": result == "waitlist", "reject": result == "reject", "accepted": decision == "accepted",
            "declined": decision == "declined"}


def _funnel(apps: list[dict[str, Any]]) -> dict[str, int]:
    out = {"applications": len(apps), **{k: 0 for k in FUNNEL_KEYS}}
    for app in apps:
        for key, hit in _funnel_flags(app["outcome"]).items():
            out[key] += hit
    return out


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


def _application(slug: str, raw: Any, institutes: dict[str, Any], docs: DocsMap | None = None) -> dict[str, Any]:
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
    checklist = [{**c, "documents": (docs or {}).get((slug, c["id"]), [])} for c in _checklist(raw)]
    applicable = [c for c in checklist if not c["notApplicable"]]
    return {
        **base,
        "officialDates": official,
        "effectiveDeadline": effective,
        "deadlineSource": source,
        "checklist": checklist,
        "progress": {"done": sum(1 for c in applicable if c["done"]), "total": len(applicable)},
        "outcome": _outcome(raw),
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
    return _application(slug, entry, known_institutes(db), doc_store.docs_by_item(db, user.user_id))


def _fresh_application(db: SafeFirestore, user: CurrentUser, slug: str) -> dict[str, Any]:
    raw = _items(get_doc(db, SHORTLISTS, user.user_id)).get(slug)
    if raw is None:
        raise HTTPException(404, "Not in your shortlist.")
    return _application(slug, raw, known_institutes(db), doc_store.docs_by_item(db, user.user_id))


# ---------------------------------------------------------------- endpoints
@router.get("/me/applications", response_model=ApplicationsResponse)
def list_applications(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    institutes = known_institutes(db)
    docs = doc_store.docs_by_item(db, user.user_id)
    apps = [_application(slug, raw, institutes, docs) for slug, raw in _items(get_doc(db, SHORTLISTS, user.user_id)).items()]
    return {"items": _sorted(apps), "funnel": _funnel(apps), "documents": doc_store.documents_config()}


@router.get("/me/applications/{slug}", response_model=Application)
def get_application(slug: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    return _fresh_application(db, user, slug)


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

    app = _mutate_checklist(db, user, slug, change)
    if doc_store.remove_where(db, user.user_id, slug, item_id):  # the item's uploaded files go with it
        app = _fresh_application(db, user, slug)
    return app


# ---------------------------------------------------------------- documents (doc_store.py)
def _require_documents() -> None:
    if not doc_store.enabled():
        raise HTTPException(503, "Document upload is not available right now.")


def _item_label(entry: dict[str, Any], item_id: str) -> str | None:
    """Label of a checklist item on this entry, or None when the item does not exist."""
    default = _DEFAULTS.get(item_id)
    if default is not None:
        return default[1]
    raw = (entry.get("checklist") or {}).get(item_id) if isinstance(entry.get("checklist"), dict) else None
    if isinstance(raw, dict) and raw.get("custom") is True and isinstance(raw.get("label"), str):
        return raw["label"].strip()
    return None


def _tick_item(db: SafeFirestore, user: CurrentUser, slug: str, item_id: str) -> None:
    """The first document on an item ticks it (unless the student marked it not applicable or already ticked it)."""
    def change(checklist: dict[str, Any], now: str) -> None:
        raw = checklist.get(item_id)
        new = dict(raw) if isinstance(raw, dict) else {}
        if new.get("done") is True or new.get("notApplicable") is True:
            return
        checklist[item_id] = {**new, "done": True, "doneAt": now, "updatedAt": now}

    try:
        _mutate_checklist(db, user, slug, change)
    except HTTPException:  # entry removed meanwhile; the document itself is fine
        pass


@router.post("/me/applications/{slug}/checklist/{item_id}/documents", response_model=UploadStart, status_code=201)
def start_upload(slug: str, item_id: str, body: UploadInput, user: CurrentUser = Depends(student),
                 db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _require_documents()
    _check_slug(slug)
    spec = doc_store.ALLOWED_TYPES.get(body.contentType.strip().lower())
    if spec is None:
        raise HTTPException(422, "Upload a PDF, JPG or PNG file.")
    content_type = body.contentType.strip().lower()
    if body.size > doc_store.MAX_BYTES:
        raise HTTPException(422, "Files can be at most 5 MB.")
    entry = _items(get_doc(db, SHORTLISTS, user.user_id)).get(slug)
    if not isinstance(entry, dict):
        raise HTTPException(404, "Not in your shortlist.")
    label = _item_label(entry, item_id)
    if label is None:
        raise HTTPException(404, "Checklist item not found.")
    mine = doc_store.user_docs(db, user.user_id)
    live = [d for _id, d in mine if d.get("status") == "ready" or not doc_store._stale_pending(d)]
    if sum(1 for d in live if d.get("slug") == slug and d.get("itemId") == item_id) >= doc_store.MAX_PER_ITEM:
        raise HTTPException(409, f"An item can have at most {doc_store.MAX_PER_ITEM} files. Delete one first.")
    if len(live) >= doc_store.MAX_PER_USER:
        raise HTTPException(409, f"You can keep at most {doc_store.MAX_PER_USER} files. Delete some first.")

    ext = spec[0]
    now = utcnow()
    doc_id = secrets.token_hex(16)
    data = {
        "userId": user.user_id, "slug": slug, "itemId": item_id, "itemLabel": label,
        "path": doc_store.object_path(user.user_id, slug, item_id, ext),
        "fileName": doc_store.clean_file_name(body.fileName, ext), "contentType": content_type, "size": body.size,
        "status": "pending", "shareWithCounsellor": False,
        "createdAt": iso(now), "uploadedAt": None, "updatedAt": iso(now),
    }
    upload = doc_store.signed_upload(data["path"], content_type)  # before the write: a signing failure leaves nothing
    db.collection(doc_store.DOCS).document(doc_id).create(data, timeout=DB_TIMEOUT)
    return {"document": doc_store.doc_out(doc_id, data),
            "upload": {**upload, "expiresAt": iso(now + doc_store.UPLOAD_TTL)}, "maxBytes": doc_store.MAX_BYTES}


@router.post("/me/application-docs/{doc_id}/complete", response_model=Application)
def complete_upload(doc_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _require_documents()
    data = doc_store.own_doc(db, user.user_id, doc_id)
    slug = str(data.get("slug"))
    if data.get("status") != "ready":
        found = doc_store.stored_object(str(data.get("path")))
        if found is None:
            raise HTTPException(409, "The file hasn't arrived yet. Try uploading it again.")
        size, stored_type, head = found
        if size > doc_store.MAX_BYTES or stored_type != data.get("contentType") or not doc_store.sniff_ok(stored_type, head):
            doc_store.remove_doc(db, doc_id, data)
            raise HTTPException(422, "That file isn't a valid PDF, JPG or PNG under 5 MB.")
        now = iso(utcnow())
        db.collection(doc_store.DOCS).document(doc_id).update(
            {"status": "ready", "size": size, "uploadedAt": now, "updatedAt": now}, timeout=DB_TIMEOUT)
        _tick_item(db, user, slug, str(data.get("itemId")))
    return _fresh_application(db, user, slug)


@router.get("/me/application-docs/{doc_id}/download", response_model=DownloadLink)
def download_doc(doc_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _require_documents()
    return doc_store.download_link(doc_store.own_doc(db, user.user_id, doc_id))


@router.patch("/me/application-docs/{doc_id}", response_model=Application)
def patch_doc(doc_id: str, body: DocumentPatch, user: CurrentUser = Depends(student),
              db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    data = doc_store.own_doc(db, user.user_id, doc_id)
    if data.get("status") != "ready":
        raise HTTPException(404, "Document not found.")
    if (data.get("shareWithCounsellor") is True) != body.shareWithCounsellor:
        db.collection(doc_store.DOCS).document(doc_id).update(
            {"shareWithCounsellor": body.shareWithCounsellor, "updatedAt": iso(utcnow())}, timeout=DB_TIMEOUT)
    return _fresh_application(db, user, str(data.get("slug")))


@router.delete("/me/application-docs/{doc_id}", response_model=Application)
def delete_doc(doc_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    data = doc_store.own_doc(db, user.user_id, doc_id)
    _require_documents()
    doc_store.remove_doc(db, doc_id, data)
    return _fresh_application(db, user, str(data.get("slug")))


# ---------------------------------------------------------------- admission outcomes
def _check_outcome(body: Outcome) -> None:
    problems = []
    if (body.shortlisted or body.result) and not body.applied:
        problems.append("mark the application as applied first")
    if body.interviewDone and not body.shortlisted:
        problems.append("an interview needs a WAT / PI call first")
    if body.decision and (body.result is None or body.result.value != "admit"):
        problems.append("you can accept or decline only an admit")
    chain = [m.date for m in (body.applied, body.shortlisted, body.interviewDone, body.result, body.decision)
             if m is not None and m.date]
    if chain != sorted(chain):
        problems.append("stage dates must be in order")
    if problems:
        raise HTTPException(422, "Can't save: " + "; ".join(problems) + ".")


@router.put("/me/applications/{slug}/outcome", response_model=Application)
def put_outcome(slug: str, body: Outcome, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _check_slug(slug)
    _check_outcome(body)
    now = iso(utcnow())
    stored = {k: v for k, v in body.model_dump().items()} | {"updatedAt": now}

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        items = dict(_items(current))
        entry = items.get(slug)
        if not isinstance(entry, dict):
            raise HTTPException(404, "Not in your shortlist.")
        old = _outcome(entry)
        old.pop("updatedAt")
        if old == body.model_dump():
            return None, entry
        entry = {**entry, "outcome": stored, "updatedAt": now}
        items[slug] = entry
        return {"items": items, "updatedAt": now}, entry

    entry = occ_update(db, SHORTLISTS, user.user_id, mutate)
    return _application(slug, entry, known_institutes(db), doc_store.docs_by_item(db, user.user_id))


@admin_router.get("/application-outcomes", response_model=OutcomesAggregate)
def admin_outcomes(_admin: CurrentAdmin = Depends(analytics_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Anonymous counts per institute over every student's shortlist (no user ids, names or dates leave the server)."""
    counts: dict[str, dict[str, int]] = {}
    for _doc_id, doc in stream_all(db, SHORTLISTS):
        for slug, entry in _items(doc).items():
            if not isinstance(entry, dict) or not isinstance(entry.get("outcome"), dict):
                continue
            flags = _funnel_flags(_outcome(entry))
            if not any(flags.values()):
                continue
            row = counts.setdefault(slug, {k: 0 for k in FUNNEL_KEYS})
            for key, hit in flags.items():
                row[key] += hit
    institutes = known_institutes(db)
    colleges = []
    for slug, row in counts.items():
        inst = institutes.get(slug)
        colleges.append({"slug": slug, "name": inst.name if inst else None, "shortName": inst.shortName if inst else None, **row})
    colleges.sort(key=lambda r: (-r["applied"], -r["admit"], r["slug"]))
    totals = {"slug": "all", "name": "All institutes", "shortName": None,
              **{k: sum(r[k] for r in colleges) for k in FUNNEL_KEYS}}
    return {"colleges": colleges, "totals": totals, "generatedAt": iso(utcnow())}
