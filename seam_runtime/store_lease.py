"""Cross-process lifetime leases for canonical SQLite stores.

Supported stores hold a shared lease for their full lifetime. Byte-replacing
maintenance such as backup restore must acquire the exclusive lease without
waiting, which turns the documented "close every runtime" precondition into an
enforced recovery boundary.
"""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


class DatabaseInUseError(RuntimeError):
    """Raised when exclusive maintenance targets an active supported store."""


@dataclass
class _SharedLease:
    handle: BinaryIO
    references: int


_LEASE_CONDITION = threading.Condition()
_SHARED_LEASES: dict[str, _SharedLease] = {}
_EXCLUSIVE_LEASES: set[str] = set()


def _database_identity(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _lease_path(identity: str) -> Path:
    database_path = Path(identity)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return database_path.parent / f".seam-store-{digest[:16]}.lock"


def _open_lock_file(identity: str) -> BinaryIO:
    lock_path = _lease_path(identity)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if os.name != "nt":
        lock_path.chmod(0o600)
    else:  # ``msvcrt.locking`` requires the byte range to exist.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
    handle.seek(0)
    return handle


def _lock_shared(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_RLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)


def _lock_exclusive_nonblocking(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class StoreUseLease:
    """Shared cross-process lease owned by one supported store lifetime."""

    def __init__(self, path: str | Path) -> None:
        self._identity = _database_identity(path)
        self._closed = False
        with _LEASE_CONDITION:
            while self._identity in _EXCLUSIVE_LEASES:
                _LEASE_CONDITION.wait()
            existing = _SHARED_LEASES.get(self._identity)
            if existing is not None:
                existing.references += 1
                return
            handle = _open_lock_file(self._identity)
            try:
                _lock_shared(handle)
            except BaseException:
                handle.close()
                raise
            _SHARED_LEASES[self._identity] = _SharedLease(handle, 1)

    def close(self) -> None:
        if self._closed:
            return
        with _LEASE_CONDITION:
            if self._closed:
                return
            lease = _SHARED_LEASES[self._identity]
            lease.references -= 1
            if lease.references == 0:
                try:
                    _unlock(lease.handle)
                finally:
                    lease.handle.close()
                    del _SHARED_LEASES[self._identity]
                    _LEASE_CONDITION.notify_all()
            self._closed = True


@contextmanager
def exclusive_store_maintenance(path: str | Path) -> Iterator[None]:
    """Acquire the target's exclusive maintenance lease without waiting."""

    identity = _database_identity(path)
    with _LEASE_CONDITION:
        if identity in _SHARED_LEASES or identity in _EXCLUSIVE_LEASES:
            raise DatabaseInUseError(
                "database has an active SEAM store; close every store before restore"
            )
        _EXCLUSIVE_LEASES.add(identity)
        try:
            handle = _open_lock_file(identity)
            try:
                _lock_exclusive_nonblocking(handle)
            except OSError as exc:
                handle.close()
                raise DatabaseInUseError(
                    "database has an active SEAM store; close every store before restore"
                ) from exc
            except BaseException:
                handle.close()
                raise
        except BaseException:
            _EXCLUSIVE_LEASES.remove(identity)
            _LEASE_CONDITION.notify_all()
            raise

    try:
        yield
    finally:
        try:
            _unlock(handle)
        finally:
            handle.close()
            with _LEASE_CONDITION:
                _EXCLUSIVE_LEASES.remove(identity)
                _LEASE_CONDITION.notify_all()
