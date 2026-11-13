"""Application documents: files a student uploads against a checklist item (contract: docs/mba-api.md
→ "Application documents").

Files live in the existing Firebase Storage bucket (the one the Java backend uses, env ``BUCKET_NAME``; override with
``MBA_DOCS_BUCKET``) under ``mba/applications/{userId}/{slug}/{itemId}/{uuid}.{ext}`` and are PRIVATE: they are never
given a public ACL; owners (and admins, for documents the student shared) get short-lived V4 signed GET URLs.

Uploads go straight from the browser to Storage with a V4 signed POST policy (the bucket's CORS config allows POST
from any origin, not PUT), which pins the object name, content type and a 5 MB size limit. The backend then checks
the stored object (size, type, magic bytes) before the document becomes ``ready``.

Metadata: ``mbaApplicationDocs/{docId}`` = ``{ userId, slug, itemId, itemLabel, path, fileName, contentType, size,
status: "pending" | "ready", shareWithCounsellor, createdAt, uploadedAt, updatedAt }``. Pending docs that were never
completed are cleaned up when the student's documents are next listed.

Signing needs the service-account JSON already used for Firestore (``FIREBASE_CONFIG`` / ``FIREBASE_CREDENTIALS_PATH``);
the account needs ``storage.objects.create/get/delete`` on the bucket. Without a bucket or credentials every document
endpoint answers 503 and ``documentsConfig()`` reports ``enabled: false``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter

from api.db import SafeFirestore
from api.db.firebase import DB_TIMEOUT, DatabaseConfigError, _load_service_account

from .store import as_dict, get_doc, iso, parse_iso, utcnow

log = logging.getLogger(__name__)

DOCS = "mbaApplicationDocs"
MAX_BYTES = 5 * 1024 * 1024
# content type -> (file extension, magic-byte prefixes)
ALLOWED_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "application/pdf": ("pdf", (b"%PDF-",)),
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
}
UPLOAD_TTL = timedelta(minutes=10)    # signed POST policy lifetime
DOWNLOAD_TTL = timedelta(minutes=5)   # signed GET URL lifetime
PENDING_TTL = timedelta(hours=1)      # pending (never completed) docs older than this are cleaned up
MAX_PER_ITEM = 5
MAX_PER_USER = 100
FILE_NAME_MAX = 120
DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------- config + storage client
def bucket_name() -> str | None:
    name = (os.getenv("MBA_DOCS_BUCKET") or os.getenv("BUCKET_NAME") or "").strip()
    return name or None


def has_credentials() -> bool:
    return bool(os.getenv("FIREBASE_CONFIG") or os.getenv("FIREBASE_CREDENTIALS_PATH"))


def enabled() -> bool:
    return bool(bucket_name()) and has_credentials()


def documents_config() -> dict[str, Any]:
    return {"enabled": enabled(), "maxBytes": MAX_BYTES, "allowedTypes": list(ALLOWED_TYPES)}


_bucket_lock = threading.Lock()
_bucket_cache: tuple[str, Any] | None = None


def _bucket() -> Any:
    """google.cloud.storage Bucket, built from the Firestore service account (cached)."""
    global _bucket_cache
    name = bucket_name()
    if not name or not has_credentials():
        raise HTTPException(503, "Document upload is not configured.")
    with _bucket_lock:
        if _bucket_cache is not None and _bucket_cache[0] == name:
            return _bucket_cache[1]
        try:
            from google.cloud import storage
            from google.oauth2 import service_account

            info = _load_service_account()
            creds = service_account.Credentials.from_service_account_info(info)
            bucket = storage.Client(project=info["project_id"], credentials=creds).bucket(name)
        except (DatabaseConfigError, ValueError, KeyError) as error:
            log.error("Document storage misconfigured: %s", error)
            raise HTTPException(503, "Document upload is not configured.") from error
        _bucket_cache = (name, bucket)
        return bucket


def reset_for_tests() -> None:
    global _bucket_cache
    with _bucket_lock:
        _bucket_cache = None


# Storage calls, isolated so checks can replace them with fakes.
def signed_upload(path: str, content_type: str) -> dict[str, Any]:
    """V4 signed POST policy for exactly this object: ``{url, fields}`` (multipart form; the file goes last as ``file``)."""
    bucket = _bucket()
    policy = bucket.client.generate_signed_post_policy_v4(
        bucket.name, path, expiration=UPLOAD_TTL,
        conditions=[["content-length-range", 1, MAX_BYTES]],  # every field below is also added as an exact-match condition
        fields={"Content-Type": content_type, "acl": "private", "success_action_status": "201"},
    )
    return {"url": policy["url"], "fields": dict(policy["fields"])}


def stored_object(path: str) -> tuple[int, str, bytes] | None:
    """``(size, contentType, first 16 bytes)`` of an uploaded object, or None when it does not exist."""
    from google.api_core import exceptions as gexc

    blob = _bucket().blob(path)
    try:
        blob.reload(timeout=DB_TIMEOUT)
        head = blob.download_as_bytes(start=0, end=15, timeout=DB_TIMEOUT)
    except gexc.NotFound:
        return None
    return int(blob.size or 0), str(blob.content_type or ""), head


def delete_object(path: str) -> None:
    from google.api_core import exceptions as gexc

    try:
        _bucket().blob(path).delete(timeout=DB_TIMEOUT)
    except gexc.NotFound:
        pass


def signed_download(path: str, file_name: str, content_type: str) -> str:
    safe = re.sub(r'["\\\r\n]', "", file_name) or "document"
    return _bucket().blob(path).generate_signed_url(
        version="v4", expiration=DOWNLOAD_TTL, method="GET",
        response_disposition=f'inline; filename="{safe}"', response_type=content_type,
    )


# ---------------------------------------------------------------- helpers
def clean_file_name(raw: str, ext: str) -> str:
    """Display name: no path parts or control characters, ≤120 chars, keeps/sets the right extension."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or f"document.{ext}"
    stem, dot, suffix = name.rpartition(".")
    if not dot or suffix.lower() not in ({ext} | ({"jpeg"} if ext == "jpg" else set())):
        stem = name
        suffix = ext
    stem = stem[: FILE_NAME_MAX - len(suffix) - 1].strip() or "document"
    return f"{stem}.{suffix}"


