"""Doubts and study groups (contract: docs/mba-api.md → "Community: doubts, study groups, events, help").

One thread model for both:

* **Question doubts** — ``scope: "question"``: one board per question. Only students who have seen that
  question's answer (same rule as question reports) may read or post, so threads never spoil a question.
* **Study-group posts** — ``scope: "group"``: the discussion board of a group such as "CAT 2026"
  (``{exam}-{year}``). Only members read or post. Membership: ``mbaGroupMembers/{userId}`` (one group).

``mbaDoubts/{id}`` holds the thread and its replies (embedded, at most ``MAX_REPLIES``):
``{ scope, questionId, groupId, paperId, section, number, userId, authorName, text, status, hidden, hiddenReason,
upvoters, reports, replies: [...], participantIds, replyCount, facultyAnswered, lastReplyAt, createdAt, updatedAt }``.
Faculty/admin replies are always ``verified``; faculty can also verify a student's reply. Students never see
userIds, only display names (leaderboard name, else first name + last initial).

Moderation: a text filter (abusive words, links, e-mail addresses, phone numbers, "message me on WhatsApp"),
per-student daily limits + a short cooldown in ``mbaCommunityUsage/{userId}_{date}``, student reports (3
distinct reports auto-hide a post until a moderator looks), admin hide/unhide.

Escalation: an open question doubt with no faculty reply after ``ESCALATE_AFTER_HOURS`` shows in the Admin
"Doubts" queue (``GET /admin/doubts?queue=escalated``), where faculty answer it.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentAdmin, CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from . import leaderboard
from .admin_roles import require_mba
from .deps import student
from .models import EXAM_IDS, SECTION_IDS, SectionId
from .profile import load_profile
from .reports import _check_revealed, _preview
from .store import get_bank, get_doc, iso, local_date, occ_update, parse_iso, query_eq, stream_all, utcnow

router = APIRouter()

DOUBTS = "mbaDoubts"
MEMBERS = "mbaGroupMembers"
USAGE = "mbaCommunityUsage"

# Faculty answer doubts, support triages reports (admin_roles.py).
faculty_admin = require_mba("content", "support")

TEXT_MIN, TEXT_MAX = 5, 2000
MAX_REPLIES = 100
AUTO_HIDE_REPORTS = 3          # distinct student reports that hide a post until a moderator reviews it
ESCALATE_AFTER_HOURS = 24
NOTIFY_WINDOW_DAYS = 14
LIMITS = {"threads": 10, "replies": 50, "reports": 20, "tickets": 5, "ticketMessages": 30}  # per student per IST day
COOLDOWN_SECONDS = 15          # between two posts (thread, reply, ticket message)
GROUP_YEARS_AHEAD = 2
EXAM_LABEL = {"cat": "CAT", "xat": "XAT", "snap": "SNAP", "nmat": "NMAT", "cmat": "CMAT", "mat": "MAT", "gmat": "GMAT",
              "mah-mba-cet": "MAH-MBA-CET"}
GROUP_ID = re.compile(r"^(" + "|".join(re.escape(e) for e in EXAM_IDS) + r")-(20\d\d)$")

Scope = Literal["question", "group"]
DoubtStatus = Literal["open", "resolved"]
AdminQueue = Literal["escalated", "unanswered", "reported", "hidden", "all"]

# ---------------------------------------------------------------- text filter
# Whole words only. The leaderboard's name list minus words that are normal in maths/DI ("BC" is a side, "sex ratio").
_ABUSIVE = leaderboard._BLOCKED - {"mc", "bc", "sex"}
_URL = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|in|co|org|net|io|me|ly|gg|xyz|app|link|info|site|online|page)\b|\bt\.me\b|\bwa\.me\b)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_DIGIT_RUN = re.compile(r"(?:\+?\d[\s\-.()]{0,2}){10,}")
_CONTACT = re.compile(r"\b(whats\s?app|telegram|insta(gram)?|snapchat|discord|dm me|ping me|call me|text me|contact me)\b", re.I)


def text_problem(text: str, allow_links: bool = False) -> str | None:
    """Why ``text`` can't be posted, or None. Faculty may post links; nobody may post abuse."""
    words = {re.sub(r"[^a-z]", "", w) for w in text.lower().split()}
    if words & _ABUSIVE:
        return "Please keep it respectful. Your post has words we don't allow."
    if allow_links:
        return None
    if _EMAIL.search(text):
        return "Please don't share e-mail addresses. Keep the discussion here so everyone can learn from it."
    for run in _DIGIT_RUN.findall(text):
        digits = re.sub(r"\D", "", run)
        if re.search(r"(?:91)?[6-9]\d{9}", digits):
            return "Please don't share phone numbers. Keep the discussion here so everyone can learn from it."
    if _URL.search(text):
        return "Links aren't allowed in posts. Describe the idea in your own words instead."
    if _CONTACT.search(text):
        return "Please keep the discussion here rather than moving it to other apps."
    return None


