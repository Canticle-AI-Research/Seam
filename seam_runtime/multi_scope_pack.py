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

# Artifact-replay-only policy.  Keep this separate from ``POLICIES`` until the
# facade has independent RAW-primary and derived auxiliary retrieval lanes.
NON_DISPLACING_FACT_POLICY_V1 = "non-displacing-fact-pack/1"
NON_DISPLACING_FACT_POLICIES = frozenset(
    {POLICY_OFF, NON_DISPLACING_FACT_POLICY_V1}
)
NON_DISPLACING_FACT_PACK_PREFIX = "SEAM-NONDISPLACING-FACT-PACK/1"
_NON_DISPLACING_FACT_PACK_ID_PREFIX = "seam-nondisplacing-fact-1-"
_NON_DISPLACING_FACT_SCOPES = frozenset(
    {"raw_protected", "raw_source", "grounded_fact", "raw_episode"}
)

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


@dataclass(frozen=True)
class PackItem:
    """One strictly parsed, directly readable non-displacing PACK item."""

    scope: str
    record_id: str
    memory: str


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


def _render_non_displacing_fact_pack(
    items: Sequence[tuple[str, Mapping[str, object]]],
) -> str:
    header = (
        f"{NON_DISPLACING_FACT_PACK_PREFIX}|"
        f"policy={NON_DISPLACING_FACT_POLICY_V1}|direct_read=1|items={len(items)}\n"
        "Context PACK: the protected RAW is the exact baseline tail; auxiliary "
        "RAW and grounded facts are additive evidence."
    )
    return "\n".join([header, *[_render_item(scope, row) for scope, row in items]])


def _valid_raw_row(row: Mapping[str, object]) -> bool:
    record_id = _record_id(row)
    memory = _memory(row)
    return (
        record_id.startswith("raw:")
        and bool(memory)
        and not memory.startswith(
            (
                "SEAM-FACT/1|",
                "SEAM-MULTISCOPE/1|",
                f"{NON_DISPLACING_FACT_PACK_PREFIX}|",
            )
        )
    )


def _valid_fact_row(row: Mapping[str, object]) -> bool:
    record_id = _record_id(row)
    memory = _memory(row)
    if not record_id or not memory.startswith("SEAM-FACT/1|"):
        return False
    lines = memory.splitlines()
    if len(lines) != 2 or not lines[1].startswith("SEAM-SOURCE/1|"):
        return False
    try:
        fact = json.loads(lines[0].split("|", 1)[1])
        source = json.loads(lines[1].split("|", 1)[1])
    except (IndexError, TypeError, ValueError):
        return False
    if not isinstance(fact, dict) or not isinstance(source, dict):
        return False
    if set(fact) != {
        "claim_id",
        "object",
        "predicate",
        "source_raw_id",
        "subject",
    } or set(source) != {"id", "raw"}:
        return False
    source_id = str(fact.get("source_raw_id") or "")
    return (
        str(fact.get("claim_id") or "") == record_id
        and source_id.startswith("raw:")
        and str(source.get("id") or "") == source_id
        and isinstance(source.get("raw"), str)
        and bool(str(source["raw"]))
        and all(
            isinstance(fact.get(key), str) and bool(str(fact[key]).strip())
            for key in ("subject", "predicate", "object")
        )
    )


def _fact_source(row: Mapping[str, object]) -> tuple[str, str] | None:
    if not _valid_fact_row(row):
        return None
    source = json.loads(_memory(row).splitlines()[1].split("|", 1)[1])
    return str(source["id"]), str(source["raw"])


