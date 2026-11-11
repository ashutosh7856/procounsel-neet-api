"""Import one MBA paper / mock (format: docs/mba-content-format.md).

    .venv/bin/python -m scripts.mba.import_paper data/mba/content/<paperId> --dry-run
    .venv/bin/python -m scripts.mba.import_paper data/mba/content/<paperId>            # as draft
    .venv/bin/python -m scripts.mba.import_paper data/mba/content/<paperId> --publish  # after review

The path is a content directory (paper.json + varc/dilr/qa.json) or a single JSON file.
Idempotent: ids are derived from paperId + key, so re-running overwrites the same
documents. Everything is written with status "draft" unless --publish is given.
Questions/sets of this paper no longer in the content are set to "archived" (never
deleted). Writes only through api.db.get_db().

Faculty work is protected: questions/sets that were reviewed or edited in the Admin
panel (reviewedAt set or version > 1), and a paper that is already published, are left
untouched unless --force is given.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paper_format import PaperFormatError, build_paper_docs, load_content

PAPERS, SETS, QUESTIONS = "mbaPapers", "mbaQuestionSets", "mbaQuestions"


def _is_reviewed(doc: dict[str, Any]) -> bool:
    return bool(doc.get("reviewedAt")) or int(doc.get("version") or 1) > 1


def _write(
    db: Any, paper: dict[str, Any], sets: list[dict[str, Any]], questions: list[dict[str, Any]], force: bool = False
) -> dict[str, int]:
    from google.cloud.firestore_v1.base_query import FieldFilter

    from api.db.firebase import DB_TIMEOUT

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    writes: list[tuple[str, str, dict[str, Any]]] = []
    skipped = 0
    for collection, docs in ((SETS, sets), (QUESTIONS, questions)):
        keep = {doc["id"] for doc in docs}
        existing: dict[str, dict[str, Any]] = {}
        query = db.collection(collection).where(filter=FieldFilter("paperId", "==", paper["id"]))
        for snap in query.stream(timeout=DB_TIMEOUT):
            existing[snap.id] = snap.to_dict() or {}
        for doc_id, current in existing.items():
            if doc_id in keep or current.get("status") == "archived":
                continue
            if _is_reviewed(current) and not force:
                skipped += 1
                continue
            writes.append((collection, doc_id, {"status": "archived", "updatedAt": now}))
        for doc in docs:
            if doc["id"] in existing and _is_reviewed(existing[doc["id"]]) and not force:
                skipped += 1
                continue
            writes.append((collection, doc["id"], {**doc, "updatedAt": now}))
    current_paper = db.collection(PAPERS).document(paper["id"]).get(timeout=DB_TIMEOUT)
    paper_published = current_paper.exists and (current_paper.to_dict() or {}).get("status") == "published"
    if not paper_published or force:
        writes.append((PAPERS, paper["id"], {**paper, "updatedAt": now}))  # paper last: visible once complete

    counts = {"sets": len(sets), "questions": len(questions), "archived": 0, "skipped": skipped}
    batch, pending = db.batch(), 0
    for collection, doc_id, data in writes:
        ref = db.collection(collection).document(doc_id)
        if data.get("status") == "archived" and len(data) == 2:
            batch.set(ref, data, merge=True)
            counts["archived"] += 1
        else:
            batch.set(ref, data)
        pending += 1
        if pending >= 400:
            batch.commit(timeout=DB_TIMEOUT)
            batch, pending = db.batch(), 0
    if pending:
        batch.commit(timeout=DB_TIMEOUT)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import an MBA paper (content directory or JSON file).")
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    parser.add_argument("--publish", action="store_true", help='write with status "published" (default "draft")')
    parser.add_argument("--force", action="store_true", help="also overwrite reviewed/edited content and a published paper")
    args = parser.parse_args(argv)

    try:
        paper, sets, questions, warnings = build_paper_docs(load_content(args.path), publish=args.publish)
    except PaperFormatError as error:
        print(f"{args.path}: {len(error.errors)} problem(s):", file=sys.stderr)
        for line in error.errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    for line in warnings:
        print(f"warning: {line}")
    summary = ", ".join(f"{s['id']} {len(s['questionIds'])}" for s in paper["sections"])
    print(f"{paper['id']}: {len(questions)} questions ({summary}), {len(sets)} sets — valid; status {paper['status']}.")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    from api.db import get_db

    counts = _write(get_db(), paper, sets, questions, force=args.force)
    print(f"Imported {paper['id']}: {counts['questions']} questions, {counts['sets']} sets, {counts['archived']} archived, "
          f"{counts['skipped']} reviewed/edited left untouched (use --force to overwrite).")
    print("The API caches content for MBA_BANK_TTL_SECONDS (default 300s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
