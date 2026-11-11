"""Write guard around the Firestore client.

``SafeFirestore`` is the only Firestore handle the rest of the app gets. Reads
work everywhere; writes are allowed only into collections registered in
``WRITABLE_COLLECTIONS``. Anything else raises ``ReadOnlyCollectionError``.

Reads of read-only collections (document gets, queries, ``list_documents``) return
snapshots whose ``reference`` is read-only too, so a raw writable reference never
escapes. Still, never write through ``snapshot.reference`` — fetch a writable ref via
``SafeFirestore.collection``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Iterable

from .collections import WRITABLE_COLLECTIONS


class ReadOnlyCollectionError(PermissionError):
    """Raised when code tries to write to a collection this service does not own."""


def _root_collection(path: str) -> str:
    return path.strip("/").split("/", 1)[0]


def _ensure_writable(path: str, writable: Iterable[str]) -> None:
    root = _root_collection(path)
    if root not in writable:
        raise ReadOnlyCollectionError(
            f"Writes to '{root}' are blocked: it is not a collection owned by this service. "
            "Register new collections in api/db/collections.py."
        )


_QUERY_METHODS = {
    "where", "order_by", "limit", "limit_to_last", "offset", "start_at", "start_after",
    "end_at", "end_before", "select", "stream", "get", "count", "sum", "avg",
    "find_nearest", "list_documents",
}


def _read_only(value: Any) -> Any:
    """Wrap a read result so no raw (writable) reference escapes from a read-only collection."""
    if isinstance(value, (ReadOnlyCollection, ReadOnlyDocument, ReadOnlyQuery, ReadOnlySnapshot, str, bytes)):
        return value
    if isinstance(value, list):
        return [_read_only(item) for item in value]
    if hasattr(value, "to_dict") and hasattr(value, "reference"):  # DocumentSnapshot
        return ReadOnlySnapshot(value)
    if hasattr(value, "path") and hasattr(value, "set"):  # DocumentReference
        return ReadOnlyDocument(value)
    if hasattr(value, "stream"):  # Query / AggregationQuery / VectorQuery
        return ReadOnlyQuery(value)
    if isinstance(value, Iterator):  # stream() generators
        return (_read_only(item) for item in value)
    return value


def _query_attr(ref: Any, name: str, where: str) -> Any:
    if name not in _QUERY_METHODS:
        raise ReadOnlyCollectionError(f"'{name}' is not allowed on read-only {where}.")
    attr = getattr(ref, name)
    if not callable(attr):
        return attr
    return lambda *args, **kwargs: _read_only(attr(*args, **kwargs))


class ReadOnlySnapshot:
    """A document snapshot whose ``reference`` is read-only."""

    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    @property
    def reference(self) -> "ReadOnlyDocument":
        return ReadOnlyDocument(self._snapshot.reference)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._snapshot, name)


class ReadOnlyQuery:
    """A query over a read-only collection; results are read-only snapshots."""

    def __init__(self, ref: Any) -> None:
        self._ref = ref

    def __getattr__(self, name: str) -> Any:
        return _query_attr(self._ref, name, "query")


class ReadOnlyCollection:
    """Read-only view of a collection; query builders return read-only queries."""

    def __init__(self, ref: Any) -> None:
        self._ref = ref

    @property
    def id(self) -> str:
        return self._ref.id

    def document(self, document_id: str | None = None) -> "ReadOnlyDocument":
        return ReadOnlyDocument(self._ref.document(document_id))

    def __getattr__(self, name: str) -> Any:
        return _query_attr(self._ref, name, f"collection '{self._ref.id}'")


class ReadOnlyDocument:
    """Read-only view of a document."""

    def __init__(self, ref: Any) -> None:
        self._ref = ref

    @property
    def id(self) -> str:
        return self._ref.id

    @property
    def path(self) -> str:
        return self._ref.path

    def get(self, *args: Any, **kwargs: Any) -> Any:
        return _read_only(self._ref.get(*args, **kwargs))

    def collection(self, collection_id: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._ref.collection(collection_id))

    def collections(self, *args: Any, **kwargs: Any) -> list[ReadOnlyCollection]:
        return [ReadOnlyCollection(ref) for ref in self._ref.collections(*args, **kwargs)]

    def __getattr__(self, name: str) -> Any:
        raise ReadOnlyCollectionError(f"'{name}' is not allowed on read-only document '{self._ref.path}'.")


class _GuardedWriter:
    """Wraps a WriteBatch or Transaction and checks every write target."""

    _WRITE_METHODS = {"set", "update", "delete", "create"}

    def __init__(self, inner: Any, writable: frozenset[str]) -> None:
        self._inner = inner
        self._writable = writable

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in self._WRITE_METHODS:
            return attr

        def checked(reference: Any, *args: Any, **kwargs: Any) -> Any:
            path = getattr(reference, "path", None)
            if not isinstance(path, str) or isinstance(reference, (ReadOnlyCollection, ReadOnlyDocument)):
                raise ReadOnlyCollectionError("Batch/transaction writes need a writable document reference.")
            _ensure_writable(path, self._writable)
            return attr(reference, *args, **kwargs)

        return checked


class SafeFirestore:
    """The Firestore handle exposed to application code."""

    def __init__(self, client: Any, writable: Iterable[str] = WRITABLE_COLLECTIONS) -> None:
        self._client = client
        self._writable = frozenset(writable)

    @property
    def project(self) -> str:
        return self._client.project

    def is_writable(self, collection_id: str) -> bool:
        return collection_id in self._writable

    def collection(self, collection_id: str) -> Any:
        """Writable CollectionReference for owned collections, read-only view otherwise."""
        ref = self._client.collection(collection_id)
        return ref if self.is_writable(collection_id) else ReadOnlyCollection(ref)

    def document(self, path: str) -> Any:
        ref = self._client.document(path)
        return ref if self.is_writable(_root_collection(path)) else ReadOnlyDocument(ref)

    def collection_group(self, collection_id: str) -> Any:
        # Collection-group queries are read-only by nature; their snapshots are too.
        return ReadOnlyQuery(self._client.collection_group(collection_id))

    def batch(self) -> _GuardedWriter:
        return _GuardedWriter(self._client.batch(), self._writable)

    def transaction(self, **kwargs: Any) -> _GuardedWriter:
        return _GuardedWriter(self._client.transaction(**kwargs), self._writable)
