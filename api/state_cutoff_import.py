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
DEFAULT_OUT = ROOT / "data" / "official" / "normalized" / "state-cutoffs.json"
PARSER_VERSION = "maharashtra-cap-pdf-v1"

ROW_RE = re.compile(
    r"^\s*(?P<serial>\d+)\s+(?P<air>\d+)\s+(?P<roll>\d+)\s+(?P<form>\d+)\s+"
    r"(?P<name>.+?)\s{2,}(?P<gender>[MF])(?P<middle>.*?)\s{2,}"
    r"(?P<collegeCode>\d{4}):(?P<collegeName>.+?)\s*$"
)

RESERVATION_MARKERS = {
    "OPEN",
    "OBC",
    "SC",
    "ST",
    "EWS",
    "SEBC",
    "VJA",
    "NTB",
    "NTC",
    "NTD",
    "HA",
    "DEF1",
    "DEF2",
    "DEF3",
    "ORP-A",
    "ORP-B",
    "ORP-C",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_category(parts: list[str], quota: str) -> str:
    for part in parts:
        token = clean(part).upper()
        if token in RESERVATION_MARKERS and token not in {"HA"}:
            return token
    quota_token = clean(quota).upper()
    for marker in sorted(RESERVATION_MARKERS, key=len, reverse=True):
        if marker != "HA" and marker in quota_token:
            return marker
    return "OPEN"


def infer_course(college_name: str) -> str:
    name = college_name.upper()
    if "DENTAL" in name or "BDS" in name:
        return "BDS"
    return "MBBS"


def parse_maharashtra_cap_pdf(
    pdf_path: Path,
    *,
    year: int,
    round_name: str,
    source_url: str,
) -> dict[str, Any]:
    content_hash = sha256(pdf_path)
    reader = PdfReader(str(pdf_path))
    rows: list[dict[str, Any]] = []

    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line in text.splitlines():
            match = ROW_RE.match(line)
            if not match:
                continue
            data = match.groupdict()
            middle_parts = [part for part in re.split(r"\s{2,}", clean(data["middle"])) if part]
            quota = next((part for part in reversed(middle_parts) if not part.startswith("(")), "OPEN")
            college_name = clean(data["collegeName"])
            rows.append(
                {
                    "exam": "NEET-UG",
                    "year": year,
                    "authority": "State Common Entrance Test Cell, Maharashtra",
                    "state": "Maharashtra",
                    "counsellingType": "State quota",
                    "round": round_name,
                    "quota": clean(quota),
                    "collegeCode": clean(data["collegeCode"]),
                    "collegeName": college_name,
                    "course": infer_course(college_name),
                    "category": infer_category(middle_parts, quota),
                    "candidateCategory": next((part for part in middle_parts if clean(part).upper() in RESERVATION_MARKERS), ""),
                    "rank": int(data["air"]),
                    "gender": "Female" if data["gender"] == "F" else "Male",
                    "sourceUrl": source_url,
                    "sourceFile": str(pdf_path.relative_to(ROOT)).replace("\\", "/"),
                    "sourcePages": [page_index],
                    "contentHash": content_hash,
                    "parserVersion": PARSER_VERSION,
                    "verificationStatus": "parsed_from_official_state_pdf",
                }
            )

    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    page_sets: dict[tuple[str, ...], set[int]] = defaultdict(set)
    for row in rows:
        key = (
            str(row["year"]),
            row["authority"],
            row["state"],
            row["counsellingType"],
            row["round"],
            row["quota"],
            row["collegeCode"],
            row["collegeName"],
            row["course"],
            row["category"],
        )
        existing = groups.get(key)
        rank = int(row["rank"])
        page_sets[key].update(row["sourcePages"])
        if not existing:
            groups[key] = {
                "exam": row["exam"],
                "year": row["year"],
                "authority": row["authority"],
                "state": row["state"],
                "counsellingType": row["counsellingType"],
                "round": row["round"],
                "quota": row["quota"],
                "collegeCode": row["collegeCode"],
                "collegeName": row["collegeName"],
                "course": row["course"],
                "category": row["category"],
                "openingRank": rank,
                "closingRank": rank,
                "allottedRows": 1,
                "sourceUrl": row["sourceUrl"],
                "sourceFile": row["sourceFile"],
                "sourcePages": row["sourcePages"],
                "contentHash": row["contentHash"],
                "parserVersion": row["parserVersion"],
                "verificationStatus": row["verificationStatus"],
            }
            continue
        existing["openingRank"] = min(existing["openingRank"], rank)
        existing["closingRank"] = max(existing["closingRank"], rank)
        existing["allottedRows"] += 1

    cutoffs = []
    for key, record in groups.items():
        record["sourcePages"] = sorted(page_sets[key])
        cutoffs.append(record)

    cutoffs.sort(
        key=lambda item: (
            item["state"],
            item["year"],
            item["round"],
            item["collegeName"],
            item["category"],
            item["closingRank"],
        )
    )
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "parserVersion": PARSER_VERSION,
        "rawRows": len(rows),
        "cutoffGroups": len(cutoffs),
        "cutoffs": cutoffs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import official state NEET UG cutoff/allotment PDFs.")
    parser.add_argument("--state", required=True, choices=["maharashtra"])
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--round", required=True, dest="round_name")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    payload = parse_maharashtra_cap_pdf(
        pdf_path,
        year=args.year,
        round_name=args.round_name,
        source_url=args.source_url,
    )
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path} ({payload['cutoffGroups']} cutoff groups from {payload['rawRows']} allotment rows)")


if __name__ == "__main__":
    main()
