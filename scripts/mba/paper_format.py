"""Load, validate and build documents for an MBA paper (docs/mba-content-format.md).

Pure (no database access) so ``--dry-run`` and tests can use it directly.

Input is either a directory ``data/mba/content/<paperId>/`` with ``paper.json`` plus one
section fragment per section (``<sectionId lowercased>.json``: ``varc.json`` / ``dilr.json`` /
``qa.json`` for CAT, e.g. ``valr.json`` / ``dm.json`` / ``qadi.json`` / ``gk.json`` for XAT), or
one JSON file ``{"paper": {...}, "sets": [...], "questions": [...]}`` with the same fields.

``paper.examId`` (default ``"cat"``) picks the exam config the paper is validated against:
``data/mba/cat_exam.json`` for CAT, ``data/mba/exams-config/<examId>.json`` for every other exam.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXAM_FILE = ROOT / "data" / "mba" / "cat_exam.json"
EXAMS_CONFIG_DIR = ROOT / "data" / "mba" / "exams-config"  # every exam except CAT (docs/mba-content-format.md)
EXAM_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

SECTION_ORDER = ("VARC", "DILR", "QA")  # CAT
FRAGMENT_FILES = {"varc.json": "VARC", "dilr.json": "DILR", "qa.json": "QA"}  # CAT
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
                 "solutionHtml", "alternativeApproaches", "videoUrl", "topic", "subtopic", "difficulty", "source"}
MAX_APPROACHES = 5  # alternativeApproaches: extra solution methods (HTML), shown after the main solution
APPROACH_MAX_CHARS = 20_000
VIDEO_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?$")  # https only, no spaces/quotes
VIDEO_URL_MAX = 500


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


def exam_file(exam_id: str) -> Path:
    """The config file of an exam: cat_exam.json for CAT, exams-config/<examId>.json otherwise."""
    return EXAM_FILE if exam_id == "cat" else EXAMS_CONFIG_DIR / f"{exam_id}.json"


def exam_config(exam_id: str) -> dict[str, Any] | None:
    """The exam config (``Exam`` shape, docs/mba-api.md) or None if missing/unreadable."""
    if not isinstance(exam_id, str) or not EXAM_ID_RE.match(exam_id):
        return None
    path = exam_file(exam_id)
    if not path.exists():
        return None
    try:
        exam = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    exam = exam.get("exam", exam) if isinstance(exam, dict) else None
    return exam if isinstance(exam, dict) else None


def section_ids(exam_id: str) -> tuple[str, ...]:
    """Every section id of the exam (all versions, first-seen order); CAT is always VARC/DILR/QA."""
    if exam_id == "cat":
        return SECTION_ORDER
    out: list[str] = []
    for version in (exam_config(exam_id) or {}).get("versions") or []:
        for section in (version or {}).get("sections") or []:
            sid = section.get("id") if isinstance(section, dict) else None
            if isinstance(sid, str) and sid not in out:
                out.append(sid)
    return tuple(out)


def fragment_files(exam_id: str) -> dict[str, str]:
    """Allowed section fragment file names -> section id."""
    if exam_id == "cat":
        return FRAGMENT_FILES
    return {f"{sid.lower()}.json": sid for sid in section_ids(exam_id)}


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
    exam_id = content["paper"].get("examId", "cat") if isinstance(content["paper"], dict) else "cat"
    files = fragment_files(exam_id) if isinstance(exam_id, str) else {}
    if not files:
        raise PaperFormatError([f"paper.examId {exam_id!r}: no exam config with sections ({exam_file(str(exam_id))})"])
    found = False
    for name, section in files.items():
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
    others = sorted(p.name for p in path.glob("*.json") if p.name != "paper.json" and p.name not in files)
    if others:
        errors.append(f"{path}: unexpected files {others} (allowed: paper.json, {', '.join(files)})")
    if not found:
        errors.append(f"{path}: no section files ({', '.join(files)})")
    if errors:
        raise PaperFormatError(errors)
    return content


def exam_versions(exam_id: str = "cat") -> dict[int, dict[str, Any]] | None:
    """The exam's versions keyed by year (None if its config file is unavailable)."""
    exam = exam_config(exam_id)
    if exam is None:
        return None
    try:
        return {v["year"]: v for v in exam.get("versions") or [] if isinstance(v.get("year"), int)}
    except (KeyError, TypeError, AttributeError):
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


