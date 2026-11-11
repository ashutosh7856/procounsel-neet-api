"""Phase D public endpoints: MBA programmes and the CAT percentile -> eligibility check.

Data: ``mbaPrograms/{slug}`` (one document per institute, programmes and official minimum
CAT thresholds embedded), imported from data/mba/programs/*.json by
scripts/mba/import_programs.py. Read through a short in-process TTL cache.

The eligibility check compares a student's percentiles with each institute's PUBLISHED
MINIMUM shortlisting thresholds only. It never estimates admission chances.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.db import SafeFirestore, get_db

from .program_models import (
    EligibilityInput,
    EligibilityResponse,
    InstituteDetail,
    InstituteRecord,
    ProgramsResponse,
)
from .store import stream_all

log = logging.getLogger(__name__)
router = APIRouter()

PROGRAMS = "mbaPrograms"

METHODOLOGY = (
    "For each institute we take the most recent official admission policy we hold and look up the "
    "minimum CAT percentiles it publishes for your category (and PwD status) for the first, "
    "CAT-based shortlisting stage. Your overall percentile and each sectional percentile you entered "
    "(VARC, DILR, QA) are compared with those minimums: a value equal to or above the minimum passes. "
    "'meets_minimum' means you are at or above every published minimum; 'below_minimum' lists the "
    "parts you are below; 'unknown' means the institute has not published a minimum for your "
    "category, we do not hold its policy, or you left out a sectional percentile it sets a minimum for."
)
LIMITATIONS = (
    "These are MINIMUM ELIGIBILITY THRESHOLDS for being considered, not closing percentiles or "
    "final cut-offs. Institutes state that the percentiles actually needed for an interview call are "
    "usually much higher, and they depend on the applicant pool. Meeting the minimum does not mean "
    "you will be shortlisted or admitted: each IIM then ranks eligible candidates on a composite score "
    "that also uses Class X/XII and graduation marks, work experience, gender/academic diversity, and "
    "later the written ability test (WAT/AWT) and personal interview, as set out in its own admission "
    "policy. Some policies also set non-CAT minimums (for example Class X/XII or graduation "
    "percentages) and require a positive or non-negative raw score in every CAT section; those are "
    "mentioned in the notes but not checked here. Thresholds may come from the previous year's policy "
    "where the current one is not yet published (see policyBatch) and can change. This tool makes no "
    "admission-probability claims; always check the official policy linked in each result."
)
FRESHNESS_NOTE = (
    "Official data retrieved on the date shown. Thresholds are minimum shortlisting criteria from "
    "each IIM's admission policy for the batch shown."
)


# ---------------------------------------------------------------- cache
_lock = threading.Lock()
_cache: tuple[int, float, dict[str, InstituteRecord]] | None = None


def _ttl() -> float:
    try:
        return float(os.getenv("MBA_BANK_TTL_SECONDS", "300"))
    except ValueError:
        return 300.0


def invalidate_programs() -> None:
    global _cache
    with _lock:
        _cache = None


def load_institutes(db: SafeFirestore) -> dict[str, InstituteRecord]:
    """slug -> validated record. Documents that fail validation are skipped (and logged)."""
    global _cache
    with _lock:
        if _cache is not None and _cache[0] == id(db) and time.monotonic() - _cache[1] < _ttl():
            return _cache[2]
    institutes: dict[str, InstituteRecord] = {}
    for doc_id, data in stream_all(db, PROGRAMS):
        try:
            record = InstituteRecord.model_validate({**data, "slug": doc_id})
        except Exception as error:  # noqa: BLE001 - one bad doc must not break the listing
            log.warning("Skipping invalid %s/%s: %s", PROGRAMS, doc_id, error)
            continue
        institutes[doc_id] = record
    with _lock:
        _cache = (id(db), time.monotonic(), institutes)
    return institutes


# ---------------------------------------------------------------- payload helpers
def _source(src: Any) -> dict[str, Any] | None:
    if src is None:
        return None
    return {"kind": "official", "title": src.title, "url": src.url, "year": src.year, "retrievedAt": src.retrievedAt}


def _all_sources(inst: InstituteRecord) -> list[Any]:
    out = [s for p in inst.programs for s in (p.feeSource, p.intakeSource, p.salarySource) if s is not None]
    out += [c.source for c in inst.cutoffs]
    return out


def _freshness(institutes: list[InstituteRecord]) -> dict[str, Any]:
    dates = [s.retrievedAt for inst in institutes for s in _all_sources(inst)]
    batches = sorted({c.policyBatch for inst in institutes for c in inst.cutoffs})
    return {"retrievedAt": max(dates) if dates else None, "cutoffPolicyBatches": batches, "note": FRESHNESS_NOTE}


def _key_facts(program: Any) -> dict[str, Any]:
    return {key: getattr(program, key) for key in
            ("code", "name", "durationYears", "feeTotal", "intake", "medianSalary", "medianSalaryYear")}


def _summary(inst: InstituteRecord) -> dict[str, Any]:
    return {
        "slug": inst.slug, "name": inst.name, "shortName": inst.shortName, "city": inst.city,
        "state": inst.state, "website": inst.website,
        "programs": [_key_facts(p) for p in inst.programs],
        "hasCutoffs": bool(inst.cutoffs),
        "dataFreshness": _freshness([inst]),
    }


def _detail(inst: InstituteRecord) -> dict[str, Any]:
    programs = [{
        **_key_facts(p), "feeNote": p.feeNote, "feeSource": _source(p.feeSource),
        "intakeNote": p.intakeNote, "intakeSource": _source(p.intakeSource), "salaryNote": p.salaryNote, "salarySource": _source(p.salarySource),
    } for p in inst.programs]
    cutoffs = [{
        "policyBatch": c.policyBatch, "stage": c.stage, "programCode": c.programCode or _flagship(inst),
        "category": c.category, "pwd": c.pwd, "gender": c.gender, "overall": c.overall, "varc": c.varc, "dilr": c.dilr, "qa": c.qa,
        "notes": c.notes, "source": _source(c.source),
    } for c in inst.cutoffs]
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for src in _all_sources(inst):
        seen.setdefault((src.url, src.title), _source(src))  # type: ignore[arg-type]
    return {**_summary(inst), "programs": programs, "cutoffs": cutoffs, "cutoffNotes": inst.cutoffNotes,
            "sources": list(seen.values())}


def _flagship(inst: InstituteRecord) -> str | None:
    return inst.programs[0].code if inst.programs else None


def _matches(inst: InstituteRecord, state: str | None, q: str | None) -> bool:
    if state and (inst.state or "").strip().lower() != state.strip().lower():
        return False
    if q:
        needle = q.strip().lower()
        hay = " ".join([inst.name, inst.shortName, inst.city or "", inst.state or "", inst.slug,
                        *[p.name for p in inst.programs], *[p.code for p in inst.programs]]).lower()
        if needle not in hay:
            return False
    return True


# ---------------------------------------------------------------- eligibility
_SECTIONS = (("overall", "overall"), ("varc", "VARC"), ("dilr", "DILR"), ("qa", "QA"))
_STATUS_ORDER = {"meets_minimum": 0, "unknown": 1, "below_minimum": 2}


def _pick(records: list[Any], body: EligibilityInput) -> tuple[Any | None, str]:
    """The record for the student's (category, pwd[, gender]); (None, reason) if there is none."""
    label = f"{body.category}{' (PwD)' if body.pwd else ''}"
    rows = [r for r in records if r.category == body.category and r.pwd == body.pwd]
    if not rows:
        return None, f"The {{batch}} policy we hold publishes no minimum for {label}."
    if body.gender is not None:
        exact = next((r for r in rows if r.gender == body.gender), None)
        if exact is not None:
            return exact, ""
    generic = next((r for r in rows if r.gender is None), None)
    if generic is not None:
        return generic, ""
    if body.gender is None:
        return None, f"The {{batch}} policy sets gender-specific minimums for {label}; give your gender to check."
    return None, f"The {{batch}} policy publishes no minimum for {label} ({body.gender})."


