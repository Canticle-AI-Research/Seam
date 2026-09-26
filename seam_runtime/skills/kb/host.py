"""Revision-safe active skill windows for cooperating host applications."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .planner import SkillFrame, SkillFrameEntry


class SkillWindowLockError(RuntimeError):
    """A window lock could not be safely acquired or reclaimed."""


@dataclass(frozen=True)
class ActivationReceipt:
    previous_revision: int
    new_revision: int
    activated_ids: tuple[str, ...]
    retained_ids: tuple[str, ...]
    evicted_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_revision": self.previous_revision,
            "new_revision": self.new_revision,
            "activated_ids": list(self.activated_ids),
            "retained_ids": list(self.retained_ids),
            "evicted_ids": list(self.evicted_ids),
        }


@dataclass(frozen=True)
class ActiveSkillWindow:
    revision: int
    pinned: tuple[SkillFrameEntry, ...]
    rotating: tuple[SkillFrameEntry, ...]
    activation_order: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = [entry.skill_id for entry in (*self.pinned, *self.rotating)]
        if len(ids) != len(set(ids)):
            raise ValueError("active window contains duplicate skill identities")
        if self.revision < 0:
            raise ValueError("window revision cannot be negative")
        order = self.activation_order or tuple(ids)
        if len(order) != len(ids) or set(order) != set(ids):
            raise ValueError("activation order must contain every active skill exactly once")
        object.__setattr__(self, "activation_order", order)

    @property
    def entries(self) -> tuple[SkillFrameEntry, ...]:
        by_id = {entry.skill_id: entry for entry in (*self.pinned, *self.rotating)}
        return tuple(by_id[skill_id] for skill_id in self.activation_order)

    def replace(
        self, frame: SkillFrame, *, expected_revision: int
    ) -> tuple["ActiveSkillWindow", ActivationReceipt]:
        if self.revision != expected_revision:
            raise ValueError(
                f"revision mismatch: expected {expected_revision}, current {self.revision}"
            )
        pinned_ids = {entry.skill_id for entry in self.pinned}
        frame_by_id = {entry.skill_id: entry for entry in frame.entries}
        missing_pins = sorted(pinned_ids - set(frame_by_id))
        if missing_pins:
            raise ValueError(
                f"complete frame is missing pinned skills: {', '.join(missing_pins)}"
            )
        pinned = tuple(frame_by_id[entry.skill_id] for entry in self.pinned)
        rotating = tuple(entry for entry in frame.entries if entry.skill_id not in pinned_ids)
        combined = frame.entries
        if len(combined) > frame.max_skills:
            raise ValueError(
                f"skill-count budget exceeded by pinned window: {len(combined)} > {frame.max_skills}"
            )
        token_count = frame.token_count
        if token_count > frame.token_budget:
            raise ValueError(
                f"token budget exceeded by pinned window: {token_count} > {frame.token_budget}"
            )
        old_ids = {entry.skill_id for entry in (*self.pinned, *self.rotating)}
        new_ids = {entry.skill_id for entry in combined}
        new_revision = self.revision + 1
        receipt = ActivationReceipt(
            previous_revision=self.revision,
            new_revision=new_revision,
            activated_ids=tuple(sorted(new_ids - old_ids)),
            retained_ids=tuple(sorted(new_ids & old_ids)),
            evicted_ids=tuple(sorted(old_ids - new_ids)),
        )
        return ActiveSkillWindow(
            new_revision,
            pinned,
            rotating,
            tuple(entry.skill_id for entry in combined),
        ), receipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "seam-active-skill-window/v1",
            "revision": self.revision,
            "pinned": [entry.to_dict() for entry in self.pinned],
            "rotating": [entry.to_dict() for entry in self.rotating],
            "activation_order": list(self.activation_order),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActiveSkillWindow":
        if value.get("schema") != "seam-active-skill-window/v1":
            raise ValueError("unsupported active skill window schema")
        return cls(
            revision=int(value["revision"]),
            pinned=tuple(SkillFrameEntry.from_dict(item) for item in value.get("pinned", ())),
            rotating=tuple(SkillFrameEntry.from_dict(item) for item in value.get("rotating", ())),
            activation_order=tuple(str(item) for item in value.get("activation_order", ())),
        )


class FileSkillWindowHost:
    """Atomic file persistence for hosts that explicitly consume SkillFrames.

    Persisting this window does not mutate a model's system/developer context;
    a cooperating host must read and place the frame at its own context boundary.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        lock_timeout: float = 5.0,
        stale_lock_seconds: float = 300.0,
    ):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        if lock_timeout <= 0 or stale_lock_seconds <= 0:
            raise ValueError("lock timeout and stale-lock threshold must be positive")
        self.lock_timeout = lock_timeout
        self.stale_lock_seconds = stale_lock_seconds

    def initialize(self, window: ActiveSkillWindow) -> None:
        self._prepare_target()
        with self._lock():
            if self.path.exists():
                raise FileExistsError(self.path)
            self._atomic_write(window)

    def load(self) -> ActiveSkillWindow:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("active skill window must be a JSON object")
        return ActiveSkillWindow.from_dict(value)

    def replace(self, frame: SkillFrame, *, expected_revision: int) -> ActivationReceipt:
        self._prepare_target()
        with self._lock():
            current = self.load()
            updated, receipt = current.replace(frame, expected_revision=expected_revision)
            self._atomic_write(updated)
            return receipt

    def _prepare_target(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.absolute() != self.path.parent.resolve():
            raise ValueError(f"unsafe symlinked window parent: {self.path.parent}")
        if self.path.is_symlink():
            raise ValueError(f"unsafe symlinked window target: {self.path}")
        if self.lock_path.is_symlink():
            raise SkillWindowLockError(f"unsafe symlinked window lock: {self.lock_path}")

    @contextmanager
    def _lock(self):
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self.lock_timeout
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_lock_seconds:
                    raise SkillWindowLockError(
                        f"stale window lock requires operator cleanup: {self.lock_path}"
                    ) from exc
                if time.monotonic() >= deadline:
                    raise SkillWindowLockError(
                        f"timed out acquiring window lock: {self.lock_path}"
                    ) from exc
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"token": token, "created": time.time()}, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            yield
        finally:
            try:
                value = json.loads(self.lock_path.read_text(encoding="utf-8"))
                if value.get("token") == token:
                    self.lock_path.unlink()
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass

    def _atomic_write(self, window: ActiveSkillWindow) -> None:
        payload = json.dumps(window.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
