from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .mht_cet import get_predictor as get_mht_cet_predictor
from .mht_cet import router as mht_cet_router


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "reference"
NORMALIZED_DIR = ROOT / "data" / "official" / "normalized"
MCC_CUTOFFS_PATH = NORMALIZED_DIR / "mcc-cutoffs.json"
STATE_CUTOFFS_PATH = NORMALIZED_DIR / "state-cutoffs.json"
COURSE_YEARS = 5
USD_TO_INR = 88
DIRECTORY_DEFAULT_CUTOFF_YEAR = 2025

CollegeType = Literal["All types", "Government", "Private", "Deemed"]
CounsellingType = Literal["State quota", "Deemed counselling", "All types"]
Gender = Literal["Female", "Male"]


def load_json(name: str) -> Any:
    with (DATA_DIR / name).open("r", encoding="utf-8") as file:
        return json.load(file)


DIRECTORY: dict[str, list[dict[str, Any]]] = load_json("stateDirectory.json")
SCORE_RANK: dict[str, Any] = load_json("scoreRank.json")
FEE_BENEFITS: dict[str, Any] = load_json("feeBenefits.json")
STATES_WITH_DATA = sorted([state for state, colleges in DIRECTORY.items() if colleges])


def load_mcc_cutoffs() -> dict[str, Any]:
    if not MCC_CUTOFFS_PATH.exists():
        return {"generatedAt": None, "rawRows": 0, "cutoffGroups": 0, "cutoffs": []}
    with MCC_CUTOFFS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_state_cutoffs() -> dict[str, Any]:
    if not STATE_CUTOFFS_PATH.exists():
        return {"generatedAt": None, "rawRows": 0, "cutoffGroups": 0, "cutoffs": []}
    with STATE_CUTOFFS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


MCC_CUTOFFS = load_mcc_cutoffs()
STATE_CUTOFFS = load_state_cutoffs()
OFFICIAL_STATE_CUTOFF_STATES = {row.get("state") for row in STATE_CUTOFFS.get("cutoffs", []) if row.get("state")}


app = FastAPI(
    title="Procounsel Counselling API",
    version="1.0.0",
    description="Read-only counselling APIs for NEET and MHT-CET college prediction.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(mht_cet_router)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "Procounsel Counselling API",
        "status": "ok",
        "docs": "/api/docs",
        "health": "/health",
        "api_health": "/api/health",
    }


@app.get("/api")
def api_root() -> dict[str, Any]:
    return root()


@app.get("/docs", include_in_schema=False)
def docs_redirect() -> RedirectResponse:
    return RedirectResponse(url="/api/docs")


class PredictRequest(BaseModel):
    neet_air: int | None = Field(default=None, ge=1, description="NEET All India Rank. More accurate when available.")
    neet_score: int | None = Field(default=None, ge=1, le=720, description="NEET score. Used to estimate AIR when neet_air is missing.")
    domicile: str = Field(default="All India", description="Student domicile state, or All India.")
    category: str = Field(default="General", description="General, OBC, SC, ST, EWS, etc.")
    gender: Gender = "Female"
    budget: str | None = Field(default=None, description="Total budget, e.g. 60L, 80 lakh, 1 Cr.")
    counselling: CounsellingType = "State quota"
    target_type: CollegeType = "All types"
    limit: int = Field(default=8, ge=1, le=50)


class TargetCollegeCheckRequest(BaseModel):
    college_name: str = Field(description="Exact or partial target college name.")
    target_state: str | None = Field(default=None, description="College state. If missing, domicile is used.")
    neet_air: int | None = Field(default=None, ge=1)
    neet_score: int | None = Field(default=None, ge=1, le=720)
    domicile: str = "All India"
    category: str = "General"
    gender: Gender = "Female"
    budget: str | None = None
    counselling: CounsellingType = "State quota"
    target_type: CollegeType = "All types"