def clean_text(raw: str, allow_links: bool = False) -> str:
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", (raw or "").replace("\r\n", "\n"))).strip()
    if len(text) < TEXT_MIN:
        raise HTTPException(422, f"Write at least {TEXT_MIN} characters.")
    problem = text_problem(text, allow_links)
    if problem:
        raise HTTPException(422, problem)
    return text


# ---------------------------------------------------------------- rate limits
def consume(db: SafeFirestore, user_id: str, kind: str, cooldown: bool = True) -> None:
    """Count one ``kind`` action for today (IST); 429 over the daily limit or inside the cooldown."""
    now = utcnow()
    today = local_date(now).isoformat()
    limit = LIMITS[kind]

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], None]:
        doc = dict(current or {"userId": user_id, "date": today})
        used = int(doc.get(kind) or 0)
        if used >= limit:
            raise HTTPException(429, f"You've reached today's limit ({limit}). Please try again tomorrow.")
        last = parse_iso(doc.get("lastPostAt"))
        if cooldown and last and (now - last).total_seconds() < COOLDOWN_SECONDS:
            raise HTTPException(429, "You're posting very fast. Please wait a few seconds and try again.")
        doc[kind] = used + 1
        if cooldown:
            doc["lastPostAt"] = iso(now)
        doc["updatedAt"] = iso(now)
        return doc, None

    occ_update(db, USAGE, f"{user_id}_{today}", mutate)


# ---------------------------------------------------------------- models
class PostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=TEXT_MAX)


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: DoubtStatus


class VoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    up: bool


class ReportPostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["spam", "abusive", "off_platform", "wrong", "other"]


class DoubtReply(BaseModel):
    id: str
    by: Literal["student", "faculty"]
    authorName: str
    isYours: bool
    text: str
    verified: bool
    upvotes: int
    youUpvoted: bool
    youReported: bool
    hidden: bool  # only ever true on the caller's own reply (hidden replies of others are left out)
    createdAt: str


class DoubtThread(BaseModel):
    id: str
    scope: Scope
    questionId: str | None
    groupId: str | None
    authorName: str
    isYours: bool
    text: str
    status: DoubtStatus
    hidden: bool  # only ever true on the caller's own thread
    upvotes: int
    youUpvoted: bool
    youReported: bool
    replyCount: int
    facultyAnswered: bool
    createdAt: str
    lastActivityAt: str


class DoubtDetail(DoubtThread):
    questionPreview: str | None  # plain text, ≤160 chars (question doubts)
    replies: list[DoubtReply]


class ThreadsResponse(BaseModel):
    threads: list[DoubtThread]


class QuestionContext(BaseModel):
    id: str
    section: SectionId | None
    number: int | None
    stemHtml: str


class QuestionThreadsResponse(ThreadsResponse):
    question: QuestionContext


class GroupInfo(BaseModel):
    id: str
    label: str
    exam: str
    year: int
    members: int


class GroupsResponse(BaseModel):
    groups: list[GroupInfo]
    mine: GroupInfo | None
    suggestedId: str | None


class JoinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groupId: str = Field(min_length=6, max_length=20)


class GroupBoard(leaderboard.WeeklyBoard):
    groupId: str
    members: int


class AdminReportEntry(BaseModel):
    reason: str
    at: str


class AdminReply(BaseModel):
    id: str
    by: Literal["student", "faculty"]
    authorName: str
    userId: str | None
    adminId: str | None
    text: str
    verified: bool
    hidden: bool
    hiddenReason: str | None
    upvotes: int
    reports: list[AdminReportEntry]
    createdAt: str


class AdminDoubt(BaseModel):
    id: str
    scope: Scope
    questionId: str | None
    groupId: str | None
    paperId: str | None
    section: SectionId | None
    number: int | None
    stemPreview: str
    authorName: str
    userId: str | None
    text: str
    status: DoubtStatus
    hidden: bool
    hiddenReason: str | None
    upvotes: int
    reports: list[AdminReportEntry]
    replyCount: int
    reportedReplies: int
    facultyAnswered: bool
    escalated: bool
    createdAt: str
    lastActivityAt: str


class AdminDoubtDetail(AdminDoubt):
    replies: list[AdminReply]


class AdminDoubtCounts(BaseModel):
    escalated: int
    unanswered: int
    reported: int
    hidden: int
    all: int


class AdminDoubtsResponse(BaseModel):
    doubts: list[AdminDoubt]
    counts: AdminDoubtCounts


class AdminDoubtPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool | None = None
    status: DoubtStatus | None = None
    clearReports: bool = False


class AdminReplyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool | None = None
    verified: bool | None = None
    clearReports: bool = False


# ---------------------------------------------------------------- helpers
def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _ids(value: Any) -> list[str]:
    return [v for v in value or [] if isinstance(v, str)]


def _reports(value: Any) -> list[dict[str, Any]]:
    return [r for r in value or [] if isinstance(r, dict)]


