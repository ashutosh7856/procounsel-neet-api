"""Load, validate and build documents for an MBA paper (docs/mba-content-format.md).

Pure (no database access) so ``--dry-run`` and tests can use it directly.

Input is either a directory ``data/mba/content/<paperId>/`` with ``paper.json`` plus
section fragments ``varc.json`` / ``dilr.json`` / ``qa.json``, or one JSON file
``{"paper": {...}, "sets": [...], "questions": [...]}`` with the same fields.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXAM_FILE = ROOT / "data" / "mba" / "cat_exam.json"

SECTION_ORDER = ("VARC", "DILR", "QA")
FRAGMENT_FILES = {"varc.json": "VARC", "dilr.json": "DILR", "qa.json": "QA"}
SET_KINDS = {"passage", "dilr_set", "data"}
DIFFICULTIES = {"easy", "medium", "hard"}
SOURCE_KINDS = {"official", "licensed", "faculty", "original"}
URL_REQUIRED_KINDS = {"official", "licensed"}
PAPER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,60}$")
OPTION_ID_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")

PAPER_KEYS = {"id", "examId", "title", "examVersionYear", "year", "slot", "source"}
SOURCE_KEYS = {"kind", "title", "url", "year", "retrievedAt", "notes"}
SET_KEYS = {"key", "kind", "section", "title", "contentHtml", "images"}
QUESTION_KEYS = {"key", "section", "number", "type", "setKey", "stemHtml", "options", "answer",
                 "solutionHtml", "topic", "subtopic", "difficulty", "source"}


class PaperFormatError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- loading
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PaperFormatError([f"{path.name}: invalid JSON ({error})"]) from error


def load_content(path: Path) -> dict[str, Any]:
    """Read a paper directory or single file into ``{"paper", "sets", "questions"}``."""
    if path.is_file():
        return _read_json(path)
    if not path.is_dir():
        raise PaperFormatError([f"{path} does not exist"])
    errors: list[str] = []
    paper_file = path / "paper.json"
    if not paper_file.exists():
        raise PaperFormatError([f"{path}: paper.json is missing"])
    content: dict[str, Any] = {"paper": _read_json(paper_file), "sets": [], "questions": []}
    found = False
    for name, section in FRAGMENT_FILES.items():
        fragment_path = path / name
        if not fragment_path.exists():
            continue
        found = True
        fragment = _read_json(fragment_path)
        if not isinstance(fragment, dict) or set(fragment) - {"sets", "questions"}:
            errors.append(f"{name}: must be an object with only 'sets' and 'questions'")
            continue
        for kind in ("sets", "questions"):
            items = fragment.get(kind) or []
            if not isinstance(items, list):
                errors.append(f"{name}: {kind} must be a list")
                continue
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{name}: {kind}[{i}] must be an object")
                    continue
                if item.get("section", section) != section:
                    errors.append(f"{name}: {kind}[{i}] has section {item.get('section')!r}, expected {section}")
                content[kind].append({**item, "section": section})
    others = sorted(p.name for p in path.glob("*.json") if p.name != "paper.json" and p.name not in FRAGMENT_FILES)
    if others:
        errors.append(f"{path}: unexpected files {others} (allowed: paper.json, {', '.join(FRAGMENT_FILES)})")
    if not found:
        errors.append(f"{path}: no section files ({', '.join(FRAGMENT_FILES)})")
    if errors:
        raise PaperFormatError(errors)
    return content


def exam_versions() -> dict[int, dict[str, Any]] | None:
    """Exam versions from data/mba/cat_exam.json keyed by year (None if the file is unavailable)."""
    if not EXAM_FILE.exists():
        return None
    try:
        exam = json.loads(EXAM_FILE.read_text(encoding="utf-8"))
        exam = exam.get("exam", exam)
        return {v["year"]: v for v in exam.get("versions") or [] if isinstance(v.get("year"), int)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------- validation helpers
def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) > 10


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _opt_int(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _unknown(where: str, data: dict[str, Any], allowed: set[str], errors: list[str]) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        errors.append(f"{where}: unknown field(s) {extra}")


def _source(where: str, raw: Any, errors: list[str], default_title: str | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        errors.append(f"{where}: source is required (object)")
        return {}
    _unknown(f"{where}.source", raw, SOURCE_KEYS, errors)
    kind = raw.get("kind")
    if kind not in SOURCE_KINDS:
        errors.append(f"{where}: source.kind must be one of {sorted(SOURCE_KINDS)}")
    url = raw.get("url")
    if kind in URL_REQUIRED_KINDS and not _is_url(url):
        errors.append(f"{where}: source.url (http/https) is required for {kind} content")
    elif url is not None and not _is_url(url):
        errors.append(f"{where}: source.url must be an http(s) URL")
    title = raw.get("title") if _nonempty(raw.get("title")) else default_title
    if not _nonempty(title):
        errors.append(f"{where}: source.title is required")
    if not _opt_int(raw.get("year")):
        errors.append(f"{where}: source.year must be an integer")
    out: dict[str, Any] = {"kind": kind, "title": title, "url": url, "year": raw.get("year")}
    if raw.get("retrievedAt") is not None:
        if not _nonempty(raw.get("retrievedAt")):
            errors.append(f"{where}: source.retrievedAt must be a string (YYYY-MM-DD)")
        out["retrievedAt"] = raw.get("retrievedAt")
    if _nonempty(raw.get("notes")):
        out["notes"] = raw["notes"]
    return out


# ---------------------------------------------------------------- build
def build_paper_docs(
    raw: Any, publish: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Validate content. Returns (paperDoc, setDocs, questionDocs, warnings); raises PaperFormatError.

    Every built document gets ``status`` "published" when ``publish`` else "draft".
    """
    status = "published" if publish else "draft"
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raise PaperFormatError(["content must be a JSON object with paper, sets, questions"])
    _unknown("file", raw, {"paper", "sets", "questions"}, errors)
    paper = raw.get("paper")
    if not isinstance(paper, dict):
        raise PaperFormatError(["paper: object is required"])
    _unknown("paper", paper, PAPER_KEYS, errors)

    exam_id = paper.get("examId", "cat")
    year, slot, version_year = paper.get("year"), paper.get("slot"), paper.get("examVersionYear")
    if exam_id != "cat":
        errors.append("paper.examId must be 'cat'")
    for name, value in (("year", year), ("slot", slot), ("examVersionYear", version_year)):
        if not _opt_int(value):
            errors.append(f"paper.{name} must be an integer or null")
    if version_year is None and isinstance(year, int):
        version_year = year
    if version_year is None:
        errors.append("paper.examVersionYear is required (the CAT pattern/marking year this paper follows)")
    paper_id = paper.get("id")
    if paper_id is None and isinstance(year, int) and isinstance(slot, int):
        paper_id = f"cat-{year}-slot{slot}"
    if not isinstance(paper_id, str) or not PAPER_ID_RE.match(paper_id):
        errors.append(f"paper.id is required and must match {PAPER_ID_RE.pattern}")
    if errors:
        raise PaperFormatError(errors)
    title = paper.get("title")
    if not _nonempty(title):
        title = f"CAT {year} Slot {slot}" if isinstance(year, int) and isinstance(slot, int) else None
    if not _nonempty(title):
        errors.append("paper.title is required")
    paper_source = _source("paper", paper.get("source"), errors, None)
    versions = exam_versions()
    version = None
    if versions is not None:
        version = versions.get(version_year)
        if version is None:
            errors.append(f"paper.examVersionYear {version_year} is not a version in {EXAM_FILE.name} ({sorted(versions)})")
    else:
        warnings.append(f"{EXAM_FILE} not found; examVersionYear {version_year} not checked")

    # Sets
    sets_raw = raw.get("sets") or []
    if not isinstance(sets_raw, list):
        errors.append("sets must be a list")
        sets_raw = []
    set_docs: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(sets_raw):
        where = f"sets[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: must be an object")
            continue
        _unknown(where, item, SET_KEYS, errors)
        key = item.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f"{where}: key must match {KEY_RE.pattern}")
            continue
        where = f"set {key}"
        if key in set_docs:
            errors.append(f"{where}: duplicate key")
        if item.get("kind") not in SET_KINDS:
            errors.append(f"{where}: kind must be one of {sorted(SET_KINDS)}")
        if item.get("section") not in SECTION_ORDER:
            errors.append(f"{where}: section must be one of {list(SECTION_ORDER)}")
        if not _nonempty(item.get("contentHtml")):
            errors.append(f"{where}: contentHtml is required")
        images = item.get("images")
        if images is not None and (not isinstance(images, list) or not all(_is_url(img) for img in images)):
            errors.append(f"{where}: images must be a list of http(s) URLs")
        set_docs[key] = {
            "id": f"{paper_id}-{key.lower()}", "key": key, "examId": exam_id, "paperId": paper_id,
            "section": item.get("section"), "kind": item.get("kind"),
            "title": item.get("title") if _nonempty(item.get("title")) else None,
            "contentHtml": item.get("contentHtml"), "images": images or [], "status": status,
        }

    # Questions
    questions_raw = raw.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        errors.append("questions must be a non-empty list")
        questions_raw = []
    question_docs: list[dict[str, Any]] = []
    keys: set[str] = set()
    used_sets: set[str] = set()
    for i, q in enumerate(questions_raw):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            errors.append(f"{where}: must be an object")
            continue
        _unknown(where, q, QUESTION_KEYS, errors)
        key, section, qtype = q.get("key"), q.get("section"), q.get("type")
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f"{where}: key must match {KEY_RE.pattern} (e.g. 'QA-01')")
            continue
        where = f"question {key}"
        if key.lower() in keys:
            errors.append(f"{where}: duplicate key")
        keys.add(key.lower())
        if section not in SECTION_ORDER:
            errors.append(f"{where}: section must be one of {list(SECTION_ORDER)}")
            continue
        number = q.get("number")
        if number is not None and (not isinstance(number, int) or isinstance(number, bool) or number < 1):
            errors.append(f"{where}: number must be a positive integer")
        if qtype not in ("MCQ", "TITA"):
            errors.append(f"{where}: type must be MCQ or TITA")
        if not _nonempty(q.get("stemHtml")):
            errors.append(f"{where}: stemHtml is required")
        answer = q.get("answer")
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            answer = str(answer)
        options = None
        if qtype == "MCQ":
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                errors.append(f"{where}: MCQ needs at least 2 options")
                opts = []
            options = []
            for j, opt in enumerate(opts):
                if not isinstance(opt, dict) or set(opt) - {"id", "textHtml"}:
                    errors.append(f"{where}: options[{j}] must be {{id, textHtml}}")
                    continue
                if not isinstance(opt.get("id"), str) or not OPTION_ID_RE.match(opt["id"]):
                    errors.append(f"{where}: options[{j}].id must be a short alphanumeric id like 'A'")
                    continue
                if not _nonempty(opt.get("textHtml")):
                    errors.append(f"{where}: options[{j}].textHtml is required")
                options.append({"id": opt["id"], "textHtml": opt.get("textHtml")})
            ids = [opt["id"] for opt in options]
            if len(ids) != len(set(ids)):
                errors.append(f"{where}: option ids must be unique")
            if not isinstance(answer, str) or answer.strip() not in ids:
                errors.append(f"{where}: answer must be one of the option ids {ids}")
        elif qtype == "TITA":
            if q.get("options"):
                errors.append(f"{where}: TITA questions must not have options")
            if not _nonempty(answer):
                errors.append(f"{where}: TITA answer is required")
            elif len(answer.strip()) > 50:
                errors.append(f"{where}: TITA answer is too long")
        set_key = q.get("setKey")
        set_id = None
        if set_key is not None:
            if set_key not in set_docs:
                errors.append(f"{where}: setKey '{set_key}' is not defined in sets")
            elif set_docs[set_key]["section"] != section:
                errors.append(f"{where}: setKey '{set_key}' belongs to section {set_docs[set_key]['section']}")
            else:
                set_id = set_docs[set_key]["id"]
                used_sets.add(set_key)
        if q.get("difficulty") is not None and q.get("difficulty") not in DIFFICULTIES:
            errors.append(f"{where}: difficulty must be one of {sorted(DIFFICULTIES)}")
        for text_field in ("solutionHtml", "topic", "subtopic"):
            if q.get(text_field) is not None and not isinstance(q.get(text_field), str):
                errors.append(f"{where}: {text_field} must be a string")
        if not _nonempty(q.get("solutionHtml")):
            warnings.append(f"{where}: no solutionHtml")
        source = _source(where, q.get("source"), errors, paper_source.get("title"))
        question_docs.append({
            "id": f"{paper_id}-{key.lower()}", "key": key, "examId": exam_id, "paperId": paper_id,
            "examVersionYear": version_year, "year": year, "slot": slot, "section": section,
            "number": number, "_order": i, "type": qtype,
            "stemHtml": q.get("stemHtml"), "options": options, "setId": set_id,
            "topic": q.get("topic") or None, "subtopic": q.get("subtopic") or None,
            "difficulty": q.get("difficulty"), "correctAnswer": answer.strip() if isinstance(answer, str) else None,
            "solutionHtml": q.get("solutionHtml") or None, "source": source, "status": status,
        })

    for key in set_docs:
        if key not in used_sets:
            warnings.append(f"set '{key}' is not used by any question")

    # Number = order within section (explicit numbers, when given, must be 1..n without gaps).
    sections = []
    for section in SECTION_ORDER:
        docs = [d for d in question_docs if d["section"] == section]
        if not docs:
            continue
        given = [d["number"] for d in docs if d["number"] is not None]
        if given and len(given) != len(docs):
            errors.append(f"{section}: give 'number' for every question or for none")
        elif given:
            if sorted(given) != list(range(1, len(docs) + 1)):
                errors.append(f"{section}: question numbers must be 1..{len(docs)} without gaps or duplicates")
            docs.sort(key=lambda d: d["number"] or 0)
        for position, doc in enumerate(docs, start=1):
            doc["number"] = position
        sections.append({"id": section, "questionIds": [d["id"] for d in docs]})
        expected = next((s.get("questionCount") for s in (version or {}).get("sections") or [] if s.get("id") == section), None)
        if isinstance(expected, int) and expected != len(docs):
            warnings.append(f"{section}: {len(docs)} questions; the {version_year} CAT pattern has {expected}")
    for doc in question_docs:
        doc.pop("_order", None)
    if errors:
        raise PaperFormatError(errors)

    paper_doc = {
        "id": paper_id, "examId": exam_id, "title": title, "examVersionYear": version_year,
        "year": year, "slot": slot, "source": paper_source, "sections": sections,
        "questionCount": len(question_docs), "status": status,
    }
    return paper_doc, list(set_docs.values()), question_docs, warnings
