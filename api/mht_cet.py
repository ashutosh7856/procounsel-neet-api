from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .mht_cet_predictor import MAHCETCollegePredictor


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "reference" / "mht-cet" / "mahcet_cutoff.csv"

router = APIRouter(prefix="/api/v1/mht-cet", tags=["MHT-CET"])

_NULL_STRINGS = {"null", "none", "undefined", ""}
_DTE_CODE_RE = re.compile(r"^\d+\s+")


class MHTCETCollegePrediction(BaseModel):
    college: str
    best_branch: str
    branches: list[str]
    best_closing_rank: int
    best_closing_percentile: float
    chance: str


class MHTCETPredictResponse(BaseModel):
    user_rank: int
    category: str
    branch_filter: str | None
    results: list[MHTCETCollegePrediction]


class MHTCETConvertResponse(BaseModel):
    marks: float | None = None
    percentile: float
    estimated_rank: int


def normalize_branch(branch: str | None) -> str | None:
    if branch is None:
        return None
    cleaned = branch.strip()
    return None if cleaned.lower() in _NULL_STRINGS else cleaned


def clean_name(name: str) -> str:
    return _DTE_CODE_RE.sub("", name).strip()


def clean_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in results:
        row["college"] = clean_name(str(row.get("college", "")))
        row["best_closing_rank"] = int(row.get("best_closing_rank") or 0)
        row["best_closing_percentile"] = float(row.get("best_closing_percentile") or 0)
    return results


@lru_cache(maxsize=1)
def get_predictor() -> MAHCETCollegePredictor:
    return MAHCETCollegePredictor(str(CSV_PATH))


def run_prediction(rank: int, category: str, branch: str | None, top_n: int) -> MHTCETPredictResponse:
    branch = normalize_branch(branch)
    try:
        results = get_predictor().predict(
            user_rank=rank,
            category=category,
            branch=branch,
            top_n=top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return MHTCETPredictResponse(
        user_rank=rank,
        category=category.upper(),
        branch_filter=branch,
        results=clean_results(results),
    )


@router.get("/health")
def mht_cet_health() -> dict[str, Any]:
    predictor = get_predictor()
    return {
        "status": "ok",
        "rows_loaded": len(predictor.df),
        "source": str(CSV_PATH.relative_to(ROOT)),
    }


@router.get("/predict", response_model=MHTCETPredictResponse, summary="Predict MHT-CET colleges by rank")
def predict_by_rank(
    rank: int = Query(..., gt=0, description="MHT-CET rank"),
    category: str = Query(..., description="OPEN, OBC, SC, ST, EWS, NT1, NT2, NT3, VJ, TFWS"),
    branch: str | None = Query(None, description="Branch keyword, e.g. Computer or Mechanical"),
    top_n: int = Query(15, ge=1, le=50),
) -> MHTCETPredictResponse:
    return run_prediction(rank, category, branch, top_n)


@router.get("/predict/by-percentile", response_model=MHTCETPredictResponse, summary="Predict MHT-CET colleges by percentile")
def predict_by_percentile(
    percentile: float = Query(..., ge=0.0, le=100.0),
    category: str = Query(...),
    branch: str | None = Query(None),
    top_n: int = Query(15, ge=1, le=50),
) -> MHTCETPredictResponse:
    rank = get_predictor().percentile_to_rank(percentile)
    return run_prediction(rank, category, branch, top_n)


@router.get("/predict/by-marks", response_model=MHTCETPredictResponse, summary="Predict MHT-CET colleges by marks")
def predict_by_marks(
    marks: float = Query(..., ge=0.0, le=200.0),
    category: str = Query(...),
    branch: str | None = Query(None),
    top_n: int = Query(15, ge=1, le=50),
) -> MHTCETPredictResponse:
    predictor = get_predictor()
    percentile = predictor.marks_to_percentile(marks)
    rank = predictor.percentile_to_rank(percentile)
    return run_prediction(rank, category, branch, top_n)


@router.get("/convert", response_model=MHTCETConvertResponse, summary="Convert MHT-CET marks or percentile to rank")
def convert(
    marks: float | None = Query(None, ge=0.0, le=200.0),
    percentile: float | None = Query(None, ge=0.0, le=100.0),
) -> MHTCETConvertResponse:
    if marks is None and percentile is None:
        raise HTTPException(status_code=422, detail="Provide either marks or percentile.")
    if marks is not None and percentile is not None:
        raise HTTPException(status_code=422, detail="Provide only one of marks or percentile, not both.")

    predictor = get_predictor()
    resolved_percentile = predictor.marks_to_percentile(marks) if marks is not None else float(percentile)
    return MHTCETConvertResponse(
        marks=marks,
        percentile=round(resolved_percentile, 4),
        estimated_rank=predictor.percentile_to_rank(resolved_percentile),
    )


@router.get("/categories")
def list_categories() -> dict[str, list[str]]:
    return {"categories": sorted(MAHCETCollegePredictor.CATEGORY_ALIASES.keys())}


@router.get("/branches")
def list_branches(category: str | None = Query(None)) -> dict[str, list[str]]:
    predictor = get_predictor()
    df = predictor.df
    if category:
        category_key = category.strip().upper()
        category_codes = MAHCETCollegePredictor.CATEGORY_ALIASES.get(category_key)
        if category_codes is None:
            raise HTTPException(status_code=422, detail=f"Unknown category '{category}'.")
        df = df[df["category"].isin(category_codes)]
    return {"branches": sorted(df["branch"].unique().tolist())}


@router.get("/colleges")
def list_colleges(
    q: str | None = Query(None, description="College search text"),
    branch: str | None = Query(None, description="Branch keyword filter"),
    category: str | None = Query(None, description="Optional category filter"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    predictor = get_predictor()
    df = predictor.df
    if q:
        query = q.strip().lower()
        df = df[df["college"].str.lower().str.contains(query, na=False)]
    if branch:
        branch_query = branch.strip().lower()
        df = df[df["branch"].str.lower().str.contains(branch_query, na=False)]
    if category:
        category_key = category.strip().upper()
        category_codes = MAHCETCollegePredictor.CATEGORY_ALIASES.get(category_key)
        if category_codes is None:
            raise HTTPException(status_code=422, detail=f"Unknown category '{category}'.")
        df = df[df["category"].isin(category_codes)]

    grouped = (
        df.groupby("college", as_index=False)
        .agg(
            branches=("branch", lambda values: sorted(set(values))),
            categories=("category", lambda values: sorted(set(values))),
            best_closing_rank=("closing_rank", "min"),
            best_closing_percentile=("closing_percentile", "max"),
            rows=("college", "count"),
        )
        .sort_values(["best_closing_percentile", "best_closing_rank"], ascending=[False, True])
    )
    total = len(grouped)
    items = grouped.iloc[offset : offset + limit].to_dict(orient="records")
    for item in items:
        item["college"] = clean_name(str(item["college"]))
        item["best_closing_rank"] = int(item["best_closing_rank"])
        item["best_closing_percentile"] = float(item["best_closing_percentile"])
        item["rows"] = int(item["rows"])
    return {"total": total, "limit": limit, "offset": offset, "items": items}
