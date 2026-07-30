"""Types for the non-official, zero-network WANDR replay lane.

WANDR (Perplexity AI, Apache-2.0) scores an agent's *submission rows*: for each
member of a key hierarchy, a source URL plus verbatim excerpts that make the
answer evident. Its official pipeline is networked and paid — every task
declares ``network_mode = "public"`` and wants ``OPENAI_API_KEY`` /
``PERPLEXITY_API_KEY``.

This lane never runs that pipeline. It replays a pinned, hand-authored corpus
so SEAM's memory behaviour (provenance, canonicalization, deduplication,
retrieval) can be measured with provider, network, and cost counters fixed at
zero. Only the *workload shape* is borrowed; no fetched page content is
vendored, which also keeps us clear of the upstream NOTICE that excludes
third-party materials from its Apache grant.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def stable_id(*parts: str) -> str:
    """Deterministic short id.

    Replay determinism is a hard requirement of this lane: the same corpus must
    always produce the same source, episode, task, and request identifiers, on
    any machine and in any order.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class WandrRow:
    """One WANDR submission row.

    Mirrors the upstream JSONL contract:
    ``{"item": {...}, "url": ..., "excerpts": [...], "answer": {...}}``
    """

    task: str
    item: dict[str, str]
    url: str
    excerpts: tuple[str, ...]
    answer: dict[str, Any] = field(default_factory=dict)

    @property
    def member_key(self) -> str:
        """The hierarchy member this row supports (e.g. the topic)."""
        return "|".join(f"{k}={self.item[k]}" for k in sorted(self.item))

    @property
    def source_id(self) -> str:
        return stable_id("source", self.task, self.url)

    @property
    def episode_id(self) -> str:
        return stable_id("episode", self.task, self.member_key, self.url)

    def to_submission(self) -> dict[str, Any]:
        """Render back into the upstream submission shape."""
        return {
            "item": dict(self.item),
            "url": self.url,
            "excerpts": list(self.excerpts),
            "answer": dict(self.answer),
        }

    @classmethod
    def from_dict(cls, task: str, payload: dict[str, Any]) -> "WandrRow":
        item = payload.get("item")
        if not isinstance(item, dict) or not item:
            raise ValueError("row 'item' must be a non-empty object")
        url = payload.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("row 'url' must be a non-empty string")
        excerpts = payload.get("excerpts") or []
        if not isinstance(excerpts, list) or not all(
            isinstance(e, str) and e for e in excerpts
        ):
            raise ValueError("row 'excerpts' must be a list of non-empty strings")
        return cls(
            task=task,
            item={str(k): str(v) for k, v in item.items()},
            url=url,
            excerpts=tuple(excerpts),
            answer=dict(payload.get("answer") or {}),
        )


@dataclass(frozen=True)
class KeySpec:
    """One level of the WANDR key hierarchy (upstream ``KeySpec``)."""

    name: str
    required: int


@dataclass(frozen=True)
class WandrTask:
    """A replayable WANDR task definition."""

    name: str
    key_hierarchy: tuple[KeySpec, ...]
    rows: tuple[WandrRow, ...]

    @property
    def task_id(self) -> str:
        return stable_id("task", self.name)

    @property
    def topology(self) -> str:
        return "hierarchical" if len(self.key_hierarchy) > 1 else "flat"

    def member_keys(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.member_key, None)
        return tuple(seen)


@dataclass
class ReplayCounters:
    """Cost/network counters. This lane asserts every one of these stays zero.

    They are incremented by explicit guards rather than inferred, so a
    regression that introduces a live call fails loudly instead of silently
    turning a free lane into a paid one.
    """

    provider_calls: int = 0
    network_calls: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_calls": self.provider_calls,
            "network_calls": self.network_calls,
            "cost_usd": self.cost_usd,
        }

    @property
    def is_free(self) -> bool:
        return (
            self.provider_calls == 0
            and self.network_calls == 0
            and self.cost_usd == 0.0
        )