def display_name(db: SafeFirestore, user: CurrentUser) -> str:
    """The student's leaderboard name if they chose one, else first name + last initial."""
    prefs = get_doc(db, leaderboard.PREFS, user.user_id) or {}
    return leaderboard.clean_name(prefs.get("displayName")) or leaderboard.suggested_name(user)


def faculty_name(admin: CurrentAdmin) -> str:
    first = leaderboard.clean_name(str((admin.profile or {}).get("firstName") or "")).split(" ")[0]
    return first or "ProCounsel faculty"


def _status(doc: dict[str, Any]) -> str:
    return "resolved" if doc.get("status") == "resolved" else "open"


def _visible_replies(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in doc.get("replies") or [] if isinstance(r, dict) and not r.get("hidden")]


def _facts(replies: list[dict[str, Any]]) -> dict[str, Any]:
    """Denormalised counters, recomputed after every change to the replies."""
    visible = [r for r in replies if not r.get("hidden")]
    return {"replyCount": len(visible), "facultyAnswered": any(r.get("verified") for r in visible),
            "lastReplyAt": max((r.get("createdAt") or "" for r in visible), default=None)}


def _reply_out(reply: dict[str, Any], user_id: str) -> dict[str, Any]:
    return {
        "id": str(reply.get("id") or ""), "by": "faculty" if reply.get("by") == "faculty" else "student",
        "authorName": str(reply.get("authorName") or "Student"), "isYours": reply.get("userId") == user_id,
        "text": str(reply.get("text") or ""), "verified": reply.get("verified") is True,
        "upvotes": len(_ids(reply.get("upvoters"))), "youUpvoted": user_id in _ids(reply.get("upvoters")),
        "youReported": any(r.get("userId") == user_id for r in _reports(reply.get("reports"))),
        "hidden": reply.get("hidden") is True, "createdAt": str(reply.get("createdAt") or ""),
    }


def _thread_out(doc_id: str, doc: dict[str, Any], user_id: str, with_replies: bool = False) -> dict[str, Any]:
    out = {
        "id": doc_id, "scope": "group" if doc.get("scope") == "group" else "question",
        "questionId": _str(doc.get("questionId")), "groupId": _str(doc.get("groupId")),
        "authorName": str(doc.get("authorName") or "Student"), "isYours": doc.get("userId") == user_id,
        "text": str(doc.get("text") or ""), "status": _status(doc), "hidden": doc.get("hidden") is True,
        "upvotes": len(_ids(doc.get("upvoters"))), "youUpvoted": user_id in _ids(doc.get("upvoters")),
        "youReported": any(r.get("userId") == user_id for r in _reports(doc.get("reports"))),
        "replyCount": int(doc.get("replyCount") or 0), "facultyAnswered": doc.get("facultyAnswered") is True,
        "createdAt": str(doc.get("createdAt") or ""),
        "lastActivityAt": str(doc.get("lastReplyAt") or doc.get("createdAt") or ""),
    }
    if with_replies:
        out["questionPreview"] = _str(doc.get("stemPreview"))  # stored when the doubt was asked
        replies = [r for r in doc.get("replies") or [] if isinstance(r, dict) and (not r.get("hidden") or r.get("userId") == user_id)]
        replies.sort(key=lambda r: (not r.get("verified"), str(r.get("createdAt") or "")))
        out["replies"] = [_reply_out(r, user_id) for r in replies]
    return out


def _can_see(doc: dict[str, Any], user_id: str) -> bool:
    return not doc.get("hidden") or doc.get("userId") == user_id


def _list(rows: list[tuple[str, dict[str, Any]]], user_id: str) -> list[dict[str, Any]]:
    threads = [_thread_out(i, d, user_id) for i, d in rows if _can_see(d, user_id)]
    threads.sort(key=lambda t: t["lastActivityAt"], reverse=True)
    threads.sort(key=lambda t: (t["status"] == "resolved", -t["upvotes"]))
    return threads


def _new_thread(db: SafeFirestore, user: CurrentUser, text: str, **scope: Any) -> tuple[str, dict[str, Any]]:
    stamp = iso(utcnow())
    doc = {
        **scope, "userId": user.user_id, "authorName": display_name(db, user), "text": text, "status": "open",
        "resolvedAt": None, "hidden": False, "hiddenReason": None, "hiddenBy": None, "upvoters": [], "reports": [],
        "replies": [], "participantIds": [user.user_id], "replyCount": 0, "facultyAnswered": False, "lastReplyAt": None,
        "createdAt": stamp, "updatedAt": stamp,
    }
    doc_id = uuid.uuid4().hex
    db.collection(DOUBTS).document(doc_id).create(doc, timeout=DB_TIMEOUT)
    return doc_id, doc


def _membership(db: SafeFirestore, user_id: str) -> str | None:
    return _str((get_doc(db, MEMBERS, user_id) or {}).get("groupId"))