def _has_rule(version: dict[str, Any], qtype: str, section: str) -> bool:
    """Whether the version marks ``qtype`` questions of ``section`` (rules may be limited to sections)."""
    for rule in version.get("marking") or []:
        if isinstance(rule, dict) and rule.get("type") == qtype:
            limited = rule.get("sections")
            if not limited or section in limited:
                return True
    return False


# ---------------------------------------------------------------- per-item checks
# Shared by ``build_paper_docs`` (import script, Admin import) and the Admin authoring
# endpoints (api/mba/authoring.py), so a paper built in the Admin panel obeys exactly the
# same rules as one imported from JSON. Each check appends problems to ``errors``.
def check_paper(paper: Any, errors: list[str], warnings: list[str]) -> dict[str, Any] | None:
    """Paper header -> context ``{id, examId, title, year, slot, examVersionYear, source, version}``.

    Returns None (with ``errors``) when the id/years are unusable; title/source/version
    problems are appended to ``errors`` but a context is still returned.
    """
    if not isinstance(paper, dict):
        errors.append("paper: object is required")
        return None
    before = len(errors)
    _unknown("paper", paper, PAPER_KEYS, errors)
    exam_id = paper.get("examId", "cat")
    year, slot, version_year = paper.get("year"), paper.get("slot"), paper.get("examVersionYear")
    if exam_id != "cat" and (not isinstance(exam_id, str) or exam_config(exam_id) is None):
        errors.append(f"paper.examId must be 'cat' or an exam with a config in {EXAMS_CONFIG_DIR.name}/ (got {exam_id!r})")
    for name, value in (("year", year), ("slot", slot), ("examVersionYear", version_year)):
        if not _opt_int(value):
            errors.append(f"paper.{name} must be an integer or null")
    if version_year is None and isinstance(year, int):
        version_year = year
    if version_year is None:
        errors.append("paper.examVersionYear is required (the exam pattern/marking year this paper follows)")
    paper_id = paper.get("id")
    if paper_id is None and exam_id == "cat" and isinstance(year, int) and isinstance(slot, int):
        paper_id = f"cat-{year}-slot{slot}"
    if not isinstance(paper_id, str) or not PAPER_ID_RE.match(paper_id):
        errors.append(f"paper.id is required and must match {PAPER_ID_RE.pattern}")
    if len(errors) > before:
        return None
    title = paper.get("title")
    if not _nonempty(title):
        title = f"CAT {year} Slot {slot}" if exam_id == "cat" and isinstance(year, int) and isinstance(slot, int) else None
    if not _nonempty(title):
        errors.append("paper.title is required")
    paper_source = _source("paper", paper.get("source"), errors, None)
    versions = exam_versions(exam_id)
    version = None
    if versions is not None:
        version = versions.get(version_year)
        if version is None:
            errors.append(f"paper.examVersionYear {version_year} is not a version in {exam_file(exam_id).name} ({sorted(versions)})")
    else:
        warnings.append(f"{exam_file(exam_id)} not found; examVersionYear {version_year} not checked")
    return {"id": paper_id, "examId": exam_id, "title": title, "year": year, "slot": slot,
            "examVersionYear": version_year, "source": paper_source, "version": version}


def check_set(item: Any, where: str, errors: list[str], paper_id: str, exam_id: str = "cat") -> dict[str, Any] | None:
    """One ``sets[]`` entry -> set document (without status). None when the key is unusable."""
    if not isinstance(item, dict):
        errors.append(f"{where}: must be an object")
        return None
    _unknown(where, item, SET_KEYS, errors)
    key = item.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        errors.append(f"{where}: key must match {KEY_RE.pattern}")
        return None
    where = f"set {key}"
    if item.get("kind") not in SET_KINDS:
        errors.append(f"{where}: kind must be one of {sorted(SET_KINDS)}")
    allowed = section_ids(exam_id)
    if item.get("section") not in allowed:
        errors.append(f"{where}: section must be one of {list(allowed)}")
    if not _nonempty(item.get("contentHtml")):
        errors.append(f"{where}: contentHtml is required")
    images = item.get("images")
    if images is not None and (not isinstance(images, list) or not all(_is_url(img) for img in images)):
        errors.append(f"{where}: images must be a list of http(s) URLs")
    return {
        "id": f"{paper_id}-{key.lower()}", "key": key, "examId": exam_id, "paperId": paper_id,
        "section": item.get("section"), "kind": item.get("kind"),
        "title": item.get("title") if _nonempty(item.get("title")) else None,
        "contentHtml": item.get("contentHtml"), "images": images or [],
    }


