"""Direct-readable reserved multi-scope context packing.

The Mem0-compatible facade returns one result row per memory.  A fixed top-k
therefore makes every experimental representation compete with RAW evidence.
This module reserves *content* quotas without sacrificing the last retained
RAW row: that row and all selected lane items are folded into one directly
readable context PACK row.  Exact source memories remain verbatim inside the
PACK, so the projection is disposable and every derived lane keeps an evidence
fallback as required by the MIRL context-PACK contract.

The policy is deliberately pure and default-off.  Retrieval of each lane stays
with the caller; this module only validates, deduplicates, bounds, and composes
already-ranked result dictionaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

POLICY_OFF = "off"
POLICY_V1 = "reserved-multi-scope/1"
POLICIES = frozenset({POLICY_OFF, POLICY_V1})

SCOPE_ORDER = (
    "grounded_fact",
    "entity_relation",
    "temporal",
    "raw_episode",
)


@dataclass(frozen=True)
class ScopeQuotas:
    grounded_fact: int = 4
    entity_relation: int = 4
    temporal: int = 4
    raw_episode: int = 4

    def as_dict(self) -> dict[str, int]:
        return {
            "grounded_fact": self.grounded_fact,
            "entity_relation": self.entity_relation,
            "temporal": self.temporal,
            "raw_episode": self.raw_episode,
        }

    def validate(self) -> None:
        for scope, quota in self.as_dict().items():
            if not isinstance(quota, int) or quota < 0:
                raise ValueError(f"{scope} quota must be a non-negative integer")


DEFAULT_QUOTAS = ScopeQuotas()
DEFAULT_MAX_PACK_CHARS = 12_000
_DATED_MEMORY = re.compile(r"^\[[^\]]+?\s+(\d{4}-\d{2}-\d{2})(?:T[^\]]+)?\]")


def resolve_policy(value: str | None) -> str:
    policy = str(value or POLICY_OFF).strip().lower() or POLICY_OFF
    if policy not in POLICIES:
        raise ValueError(f"unknown multi-scope pack policy {policy!r}")
    return policy


def _memory(row: Mapping[str, object]) -> str:
    return str(row.get("memory") or "")


def _record_id(row: Mapping[str, object]) -> str:
    return str(row.get("id") or "")


def _render_item(scope: str, row: Mapping[str, object]) -> str:
    memory = _memory(row)
    metadata = json.dumps(
        {
            "chars": len(memory),
            "id": _record_id(row),
            "scope": scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    # The memory body is intentionally verbatim, rather than JSON escaped.
    # Direct readers and evidence gates can therefore find exact source text.
    return f"ITEM|{metadata}\n{memory}\nEND-ITEM"


def _render_pack(items: Sequence[tuple[str, Mapping[str, object]]]) -> str:
    header = (
        f"SEAM-MULTISCOPE/1|policy={POLICY_V1}|direct_read=1|"
        f"items={len(items)}\n"
        "Context PACK: read each ITEM body directly; RAW bodies are exact "
        "evidence fallbacks."
    )
    return "\n".join([header, *[_render_item(scope, row) for scope, row in items]])


def _selected_lane_items(
    baseline: Sequence[Mapping[str, object]],
    lanes: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    quotas: ScopeQuotas,
    protected: Mapping[str, object],
    max_pack_chars: int,
) -> list[tuple[str, Mapping[str, object]]]:
    seen_memories = {_memory(row) for row in baseline if _memory(row)}
    seen_ids = {_record_id(row) for row in baseline if _record_id(row)}
    selected: list[tuple[str, Mapping[str, object]]] = []
    quota_map = quotas.as_dict()

    for scope in SCOPE_ORDER:
        quota = quota_map[scope]
        if quota == 0:
            continue
        accepted = 0
        for row in lanes.get(scope, ()):
            memory = _memory(row)
            record_id = _record_id(row)
            if not memory or memory in seen_memories:
                continue
            if record_id and record_id in seen_ids:
                continue
            trial = [
                ("raw_protected", protected),
                *selected,
                (scope, row),
            ]
            if len(_render_pack(trial)) > max_pack_chars:
                continue
            seen_memories.add(memory)
            if record_id:
                seen_ids.add(record_id)
            selected.append((scope, row))
            accepted += 1
            if accepted >= quota:
                break
    return selected


def compose_reserved_multi_scope(
    baseline: list[dict],
    lanes: Mapping[str, Sequence[dict]],
    *,
    limit: int,
    policy: str = POLICY_OFF,
    quotas: ScopeQuotas = DEFAULT_QUOTAS,
    max_pack_chars: int = DEFAULT_MAX_PACK_CHARS,
) -> list[dict]:
    """Return a bounded result list with one tail PACK, or the exact off path.

    The final retained baseline row is moved inside the PACK before any new
    lane item.  Consequently an enabled candidate can add directly readable
    evidence without dropping the baseline tail's text.  No PACK is emitted
    unless at least one novel lane item survives quotas and the character cap.
    """

    resolved = resolve_policy(policy)
    if resolved == POLICY_OFF:
        return baseline
    quotas.validate()
    if limit <= 0:
        return []
    if max_pack_chars <= 0:
        raise ValueError("max_pack_chars must be positive")

    bounded = baseline[:limit]
    if not bounded:
        return bounded
    protected = bounded[-1]
    if len(_render_pack([("raw_protected", protected)])) > max_pack_chars:
        return bounded
    selected = _selected_lane_items(
        bounded,
        lanes,
        quotas=quotas,
        protected=protected,
        max_pack_chars=max_pack_chars,
    )
    if not selected:
        return baseline if len(baseline) <= limit else bounded

    items = [("raw_protected", protected), *selected]
    body = _render_pack(items)
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    pack_row = {
        "memory": body,
        "score": float(protected.get("score") or 0.0),
        "id": f"seam-multiscope-1-{digest}",
        "created_at": "",
    }
    return [*bounded[:-1], pack_row]


def select_date_diverse_rows(
    rows: Sequence[dict],
    *,
    exclude: Sequence[dict] = (),
    limit: int,
) -> list[dict]:
    """Select ranked RAW rows while protecting distinct observation dates."""

    if limit <= 0:
        return []
    excluded_memories = {_memory(row) for row in exclude if _memory(row)}
    selected: list[dict] = []
    seen_dates: set[str] = set()
    fallback: list[dict] = []
    for row in rows:
        memory = _memory(row)
        if not memory or memory in excluded_memories:
            continue
        match = _DATED_MEMORY.match(memory)
        if match and match.group(1) not in seen_dates:
            seen_dates.add(match.group(1))
            selected.append(row)
            if len(selected) >= limit:
                return selected
        else:
            fallback.append(row)
    for row in fallback:
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def pack_scope_counts(row: Mapping[str, object]) -> dict[str, int]:
    """Return scope counts from a rendered PACK without exposing its bodies."""

    memory = _memory(row)
    counts = {scope: 0 for scope in ("raw_protected", *SCOPE_ORDER)}
    for line in memory.splitlines():
        if not line.startswith("ITEM|"):
            continue
        try:
            payload = json.loads(line.split("|", 1)[1])
        except (json.JSONDecodeError, TypeError):
            continue
        scope = str(payload.get("scope") or "")
        if scope in counts:
            counts[scope] += 1
    return counts