def _check_access(db: SafeFirestore, user: CurrentUser, doc: dict[str, Any]) -> None:
    """403 unless the student may read this thread (seen the question's answer / member of the group)."""
    if doc.get("scope") == "group":
        if _membership(db, user.user_id) != doc.get("groupId"):
            raise HTTPException(403, "Join this study group to see its discussion.")
    else:
        _check_revealed(db, user, str(doc.get("questionId") or ""))


def _load(db: SafeFirestore, user: CurrentUser, doubt_id: str) -> dict[str, Any]:
    doc = get_doc(db, DOUBTS, doubt_id)
    if doc is None or not _can_see(doc, user.user_id):
        raise HTTPException(404, "Doubt not found.")
    _check_access(db, user, doc)
    return doc


def _find_reply(doc: dict[str, Any], reply_id: str) -> tuple[list[dict[str, Any]], int]:
    replies = [dict(r) for r in doc.get("replies") or [] if isinstance(r, dict)]
    index = next((i for i, r in enumerate(replies) if r.get("id") == reply_id), -1)
    if index < 0:
        raise HTTPException(404, "Reply not found.")
    return replies, index


def _report_into(entries: list[dict[str, Any]], user_id: str, reason: str) -> tuple[list[dict[str, Any]], bool]:
    """Adds the student's report (one per student). Returns (entries, auto_hide)."""
    if any(r.get("userId") == user_id for r in entries):
        return entries, False
    entries = [*entries, {"userId": user_id, "reason": reason, "at": iso(utcnow())}]
    return entries, len({r.get("userId") for r in entries}) >= AUTO_HIDE_REPORTS