def parse_budget(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.lower().replace(",", "").replace(" ", "").replace("₹", "").replace("rs", "")
    match = re.fullmatch(r"([\d.]+)(crores?|cr|c|lakhs?|lacs?|l|k)?", cleaned)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or ""
    if amount <= 0 or not math.isfinite(amount):
        return None
    if unit.startswith("c"):
        return round(amount * 10_000_000)
    if unit.startswith("l"):
        return round(amount * 100_000)
    if unit == "k":
        return round(amount * 1_000)
    return round(amount * 100_000) if amount < 1000 else round(amount)


def format_inr(amount: int | float) -> str:
    if amount >= 10_000_000:
        return f"₹{amount / 10_000_000:.2f}".rstrip("0").rstrip(".") + " Cr"
    if amount >= 100_000:
        return f"₹{amount / 100_000:.1f}".rstrip("0").rstrip(".") + " L"
    return f"₹{round(amount / 1000)}K"


def estimate_rank_from_score(score: int | None) -> int | None:
    if score is None or score < 0 or score > 720:
        return None
    anchors = SCORE_RANK.get("anchors", [])
    if not anchors:
        return None
    first = anchors[0]
    last = anchors[-1]
    if score >= first["score"]:
        return first["rank"]
    if score <= last["score"]:
        return last["rank"]
    for index in range(len(anchors) - 1):
        high = anchors[index]
        low = anchors[index + 1]
        if low["score"] <= score <= high["score"]:
            denominator = high["score"] - low["score"] or 1
            t = (high["score"] - score) / denominator
            return round(high["rank"] + t * (low["rank"] - high["rank"]))
    return last["rank"]


def effective_rank(neet_air: int | None, neet_score: int | None) -> tuple[int | None, str]:
    if neet_air and neet_air > 0:
        return neet_air, "AIR"
    estimated = estimate_rank_from_score(neet_score)
    return estimated, "Estimated AIR"


def parse_amount_to_inr(segment: str) -> tuple[int, bool] | None:
    usd = re.search(r"(?:us\s*\$|\$|usd)\s*([\d,]+(?:\.\d+)?)", segment, re.I)
    if usd:
        return round(float(usd.group(1).replace(",", "")) * USD_TO_INR), True

    normalized = segment.replace("â‚¹", "₹")
    inr = re.search(r"₹\s*([\d,]+(?:\.\d+)?)\s*(cr|l|k)?", normalized, re.I)
    if not inr:
        return None
    amount = float(inr.group(1).replace(",", ""))
    unit = (inr.group(2) or "").lower()
    if unit == "cr":
        amount *= 10_000_000
    elif unit == "l":
        amount *= 100_000
    elif unit == "k":
        amount *= 1_000
    return round(amount), False


def fee_label(segment: str) -> str:
    lowered = segment.lower()
    if "nri" in lowered:
        return "NRI quota"
    if "mgmt" in lowered or "management" in lowered:
        return "Management quota"
    if "govt seat" in lowered or "government quota" in lowered or "state quota" in lowered:
        return "Govt-seat quota"
    if "tuition" in lowered or "fees" in lowered:
        return "Tuition"
    return segment.split("₹")[0].strip() or "Fee"


def parse_fee_tracks(fees: str | None) -> list[dict[str, Any]]:
    if not fees:
        return []
    normalized = fees.replace("Â·", "·").replace("â‚¹", "₹")
    tracks: list[dict[str, Any]] = []
    for segment in normalized.split("·"):
        parsed = parse_amount_to_inr(segment)
        if not parsed:
            continue
        amount, approx = parsed
        is_total = bool(re.search(r"for\s*\d|/\s*\d+\s*yrs?|full course|entire course|one[- ]time", segment, re.I))
        total = amount if is_total else amount * COURSE_YEARS
        tracks.append(
            {
                "label": fee_label(segment),
                "annual": round(amount / COURSE_YEARS) if is_total else amount,
                "total": total,
                "approx": approx or is_total,
                "formatted_total": format_inr(total),
            }
        )
    return sorted(tracks, key=lambda track: track["total"])


def type_allowed(college_type: str, counselling: str, target_type: str) -> bool:
    if target_type != "All types" and college_type != target_type:
        return False
    if counselling == "State quota":
        return college_type in {"Government", "Private"}
    if counselling == "Deemed counselling":
        return college_type == "Deemed"
    return True


def classify(rank: int, closing_rank: int) -> tuple[str, str] | None:
    if closing_rank >= rank * 2:
        return "High chance", "mint"
    if closing_rank >= rank:
        return "Good chance", "lime"
    if closing_rank >= rank * 0.75:
        return "Borderline", "yellow"
    return None


def fit_percent(rank: int, closing_rank: int) -> int:
    ratio = closing_rank / rank
    fit = 40 + 55 * min(1, math.log10(ratio + 0.35) + 0.55)
    return round(max(40, min(96, fit)))


def infer_directory_cutoff_year(college: dict[str, Any]) -> int | None:
    detail = str(college.get("detail", ""))
    matches = re.findall(r"\b(20\d{2})\b", detail)
    if matches:
        return int(matches[-1])
    has_rank = str(college.get("closingRank", "")).isdigit()
    has_rounds = bool(college.get("rounds"))
    return DIRECTORY_DEFAULT_CUTOFF_YEAR if has_rank or has_rounds else None


def normalize_college_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    aliases = {
        "government": "gmc",
        "govt": "gmc",
        "medical": "",
        "college": "",
        "hospital": "",
        "and": "",
    }
    tokens = [aliases.get(token, token) for token in normalized.split()]
    return " ".join(token for token in tokens if token)


def official_state_cutoffs_for_directory_college(state: str, college: dict[str, Any]) -> list[dict[str, Any]]:
    if state not in OFFICIAL_STATE_CUTOFF_STATES:
        return []

    college_key = normalize_college_name(str(college.get("name", "")))
    city_key = normalize_college_name(str(college.get("city", "")))
    if not college_key:
        return []

    matches: list[dict[str, Any]] = []
    for row in STATE_CUTOFFS.get("cutoffs", []):
        if str(row.get("state", "")).lower() != state.lower():
            continue
        if str(row.get("course", "")).upper() != "MBBS":
            continue
        row_key = normalize_college_name(str(row.get("collegeName", "")))
        if not row_key:
            continue
        if len(row_key) < 6:
            continue
        city_matches = not city_key or city_key in row_key
        name_matches = row_key in college_key or college_key in row_key
        if city_matches and name_matches:
            matches.append(row)

    return sorted(
        matches,
        key=lambda row: (
            str(row.get("round", "")),
            normalized_category(str(row.get("category", ""))) != "OPEN",
            row.get("closingRank") or 999_999_999,
        ),
    )


def directory_round_sources(college: dict[str, Any], cutoff_year: int | None) -> dict[str, str]:
    rounds = college.get("rounds")
    if not isinstance(rounds, dict) or cutoff_year is None:
        return {}
    return {str(round_name): "directory_reference" for round_name in rounds}


def directory_round_years(college: dict[str, Any], cutoff_year: int | None) -> dict[str, int]:
    rounds = college.get("rounds")
    if not isinstance(rounds, dict) or cutoff_year is None:
        return {}
    return {str(round_name): cutoff_year for round_name in rounds}


def build_year_wise_rounds(
    rounds: dict[str, Any] | None,
    round_years: dict[str, int],
    round_sources: dict[str, str],
    official_rows_by_round: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not isinstance(rounds, dict):
        return {}

    official_rows_by_round = official_rows_by_round or {}
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for round_name, closing_rank in rounds.items():
        round_key = str(round_name)
        year = round_years.get(round_key)
        if year is None:
            continue
        source = round_sources.get(round_key, "directory_reference")
        official_row = official_rows_by_round.get(round_key)
        grouped.setdefault(str(year), {})[round_key] = {
            "closing_rank": closing_rank,
            "source": source,
            "source_label": official_row.get("authority") if official_row else "Directory reference",
            "verified": source != "directory_reference",
        }
        if official_row:
            grouped[str(year)][round_key].update(
                {
                    "quota": official_row.get("quota"),
                    "category": official_row.get("category"),
                    "source_url": official_row.get("sourceUrl"),
                    "verification_status": official_row.get("verificationStatus"),
                }
            )
    return grouped


def college_response(college: dict[str, Any], state: str) -> dict[str, Any]:
    tracks = parse_fee_tracks(college.get("fees"))
    cutoff_year = infer_directory_cutoff_year(college)
    rounds = college.get("rounds")
    round_years = directory_round_years(college, cutoff_year)
    round_sources = directory_round_sources(college, cutoff_year)
    official_cutoffs = official_state_cutoffs_for_directory_college(state, college)
    official_rounds = {
        row.get("round"): row
        for row in official_cutoffs
        if row.get("round") and normalized_category(str(row.get("category", ""))) == "OPEN" and row.get("quota") == "OPEN"
    }
    if isinstance(rounds, dict) and official_rounds:
        rounds = dict(rounds)
        for round_name, row in official_rounds.items():
            rounds[str(round_name)] = row.get("closingRank")
            if row.get("year"):
                round_years[str(round_name)] = row.get("year")
            round_sources[str(round_name)] = "official_state_cutoff"
    official_years = [row.get("year") for row in official_cutoffs if row.get("year")]
    official_latest_year = max(official_years) if official_years else None
    detail = college.get("detail", "")
    if official_rounds:
        official_notes = [
            f"Official {row.get('year')} {round_name}: {row.get('authority')} {row.get('quota')} {row.get('category')} closing rank {row.get('closingRank')}"
            for round_name, row in sorted(official_rounds.items())
        ]
        detail = f"{detail} | " + " | ".join(official_notes)
    return {
        "name": college.get("name", ""),
        "state": state,
        "city": college.get("city", ""),
        "type": college.get("type", ""),
        "seats": college.get("seats", ""),
        "established": college.get("estb", ""),
        "closing_rank": int(college["closingRank"]) if str(college.get("closingRank", "")).isdigit() else None,
        "fees": college.get("fees", ""),
        "fee_tracks": tracks,
        "rounds": rounds,
        "round_years": round_years,
        "round_sources": round_sources,
        "year_wise_rounds": build_year_wise_rounds(rounds, round_years, round_sources, official_rounds),
        "cutoff_year": official_latest_year or cutoff_year,
        "detail": detail,
        "official_cutoffs": official_cutoffs,
    }


def filter_mcc_cutoffs(
    year: int | None = None,
    round_name: str | None = None,
    quota: str | None = None,
    category: str | None = None,
    course: str | None = None,
    college_name: str | None = None,
    max_closing_rank: int | None = None,
) -> list[dict[str, Any]]:
    rows = MCC_CUTOFFS.get("cutoffs", [])
    query = (college_name or "").lower().strip()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if year is not None and row.get("year") != year:
            continue
        if round_name and str(row.get("round", "")).lower() != round_name.lower():
            continue
        if quota and str(row.get("quota", "")).lower() != quota.lower():
            continue
        if category and str(row.get("category", "")).lower() != category.lower():
            continue
        if course and str(row.get("course", "")).lower() != course.lower():
            continue
        if query and query not in str(row.get("collegeName", "")).lower():
            continue
        closing_rank = row.get("closingRank")
        if max_closing_rank is not None and (not isinstance(closing_rank, int) or closing_rank > max_closing_rank):
            continue
        filtered.append(row)
    return filtered


def normalized_category(category: str) -> str:
    value = category.upper().strip()
    if value in {"GENERAL", "GEN", "UR"}:
        return "OPEN"
    return value


def filter_state_cutoffs(
    state: str | None = None,
    year: int | None = None,
    round_name: str | None = None,
    category: str | None = None,
    course: str | None = None,
    college_name: str | None = None,
    max_closing_rank: int | None = None,
) -> list[dict[str, Any]]:
    rows = STATE_CUTOFFS.get("cutoffs", [])
    query = (college_name or "").lower().strip()
    wanted_category = normalized_category(category or "") if category else None
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if state and str(row.get("state", "")).lower() != state.lower():
            continue
        if year is not None and row.get("year") != year:
            continue
        if round_name and str(row.get("round", "")).lower() != round_name.lower():
            continue
        if wanted_category and normalized_category(str(row.get("category", ""))) != wanted_category:
            continue
        if course and str(row.get("course", "")).lower() != course.lower():
            continue
        if query and query not in str(row.get("collegeName", "")).lower():
            continue
        closing_rank = row.get("closingRank")
        if max_closing_rank is not None and (not isinstance(closing_rank, int) or closing_rank > max_closing_rank):
            continue
        filtered.append(row)
    return filtered


def state_cutoff_college_response(row: dict[str, Any]) -> dict[str, Any]:
    round_name = row.get("round", "Round")
    cutoff_year = row.get("year")
    rounds = {round_name: row.get("closingRank")}
    round_years = {round_name: cutoff_year} if cutoff_year else {}
    round_sources = {round_name: "official_state_cutoff"}
    return {
        "name": row.get("collegeName", ""),
        "state": row.get("state", ""),
        "city": "",
        "type": "Official state cutoff",
        "seats": "",
        "established": "",
        "closing_rank": row.get("closingRank"),
        "fees": "",
        "fee_tracks": [],
        "rounds": rounds,
        "round_years": round_years,
        "round_sources": round_sources,
        "year_wise_rounds": build_year_wise_rounds(rounds, round_years, round_sources, {round_name: row}),
        "cutoff_year": cutoff_year,
        "detail": f"{row.get('authority')} · {row.get('year')} {row.get('round')} · {row.get('quota')} · {row.get('category')} · Source: {row.get('sourceUrl')}",
        "official_cutoff": row,
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        mht_cet_rows = len(get_mht_cet_predictor().df)
    except Exception:
        mht_cet_rows = 0
    return {
        "ok": True,
        "states": len(STATES_WITH_DATA),
        "colleges": sum(len(items) for items in DIRECTORY.values()),
        "mcc_cutoff_groups": MCC_CUTOFFS.get("cutoffGroups", 0),
        "state_cutoff_groups": STATE_CUTOFFS.get("cutoffGroups", 0),
        "mht_cet_rows": mht_cet_rows,
    }


@app.get("/api/v1/states")
def states() -> dict[str, Any]:
    return {"states": STATES_WITH_DATA}


@app.get("/api/v1/colleges")
def colleges(
    state: str = Query(default="All India"),
    college_type: CollegeType = Query(default="All types"),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    selected_states = STATES_WITH_DATA if state == "All India" else [state]
    rows: list[dict[str, Any]] = []
    query = (q or "").lower().strip()
    for state_name in selected_states:
        for college in DIRECTORY.get(state_name, []):
            if college_type != "All types" and college.get("type") != college_type:
                continue
            if query and query not in college.get("name", "").lower() and query not in college.get("city", "").lower():
                continue
            rows.append(college_response(college, state_name))
    return {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset : offset + limit]}


@app.get("/api/v1/score-rank")
def score_rank(score: int = Query(ge=1, le=720)) -> dict[str, Any]:
    return {
        "score": score,
        "estimated_air": estimate_rank_from_score(score),
        "source": SCORE_RANK.get("source"),
        "built_at": SCORE_RANK.get("builtAt"),
    }


@app.get("/api/v1/fee-benefits")
def fee_benefits(state: str = "All India", gender: Gender = "Female", category: str = "General", counselling: str = "State quota") -> dict[str, Any]:
    record = FEE_BENEFITS.get(state) or FEE_BENEFITS["All India"]
    gender_key = gender.lower()
    verified = record.get(gender_key)
    if record.get("status") == "verified_guidance" and verified:
        lines = [*verified.get("lines", []), f"Source: {record.get('authority')}{' - ' + record.get('sourceUrl') if record.get('sourceUrl') else ''}"]
        return {"state": state, "gender": gender, "category": category, "counselling": counselling, "status": record.get("status"), "title": verified.get("title"), "badge": verified.get("badge"), "lines": lines}
    return {
        "state": state,
        "gender": gender,
        "category": category,
        "counselling": counselling,
        "status": record.get("status"),
        "title": f"{state} {gender.lower()} fee benefit check",
        "badge": "Verify state",
        "lines": [
            f"No verified automatic {gender.lower()} fee concession is imported yet for {state} / {counselling}.",
            record.get("note") or "Check official counselling brochure, scholarship portal, and college fee order.",
            f"Authority to verify: {record.get('authority')}.",
        ],
    }


@app.get("/api/v1/mcc/metadata")
def mcc_metadata() -> dict[str, Any]:
    cutoffs = MCC_CUTOFFS.get("cutoffs", [])
    return {
        "loaded": bool(cutoffs),
        "generated_at": MCC_CUTOFFS.get("generatedAt"),
        "raw_rows": MCC_CUTOFFS.get("rawRows", 0),
        "cutoff_groups": MCC_CUTOFFS.get("cutoffGroups", 0),
        "years": sorted({row.get("year") for row in cutoffs if row.get("year") is not None}),
        "rounds": sorted({row.get("round") for row in cutoffs if row.get("round")}),
        "quotas": sorted({row.get("quota") for row in cutoffs if row.get("quota")}),
        "categories": sorted({row.get("category") for row in cutoffs if row.get("category")}),
        "courses": sorted({row.get("course") for row in cutoffs if row.get("course")}),
        "source": str(MCC_CUTOFFS_PATH.relative_to(ROOT)),
    }


@app.get("/api/v1/mcc/cutoffs")
def mcc_cutoffs(
    year: int | None = Query(default=None),
    round_name: str | None = Query(default=None, alias="round"),
    quota: str | None = Query(default=None),
    category: str | None = Query(default=None),
    course: str | None = Query(default=None),
    college_name: str | None = Query(default=None),
    max_closing_rank: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows = filter_mcc_cutoffs(
        year=year,
        round_name=round_name,
        quota=quota,
        category=category,
        course=course,
        college_name=college_name,
        max_closing_rank=max_closing_rank,
    )
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
        "source": str(MCC_CUTOFFS_PATH.relative_to(ROOT)),
    }


@app.get("/api/v1/state-cutoffs/metadata")
def state_cutoffs_metadata() -> dict[str, Any]:
    cutoffs = STATE_CUTOFFS.get("cutoffs", [])
    return {
        "loaded": bool(cutoffs),
        "generated_at": STATE_CUTOFFS.get("generatedAt"),
        "raw_rows": STATE_CUTOFFS.get("rawRows", 0),
        "cutoff_groups": STATE_CUTOFFS.get("cutoffGroups", 0),
        "states": sorted({row.get("state") for row in cutoffs if row.get("state")}),
        "years": sorted({row.get("year") for row in cutoffs if row.get("year") is not None}),
        "rounds": sorted({row.get("round") for row in cutoffs if row.get("round")}),
        "categories": sorted({row.get("category") for row in cutoffs if row.get("category")}),
        "courses": sorted({row.get("course") for row in cutoffs if row.get("course")}),
        "source": str(STATE_CUTOFFS_PATH.relative_to(ROOT)),
    }


@app.get("/api/v1/state-cutoffs")
def state_cutoffs(
    state: str | None = Query(default=None),
    year: int | None = Query(default=None),
    round_name: str | None = Query(default=None, alias="round"),
    category: str | None = Query(default=None),
    course: str | None = Query(default=None),
    college_name: str | None = Query(default=None),
    max_closing_rank: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows = filter_state_cutoffs(
        state=state,
        year=year,
        round_name=round_name,
        category=category,
        course=course,
        college_name=college_name,
        max_closing_rank=max_closing_rank,
    )
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
        "source": str(STATE_CUTOFFS_PATH.relative_to(ROOT)),
    }


@app.post("/api/v1/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    rank, rank_label = effective_rank(request.neet_air, request.neet_score)
    if not rank:
        raise HTTPException(status_code=422, detail="Provide neet_air, or provide neet_score from 1 to 720.")

    budget_value = parse_budget(request.budget)
    states_to_check = [request.domicile] if request.domicile != "All India" and request.domicile in DIRECTORY else STATES_WITH_DATA
    results: list[dict[str, Any]] = []
    ranked_pool = 0
    unranked_pool = 0
    excluded_by_budget = 0
    official_state_cutoff_pool = 0

    if request.counselling in {"State quota", "All types"}:
        for row in filter_state_cutoffs(
            state=None if request.domicile == "All India" else request.domicile,
            category=request.category,
            course="MBBS",
        ):
            closing_rank = row.get("closingRank")
            if not isinstance(closing_rank, int):
                continue
            official_state_cutoff_pool += 1
            verdict = classify(rank, closing_rank)
            if not verdict:
                continue
            chance, tone = verdict
            item = state_cutoff_college_response(row)
            item.update(
                {
                    "chance": chance,
                    "tone": tone,
                    "fit_percent": fit_percent(rank, closing_rank),
                    "cheapest_track": None,
                    "why": f"{rank_label} {rank:,} vs official {row.get('year')} {row.get('round')} closing rank {closing_rank:,}.",
                }
            )
            results.append(item)

    for state_name in states_to_check:
        for college in DIRECTORY.get(state_name, []):
            if not type_allowed(college.get("type", ""), request.counselling, request.target_type):
                continue
            closing_raw = str(college.get("closingRank", ""))
            if not closing_raw.isdigit():
                unranked_pool += 1
                continue
            closing_rank = int(closing_raw)
            ranked_pool += 1
            verdict = classify(rank, closing_rank)
            if not verdict:
                continue
            tracks = parse_fee_tracks(college.get("fees"))
            cheapest = tracks[0] if tracks else None
            if budget_value is not None and cheapest and cheapest["total"] > budget_value:
                excluded_by_budget += 1
                continue
            chance, tone = verdict
            row = college_response(college, state_name)
            row.update(
                {
                    "chance": chance,
                    "tone": tone,
                    "fit_percent": fit_percent(rank, closing_rank),
                    "cheapest_track": cheapest,
                    "why": f"{rank_label} {rank:,} vs closing rank {closing_rank:,}.",
                }
            )
            results.append(row)

    results.sort(key=lambda item: item["closing_rank"] or 999_999_999)
    return {
        "input": request.model_dump(),
        "rank_used": rank,
        "rank_label": rank_label,
        "budget_rupees": budget_value,
        "ranked_pool": ranked_pool,
        "unranked_pool": unranked_pool,
        "official_state_cutoff_pool": official_state_cutoff_pool,
        "excluded_by_budget": excluded_by_budget,
        "category_warning": None if request.category == "General" else f"Category-specific {request.category} cutoffs are not imported yet; response uses General/UR/Open records.",
        "items": results[: request.limit],
    }


@app.post("/api/v1/target-college-check")
def target_college_check(request: TargetCollegeCheckRequest) -> dict[str, Any]:
    rank, rank_label = effective_rank(request.neet_air, request.neet_score)
    budget_value = parse_budget(request.budget)
    state_to_check = request.target_state or (request.domicile if request.domicile != "All India" else "All India")
    selected_states = STATES_WITH_DATA if state_to_check == "All India" else [state_to_check]
    query = request.college_name.lower().strip()
    matches: list[tuple[str, dict[str, Any]]] = []

    for state_name in selected_states:
        for college in DIRECTORY.get(state_name, []):
            if not type_allowed(college.get("type", ""), request.counselling, request.target_type):
                continue
            if query in college.get("name", "").lower():
                matches.append((state_name, college))

    if not matches:
        cutoff_matches = filter_state_cutoffs(
            state=None if state_to_check == "All India" else state_to_check,
            category=request.category,
            course="MBBS",
            college_name=request.college_name,
        )
        if not cutoff_matches:
            return {"matched": False, "message": "No imported college matched this name/state/filter.", "suggestions": []}
        row = sorted(cutoff_matches, key=lambda item: item.get("closingRank") or 999_999_999)[-1]
        base = state_cutoff_college_response(row)
        if not rank:
            base.update({"matched": True, "verdict": "Need score/rank", "message": "Provide NEET AIR or NEET Score to check reach."})
            return base
        closing_rank = base["closing_rank"]
        verdict = classify(rank, closing_rank)
        if verdict:
            chance, tone = verdict
            message = f"{rank_label} {rank:,} vs official {row.get('year')} {row.get('round')} closing rank {closing_rank:,}."
        else:
            chance, tone = "Low chance", "danger"
            message = f"{rank_label} {rank:,} is beyond official {row.get('year')} {row.get('round')} closing rank {closing_rank:,}."
        base.update({"matched": True, "rank_used": rank, "rank_label": rank_label, "verdict": chance, "tone": tone, "message": message})
        return base

    state_name, college = matches[0]
    base = college_response(college, state_name)
    if not rank:
        base.update({"matched": True, "verdict": "Need score/rank", "message": "Provide NEET AIR or NEET Score to check reach."})
        return base

    closing_rank = base["closing_rank"]
    if not closing_rank:
        cutoff_matches = filter_state_cutoffs(
            state=state_name,
            category=request.category,
            course="MBBS",
            college_name=request.college_name,
        )
        if not cutoff_matches:
            base.update({"matched": True, "verdict": "Verify", "message": "No imported closing rank exists for this college. Verify official round-wise cutoff."})
            return base
        row = sorted(cutoff_matches, key=lambda item: item.get("closingRank") or 999_999_999)[-1]
        closing_rank = row["closingRank"]
        base["closing_rank"] = closing_rank
        base["rounds"] = {row.get("round", "Round"): closing_rank}
        base["round_years"] = {row.get("round", "Round"): row.get("year")}
        base["round_sources"] = {row.get("round", "Round"): "official_state_cutoff"}
        base["year_wise_rounds"] = build_year_wise_rounds(
            base["rounds"],
            base["round_years"],
            base["round_sources"],
            {row.get("round", "Round"): row},
        )
        base["cutoff_year"] = row.get("year")
        base["official_cutoff"] = row
        base["detail"] += f" · Official cutoff: {row.get('authority')} {row.get('year')} {row.get('round')} {row.get('quota')} {row.get('category')}."

    tracks = base["fee_tracks"]
    cheapest = tracks[0] if tracks else None
    budget_message = "Fee data unavailable; verify official fee order."
    if cheapest and budget_value:
        budget_message = f"Cheapest known track is {cheapest['formatted_total']}; budget is {format_inr(budget_value)}."
    elif cheapest:
        budget_message = f"Cheapest known track is {cheapest['formatted_total']}."

    verdict = classify(rank, closing_rank)
    if verdict:
        chance, tone = verdict
        message = f"{rank_label} {rank:,} vs imported closing rank {closing_rank:,}. {budget_message}"
    else:
        chance, tone = "Low chance", "danger"
        message = f"{rank_label} {rank:,} is beyond imported closing rank {closing_rank:,}. {budget_message}"

    if request.counselling == "State quota" and request.domicile != "All India" and request.domicile != state_name:
        message += f" Eligibility warning: {state_name} state quota may not be open for {request.domicile} domicile."

    base.update({"matched": True, "rank_used": rank, "rank_label": rank_label, "verdict": chance, "tone": tone, "message": message})
    return base
