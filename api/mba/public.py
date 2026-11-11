"""The ONLY place stored questions are turned into API payloads.

``public_question`` never includes the answer key or solution. ``reveal`` is the
single place those fields are read for output; it is called only by practice
answers (after the student answered) and by submitted attempt results.
"""

from __future__ import annotations

from typing import Any

from .models import SECTION_IDS

SECRET_FIELDS = frozenset({"correctAnswer", "solutionHtml"})

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
    return {
        "id": str(data.get("id")),
        "examId": "cat",
        "paperId": _str(data.get("paperId")),
        "section": data.get("section") if data.get("section") in SECTION_IDS else "VARC",
        "topic": _str(data.get("topic")),
        "subtopic": _str(data.get("subtopic")),
        "type": qtype,
        "stemHtml": data.get("stemHtml") if isinstance(data.get("stemHtml"), str) else "",
        "options": options,
        "setId": set_id,
        "set": public_set((sets or {}).get(set_id)) if set_id else None,
        "difficulty": data.get("difficulty") if data.get("difficulty") in _DIFFICULTIES else None,
        "year": _int(data.get("year")),
        "slot": _int(data.get("slot")),
        "source": public_source(data.get("source")),
    }


def reveal(raw: dict[str, Any], is_correct: bool | None) -> dict[str, Any]:
    """QuestionReveal — only for answered practice questions and submitted results."""
    return {
        "correctAnswer": str(raw.get("correctAnswer") or ""),
        "solutionHtml": raw.get("solutionHtml") if isinstance(raw.get("solutionHtml"), str) else None,
        "isCorrect": is_correct,
    }