def evaluate_institute(inst: InstituteRecord, body: EligibilityInput) -> list[dict[str, Any]]:
    """One result per programme that has published thresholds (or one 'unknown' result)."""
    base = {"slug": inst.slug, "name": inst.name, "shortName": inst.shortName}
    flagship = _flagship(inst)
    names = {p.code: p.name for p in inst.programs}
    groups: dict[str | None, list[Any]] = {}
    for record in inst.cutoffs:
        groups.setdefault(record.programCode or flagship, []).append(record)
    if not groups:
        return [{**base, "programCode": flagship, "programName": names.get(flagship) if flagship else None,
                 "policyBatch": None, "status": "unknown", "failedOn": [], "notChecked": [], "thresholds": None,
                 "notes": inst.cutoffNotes or "No official minimum CAT thresholds on record for this institute.",
                 "source": None}]
    results = []
    order = {code: i for i, code in enumerate(names)}
    for code in sorted(groups, key=lambda c: order.get(c, len(order))):
        records = groups[code]
        batch = max(r.policyBatch for r in records)
        latest = [r for r in records if r.policyBatch == batch]
        match, why = _pick(latest, body)
        out = {**base, "programCode": code, "programName": names.get(code) if code else None, "policyBatch": batch}
        if match is None:
            results.append({**out, "status": "unknown", "failedOn": [], "notChecked": [], "thresholds": None,
                            "notes": " ".join(x for x in (why.format(batch=batch), inst.cutoffNotes) if x),
                            "source": _source(latest[0].source)})
            continue
        failed, not_checked = [], []
        for attr, label in _SECTIONS:
            minimum = getattr(match, attr)
            if minimum is None:
                continue
            value = getattr(body, attr)
            if value is None:
                not_checked.append(label)
            elif value < minimum:
                failed.append(label)
        status = "below_minimum" if failed else ("unknown" if not_checked else "meets_minimum")
        results.append({**out, "status": status, "failedOn": failed, "notChecked": not_checked,
                        "thresholds": {"overall": match.overall, "varc": match.varc, "dilr": match.dilr, "qa": match.qa},
                        "notes": match.notes, "source": _source(match.source)})
    return results


