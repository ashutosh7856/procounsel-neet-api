"""Import MBA institutes, programmes and official minimum CAT thresholds into mbaPrograms.

    .venv/bin/python -m scripts.mba.import_programs --dry-run
    .venv/bin/python -m scripts.mba.import_programs                 # all data/mba/programs/*.json
    .venv/bin/python -m scripts.mba.import_programs data/mba/programs/iim-ahmedabad.json

One file per institute; the document id is the file's ``slug`` (must equal the file name).
Every fee / intake / salary figure and every cutoff record must carry an official source
(``kind: "official"``, url, retrievedAt). Documents are overwritten with ``set`` so
re-running is idempotent. Institutes are never deleted by this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "data" / "mba" / "programs"


def load(paths: list[Path]) -> tuple[list[dict], list[str]]:
    from pydantic import ValidationError

    from api.mba.program_models import InstituteRecord

    docs, errors = [], []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: cannot read JSON ({error})")
            continue
        try:
            record = InstituteRecord.model_validate(raw)
        except ValidationError as error:
            errors.append(f"{path.name}: {error}")
            continue
        if record.slug != path.stem:
            errors.append(f"{path.name}: slug {record.slug!r} must match the file name")
            continue
        # Keep source quotes (audit trail) in the document; the API never returns them.
        docs.append(record.model_dump(exclude_none=False))
    slugs = [d["slug"] for d in docs]
    if len(slugs) != len(set(slugs)):
        errors.append("duplicate slugs across files")
    return docs, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import data/mba/programs/*.json into mbaPrograms.")
    parser.add_argument("files", nargs="*", type=Path, help="specific files (default: every *.json in data/mba/programs)")
    parser.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    args = parser.parse_args(argv)

    paths = args.files or sorted(PROGRAMS_DIR.glob("*.json"))
    if not paths:
        print(f"No institute files found in {PROGRAMS_DIR}; nothing was written.", file=sys.stderr)
        return 2
    docs, errors = load(paths)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("Validation failed; nothing was written.", file=sys.stderr)
        return 1

    for doc in docs:
        figures = sum(1 for p in doc["programs"] for k in ("feeTotal", "intake", "medianSalary") if p[k] is not None)
        print(f"{doc['slug']}: {len(doc['programs'])} programme(s), {figures} sourced figure(s), "
              f"{len(doc['cutoffs'])} cutoff record(s)")
    print(f"{len(docs)} institute file(s) valid.")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    from api.db import get_db
    from api.db.firebase import DB_TIMEOUT

    db = get_db()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for doc in docs:
        db.collection("mbaPrograms").document(doc["slug"]).set({**doc, "updatedAt": stamp}, timeout=DB_TIMEOUT)
    print(f"Wrote {len(docs)} document(s) to mbaPrograms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