def check_question(
    q: Any, where: str, errors: list[str], warnings: list[str], paper: dict[str, Any], set_docs: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """One ``questions[]`` entry -> question document (without status/number ordering).

    ``paper`` is the ``check_paper`` context; ``set_docs`` maps set key -> set document
    (needs ``id`` and ``section``). Returns None when the key or section is unusable.
    """
    if not isinstance(q, dict):
        errors.append(f"{where}: must be an object")
        return None
    _unknown(where, q, QUESTION_KEYS, errors)
    key, section, qtype = q.get("key"), q.get("section"), q.get("type")
    if not isinstance(key, str) or not KEY_RE.match(key):
        errors.append(f"{where}: key must match {KEY_RE.pattern} (e.g. 'QA-01')")
        return None
    where = f"question {key}"
    allowed = section_ids(paper.get("examId") or "cat")
    if section not in allowed:
        errors.append(f"{where}: section must be one of {list(allowed)}")
        return None
    number = q.get("number")
    if number is not None and (not isinstance(number, int) or isinstance(number, bool) or number < 1):
        errors.append(f"{where}: number must be a positive integer")
    if qtype not in ("MCQ", "TITA"):
        errors.append(f"{where}: type must be MCQ or TITA")
    elif paper.get("version") and not _has_rule(paper["version"], qtype, section):
        errors.append(f"{where}: the {paper.get('examId')} {paper.get('examVersionYear')} pattern has no marking rule for {qtype} in {section}")
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
    if q.get("difficulty") is not None and q.get("difficulty") not in DIFFICULTIES:
        errors.append(f"{where}: difficulty must be one of {sorted(DIFFICULTIES)}")
    for text_field in ("solutionHtml", "topic", "subtopic"):
        if q.get(text_field) is not None and not isinstance(q.get(text_field), str):
            errors.append(f"{where}: {text_field} must be a string")
    if not _nonempty(q.get("solutionHtml")):
        warnings.append(f"{where}: no solutionHtml")
    approaches = q.get("alternativeApproaches")
    if approaches is not None:
        if not isinstance(approaches, list) or len(approaches) > MAX_APPROACHES or not all(
                _nonempty(a) and len(a) <= APPROACH_MAX_CHARS for a in approaches):
            errors.append(f"{where}: alternativeApproaches must be a list of at most {MAX_APPROACHES} non-empty HTML strings")
            approaches = None
    video = q.get("videoUrl")
    if video is not None and not (isinstance(video, str) and len(video) <= VIDEO_URL_MAX and VIDEO_URL_RE.match(video.strip())):
        errors.append(f"{where}: videoUrl must be an https:// link (e.g. a YouTube video)")
        video = None
    source = _source(where, q.get("source"), errors, (paper.get("source") or {}).get("title"))
    paper_id = paper["id"]
    return {
        "id": f"{paper_id}-{key.lower()}", "key": key, "examId": paper["examId"], "paperId": paper_id,
        "examVersionYear": paper["examVersionYear"], "year": paper["year"], "slot": paper["slot"], "section": section,
        "number": number, "type": qtype,
        "stemHtml": q.get("stemHtml"), "options": options, "setId": set_id,
        "topic": q.get("topic") or None, "subtopic": q.get("subtopic") or None,
        "difficulty": q.get("difficulty"), "correctAnswer": answer.strip() if isinstance(answer, str) else None,
        "solutionHtml": q.get("solutionHtml") or None,
        "alternativeApproaches": list(approaches) if approaches else None,
        "videoUrl": video.strip() if isinstance(video, str) and video.strip() else None, "source": source,
    }


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
    if not isinstance(raw.get("paper"), dict):
        raise PaperFormatError(["paper: object is required"])
    paper = check_paper(raw["paper"], errors, warnings)
    if paper is None:
        raise PaperFormatError(errors)
    paper_id, version, version_year = paper["id"], paper["version"], paper["examVersionYear"]

    # Sets
    sets_raw = raw.get("sets") or []
    if not isinstance(sets_raw, list):
        errors.append("sets must be a list")
        sets_raw = []
    set_docs: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(sets_raw):
        doc = check_set(item, f"sets[{i}]", errors, paper_id, paper["examId"])
        if doc is None:
            continue
        if doc["key"] in set_docs:
            errors.append(f"set {doc['key']}: duplicate key")
        set_docs[doc["key"]] = {**doc, "status": status}

    # Questions
    questions_raw = raw.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        errors.append("questions must be a non-empty list")
        questions_raw = []
    question_docs: list[dict[str, Any]] = []
    keys: set[str] = set()
    used_sets: set[str] = set()
    for i, q in enumerate(questions_raw):
        if isinstance(q, dict) and isinstance(q.get("key"), str) and KEY_RE.match(q["key"]):
            key = q["key"]
            if key.lower() in keys:
                errors.append(f"question {key}: duplicate key")
            keys.add(key.lower())
        doc = check_question(q, f"questions[{i}]", errors, warnings, paper, set_docs)
        if doc is None:
            continue
        if q.get("setKey") is not None and doc["setId"] is not None:
            used_sets.add(q["setKey"])
        question_docs.append({**doc, "status": status})

    for key in set_docs:
        if key not in used_sets:
            warnings.append(f"set '{key}' is not used by any question")

    # Number = order within section (explicit numbers, when given, must be 1..n without gaps).
    sections = []
    for section in section_ids(paper["examId"]):
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
            exam_name = "CAT" if paper["examId"] == "cat" else paper["examId"].upper()
            warnings.append(f"{section}: {len(docs)} questions; the {version_year} {exam_name} pattern has {expected}")
    if errors:
        raise PaperFormatError(errors)

    paper_doc = {
        "id": paper_id, "examId": paper["examId"], "title": paper["title"], "examVersionYear": version_year,
        "year": paper["year"], "slot": paper["slot"], "source": paper["source"], "sections": sections,
        "questionCount": len(question_docs), "status": status,
    }
    return paper_doc, list(set_docs.values()), question_docs, warnings


# ---------------------------------------------------------------- stored docs -> content
def _source_input(source: Any) -> Any:
    if not isinstance(source, dict):
        return source
    return {k: v for k, v in source.items() if k in SOURCE_KEYS and v is not None}


def set_input(doc: dict[str, Any]) -> dict[str, Any]:
    """A stored ``mbaQuestionSets`` document as a ``sets[]`` entry of the content format."""
    out = {k: doc.get(k) for k in ("key", "kind", "section", "contentHtml")}
    if _nonempty(doc.get("title")):
        out["title"] = doc["title"]
    if doc.get("images"):
        out["images"] = doc["images"]
    return out


def question_input(doc: dict[str, Any], set_keys: dict[str, str]) -> dict[str, Any]:
    """A stored ``mbaQuestions`` document as a ``questions[]`` entry (``set_keys``: set id -> key)."""
    out: dict[str, Any] = {k: doc.get(k) for k in ("key", "section", "number", "type", "stemHtml")}
    if doc.get("type") != "TITA" or doc.get("options"):
        out["options"] = doc.get("options")
    out["answer"] = doc.get("correctAnswer")
    if doc.get("setId"):
        out["setKey"] = set_keys.get(doc["setId"], doc["setId"])
    for name in ("solutionHtml", "alternativeApproaches", "videoUrl", "topic", "subtopic", "difficulty"):
        if doc.get(name) is not None:
            out[name] = doc[name]
    out["source"] = _source_input(doc.get("source"))
    return out


def content_from_docs(paper: dict[str, Any], sets: list[dict[str, Any]], questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Stored paper + its sets + its questions (in paper order) -> the importable content format."""
    set_keys = {s["id"]: s.get("key") for s in sets if s.get("id")}
    header = {k: paper.get(k) for k in ("id", "examId", "title", "examVersionYear", "year", "slot")}
    header["source"] = _source_input(paper.get("source"))
    return {
        "paper": {k: v for k, v in header.items() if v is not None},
        "sets": [set_input(s) for s in sets],
        "questions": [question_input(q, set_keys) for q in questions],
    }