# ---------------------------------------------------------------- question doubts
@router.get("/questions/{question_id}/doubts", response_model=QuestionThreadsResponse)
def question_doubts(question_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    q = _check_revealed(db, user, question_id)
    number = q.get("number")
    context = {"id": question_id, "section": q.get("section") if q.get("section") in SECTION_IDS else None,
               "number": number if isinstance(number, int) and not isinstance(number, bool) else None,
               "stemHtml": str(q.get("stemHtml") or "")}
    return {"threads": _list(query_eq(db, DOUBTS, "questionId", question_id), user.user_id), "question": context}


@router.post("/questions/{question_id}/doubts", response_model=DoubtDetail, status_code=201)
def ask_doubt(question_id: str, body: PostInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    question = _check_revealed(db, user, question_id)
    text = clean_text(body.text)
    consume(db, user.user_id, "threads")
    doc_id, doc = _new_thread(db, user, text, scope="question", questionId=question_id, groupId=None,
                              paperId=question.get("paperId"), section=question.get("section"), number=question.get("number"),
                              stemPreview=_preview(question.get("stemHtml")))
    return _thread_out(doc_id, doc, user.user_id, with_replies=True)


@router.get("/me/doubts", response_model=ThreadsResponse)
def my_doubts(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """Threads the student started (question doubts and group posts), newest activity first."""
    threads = [_thread_out(i, d, user.user_id) for i, d in query_eq(db, DOUBTS, "userId", user.user_id)]
    threads.sort(key=lambda t: t["lastActivityAt"], reverse=True)
    return {"threads": threads}


# ---------------------------------------------------------------- one thread
@router.get("/doubts/{doubt_id}", response_model=DoubtDetail)
def get_doubt(doubt_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _thread_out(doubt_id, _load(db, user, doubt_id), user.user_id, with_replies=True)


@router.post("/doubts/{doubt_id}/replies", response_model=DoubtDetail, status_code=201)
def reply(doubt_id: str, body: PostInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _load(db, user, doubt_id)
    text = clean_text(body.text)
    consume(db, user.user_id, "replies")
    name = display_name(db, user)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None or current.get("hidden"):
            raise HTTPException(404, "Doubt not found.")
        replies = [r for r in current.get("replies") or [] if isinstance(r, dict)]
        if len(replies) >= MAX_REPLIES:
            raise HTTPException(409, "This thread is full. Ask a new doubt instead.")
        stamp = iso(utcnow())
        replies.append({"id": uuid.uuid4().hex[:12], "by": "student", "userId": user.user_id, "adminId": None, "authorName": name,
                        "text": text, "verified": False, "hidden": False, "hiddenReason": None, "upvoters": [], "reports": [],
                        "createdAt": stamp})
        participants = _ids(current.get("participantIds"))
        fields = {"replies": replies, **_facts(replies), "updatedAt": stamp,
                  "participantIds": participants if user.user_id in participants else [*participants, user.user_id]}
        return fields, {**current, **fields}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


@router.patch("/doubts/{doubt_id}", response_model=DoubtDetail)
def set_status(doubt_id: str, body: StatusInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """The author marks their doubt resolved (or reopens it)."""
    _load(db, user, doubt_id)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        if current.get("userId") != user.user_id:
            raise HTTPException(403, "Only the student who asked can mark this resolved.")
        if _status(current) == body.status:
            return None, current
        stamp = iso(utcnow())
        fields = {"status": body.status, "resolvedAt": stamp if body.status == "resolved" else None, "updatedAt": stamp}
        return fields, {**current, **fields}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


def _vote(doc: dict[str, Any], user_id: str, up: bool) -> list[str]:
    voters = _ids(doc.get("upvoters"))
    if up and user_id not in voters:
        voters.append(user_id)
    if not up:
        voters = [v for v in voters if v != user_id]
    return voters


@router.put("/doubts/{doubt_id}/vote", response_model=DoubtDetail)
def vote_thread(doubt_id: str, body: VoteInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _load(db, user, doubt_id)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        voters = _vote(current, user.user_id, body.up)
        if voters == _ids(current.get("upvoters")):
            return None, current
        return {"upvoters": voters}, {**current, "upvoters": voters}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


@router.put("/doubts/{doubt_id}/replies/{reply_id}/vote", response_model=DoubtDetail)
def vote_reply(doubt_id: str, reply_id: str, body: VoteInput, user: CurrentUser = Depends(student),
               db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _load(db, user, doubt_id)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        replies, i = _find_reply(current, reply_id)
        if replies[i].get("hidden") and replies[i].get("userId") != user.user_id:
            raise HTTPException(404, "Reply not found.")
        voters = _vote(replies[i], user.user_id, body.up)
        if voters == _ids(replies[i].get("upvoters")):
            return None, current
        replies[i]["upvoters"] = voters
        return {"replies": replies}, {**current, "replies": replies}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


@router.post("/doubts/{doubt_id}/report", response_model=DoubtDetail)
def report_thread(doubt_id: str, body: ReportPostInput, user: CurrentUser = Depends(student),
                  db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    doc = _load(db, user, doubt_id)
    if doc.get("userId") == user.user_id:
        raise HTTPException(422, "You can't report your own post.")
    consume(db, user.user_id, "reports", cooldown=False)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        before = _reports(current.get("reports"))
        entries, hide = _report_into(before, user.user_id, body.reason)
        if entries == before:
            return None, current
        fields: dict[str, Any] = {"reports": entries}
        if hide and not current.get("hidden"):
            fields.update({"hidden": True, "hiddenReason": "reports", "hiddenBy": None, "hiddenAt": iso(utcnow())})
        return fields, {**current, **fields}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


@router.post("/doubts/{doubt_id}/replies/{reply_id}/report", response_model=DoubtDetail)
def report_reply(doubt_id: str, reply_id: str, body: ReportPostInput, user: CurrentUser = Depends(student),
                 db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    doc = _load(db, user, doubt_id)
    replies, i = _find_reply(doc, reply_id)
    if replies[i].get("userId") == user.user_id:
        raise HTTPException(422, "You can't report your own reply.")
    if replies[i].get("hidden"):
        raise HTTPException(404, "Reply not found.")
    consume(db, user.user_id, "reports", cooldown=False)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        replies, i = _find_reply(current, reply_id)
        before = _reports(replies[i].get("reports"))
        entries, hide = _report_into(before, user.user_id, body.reason)
        if entries == before:
            return None, current
        replies[i]["reports"] = entries
        if hide and not replies[i].get("verified"):  # a verified (faculty) answer is never auto-hidden
            replies[i].update({"hidden": True, "hiddenReason": "reports"})
        fields = {"replies": replies, **_facts(replies)}
        return fields, {**current, **fields}

    return _thread_out(doubt_id, occ_update(db, DOUBTS, doubt_id, mutate), user.user_id, with_replies=True)


# ---------------------------------------------------------------- study groups
def _group(group_id: str, members: int) -> dict[str, Any]:
    match = GROUP_ID.match(group_id)
    if not match:
        raise HTTPException(404, "Study group not found.")
    exam, year = match.group(1), int(match.group(2))
    return {"id": group_id, "label": f"{EXAM_LABEL.get(exam, exam.upper())} {year}", "exam": exam, "year": year, "members": members}


def _years() -> list[int]:
    this = local_date().year
    return list(range(this, this + GROUP_YEARS_AHEAD + 1))


def _member_counts(db: SafeFirestore) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, doc in stream_all(db, MEMBERS):
        gid = _str(doc.get("groupId"))
        if gid:
            counts[gid] = counts.get(gid, 0) + 1
    return counts


def _suggested(db: SafeFirestore, user_id: str) -> str | None:
    """The student's first target exam and the year of their exam date (profile), if it is a listed year."""
    profile = load_profile(db, user_id) or {}
    exam = (profile.get("targetExams") or [profile.get("targetExam") or "cat"])[0]
    try:
        year = date.fromisoformat(profile["examDate"]).year if profile.get("examDate") else None
    except ValueError:
        year = None
    return f"{exam}-{year}" if exam in EXAM_IDS and year in _years() else None


@router.get("/groups", response_model=GroupsResponse)
def list_groups(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    counts = _member_counts(db)
    groups = [_group(f"{exam}-{year}", counts.get(f"{exam}-{year}", 0)) for exam in EXAM_IDS for year in _years()]
    mine_id = _membership(db, user.user_id)
    mine = _group(mine_id, counts.get(mine_id, 0)) if mine_id and GROUP_ID.match(mine_id) else None
    return {"groups": groups, "mine": mine, "suggestedId": _suggested(db, user.user_id)}


@router.put("/me/group", response_model=GroupInfo)
def join_group(body: JoinInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    group = _group(body.groupId, 0)
    if group["year"] not in _years() and _membership(db, user.user_id) != body.groupId:
        raise HTTPException(422, "Choose a group for this year or the next two.")
    now = iso(utcnow())

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, None]:
        if current and current.get("groupId") == body.groupId:
            return None, None
        return {"userId": user.user_id, "groupId": body.groupId, "exam": group["exam"], "year": group["year"], "joinedAt": now}, None

    occ_update(db, MEMBERS, user.user_id, mutate)
    return _group(body.groupId, len(query_eq(db, MEMBERS, "groupId", body.groupId)))


@router.delete("/me/group", status_code=204)
def leave_group(user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> None:
    db.collection(MEMBERS).document(user.user_id).delete(timeout=DB_TIMEOUT)


def _require_member(db: SafeFirestore, user: CurrentUser, group_id: str) -> None:
    _group(group_id, 0)  # 404 on a malformed id
    if _membership(db, user.user_id) != group_id:
        raise HTTPException(403, "Join this study group first.")


@router.get("/groups/{group_id}/posts", response_model=ThreadsResponse)
def group_posts(group_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _require_member(db, user, group_id)
    return {"threads": _list(query_eq(db, DOUBTS, "groupId", group_id), user.user_id)}


@router.post("/groups/{group_id}/posts", response_model=DoubtDetail, status_code=201)
def group_post(group_id: str, body: PostInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    _require_member(db, user, group_id)
    text = clean_text(body.text)
    consume(db, user.user_id, "threads")
    doc_id, doc = _new_thread(db, user, text, scope="group", questionId=None, groupId=group_id,
                              paperId=None, section=None, number=None, stemPreview=None)
    return _thread_out(doc_id, doc, user.user_id, with_replies=True)


@router.get("/groups/{group_id}/leaderboard", response_model=GroupBoard)
def group_leaderboard(group_id: str, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    """The weekly daily-challenge board (same rule, same opt-in) limited to the group's members."""
    _require_member(db, user, group_id)
    members = {str(d.get("userId") or i) for i, d in query_eq(db, MEMBERS, "groupId", group_id)}
    end = local_date()
    board = leaderboard.weekly_board(None, user, db)  # records today's results and applies the opt-in
    rows = [dict(r) for r in leaderboard.weekly_rows(db, end) if r["userId"] in members]
    rows = leaderboard._rank(rows, leaderboard.weekly_key)
    entries, you = leaderboard._public(rows, user.user_id, leaderboard.WEEKLY_FIELDS)
    return {**board, "participants": len(rows), "entries": entries, "you": you, "groupId": group_id, "members": len(members)}


# ---------------------------------------------------------------- notifications (api/mba/notifications.py)
def student_notifications(db: SafeFirestore, user_id: str) -> list[dict[str, Any]]:
    """The newest visible reply by someone else on each thread the student started (last 14 days)."""
    items = []
    cutoff = utcnow() - timedelta(days=NOTIFY_WINDOW_DAYS)
    for doc_id, doc in query_eq(db, DOUBTS, "userId", user_id):
        others = [r for r in _visible_replies(doc) if r.get("userId") != user_id]
        latest = max(others, key=lambda r: str(r.get("createdAt") or ""), default=None)
        at = parse_iso(latest.get("createdAt")) if latest else None
        if latest is None or at is None or at < cutoff:
            continue
        faculty = latest.get("by") == "faculty"
        where = "your study group post" if doc.get("scope") == "group" else "your doubt"
        items.append({"id": f"doubt-{doc_id}-{latest.get('id')}", "kind": "doubt_reply",
                      "title": f"Faculty answered {where}" if faculty else f"New reply on {where}",
                      "detail": f"{latest.get('authorName') or 'Someone'}: {_preview(latest.get('text'))[:90]}",
                      "href": f"/mba/community/doubts/{doc_id}", "at": at})
    return items


# ---------------------------------------------------------------- delete my data (api/mba/privacy.py)
def forget_user(db: SafeFirestore, user_id: str) -> int:
    """Anonymise the student in every thread they took part in. Threads stay (others' answers live in them)."""
    query = db.collection(DOUBTS).where(filter=FieldFilter("participantIds", "array_contains", user_id))
    changed = 0
    for snap in query.stream(timeout=DB_TIMEOUT):
        doc = snap.to_dict() or {}
        replies = []
        for r in doc.get("replies") or []:
            if not isinstance(r, dict):
                continue
            r = {**r, "upvoters": [v for v in _ids(r.get("upvoters")) if v != user_id],
                 "reports": [x for x in _reports(r.get("reports")) if x.get("userId") != user_id]}
            if r.get("userId") == user_id:
                r.update({"userId": None, "authorName": "Former student"})
            replies.append(r)
        fields: dict[str, Any] = {
            "replies": replies, "participantIds": [p for p in _ids(doc.get("participantIds")) if p != user_id],
            "upvoters": [v for v in _ids(doc.get("upvoters")) if v != user_id],
            "reports": [x for x in _reports(doc.get("reports")) if x.get("userId") != user_id],
        }
        if doc.get("userId") == user_id:
            fields.update({"userId": None, "authorName": "Former student"})
        db.collection(DOUBTS).document(snap.id).update(fields, timeout=DB_TIMEOUT)
        changed += 1
    return changed


# ---------------------------------------------------------------- admin (faculty) queue
def _admin_reports(entries: Any) -> list[dict[str, Any]]:
    return [{"reason": str(r.get("reason") or "other"), "at": str(r.get("at") or "")} for r in _reports(entries)]


def _escalated(doc: dict[str, Any]) -> bool:
    created = parse_iso(doc.get("createdAt"))
    return (doc.get("scope") != "group" and _status(doc) == "open" and not doc.get("hidden") and not doc.get("facultyAnswered")
            and created is not None and utcnow() - created >= timedelta(hours=ESCALATE_AFTER_HOURS))


def _admin_out(doc_id: str, doc: dict[str, Any], question: dict[str, Any] | None, with_replies: bool = False) -> dict[str, Any]:
    q = question or {}
    section = q.get("section", doc.get("section"))
    number = q.get("number", doc.get("number"))
    replies = [r for r in doc.get("replies") or [] if isinstance(r, dict)]
    out = {
        "id": doc_id, "scope": "group" if doc.get("scope") == "group" else "question",
        "questionId": _str(doc.get("questionId")), "groupId": _str(doc.get("groupId")),
        "paperId": _str(q.get("paperId")) or _str(doc.get("paperId")),
        "section": section if section in SECTION_IDS else None,
        "number": number if isinstance(number, int) and not isinstance(number, bool) else None,
        "stemPreview": _preview(q.get("stemHtml")), "authorName": str(doc.get("authorName") or "Student"),
        "userId": _str(doc.get("userId")), "text": str(doc.get("text") or ""), "status": _status(doc),
        "hidden": doc.get("hidden") is True, "hiddenReason": _str(doc.get("hiddenReason")),
        "upvotes": len(_ids(doc.get("upvoters"))), "reports": _admin_reports(doc.get("reports")),
        "replyCount": int(doc.get("replyCount") or 0),
        "reportedReplies": sum(1 for r in replies if _unreviewed(r)),
        "facultyAnswered": doc.get("facultyAnswered") is True, "escalated": _escalated(doc),
        "createdAt": str(doc.get("createdAt") or ""), "lastActivityAt": str(doc.get("lastReplyAt") or doc.get("createdAt") or ""),
    }
    if with_replies:
        out["replies"] = [{
            "id": str(r.get("id") or ""), "by": "faculty" if r.get("by") == "faculty" else "student",
            "authorName": str(r.get("authorName") or "Student"), "userId": _str(r.get("userId")), "adminId": _str(r.get("adminId")),
            "text": str(r.get("text") or ""), "verified": r.get("verified") is True, "hidden": r.get("hidden") is True,
            "hiddenReason": _str(r.get("hiddenReason")), "upvotes": len(_ids(r.get("upvoters"))),
            "reports": _admin_reports(r.get("reports")), "createdAt": str(r.get("createdAt") or ""),
        } for r in replies]
    return out


def _unreviewed(item: dict[str, Any]) -> bool:
    """Has a student report newer than the last moderator review of this post."""
    reviewed = str(item.get("reviewedAt") or "")
    return any(str(r.get("at") or "") > reviewed for r in _reports(item.get("reports")))


def _reported(doc: dict[str, Any]) -> bool:
    return _unreviewed(doc) or any(_unreviewed(r) for r in doc.get("replies") or [] if isinstance(r, dict))


def _in_queue(doc: dict[str, Any], queue: str) -> bool:
    if queue == "escalated":
        return _escalated(doc)
    if queue == "unanswered":
        return doc.get("scope") != "group" and _status(doc) == "open" and not doc.get("hidden") and not doc.get("facultyAnswered")
    if queue == "reported":
        return _reported(doc)
    if queue == "hidden":
        return doc.get("hidden") is True or any(isinstance(r, dict) and r.get("hidden") for r in doc.get("replies") or [])
    return True


@router.get("/admin/doubts", response_model=AdminDoubtsResponse)
def admin_doubts(
    queue: AdminQueue = Query(default="escalated"),
    scope: Scope | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _admin: CurrentAdmin = Depends(faculty_admin),
    db: SafeFirestore = Depends(get_db),
) -> dict[str, Any]:
    docs = [(i, d) for i, d in stream_all(db, DOUBTS) if scope is None or (d.get("scope") or "question") == scope]
    counts = {q: sum(1 for _, d in docs if _in_queue(d, q)) for q in ("escalated", "unanswered", "reported", "hidden", "all")}
    rows = [(i, d) for i, d in docs if _in_queue(d, queue)]
    rows.sort(key=lambda r: str(r[1].get("createdAt") or ""), reverse=queue not in ("escalated", "unanswered"))  # oldest waiting first
    rows = rows[:limit]
    bank = get_bank(db)
    return {"doubts": [_admin_out(i, d, bank.questions.get(str(d.get("questionId") or ""))) for i, d in rows], "counts": counts}


def _admin_load(db: SafeFirestore, doubt_id: str) -> dict[str, Any]:
    doc = get_doc(db, DOUBTS, doubt_id)
    if doc is None:
        raise HTTPException(404, "Doubt not found.")
    return doc


def _admin_detail(db: SafeFirestore, doubt_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    return _admin_out(doubt_id, doc, get_bank(db).questions.get(str(doc.get("questionId") or "")), with_replies=True)


@router.get("/admin/doubts/{doubt_id}", response_model=AdminDoubtDetail)
def admin_doubt(doubt_id: str, _admin: CurrentAdmin = Depends(faculty_admin), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    return _admin_detail(db, doubt_id, _admin_load(db, doubt_id))


@router.post("/admin/doubts/{doubt_id}/replies", response_model=AdminDoubtDetail, status_code=201)
def admin_reply(doubt_id: str, body: PostInput, admin: CurrentAdmin = Depends(faculty_admin),
                db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    text = clean_text(body.text, allow_links=True)
    name = faculty_name(admin)

    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        replies = [r for r in current.get("replies") or [] if isinstance(r, dict)]
        if len(replies) >= MAX_REPLIES + 20:  # faculty get some headroom over the student cap
            raise HTTPException(409, "This thread is full.")
        stamp = iso(utcnow())
        replies.append({"id": uuid.uuid4().hex[:12], "by": "faculty", "userId": None, "adminId": admin.admin_id, "authorName": name,
                        "text": text, "verified": True, "hidden": False, "hiddenReason": None, "upvoters": [], "reports": [],
                        "createdAt": stamp})
        fields = {"replies": replies, **_facts(replies), "updatedAt": stamp}
        return fields, {**current, **fields}

    return _admin_detail(db, doubt_id, occ_update(db, DOUBTS, doubt_id, mutate))


@router.patch("/admin/doubts/{doubt_id}", response_model=AdminDoubtDetail)
def admin_patch_doubt(doubt_id: str, body: AdminDoubtPatch, admin: CurrentAdmin = Depends(faculty_admin),
                      db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        stamp = iso(utcnow())
        fields: dict[str, Any] = {"updatedAt": stamp, "reviewedAt": stamp, "reviewedBy": admin.admin_id}
        if body.hidden is not None:
            fields.update({"hidden": body.hidden, "hiddenReason": "moderator" if body.hidden else None,
                           "hiddenBy": admin.admin_id if body.hidden else None, "hiddenAt": stamp if body.hidden else None})
        if body.status is not None:
            fields.update({"status": body.status, "resolvedAt": stamp if body.status == "resolved" else None})
        if body.clearReports:
            fields["reports"] = []
        return fields, {**current, **fields}

    return _admin_detail(db, doubt_id, occ_update(db, DOUBTS, doubt_id, mutate))


@router.patch("/admin/doubts/{doubt_id}/replies/{reply_id}", response_model=AdminDoubtDetail)
def admin_patch_reply(doubt_id: str, reply_id: str, body: AdminReplyPatch, admin: CurrentAdmin = Depends(faculty_admin),
                      db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    def mutate(current: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if current is None:
            raise HTTPException(404, "Doubt not found.")
        replies, i = _find_reply(current, reply_id)
        stamp = iso(utcnow())
        r = replies[i]
        r.update({"reviewedAt": stamp, "reviewedBy": admin.admin_id})
        if body.hidden is not None:
            r.update({"hidden": body.hidden, "hiddenReason": "moderator" if body.hidden else None})
        if body.verified is not None:
            if r.get("by") == "faculty" and not body.verified:
                raise HTTPException(422, "Faculty answers are always verified. Hide it instead.")
            r.update({"verified": body.verified, "verifiedBy": admin.admin_id if body.verified else None})
        if body.clearReports:
            r["reports"] = []
        fields = {"replies": replies, **_facts(replies), "updatedAt": stamp}
        return fields, {**current, **fields}

    return _admin_detail(db, doubt_id, occ_update(db, DOUBTS, doubt_id, mutate))
