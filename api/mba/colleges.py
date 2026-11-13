"""In-app college list: the IIMs (``mbaPrograms``) plus the non-IIM colleges bundled in
``data/mba/colleges/*.json`` — every institute a student can shortlist (see shortlist.known_institutes).

Public, read-only. The bundled files are official data with per-field source URLs (data/mba/SOURCES.md);
they ship with the deployment (not excluded in .vercelignore) and are read once per process.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.db import SafeFirestore, get_db

from .program_models import SLUG_RE
from .programs import load_institutes

router = APIRouter()

COLLEGES_DIR = Path(__file__).resolve().parents[2] / "data" / "mba" / "colleges"

Kind = Literal["iim", "other"]


class CollegeProgram(BaseModel):
    code: str | None
    name: str
    durationYears: float | None
    feeTotal: int | None
    intake: int | None
    medianSalary: int | None
    salaryYear: str | None  # e.g. "2024-26 batch final placements" or "2025"


class CollegeSummary(BaseModel):
    slug: str
    name: str
    shortName: str
    kind: Kind
    type: str | None  # bundled colleges: "private", "government", "deemed", "university department"
    city: str | None
    state: str | None
    website: str | None
    examsAccepted: list[str]
    programs: list[CollegeProgram]
    hasCutoffs: bool  # official minimum CAT thresholds on record (IIMs only, used by /eligibility)
    applicationDeadline: str | None  # official, YYYY-MM-DD or YYYY-MM (bundled colleges only)
    sourceUrl: str | None  # official admissions page for the figures shown (bundled colleges only)


class CollegesResponse(BaseModel):
    colleges: list[CollegeSummary]
    total: int  # before filters
    cities: list[str]  # every city in the unfiltered list, for the filter control


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _bundled_summary(data: dict[str, Any]) -> dict[str, Any] | None:
    slug, name = data.get("slug"), _str(data.get("name"))
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or name is None:
        return None
    programs, exams = [], []
    for prog in data.get("programs") or []:
        if not isinstance(prog, dict) or not _str(prog.get("name")):
            continue
        programs.append({
            "code": None, "name": prog["name"].strip(), "durationYears": _num(prog.get("durationYears")),
            "feeTotal": _int(prog.get("feeTotal")), "intake": _int(prog.get("intake")),
            "medianSalary": _int(prog.get("medianSalary")), "salaryYear": _str(prog.get("salaryYear")),
        })
        for exam in prog.get("examsAccepted") or []:
            if isinstance(exam, str) and exam.strip() and exam.strip() not in exams:
                exams.append(exam.strip())
    dates = data.get("keyDates") if isinstance(data.get("keyDates"), dict) else {}
    first = next((p for p in data.get("programs") or [] if isinstance(p, dict)), {})
    sources = first.get("sources") if isinstance(first.get("sources"), dict) else {}
    return {
        "slug": slug, "name": name, "shortName": _str(data.get("shortName")) or name, "kind": "other",
        "type": _str(data.get("type")), "city": _str(data.get("city")), "state": _str(data.get("state")),
        "website": _str(data.get("website")), "examsAccepted": exams, "programs": programs, "hasCutoffs": False,
        "applicationDeadline": _str(dates.get("applicationDeadline")),
        "sourceUrl": _str(sources.get("admission")) or _str(dates.get("source")),
    }


@lru_cache(maxsize=1)
def bundled_colleges() -> dict[str, dict[str, Any]]:
    """slug -> summary of each bundled (non-IIM) college file. Unreadable files are skipped."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(COLLEGES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        summary = _bundled_summary(data) if isinstance(data, dict) else None
        if summary:
            found[summary["slug"]] = summary
    return found


def _iim_summary(inst: Any) -> dict[str, Any]:
    return {
        "slug": inst.slug, "name": inst.name, "shortName": inst.shortName, "kind": "iim", "type": None,
        "city": inst.city, "state": inst.state, "website": inst.website, "examsAccepted": ["CAT"],
        "programs": [{
            "code": p.code, "name": p.name, "durationYears": p.durationYears, "feeTotal": p.feeTotal, "intake": p.intake,
            "medianSalary": p.medianSalary, "salaryYear": str(p.medianSalaryYear) if p.medianSalaryYear else None,
        } for p in inst.programs],
        "hasCutoffs": bool(inst.cutoffs), "applicationDeadline": None, "sourceUrl": None,
    }


def _matches(row: dict[str, Any], needle: str) -> bool:
    hay = " ".join([row["name"], row["shortName"], row["slug"], row["city"] or "", row["state"] or "",
                    *[p["name"] for p in row["programs"]], *[p["code"] or "" for p in row["programs"]]])
    return needle in hay.casefold()


@router.get("/colleges", response_model=CollegesResponse)
def list_colleges(
    q: str | None = Query(default=None, max_length=80),
    city: str | None = Query(default=None, max_length=60),
    state: str | None = Query(default=None, max_length=60),
    kind: Kind | None = Query(default=None),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    # IIMs from Firestore win over a bundled file with the same slug (same rule as the shortlist).
    rows = {**bundled_colleges(), **{slug: _iim_summary(inst) for slug, inst in load_institutes(db).items()}}
    everything = sorted(rows.values(), key=lambda r: (r["kind"] != "iim", r["shortName"].casefold()))
    needle = (q or "").strip().casefold()
    want_city = (city or "").strip().casefold()
    want_state = (state or "").strip().casefold()
    shown = [
        r for r in everything
        if (kind is None or r["kind"] == kind)
        and (not want_city or (r["city"] or "").casefold() == want_city)
        and (not want_state or (r["state"] or "").casefold() == want_state)
        and (not needle or _matches(r, needle))
    ]
    cities = sorted({r["city"] for r in everything if r["city"]}, key=str.casefold)
    return {"colleges": shown, "total": len(everything), "cities": cities}
