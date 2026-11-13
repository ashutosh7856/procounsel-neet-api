"""Seed an exam config (mbaExams/<examId>) from its file.

    .venv/bin/python -m scripts.mba.seed_exam --dry-run                 # CAT (data/mba/cat_exam.json)
    .venv/bin/python -m scripts.mba.seed_exam --exam xat --dry-run      # data/mba/exams-config/xat.json
    .venv/bin/python -m scripts.mba.seed_exam --all --dry-run           # CAT + every exams-config file
    .venv/bin/python -m scripts.mba.seed_exam --exam xat                # write

The files are researched from the exam bodies' official sites (data/mba/SOURCES.md); this
script never invents values. It validates against the API's Exam model (every version needs
a source with a URL, consistent timing and marking) and overwrites mbaExams/<examId>, so
re-running is idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paper_format import EXAMS_CONFIG_DIR, SECTION_ORDER, exam_file


def _problems(exam: Any, exam_id: str) -> list[str]:
    """Consistency checks the Exam schema cannot express."""
    problems = []
    if exam.id != exam_id:
        problems.append(f"id is {exam.id!r}, expected {exam_id!r} (the file name)")
    for version in exam.versions:
        where = f"version {version.year}"
        if not version.source.url:
            problems.append(f"{where}: source.url is required")
        ids = [s.id for s in version.sections]
        if len(ids) != len(set(ids)) or not ids:
            problems.append(f"{where}: section ids must be unique and non-empty")
        if exam_id == "cat":
            if set(ids) - set(SECTION_ORDER):
                problems.append(f"{where}: CAT sections must be {list(SECTION_ORDER)}")
        elif set(ids) & set(SECTION_ORDER):
            problems.append(f"{where}: VARC/DILR/QA are reserved for CAT (CAT-only features key on them)")
        types = {rule.type for rule in version.marking}
        if exam_id == "cat" and not {"MCQ", "TITA"} <= types:
            problems.append(f"{where}: marking must cover MCQ and TITA")
        if "MCQ" not in types:
            problems.append(f"{where}: marking must cover MCQ")
        for rule in version.marking:
            if rule.sections and set(rule.sections) - set(ids):
                problems.append(f"{where}: marking rule for {rule.type} names unknown sections")
        penalty = version.unansweredPenalty
        if penalty and set(penalty.sections) - set(ids):
            problems.append(f"{where}: unansweredPenalty names unknown sections")
        if version.timerBlocks:
            covered = [sid for block in version.timerBlocks for sid in block.sectionIds]
            if sorted(covered) != sorted(ids):
                problems.append(f"{where}: timerBlocks must cover every section exactly once")
            block_ids = [block.id for block in version.timerBlocks]
            if len(block_ids) != len(set(block_ids)):
                problems.append(f"{where}: timerBlock ids must be unique")
            for block in version.timerBlocks:
                if len(block.sectionIds) == 1 and block.id != block.sectionIds[0]:
                    problems.append(f"{where}: a one-section timer block must have that section's id ({block.sectionIds[0]})")
                if len(block.sectionIds) > 1 and block.id in ids:
                    problems.append(f"{where}: multi-section timer block id {block.id} clashes with a section id")
            if sum(block.durationMinutes for block in version.timerBlocks) != version.totalDurationMinutes:
                problems.append(f"{where}: timer block durations do not add up to totalDurationMinutes")
        else:
            if any(s.durationMinutes is None for s in version.sections):
                problems.append(f"{where}: without timerBlocks every section needs durationMinutes")
            elif sum(s.durationMinutes or 0 for s in version.sections) != version.totalDurationMinutes:
                problems.append(f"{where}: section durations do not add up to totalDurationMinutes")
    years = [v.year for v in exam.versions]
    if not years or len(years) != len(set(years)):
        problems.append("versions must be non-empty with unique years")
    return problems


def _load(exam_id: str) -> tuple[dict[str, Any] | None, int]:
    from pydantic import ValidationError

    from api.mba.models import Exam

    path: Path = exam_file(exam_id)
    if not path.exists():
        print(f"{path} does not exist. Add the researched exam pattern first "
              "(see docs/mba-content-format.md); nothing was written.", file=sys.stderr)
        return None, 2
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"Invalid JSON in {path}: {error}", file=sys.stderr)
        return None, 2
    raw = raw.get("exam", raw) if isinstance(raw, dict) else raw
    try:
        exam = Exam.model_validate(raw)
    except ValidationError as error:
        print(f"{path} does not match the Exam schema:\n{error}", file=sys.stderr)
        return None, 1
    problems = _problems(exam, exam_id)
    if problems:
        print(f"{path}:\n  " + "\n  ".join(problems), file=sys.stderr)
        return None, 1
    years = sorted(v.year for v in exam.versions)
    print(f"{exam_id}: {len(years)} version(s) {years} — valid.")
    return exam.model_dump(), 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed mbaExams/<examId> from its exam config file.")
    parser.add_argument("--exam", default="cat", help="exam id (default cat; others: data/mba/exams-config/<id>.json)")
    parser.add_argument("--all", action="store_true", help="CAT and every file in data/mba/exams-config/")
    parser.add_argument("--dry-run", action="store_true", help="validate only; no database access")
    args = parser.parse_args(argv)

    exam_ids = [args.exam]
    if args.all:
        exam_ids = ["cat"] + sorted(p.stem for p in EXAMS_CONFIG_DIR.glob("*.json"))
    docs, status = {}, 0
    for exam_id in exam_ids:
        doc, code = _load(exam_id)
        status = max(status, code)
        if doc is not None:
            docs[exam_id] = doc
    if status:
        return status
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    from api.db import get_db
    from api.db.firebase import DB_TIMEOUT

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    db = get_db()
    for exam_id, doc in docs.items():
        db.collection("mbaExams").document(exam_id).set({**doc, "updatedAt": now}, timeout=DB_TIMEOUT)
        print(f"Wrote mbaExams/{exam_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
