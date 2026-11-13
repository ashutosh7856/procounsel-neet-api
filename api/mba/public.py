"""The ONLY place stored questions are turned into API payloads.

``public_question`` never includes the answer key or solution. ``reveal`` is the
single place those fields are read for output; it is called only by practice
answers (after the student answered) and by submitted attempt results.
"""

from __future__ import annotations

import re
from typing import Any

from .models import SECTION_IDS

_SECTION_RE = re.compile(r"^[A-Z][A-Z0-9]{0,11}$")  # models.ExamSectionId

SECRET_FIELDS = frozenset({"correctAnswer", "solutionHtml", "alternativeApproaches", "videoUrl"})

_SOURCE_KINDS = {"official", "licensed", "faculty", "original"}
_SET_KINDS = {"passage", "dilr_set", "data"}
_DIFFICULTIES = {"easy", "medium", "hard"}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def public_source(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get("kind") if raw.get("kind") in _SOURCE_KINDS else "original"
    return {
        "kind": kind,
        "title": _str(raw.get("title")) or "",
        "url": _str(raw.get("url")),
        "year": _int(raw.get("year")),
        "retrievedAt": _str(raw.get("retrievedAt")),
    }


def public_set(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    images = raw.get("images")
    return {
        "id": str(raw.get("id")),
        "kind": raw.get("kind") if raw.get("kind") in _SET_KINDS else "passage",
        "title": _str(raw.get("title")),
        "contentHtml": raw.get("contentHtml") if isinstance(raw.get("contentHtml"), str) else "",
        "images": [img for img in images if isinstance(img, str)] if isinstance(images, list) else None,
    }


def _section(data: dict[str, Any]) -> str:
    """CAT questions keep the old VARC fallback; other exams' section ids pass through (validated on import)."""
    section = data.get("section")
    if (data.get("examId") or "cat") == "cat":
        return section if section in SECTION_IDS else "VARC"
    return section if isinstance(section, str) and _SECTION_RE.match(section) else "GEN"


def public_question(raw: dict[str, Any], sets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Whitelisted, answer-free view of a stored question (QuestionPublic)."""
    data = {key: value for key, value in raw.items() if key not in SECRET_FIELDS}
    qtype = "TITA" if data.get("type") == "TITA" else "MCQ"
    options = None
    if qtype == "MCQ" and isinstance(data.get("options"), list):
        options = [
            {"id": str(opt.get("id")), "textHtml": opt.get("textHtml") if isinstance(opt.get("textHtml"), str) else ""}
            for opt in data["options"]
            if isinstance(opt, dict) and opt.get("id") is not None
        ]
    set_id = _str(data.get("setId"))
    source = public_source(data.get("source"))
    year, slot = _int(data.get("year")), _int(data.get("slot"))
    return {
        "id": str(data.get("id")),
        "examId": _str(data.get("examId")) or "cat",
        "paperId": _str(data.get("paperId")),
        "section": _section(data),
        "topic": _str(data.get("topic")),
        "subtopic": _str(data.get("subtopic")),
        "type": qtype,
        "stemHtml": data.get("stemHtml") if isinstance(data.get("stemHtml"), str) else "",
        "options": options,
        "setId": set_id,
        "set": public_set((sets or {}).get(set_id)) if set_id else None,
        "difficulty": data.get("difficulty") if data.get("difficulty") in _DIFFICULTIES else None,
        "year": year,
        "slot": slot,
        "source": source,
        # Same rule as exams.is_pyq: a question of an actual past CAT paper.
        "isPyq": source["kind"] == "official" and year is not None and slot is not None,
    }


def approaches(raw: dict[str, Any]) -> list[str] | None:
    """Alternative solution approaches (HTML strings), or None."""
    value = raw.get("alternativeApproaches")
    items = [a for a in value if _str(a)] if isinstance(value, list) else []
    return items or None


def video_url(raw: dict[str, Any]) -> str | None:
    """The video solution link — only ever an https URL (validated on import/edit; re-checked here)."""
    value = _str(raw.get("videoUrl"))
    return value.strip() if value and value.strip().startswith("https://") else None


def reveal(raw: dict[str, Any], is_correct: bool | None) -> dict[str, Any]:
    """QuestionReveal — only for answered practice questions and submitted results."""
    return {
        "correctAnswer": str(raw.get("correctAnswer") or ""),
        "solutionHtml": raw.get("solutionHtml") if isinstance(raw.get("solutionHtml"), str) else None,
        "alternativeApproaches": approaches(raw),
        "videoUrl": video_url(raw),
        "isCorrect": is_correct,
    }