# ---------------------------------------------------------------- routes
@router.get("/programs", response_model=ProgramsResponse)
def list_programs(
    state: str | None = Query(default=None, max_length=60),
    q: str | None = Query(default=None, max_length=80),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    institutes = sorted(load_institutes(db).values(), key=lambda i: i.shortName.lower())
    chosen = [inst for inst in institutes if _matches(inst, state, q)]
    return {"institutes": [_summary(inst) for inst in chosen], "dataFreshness": _freshness(chosen)}


@router.get("/programs/{slug}", response_model=InstituteDetail)
def get_program(slug: str, db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    inst = load_institutes(db).get(slug)
    if inst is None:
        raise HTTPException(404, "Institute not found.")
    return _detail(inst)


@router.post("/eligibility", response_model=EligibilityResponse)
def eligibility(body: EligibilityInput, db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    institutes = list(load_institutes(db).values())
    results = [r for inst in institutes for r in evaluate_institute(inst, body)]
    results.sort(key=lambda r: (_STATUS_ORDER[r["status"]], r["shortName"].lower(), r["programCode"] or ""))
    counts = {status: sum(1 for r in results if r["status"] == status) for status in _STATUS_ORDER}
    return {"input": body.model_dump(), "results": results, "counts": counts, "methodology": METHODOLOGY,
            "limitations": LIMITATIONS, "dataFreshness": _freshness(institutes)}