def parse_pack_items(row: Mapping[str, object]) -> tuple[PackItem, ...] | None:
    """Strictly parse a ``non-displacing-fact-pack/1`` result row.

    ITEM bodies are sliced by their declared character lengths.  Delimiter-like
    source text therefore cannot truncate or create a synthetic item.  Any
    malformed header, digest, item, scope, ordering, or duplicate id fails
    closed with ``None``.
    """

    memory = _memory(row)
    record_id = _record_id(row)
    if not memory.startswith(f"{NON_DISPLACING_FACT_PACK_PREFIX}|"):
        return None
    digest = hashlib.sha256(memory.encode()).hexdigest()[:16]
    if record_id != f"{_NON_DISPLACING_FACT_PACK_ID_PREFIX}{digest}":
        return None

    first_end = memory.find("\n")
    second_end = memory.find("\n", first_end + 1) if first_end >= 0 else -1
    if first_end < 0 or second_end < 0:
        return None
    header = memory[:first_end]
    header_match = re.fullmatch(
        rf"{re.escape(NON_DISPLACING_FACT_PACK_PREFIX)}\|"
        rf"policy={re.escape(NON_DISPLACING_FACT_POLICY_V1)}\|"
        r"direct_read=1\|items=(\d+)",
        header,
    )
    if header_match is None:
        return None
    if (
        memory[first_end + 1 : second_end]
        != "Context PACK: the protected RAW is the exact baseline tail; auxiliary "
        "RAW and grounded facts are additive evidence."
    ):
        return None

    expected_items = int(header_match.group(1))
    cursor = second_end + 1
    items: list[PackItem] = []
    seen_ids: set[str] = set()
    while cursor < len(memory):
        if not memory.startswith("ITEM|", cursor):
            return None
        metadata_end = memory.find("\n", cursor)
        if metadata_end < 0:
            return None
        try:
            metadata = json.loads(memory[cursor + len("ITEM|") : metadata_end])
        except (TypeError, ValueError):
            return None
        if not isinstance(metadata, dict) or set(metadata) != {"chars", "id", "scope"}:
            return None
        chars = metadata.get("chars")
        item_id = metadata.get("id")
        scope = metadata.get("scope")
        if (
            not isinstance(chars, int)
            or isinstance(chars, bool)
            or chars < 0
            or not isinstance(item_id, str)
            or not item_id
            or item_id in seen_ids
            or not isinstance(scope, str)
            or scope not in _NON_DISPLACING_FACT_SCOPES
        ):
            return None
        body_start = metadata_end + 1
        body_end = body_start + chars
        marker = "\nEND-ITEM"
        if body_end > len(memory) or memory[body_end : body_end + len(marker)] != marker:
            return None
        body = memory[body_start:body_end]
        if not body:
            return None
        cursor = body_end + len(marker)
        if cursor < len(memory):
            if memory[cursor] != "\n":
                return None
            cursor += 1
        seen_ids.add(item_id)
        items.append(PackItem(scope=scope, record_id=item_id, memory=body))

    if len(items) != expected_items or not items:
        return None
    scopes = [item.scope for item in items]
    if (
        scopes[0] != "raw_protected"
        or scopes.count("raw_protected") != 1
        or scopes.count("raw_source") != 1
        or scopes.count("grounded_fact") != 1
        or scopes.count("raw_episode") > 4
        or scopes
        != [
            "raw_protected",
            "raw_source",
            *(["raw_episode"] * scopes.count("raw_episode")),
            "grounded_fact",
        ]
    ):
        return None
    for item in items:
        candidate = {"id": item.record_id, "memory": item.memory}
        if item.scope == "grounded_fact":
            if not _valid_fact_row(candidate):
                return None
        elif not _valid_raw_row(candidate):
            return None
    source_item = items[1]
    fact_item = items[-1]
    fact_source = _fact_source(
        {"id": fact_item.record_id, "memory": fact_item.memory}
    )
    if (
        fact_source is None
        or fact_source[0] != source_item.record_id
        or fact_source[1] != source_item.memory
    ):
        return None
    return tuple(items)


def expand_logical_raw_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, str]] | None:
    """Expand physical result rows into their logical RAW id/text sequence."""

    expanded: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    pack_seen = False
    for index, row in enumerate(rows):
        memory = _memory(row)
        if memory.startswith(f"{NON_DISPLACING_FACT_PACK_PREFIX}|"):
            if pack_seen or index != len(rows) - 1:
                return None
            pack_seen = True
            items = parse_pack_items(row)
            if items is None:
                return None
            raw_items = [
                item
                for item in items
                if item.scope in {"raw_protected", "raw_source", "raw_episode"}
            ]
            for item in raw_items:
                if item.record_id in seen_ids:
                    return None
                seen_ids.add(item.record_id)
                expanded.append({"id": item.record_id, "memory": item.memory})
            continue
        if not _valid_raw_row(row):
            return None
        record_id = _record_id(row)
        if record_id in seen_ids:
            return None
        seen_ids.add(record_id)
        expanded.append({"id": record_id, "memory": memory})
    return expanded


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


