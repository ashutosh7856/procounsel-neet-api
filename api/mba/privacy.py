"""Student "delete my MBA data": ``POST /api/v1/mba/me/data/delete`` (contract: docs/mba-api.md → "Delete my MBA data").

Deletes every per-student document in the ``mba*`` collections and anonymises the
student's question reports (kept, without the userId, under a new random id, because
they describe problems with shared content). Never touches a Java collection: the
collections are listed here explicitly, all ``mba``-prefixed, and the database guard
(api/db/guard.py) refuses writes outside ``WRITABLE_COLLECTIONS`` anyway. The ProCounsellor
account itself (Java ``users``) is not affected. Aggregates without identities
(``mbaTestScoreStats`` histograms) are left as they are.

When a new per-student ``mba*`` collection is added, add it to ``USER_COLLECTIONS``. Uploaded application documents
(``mbaApplicationDocs``) are deleted file first, then metadata (doc_store.py).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import CurrentUser
from api.db import SafeFirestore, get_db
from api.db.firebase import DB_TIMEOUT

from . import doc_store
from .community import forget_user
from .deps import student
from .store import iso, query_eq, utcnow

router = APIRouter()

BATCH_LIMIT = 400
CONFIRM_PHRASE = "DELETE"
# Every document with this student's ``userId`` is deleted.
USER_COLLECTIONS = (
    "mbaAttempts", "mbaAttemptAnalyses", "mbaQuestionStats", "mbaStudyTasks", "mbaAiUsage",
    "mbaGdpiSessions", "mbaCounsellorRequests", "mbaDailyResults", "mbaLeaderboardPrefs",
    "mbaNotificationState", "mbaShortlists", "mbaProfiles", "mbaApplicationDocs",
    "mbaGroupMembers", "mbaCommunityUsage", "mbaSupportTickets", "mbaCoachChats", "mbaSyllabusProgress",
)
# Also keyed by userId (doc id), deleted even if an old doc lacks the userId field.
USER_ID_DOCS = ("mbaProfiles", "mbaShortlists", "mbaNotificationState", "mbaLeaderboardPrefs", "mbaGroupMembers")
REPORTS = "mbaQuestionReports"  # anonymised, not deleted
REPORT_PRIVATE_FIELDS = ("userId", "lastWriteDate", "writesToday")

assert all(name.startswith("mba") for name in (*USER_COLLECTIONS, *USER_ID_DOCS, REPORTS))


class DeleteDataInput(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: Literal["DELETE"]


class DeleteDataResult(BaseModel):
    deleted: dict[str, int]     # collection -> documents deleted
    anonymised: dict[str, int]  # collection -> documents kept without the userId
    completedAt: str


class _Writer:
    """Batched writes, committed every ``BATCH_LIMIT`` operations."""

    def __init__(self, db: SafeFirestore) -> None:
        self.db, self.batch, self.pending = db, db.batch(), 0

    def _tick(self) -> None:
        self.pending += 1
        if self.pending >= BATCH_LIMIT:
            self.flush()

    def delete(self, collection: str, doc_id: str) -> None:
        self.batch.delete(self.db.collection(collection).document(doc_id))
        self._tick()

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        self.batch.set(self.db.collection(collection).document(doc_id), data)
        self._tick()

    def flush(self) -> None:
        if self.pending:
            self.batch.commit(timeout=DB_TIMEOUT)
        self.batch, self.pending = self.db.batch(), 0


def delete_user_data(db: SafeFirestore, user_id: str) -> dict[str, Any]:
    files = doc_store.remove_where(db, user_id)  # stored files first, each with its metadata doc
    writer = _Writer(db)
    deleted: dict[str, int] = {}
    for collection in USER_COLLECTIONS:
        ids = {doc_id for doc_id, _ in query_eq(db, collection, "userId", user_id)}
        if collection in USER_ID_DOCS and db.collection(collection).document(user_id).get(timeout=DB_TIMEOUT).exists:
            ids.add(user_id)
        for doc_id in ids:
            writer.delete(collection, doc_id)
        deleted[collection] = len(ids) + (files if collection == doc_store.DOCS else 0)
    anonymised = 0
    now = iso(utcnow())
    for doc_id, doc in query_eq(db, REPORTS, "userId", user_id):
        kept = {k: v for k, v in doc.items() if k not in REPORT_PRIVATE_FIELDS}
        # The old id is derived from the userId (reports.report_id), so the report moves to a random one.
        writer.set(REPORTS, uuid.uuid4().hex[:28], {**kept, "userId": None, "anonymisedAt": now})
        writer.delete(REPORTS, doc_id)
        anonymised += 1
    writer.flush()
    # Doubt threads hold other students' answers too, so the student is anonymised in them, not deleted.
    doubts = forget_user(db, user_id)
    return {"deleted": deleted, "anonymised": {REPORTS: anonymised, "mbaDoubts": doubts}, "completedAt": now}


@router.post("/me/data/delete", response_model=DeleteDataResult)
def delete_my_data(body: DeleteDataInput, user: CurrentUser = Depends(student), db: SafeFirestore = Depends(get_db)) -> dict[str, Any]:
    if body.confirm != CONFIRM_PHRASE:  # pragma: no cover - the model already enforces it
        raise HTTPException(422, f'Type "{CONFIRM_PHRASE}" to confirm.')
    return delete_user_data(db, user.user_id)
