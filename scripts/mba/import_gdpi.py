"""Import GDPI preparation content (WAT topics, GD topics, PI questions) into mbaGdpiItems.

    .venv/bin/python -m scripts.mba.import_gdpi --dry-run
    .venv/bin/python -m scripts.mba.import_gdpi                  # data/mba/gdpi/{wat,gd,pi}.json
    .venv/bin/python -m scripts.mba.import_gdpi data/mba/gdpi/pi.json

Each file is ``{"items": [...]}``; the item kind is the file name (``wat``/``gd``/``pi``). Every item
is validated with ``api.mba.gdpi_models.GdpiItemRecord`` (all or nothing). Documents use the item
``id`` as the document id and are written with ``set`` (idempotent). Items are imported as
``status: "published"`` unless the file says otherwise (this is guidance content, not a question
bank). Items that were imported before but are no longer in the files are archived, not deleted.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GDPI_DIR = ROOT / "data" / "mba" / "gdpi"
COLLECTION = "mbaGdpiItems"
KINDS = ("wat", "gd", "pi")


def load_file(path: Path, kind: str) -> tuple[list[dict[str, Any]], list[str]]:
    from pydantic import ValidationError

    from api.mba.gdpi_models import GdpiItemRecord

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [], [f"{path.name}: cannot read JSON ({error})"]
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        return [], [f"{path.name}: expected a non-empty 'items' list"]
    docs, errors = [], []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{path.name}[{index}]: not an object")
            continue
        try:
            record = GdpiItemRecord.model_validate({**item, "kind": kind})
        except ValidationError as error:
            errors.append(f"{path.name}[{index}] {item.get('id')!r}: {error}")
            continue
        docs.append(record.model_dump(by_alias=False))
    return docs, errors


def load(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    docs, errors = [], []
    for path in paths:
        kind = path.stem.split(".")[0]
        if kind not in KINDS:
            errors.append(f"{path.name}: file name must start with one of {KINDS}")
            continue
        file_docs, file_errors = load_file(path, kind)
        docs += file_docs
        errors += file_errors
    ids = [d["id"] for d in docs]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate ids: {', '.join(dupes)}")
    prompts = [d["prompt"].strip().lower() for d in docs]
    same = sorted({p for p in prompts if prompts.count(p) > 1})
    if same:
        errors.append(f"duplicate prompts: {same[:5]}")
    return docs, errors


def write(db: Any, docs: list[dict[str, Any]], kinds: set[str], stamp: str) -> tuple[int, int]:
    """Upsert ``docs``; archive previously imported items of ``kinds`` that are gone. Returns (written, archived)."""
    from api.db.firebase import DB_TIMEOUT

    collection = db.collection(COLLECTION)
    keep = {d["id"] for d in docs}
    archived = 0
    for snap in collection.stream(timeout=DB_TIMEOUT):
        data = snap.to_dict() or {}
        if snap.id not in keep and data.get("kind") in kinds and data.get("status") != "archived":
            collection.document(snap.id).set({**data, "status": "archived", "updatedAt": stamp}, timeout=DB_TIMEOUT)
            archived += 1
    for doc in docs:
        collection.document(doc["id"]).set({**doc, "updatedAt": stamp}, timeout=DB_TIMEOUT)
    return len(docs), archived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import data/mba/gdpi/*.json into mbaGdpiItems.")
    parser.add_argument("files", nargs="*", type=Path, help="specific files (default: wat.json, gd.json, pi.json)")
    parser.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    args = parser.parse_args(argv)

    paths = args.files or [GDPI_DIR / f"{kind}.json" for kind in KINDS]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"Missing file(s): {', '.join(missing)}; nothing was written.", file=sys.stderr)
        return 2
    docs, errors = load(paths)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("Validation failed; nothing was written.", file=sys.stderr)
        return 1

    counts: dict[str, dict[str, int]] = {}
    for doc in docs:
        counts.setdefault(doc["kind"], {}).setdefault(doc["group"], 0)
        counts[doc["kind"]][doc["group"]] += 1
    for kind, groups in counts.items():
        print(f"{kind}: {sum(groups.values())} item(s) — " + ", ".join(f"{g} {n}" for g, n in sorted(groups.items())))
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    from api.db import get_db

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    written, archived = write(get_db(), docs, set(counts), stamp)
    print(f"Wrote {written} document(s) to {COLLECTION}; archived {archived} item(s) no longer in the files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