def compose_non_displacing_fact_pack(
    baseline_rows: list[dict],
    auxiliary_rows: Sequence[dict],
    fact_rows: Sequence[dict],
    *,
    limit: int,
    policy: str = POLICY_OFF,
    fact_limit: int = 1,
    novel_raw_limit: int = 3,
    max_pack_chars: int = DEFAULT_MAX_PACK_CHARS,
) -> list[dict]:
    """Attach one sourced fact and bounded novel RAWs without losing baseline RAW.

    This pure artifact-replay primitive intentionally has no facade wiring.  The
    exact auxiliary source RAW precedes the fact even when its text duplicates
    baseline evidence.  The live runtime cannot use this until RAW-primary
    retrieval is isolated from the derived-fact auxiliary lane.
    """

    resolved = str(policy or POLICY_OFF).strip().lower() or POLICY_OFF
    if resolved not in NON_DISPLACING_FACT_POLICIES:
        raise ValueError(f"unknown non-displacing fact pack policy {resolved!r}")
    if resolved == POLICY_OFF:
        return baseline_rows
    if (
        not isinstance(fact_limit, int)
        or isinstance(fact_limit, bool)
        or fact_limit not in {0, 1}
    ):
        raise ValueError("fact_limit must be zero or one")
    if (
        not isinstance(novel_raw_limit, int)
        or isinstance(novel_raw_limit, bool)
        or not 0 <= novel_raw_limit <= 4
    ):
        raise ValueError("novel_raw_limit must be between zero and four")
    if max_pack_chars <= 0:
        raise ValueError("max_pack_chars must be positive")
    if limit <= 0:
        return []

    bounded = baseline_rows[:limit]
    fallback = baseline_rows if len(baseline_rows) <= limit else bounded
    if not bounded:
        return fallback
    if any(not _valid_raw_row(row) for row in bounded):
        return fallback
    baseline_ids = [_record_id(row) for row in bounded]
    if len(set(baseline_ids)) != len(baseline_ids):
        return fallback
    if any(not _valid_fact_row(row) for row in fact_rows):
        return fallback
    if any(not _valid_raw_row(row) for row in auxiliary_rows):
        return fallback
    if fact_limit == 0:
        return fallback

    selected_fact: Mapping[str, object] | None = None
    seen_fact_rows: set[tuple[str, str]] = set()
    for row in fact_rows:
        key = (_record_id(row), _memory(row))
        if key in seen_fact_rows:
            continue
        seen_fact_rows.add(key)
        selected_fact = row
        break
    if selected_fact is None:
        return fallback
    fact_source = _fact_source(selected_fact)
    if fact_source is None:
        return fallback
    source_id, source_memory = fact_source
    matching_sources = [
        row for row in auxiliary_rows if _record_id(row) == source_id
    ]
    if (
        not matching_sources
        or any(_memory(row) != source_memory for row in matching_sources)
        or source_id in baseline_ids
    ):
        return fallback
    source_row = matching_sources[0]

    baseline_id_set = set(baseline_ids)
    baseline_memories = {
        " ".join(_memory(row).casefold().split()) for row in bounded
    }
    selected_auxiliary: list[Mapping[str, object]] = []
    seen_auxiliary_ids = {*baseline_id_set, source_id}
    seen_auxiliary_memories = {
        *baseline_memories,
        " ".join(source_memory.casefold().split()),
    }
    if novel_raw_limit:
        for row in auxiliary_rows:
            record_id = _record_id(row)
            normalized_memory = " ".join(_memory(row).casefold().split())
            if (
                record_id in seen_auxiliary_ids
                or normalized_memory in seen_auxiliary_memories
            ):
                continue
            seen_auxiliary_ids.add(record_id)
            seen_auxiliary_memories.add(normalized_memory)
            selected_auxiliary.append(row)
            if len(selected_auxiliary) >= novel_raw_limit:
                break

    protected = bounded[-1]
    prefix_items: list[tuple[str, Mapping[str, object]]] = [
        ("raw_protected", protected),
        ("raw_source", source_row),
    ]
    required_items = [*prefix_items, ("grounded_fact", selected_fact)]
    if len(_render_non_displacing_fact_pack(required_items)) > max_pack_chars:
        return fallback
    accepted_auxiliary: list[Mapping[str, object]] = []
    for row in selected_auxiliary:
        trial = [
            *prefix_items,
            *[("raw_episode", item) for item in accepted_auxiliary],
            ("raw_episode", row),
            ("grounded_fact", selected_fact),
        ]
        if len(_render_non_displacing_fact_pack(trial)) > max_pack_chars:
            continue
        accepted_auxiliary.append(row)
    items = [
        *prefix_items,
        *[("raw_episode", row) for row in accepted_auxiliary],
        ("grounded_fact", selected_fact),
    ]

    body = _render_non_displacing_fact_pack(items)
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    try:
        protected_score = float(protected.get("score") or 0.0)
    except (TypeError, ValueError):
        return fallback
    pack_row = {
        "memory": body,
        "score": protected_score,
        "id": f"{_NON_DISPLACING_FACT_PACK_ID_PREFIX}{digest}",
        "created_at": protected.get("created_at", ""),
    }
    composed = [*bounded[:-1], pack_row]

    logical = expand_logical_raw_rows(composed)
    expected_baseline = [
        {"id": _record_id(row), "memory": _memory(row)} for row in bounded
    ]
    if logical is None or logical[: len(expected_baseline)] != expected_baseline:
        return fallback
    return composed


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
