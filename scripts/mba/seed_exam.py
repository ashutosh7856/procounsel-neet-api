"""Seed the CAT exam config (mbaExams/cat) from data/mba/cat_exam.json.

    .venv/bin/python -m scripts.mba.seed_exam --dry-run
    .venv/bin/python -m scripts.mba.seed_exam

The file is researched from iimcat.ac.in; this script never invents values. It
validates against the API's Exam model (every version needs a source with a URL)
and overwrites mbaExams/cat, so re-running is idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from .paper_format import EXAM_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed mbaExams/cat from data/mba/cat_exam.json.")
    parser.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    args = parser.parse_args(argv)

    if not EXAM_FILE.exists():
        print(f"{EXAM_FILE} does not exist yet. Add the researched CAT exam pattern first "
              "(see docs/mba-content-format.md); nothing was written.", file=sys.stderr)
        return 2
    try:
        raw = json.loads(EXAM_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"Invalid JSON in {EXAM_FILE}: {error}", file=sys.stderr)
        return 2
    raw = raw.get("exam", raw) if isinstance(raw, dict) else raw

    from pydantic import ValidationError

    from api.mba.models import Exam

    try:
        exam = Exam.model_validate(raw)
    except ValidationError as error:
        print(f"{EXAM_FILE} does not match the Exam schema:\n{error}", file=sys.stderr)
        return 1
    problems = []
    for version in exam.versions:
        if not version.source.url:
            problems.append(f"version {version.year}: source.url is required")
        types = {rule.type for rule in version.marking}
        if not {"MCQ", "TITA"} <= types:
            problems.append(f"version {version.year}: marking must cover MCQ and TITA")
        if sum(s.durationMinutes for s in version.sections) != version.totalDurationMinutes:
            problems.append(f"version {version.year}: section durations do not add up to totalDurationMinutes")
    years = [v.year for v in exam.versions]
    if not years or len(years) != len(set(years)):
        problems.append("versions must be non-empty with unique years")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    print(f"cat: {len(exam.versions)} version(s) {sorted(years)} — valid.")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    from api.db import get_db
    from api.db.firebase import DB_TIMEOUT

    doc = {**exam.model_dump(), "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    get_db().collection("mbaExams").document("cat").set(doc, timeout=DB_TIMEOUT)
    print("Wrote mbaExams/cat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
