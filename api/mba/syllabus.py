"""CAT syllabus + lesson progress (LMS-lite): ``/syllabus``, ``/me/syllabus/*`` (contract: docs/mba-api.md → "Syllabus").

The hierarchy section → topic → subtopic and the concept notes come from the curated
``data/mba/syllabus/cat.json``. Topics carry the question bank's own topic labels
(``bankTopics``); each subtopic lists lowercase ``match`` keywords that map the bank's free-text
subtopics onto it: a bank subtopic belongs to the syllabus subtopic whose keyword appears
earliest in it (ties: the longer keyword). Bank subtopics that match nothing still count
towards their topic. Question counts are live from the published bank (CAT only).

Per student, per subtopic, ``mbaSyllabusProgress/{userId}_{subtopicId}`` holds the
"completed" mark, a bookmark and a private note. A doc is deleted once all three are cleared.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from .analysis import practice_href
from .deps import student
from .store import Bank, get_bank, iso, occ_update, query_eq, utcnow

router = APIRouter()

PROGRESS = "mbaSyllabusProgress"
SYLLABUS_FILE = Path(__file__).resolve().parents[2] / "data" / "mba" / "syllabus" / "cat.json"
NOTE_MAX = 2000
DRILL_PATH = "/mba/mocks/build"


# ---------------------------------------------------------------- models
class SyllabusSubtopic(BaseModel):
    id: str
    title: str
    notes: list[str]
    questionCount: int
    bankSubtopics: list[str]  # question-bank subtopic labels mapped here (used by the drill link)
    practiceHref: str
    drillHref: str | None
    completed: bool
    completedAt: str | None
    bookmarked: bool
    note: str | None


class SyllabusTopic(BaseModel):
    id: str
    title: str
    questionCount: int
    practiceHref: str
    completed: int
    total: int
    subtopics: list[SyllabusSubtopic]


class SyllabusSection(BaseModel):
    id: Literal["VARC", "DILR", "QA"]
    title: str
    completed: int
    total: int
    topics: list[SyllabusTopic]


class SyllabusProgress(BaseModel):
    completed: int
    total: int
    bookmarked: int


class SyllabusResponse(BaseModel):
    examId: str
    version: int
    sections: list[SyllabusSection]
    progress: SyllabusProgress


class SyllabusItemPatch(BaseModel):
    """Only the fields sent are changed; ``note: null`` (or blank) clears the note."""

    model_config = {"extra": "forbid"}

    completed: bool | None = None
    bookmarked: bool | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class SyllabusItemState(BaseModel):
    subtopicId: str
    completed: bool
    completedAt: str | None
    bookmarked: bool
    note: str | None
    updatedAt: str | None


# ---------------------------------------------------------------- data
@lru_cache(maxsize=1)
def load_syllabus() -> dict[str, Any]:
    return json.loads(SYLLABUS_FILE.read_text(encoding="utf-8"))


def subtopic_index() -> dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """subtopicId -> (section, topic, subtopic)."""
    return {
        sub["id"]: (section, topic, sub)
        for section in load_syllabus()["sections"]
        for topic in section["topics"]
        for sub in topic["subtopics"]
    }


def match_subtopic(topic: dict[str, Any], bank_subtopic: str) -> str | None:
    """The syllabus subtopic id a bank subtopic label belongs to (earliest keyword, then longest), or None."""
    label = bank_subtopic.strip().lower()
    best: tuple[int, int, str] | None = None
    for sub in topic["subtopics"]:
        for keyword in sub.get("match") or []:
            pos = label.find(keyword)
            if pos >= 0 and (best is None or (pos, -len(keyword)) < best[:2]):
                best = (pos, -len(keyword), sub["id"])
    return best[2] if best else None


def bank_map(bank: Bank) -> tuple[dict[str, int], dict[str, int], dict[str, set[str]]]:
    """(questions per syllabus subtopic, questions per syllabus topic, bank subtopic labels per syllabus subtopic)."""
    topics_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for section in load_syllabus()["sections"]:
        for topic in section["topics"]:
            for bank_topic in topic.get("bankTopics") or []:
                topics_by_key[(section["id"], bank_topic.strip().lower())] = topic
    per_sub: dict[str, int] = {}
    per_topic: dict[str, int] = {}
    labels: dict[str, set[str]] = {}
    cache: dict[tuple[str, str], str | None] = {}
    for question in bank.questions.values():
        if (question.get("examId") or "cat") != "cat" or not isinstance(question.get("topic"), str):
            continue
        topic = topics_by_key.get((str(question.get("section")), question["topic"].strip().lower()))
        if topic is None:
            continue
        per_topic[topic["id"]] = per_topic.get(topic["id"], 0) + 1
        label = question.get("subtopic").strip() if isinstance(question.get("subtopic"), str) else ""
        if not label:
            continue
        key = (topic["id"], label)
        if key not in cache:
            cache[key] = match_subtopic(topic, label)
        sub_id = cache[key]
        if sub_id:
            per_sub[sub_id] = per_sub.get(sub_id, 0) + 1
            labels.setdefault(sub_id, set()).add(label)
    return per_sub, per_topic, labels


def drill_href(section: str, bank_topic: str, labels: list[str]) -> str:
    params = [("section", section), ("topic", bank_topic), *(("subtopic", label) for label in labels)]
    return f"{DRILL_PATH}?{urlencode(params)}"


def progress_id(user_id: str, subtopic_id: str) -> str:
    return f"{user_id}_{subtopic_id}"


def item_state(subtopic_id: str, doc: dict[str, Any] | None) -> dict[str, Any]:
    doc = doc or {}
    note = doc.get("note") if isinstance(doc.get("note"), str) and doc["note"].strip() else None
    return {
        "subtopicId": subtopic_id,
        "completed": bool(doc.get("completed")),
        "completedAt": doc.get("completedAt") if doc.get("completed") and isinstance(doc.get("completedAt"), str) else None,
        "bookmarked": bool(doc.get("bookmarked")),
        "note": note,
        "updatedAt": doc.get("updatedAt") if isinstance(doc.get("updatedAt"), str) else None,
    }


def build_syllabus(bank: Bank, progress: dict[str, dict[str, Any]]) -> dict[str, Any]:
    data = load_syllabus()
    per_sub, per_topic, labels = bank_map(bank)
    sections = []
    for section in data["sections"]:
        topics = []
        for topic in section["topics"]:
            bank_topic = (topic.get("bankTopics") or [topic["title"]])[0]
            subs = []
            for sub in topic["subtopics"]:
                state = item_state(sub["id"], progress.get(sub["id"]))
                mapped = sorted(labels.get(sub["id"], set()), key=str.lower)
                subs.append({
                    "id": sub["id"], "title": sub["title"], "notes": list(sub.get("notes") or []),
                    "questionCount": per_sub.get(sub["id"], 0), "bankSubtopics": mapped,
                    "practiceHref": practice_href(section["id"], bank_topic),
                    "drillHref": drill_href(section["id"], bank_topic, mapped) if mapped else None,
                    **{k: state[k] for k in ("completed", "completedAt", "bookmarked", "note")},
                })
            topics.append({
                "id": topic["id"], "title": topic["title"], "questionCount": per_topic.get(topic["id"], 0),
                "practiceHref": practice_href(section["id"], bank_topic),
                "completed": sum(1 for s in subs if s["completed"]), "total": len(subs), "subtopics": subs,
            })
        sections.append({
            "id": section["id"], "title": section["title"],
            "completed": sum(t["completed"] for t in topics), "total": sum(t["total"] for t in topics), "topics": topics,
        })
    all_subs = [s for sec in sections for t in sec["topics"] for s in t["subtopics"]]
    return {
        "examId": data.get("examId", "cat"), "version": int(data.get("version") or 1), "sections": sections,
        "progress": {"completed": sum(1 for s in all_subs if s["completed"]), "total": len(all_subs),
                     "bookmarked": sum(1 for s in all_subs if s["bookmarked"])},
    }


def user_progress(db: SafeFirestore, user_id: str) -> dict[str, dict[str, Any]]:
    """subtopicId -> progress doc of this student."""
    return {doc["subtopicId"]: doc for _id, doc in query_eq(db, PROGRESS, "userId", user_id) if isinstance(doc.get("subtopicId"), str)}


# ---------------------------------------------------------------- routes
@router.get("/syllabus", response_model=SyllabusResponse)
def get_syllabus(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return build_syllabus(get_bank(db), user_progress(db, user.user_id))


@router.patch("/me/syllabus/{subtopic_id}", response_model=SyllabusItemState)
def patch_syllabus_item(subtopic_id: str, body: SyllabusItemPatch, user: CurrentUser = Depends(student),
                        db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    located = subtopic_index().get(subtopic_id)
    if located is None:
        raise HTTPException(404, "Unknown syllabus subtopic.")
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(422, "Nothing to change.")
    if ("completed" in sent and body.completed is None) or ("bookmarked" in sent and body.bookmarked is None):
        raise HTTPException(422, "completed and bookmarked must be true or false.")
    section = located[0]["id"]
    now = iso(utcnow())
    doc_id = progress_id(user.user_id, subtopic_id)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        doc = dict(current or {})
        if "completed" in sent:
            if body.completed and not doc.get("completed"):
                doc["completedAt"] = now
            elif not body.completed:
                doc["completedAt"] = None
            doc["completed"] = bool(body.completed)
        if "bookmarked" in sent:
            doc["bookmarked"] = bool(body.bookmarked)
        if "note" in sent:
            doc["note"] = body.note.strip() if body.note and body.note.strip() else None
        doc.update({"userId": user.user_id, "examId": "cat", "subtopicId": subtopic_id, "section": section, "updatedAt": now})
        doc.setdefault("createdAt", now)
        return doc, doc

    doc = occ_update(db, PROGRESS, doc_id, mutate)
    if not doc.get("completed") and not doc.get("bookmarked") and not doc.get("note"):
        db.collection(PROGRESS).document(doc_id).delete(timeout=DB_TIMEOUT)
        return item_state(subtopic_id, None)
    return item_state(subtopic_id, doc)
