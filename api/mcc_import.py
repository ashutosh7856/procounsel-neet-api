from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "official" / "normalized" / "mcc-cutoffs.json"

COURSE_RE = re.compile(r"\b(MBBS|BDS|B\.?Sc\.?\s*Nursing)\b", re.I)
RANK_RE = re.compile(r"\b(\d{1,7})\b")
CATEGORY_RE = re.compile(
    r"\b(OPEN|GENERAL|GN|UR|EWS|EW|OBC|BC|SC|ST|GN-PH|OPEN-PH|OPEN PWD|EWS-PH|EWS PWD|OBC-PH|OBC PWD|BC PWD|SC-PH|SC PWD|ST-PH|ST PWD|NRI|MNG|MANAGEMENT)\b",
    re.I,
)
QUOTA_RE = re.compile(
    r"\b(AIQ|ALL INDIA|DEEMED|CENTRAL UNIVERSITY|ESIC|AMU|BHU|DU|IP|JIPMER|AIIMS|STATE|MANAGEMENT|NRI)\b",
    re.I,
)
ROW_START_RE = re.compile(r"^\s*(\d{1,6})\s+(\d{1,7})\s+(.*)$")
REMARK_RE = re.compile(r"\b(Allotted|Upgraded|Retained|Not\s+Reported|Joined)\b", re.I)
KNOWN_QUOTAS = [
    "(AMU) Self finance All India",
    "(AMU)Self finance internal",
    "Aligarh Muslim University (AMU) Quota",
    "Delhi NCR Children/Widows of Personnel of the Armed Forces (CW) DU Quota",
    "Delhi NCR Children/Widows of Personnel of the Armed Forces (CW) IP Quota",
    "Employees State Insurance Scheme Nursing Quota",
    "Employees State Insurance Scheme(ESI)",
    "Non-Resident Indian(AMU)Quota",
    "Non-Resident Indian",
    "B.Sc Nursing Delhi NCR CW Quota",
    "B.Sc Nursing Delhi NCR",
    "B.Sc Nursing All India",
    "Self-Financed Merit Seat",
    "Delhi University Quota",
    "IP University Quota",
    "Jain Minority Quota",
    "Jamia Internal Quota",
    "Muslim Minority Quota",
    "Muslim OBC Quota",
    "Muslim Women Quota",
    "Muslim ST Quota",
    "Muslim Quota",
    "Foreign Country Quota",
    "Internal -Puducherry UT Domicile",
    "Open Seat Quota",
    "All India",
    "Deemed",
    "NRI",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
      for chunk in iter(lambda: file.read(1024 * 1024), b""):
          digest.update(chunk)
    return digest.hexdigest()


def compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_course(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.upper().replace(".", "")
    if "NURSING" in normalized:
        return "B.Sc Nursing"
    return normalized


def normalize_category(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.upper()
    normalized = normalized.replace(" PWD", " PwD").replace("-PH", " PwD")
    if normalized in {"GN", "UR", "OPEN"}:
        return "OPEN"
    if normalized == "EW":
        return "EWS"
    if normalized == "BC":
        return "OBC"
    if normalized == "GENERAL":
        return "OPEN"
    return normalized


def normalize_quota(value: str | None) -> str | None:
    if not value:
        return None
    normalized = compact_space(value.upper())
    if normalized == "ALL INDIA":
        return "AIQ"
    if normalized == "OPEN SEAT QUOTA":
        return "Open Seat Quota"
    if normalized == "SELF-FINANCED MERIT SEAT":
        return "Self-Financed Merit Seat"
    return normalized


def likely_college_name(line: str, course_match: re.Match[str] | None, rank_match: re.Match[str] | None) -> str | None:
    working = line
    if course_match:
        working = working[: course_match.start()]
    elif rank_match:
        working = working[rank_match.end() :]

    working = re.sub(r"^\s*\d+\s+", "", working)
    working = re.sub(r"\b\d{1,7}\b", " ", working)
    working = CATEGORY_RE.sub(" ", working)
    working = QUOTA_RE.sub(" ", working)
    working = compact_space(working)

    if len(working) < 8:
        return None
    if not re.search(r"(college|institute|medical|dental|hospital|university|aiims|jipmer|bhu|amu)", working, re.I):
        return None
    return working


def parse_result_line(line: str, page: int, year: int, round_name: str, source_url: str | None, source_file: str, content_hash: str) -> dict[str, Any] | None:
    line = compact_space(line)
    if len(line) < 20:
        return None
    if re.search(r"(page\s+\d+|final result|provisional result|medical counselling committee|ministry)", line, re.I):
        return None

    course_match = COURSE_RE.search(line)
    if not course_match:
        return None

    ranks = [int(match.group(1)) for match in RANK_RE.finditer(line)]
    ranks = [rank for rank in ranks if 1 <= rank <= 2_500_000]
    if not ranks:
        return None

    # MCC allotment tables often contain serial number and rank. The closing
    # rank source row needs candidate rank, so use the largest plausible rank
    # on the row after filtering out tiny serial numbers.
    candidate_rank = max(ranks)
    category = normalize_category(CATEGORY_RE.search(line).group(1) if CATEGORY_RE.search(line) else None)
    quota = normalize_quota(QUOTA_RE.search(line).group(1) if QUOTA_RE.search(line) else None)
    college_name = likely_college_name(line, course_match, RANK_RE.search(line))
    if not college_name:
        return None

    return {
        "authority": "MCC",
        "year": year,
        "round": round_name,
        "quota": quota,
        "category": category,
        "course": normalize_course(course_match.group(1)),
        "collegeName": college_name,
        "rank": candidate_rank,
        "sourceUrl": source_url,
        "sourceFile": source_file,
        "sourcePage": page,
        "contentHash": content_hash,
        "verificationStatus": "parsed_from_official_pdf",
    }


def split_pdf_rows(text: str) -> list[str]:
    rows: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = compact_space(raw_line)
        if not line:
            continue
        if re.search(r"^(Provisional NEET|SNo Rank|Quota Abbrevation|Abbrevation Description|Page No\.|Allotted Category|Note\*)", line, re.I):
            continue
        if ROW_START_RE.match(line):
            if current:
                rows.append(compact_space(" ".join(current)))
            current = [line]
        elif current:
            current.append(line)
    if current:
        rows.append(compact_space(" ".join(current)))
    return rows


def match_known_quota(value: str) -> tuple[str | None, str]:
    normalized = compact_space(value)
    for quota in sorted(KNOWN_QUOTAS, key=len, reverse=True):
        flexible = re.escape(quota).replace(r"\ ", r"\s+")
        match = re.match(flexible + r"(?=\s|$)", normalized, re.I)
        if match:
            return quota, compact_space(normalized[match.end() :])
    return None, normalized


def clean_college_name(value: str) -> str:
    value = compact_space(value)
    parts = [compact_space(part) for part in value.split(",") if compact_space(part)]
    if len(parts) < 2:
        return value

    first = parts[0]
    second = parts[1]
    include_second = (
        len(second) <= 35
        and not re.search(r"\b(road|sector|phase|campus|building|near|post|pin|village|nagar|marg|po|p\.o)\b", second, re.I)
    ) or second.upper() in {"BHU", "AMU"}
    return f"{first}, {second}" if include_second else first


def parse_mcc_table_row(row: str, page: int, year: int, round_name: str, source_url: str | None, source_file: str, content_hash: str) -> dict[str, Any] | None:
    start = ROW_START_RE.match(row)
    if not start:
        return None
    serial = int(start.group(1))
    rank = int(start.group(2))
    rest = compact_space(start.group(3))
    course_match = COURSE_RE.search(rest)
    if not course_match:
        return None

    before_course = compact_space(rest[: course_match.start()])
    after_course = compact_space(rest[course_match.end() :])
    after_course = REMARK_RE.sub("", after_course).strip()
    category_matches = list(CATEGORY_RE.finditer(after_course))
    allotted_category = normalize_category(category_matches[0].group(1) if category_matches else None)
    candidate_category = normalize_category(category_matches[1].group(1) if len(category_matches) > 1 else None)

    quota, college_text = match_known_quota(before_course)
    if not quota:
        # Fallback for less common MCC quotas: use text before a college-like
        # token as quota, and the rest as institute.
        college_token = re.search(r"(AIIMS|JIPMER|College|Institute|University|Hospital|Faculty|School)", before_course, re.I)
        if not college_token:
            return None
        quota = before_course[: college_token.start()]
        college_text = before_course[college_token.start() :]

    college_name = clean_college_name(college_text)
    if len(college_name) < 4:
        return None

    return {
        "authority": "MCC",
        "year": year,
        "round": round_name,
        "quota": normalize_quota(quota),
        "category": allotted_category,
        "candidateCategory": candidate_category,
        "course": normalize_course(course_match.group(1)),
        "collegeName": college_name,
        "rank": rank,
        "serial": serial,
        "sourceUrl": source_url,
        "sourceFile": source_file,
        "sourcePage": page,
        "contentHash": content_hash,
        "verificationStatus": "parsed_from_official_pdf",
    }


def extract_rows(pdf_path: Path, year: int, round_name: str, source_url: str | None) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    content_hash = sha256_file(pdf_path)
    rows: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for table_row in split_pdf_rows(text):
            row = parse_mcc_table_row(table_row, index, year, round_name, source_url, pdf_path.name, content_hash)
            if row:
                rows.append(row)
        if rows:
            continue
        for line in text.splitlines():
            row = parse_result_line(line, index, year, round_name, source_url, pdf_path.name, content_hash)
            if row:
                rows.append(row)
    return rows


def build_cutoffs(rows: list[dict[str, Any]], imported_at: str) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["authority"],
            row["year"],
            row["round"],
            row.get("quota"),
            row.get("category"),
            row.get("course"),
            row.get("collegeName"),
        )
        grouped[key].append(row)

    cutoffs: list[dict[str, Any]] = []
    for key, items in grouped.items():
        closing = max(items, key=lambda item: item["rank"])
        opening = min(items, key=lambda item: item["rank"])
        cutoffs.append(
            {
                "authority": key[0],
                "year": key[1],
                "round": key[2],
                "quota": key[3],
                "category": key[4],
                "course": key[5],
                "collegeName": key[6],
                "openingRank": opening["rank"],
                "closingRank": closing["rank"],
                "candidateCategories": sorted({item.get("candidateCategory") for item in items if item.get("candidateCategory")}),
                "allottedRows": len(items),
                "sourceUrl": closing.get("sourceUrl"),
                "sourceFile": closing.get("sourceFile"),
                "sourcePages": sorted({item["sourcePage"] for item in items}),
                "contentHash": closing.get("contentHash"),
                "verificationStatus": closing.get("verificationStatus"),
            }
        )

    cutoffs.sort(key=lambda item: (item["year"], str(item["round"]), item["closingRank"], item["collegeName"]))
    return {
        "generatedAt": imported_at,
        "parser": "api.mcc_import:v1",
        "rawRows": len(rows),
        "cutoffGroups": len(cutoffs),
        "cutoffs": cutoffs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import MCC allotment/cutoff PDF into normalized JSON.")
    parser.add_argument("--pdf", required=True, help="Path to official MCC result/cutoff PDF.")
    parser.add_argument("--year", required=True, type=int, help="Counselling year, e.g. 2025 or 2026.")
    parser.add_argument("--round", required=True, dest="round_name", help="Round label, e.g. R1, R2, R3, Stray.")
    parser.add_argument("--source-url", default=None, help="Official MCC PDF URL.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    imported_at = datetime.now(timezone.utc).isoformat()
    rows = extract_rows(pdf_path, args.year, args.round_name, args.source_url)
    output = build_cutoffs(rows, imported_at)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "rawRows": output["rawRows"], "cutoffGroups": output["cutoffGroups"]}, indent=2))


if __name__ == "__main__":
    main()