def object_path(user_id: str, slug: str, item_id: str, ext: str) -> str:
    return f"mba/applications/{user_id}/{slug}/{item_id}/{uuid.uuid4().hex}.{ext}"


def sniff_ok(content_type: str, head: bytes) -> bool:
    spec = ALLOWED_TYPES.get(content_type)
    return bool(spec) and any(head.startswith(magic) for magic in spec[1])


def doc_out(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc_id,
        "itemId": str(data.get("itemId") or ""),
        "fileName": str(data.get("fileName") or "document"),
        "contentType": str(data.get("contentType") or ""),
        "size": int(data.get("size") or 0),
        "status": "ready" if data.get("status") == "ready" else "pending",
        "shareWithCounsellor": data.get("shareWithCounsellor") is True,
        "uploadedAt": data.get("uploadedAt") if isinstance(data.get("uploadedAt"), str) else None,
        "createdAt": str(data.get("createdAt") or ""),
    }


def user_docs(db: SafeFirestore, user_id: str) -> list[tuple[str, dict[str, Any]]]:
    query = db.collection(DOCS).where(filter=FieldFilter("userId", "==", user_id))
    return [(snap.id, as_dict(snap) or {}) for snap in query.stream(timeout=DB_TIMEOUT)]


def _stale_pending(data: dict[str, Any]) -> bool:
    created = parse_iso(data.get("createdAt"))
    return data.get("status") != "ready" and (created is None or utcnow() - created > PENDING_TTL)


def remove_doc(db: SafeFirestore, doc_id: str, data: dict[str, Any]) -> None:
    """Delete the stored object (if any) and then the metadata doc."""
    path = data.get("path")
    if isinstance(path, str) and path.startswith("mba/applications/") and enabled():
        delete_object(path)
    db.collection(DOCS).document(doc_id).delete(timeout=DB_TIMEOUT)


def docs_by_item(db: SafeFirestore, user_id: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(slug, itemId) -> ready documents, oldest first. Cleans up abandoned pending uploads on the way."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for doc_id, data in user_docs(db, user_id):
        if data.get("status") != "ready":
            if _stale_pending(data):
                try:
                    remove_doc(db, doc_id, data)
                except Exception as error:  # noqa: BLE001 - cleanup is best effort
                    log.warning("Could not clean up pending doc %s: %s", doc_id, error)
            continue
        out.setdefault((str(data.get("slug")), str(data.get("itemId"))), []).append(doc_out(doc_id, data))
    for docs in out.values():
        docs.sort(key=lambda d: (d["uploadedAt"] or d["createdAt"], d["id"]))
    return out


def own_doc(db: SafeFirestore, user_id: str, doc_id: str) -> dict[str, Any]:
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(404, "Document not found.")
    data = get_doc(db, DOCS, doc_id)
    if data is None or data.get("userId") != user_id:
        raise HTTPException(404, "Document not found.")
    return data


def remove_where(db: SafeFirestore, user_id: str, slug: str | None = None, item_id: str | None = None) -> int:
    """Delete this student's documents (all, one institute's, or one checklist item's). Returns how many."""
    removed = 0
    for doc_id, data in user_docs(db, user_id):
        if (slug is None or data.get("slug") == slug) and (item_id is None or data.get("itemId") == item_id):
            remove_doc(db, doc_id, data)
            removed += 1
    return removed


def download_link(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") != "ready" or not isinstance(data.get("path"), str):
        raise HTTPException(404, "Document not found.")
    expires = utcnow() + DOWNLOAD_TTL
    url = signed_download(data["path"], str(data.get("fileName") or "document"), str(data.get("contentType") or ""))
    return {"url": url, "expiresAt": iso(expires)}


def shared_docs(db: SafeFirestore, user_id: str) -> list[dict[str, Any]]:
    """Ready documents the student chose to share with their counsellor (for the admin request detail)."""
    rows = []
    for doc_id, data in user_docs(db, user_id):
        if data.get("status") == "ready" and data.get("shareWithCounsellor") is True:
            rows.append({**doc_out(doc_id, data), "slug": str(data.get("slug") or ""),
                         "itemLabel": str(data.get("itemLabel") or data.get("itemId") or "")})
    rows.sort(key=lambda d: (d["slug"], d["itemLabel"], d["uploadedAt"] or ""))
    return rows
