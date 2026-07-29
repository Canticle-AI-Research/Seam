"""Deterministic, provenance-preserving G5 context assembly.

This module is intentionally storage-agnostic. Retrieval and graph-product
adapters offer already-resolved candidates; the assembler independently
enforces boundary, trust, time, provenance, and token-budget contracts before
emitting a disposable context PACK.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from .mirl import token_count

CONTEXT_ASSEMBLY_SCHEMA_VERSION = 1
CONTEXT_ASSEMBLY_CONTRACT_VERSION = "context-assembly/1"
CONTEXT_KINDS = frozenset(
    {
        "fact",
        "entity",
        "episode",
        "entity_summary",
        "community_summary",
        "observation",
    }
)
DERIVED_CONTEXT_KINDS = frozenset(
    {"entity_summary", "community_summary", "observation"}
)
ASSERTABLE_TRUST_STATES = frozenset({"supported", "verified"})
_TRUST_RANK = {"verified": 2, "supported": 1}
_KIND_RANK = {
    "fact": 0,
    "entity": 1,
    "episode": 2,
    "observation": 3,
    "entity_summary": 4,
    "community_summary": 5,
}
_TERM_RE = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """One context unit with an exact route back to canonical evidence.

    ``occurred_at`` and ``valid_until`` must be timezone-aware ISO-8601 values.
    The end of the validity interval is exclusive. Derived G4 products must
    carry ``product_id`` in addition to their exact source record and episode
    references.
    """

    candidate_id: str
    kind: str
    text: str
    namespace: str
    scope: str
    trust_state: str
    record_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    occurred_at: str
    entity_ids: tuple[str, ...] = ()
    product_id: str | None = None
    task_tags: tuple[str, ...] = ()
    valid_until: str | None = None
    current: bool = True


@dataclass(frozen=True, slots=True)
class PackedContextItem:
    candidate_id: str
    kind: str
    text: str
    trust_state: str
    occurred_at: str
    record_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    product_id: str | None
    task_score: int


@dataclass(frozen=True, slots=True)
class ContextPack:
    contract_version: str
    schema_version: int
    task: str
    namespace: str
    scope: str
    as_of: str
    token_budget: int
    token_cost: int
    fact_reserve_tokens: int
    items: tuple[PackedContextItem, ...]
    omitted_candidate_ids: tuple[str, ...]
    rejected_counts: tuple[tuple[str, int], ...]
    rendered: str

    @property
    def refs(self) -> tuple[str, ...]:
        """Canonical MIRL record refs represented by the selected items."""

        return tuple(
            sorted({record_id for item in self.items for record_id in item.record_ids})
        )

    @property
    def backtraces(self) -> tuple[dict[str, object], ...]:
        """Exact record/episode routes, in rendered-item order."""

        return tuple(
            {
                "candidate_id": item.candidate_id,
                "record_ids": item.record_ids,
                "episode_ids": item.episode_ids,
                "entity_ids": item.entity_ids,
                "product_id": item.product_id,
            }
            for item in self.items
        )


@dataclass(frozen=True, slots=True)
class _EligibleCandidate:
    item: PackedContextItem
    sort_key: tuple[object, ...]
    fingerprint: str


def assemble_context(
    candidates: Iterable[ContextCandidate],
    *,
    task: str,
    namespace: str,
    scope: str,
    as_of: str,
    token_budget: int,
    fact_reserve_tokens: int = 0,
    token_counter: Callable[[str], int] = token_count,
) -> ContextPack:
    """Build one deterministic G5 context PACK.

    Grounded facts receive the configured reservation before any entity,
    episode, summary, or observation can consume it. Remaining facts then
    compete normally for the unreserved budget. Candidate text is never
    partially truncated: a whole item and its exact backtrace fit, or the item
    is reported as omitted.
    """

    normalized_task = _required(task, "task")
    ns = _required(namespace, "namespace")
    selected_scope = _required(scope, "scope")
    time_view, normalized_as_of = _parse_time(as_of, "as_of")
    if not isinstance(token_budget, int) or isinstance(token_budget, bool):
        raise TypeError("token_budget must be an integer")
    if token_budget < 1:
        raise ValueError("token_budget must be positive")
    if not isinstance(fact_reserve_tokens, int) or isinstance(
        fact_reserve_tokens, bool
    ):
        raise TypeError("fact_reserve_tokens must be an integer")
    if fact_reserve_tokens < 0:
        raise ValueError("fact_reserve_tokens must be non-negative")
    if not callable(token_counter):
        raise TypeError("token_counter must be callable")

    header = _render_header(
        task=normalized_task,
        namespace=ns,
        scope=selected_scope,
        as_of=normalized_as_of,
    )
    header_cost = _count(token_counter, header)
    if header_cost > token_budget:
        raise ValueError(
            "token_budget is too small for the context-assembly header"
        )

    rejected: Counter[str] = Counter()
    grouped: dict[str, list[_EligibleCandidate]] = defaultdict(list)
    for candidate in candidates:
        eligible, reason = _eligible_candidate(
            candidate,
            task=normalized_task,
            namespace=ns,
            scope=selected_scope,
            as_of=time_view,
        )
        if eligible is None:
            rejected[reason] += 1
            continue
        grouped[eligible.item.candidate_id].append(eligible)

    eligible_candidates: list[_EligibleCandidate] = []
    for candidate_id in sorted(grouped):
        variants = grouped[candidate_id]
        fingerprints = {variant.fingerprint for variant in variants}
        if len(fingerprints) != 1:
            rejected["conflicting_candidate_id"] += len(variants)
            continue
        eligible_candidates.append(min(variants, key=lambda item: item.sort_key))
        if len(variants) > 1:
            rejected["duplicate_candidate"] += len(variants) - 1

    ranked = sorted(eligible_candidates, key=lambda item: item.sort_key)
    fact_lane = [item for item in ranked if item.item.kind == "fact"]
    selected: list[_EligibleCandidate] = []
    selected_ids: set[str] = set()
    selected_lines: list[str] = []
    conservative_cost = header_cost
    line_cache: dict[str, tuple[str, int]] = {}
    reserve_limit = min(
        token_budget, header_cost + min(fact_reserve_tokens, token_budget - header_cost)
    )

    def try_select(candidate: _EligibleCandidate, limit: int) -> bool:
        nonlocal conservative_cost
        candidate_id = candidate.item.candidate_id
        cached = line_cache.get(candidate_id)
        if cached is None:
            line = f"ITEM|{_canonical_json(_item_payload(candidate.item))}"
            cached = (line, _count(token_counter, f"\n{line}"))
            line_cache[candidate_id] = cached
        line, line_cost = cached
        upper_bound = conservative_cost + line_cost
        if upper_bound > limit:
            proposed_render = "\n".join([header, *selected_lines, line])
            if _count(token_counter, proposed_render) > limit:
                return False
        selected.append(candidate)
        selected_lines.append(line)
        selected_ids.add(candidate_id)
        conservative_cost = upper_bound
        return True

    for candidate in fact_lane:
        try_select(candidate, reserve_limit)

    for candidate in ranked:
        if candidate.item.candidate_id in selected_ids:
            continue
        try_select(candidate, token_budget)

    rendered = "\n".join([header, *selected_lines])
    final_cost = _count(token_counter, rendered)
    if final_cost > token_budget:  # Defensive check for stateful counters.
        raise ValueError("token_counter produced an unstable budget result")
    omitted = tuple(
        item.item.candidate_id
        for item in ranked
        if item.item.candidate_id not in selected_ids
    )
    return ContextPack(
        contract_version=CONTEXT_ASSEMBLY_CONTRACT_VERSION,
        schema_version=CONTEXT_ASSEMBLY_SCHEMA_VERSION,
        task=normalized_task,
        namespace=ns,
        scope=selected_scope,
        as_of=normalized_as_of,
        token_budget=token_budget,
        token_cost=final_cost,
        fact_reserve_tokens=fact_reserve_tokens,
        items=tuple(item.item for item in selected),
        omitted_candidate_ids=omitted,
        rejected_counts=tuple(sorted(rejected.items())),
        rendered=rendered,
    )


def _eligible_candidate(
    candidate: ContextCandidate,
    *,
    task: str,
    namespace: str,
    scope: str,
    as_of: datetime,
) -> tuple[_EligibleCandidate | None, str]:
    if not isinstance(candidate, ContextCandidate):
        return None, "malformed"
    try:
        candidate_id = _required(candidate.candidate_id, "candidate_id")
        kind = _required(candidate.kind, "kind").lower()
        text = _required(candidate.text, "text")
        candidate_namespace = _required(candidate.namespace, "candidate namespace")
        candidate_scope = _required(candidate.scope, "candidate scope")
        trust_state = _required(candidate.trust_state, "trust_state").lower()
        record_ids = _refs(candidate.record_ids, "record_ids")
        episode_ids = _refs(candidate.episode_ids, "episode_ids")
        entity_ids = _optional_refs(candidate.entity_ids, "entity_ids")
        task_tags = _optional_refs(candidate.task_tags, "task_tags")
        occurred_at, occurred_text = _parse_time(
            candidate.occurred_at, "occurred_at"
        )
        valid_until: datetime | None = None
        valid_until_text: str | None = None
        if candidate.valid_until is not None:
            valid_until, valid_until_text = _parse_time(
                candidate.valid_until, "valid_until"
            )
        product_id = (
            _required(candidate.product_id, "product_id")
            if candidate.product_id is not None
            else None
        )
    except (TypeError, ValueError):
        return None, "malformed"

    if candidate_namespace != namespace or candidate_scope != scope:
        return None, "boundary"
    if kind not in CONTEXT_KINDS:
        return None, "kind"
    if trust_state not in ASSERTABLE_TRUST_STATES:
        return None, "trust"
    if not candidate.current:
        return None, "not_current"
    if occurred_at > as_of or (
        valid_until is not None and valid_until <= as_of
    ):
        return None, "time"
    if kind in DERIVED_CONTEXT_KINDS and product_id is None:
        return None, "derived_without_product"

    task_score = _task_score(task, text, task_tags)
    item = PackedContextItem(
        candidate_id=candidate_id,
        kind=kind,
        text=text,
        trust_state=trust_state,
        occurred_at=occurred_text,
        record_ids=record_ids,
        episode_ids=episode_ids,
        entity_ids=entity_ids,
        product_id=product_id,
        task_score=task_score,
    )
    fingerprint = _canonical_json(_item_payload(item))
    timestamp = occurred_at.timestamp()
    sort_key = (
        -_TRUST_RANK[trust_state],
        -task_score,
        -timestamp,
        _KIND_RANK[kind],
        candidate_id,
        fingerprint,
    )
    return _EligibleCandidate(item, sort_key, fingerprint), ""


def _render_header(
    *,
    task: str,
    namespace: str,
    scope: str,
    as_of: str,
) -> str:
    return (
        "SEAM-CONTEXT/1|"
        + _canonical_json(
            {
                "as_of": as_of,
                "contract": CONTEXT_ASSEMBLY_CONTRACT_VERSION,
                "namespace": namespace,
                "schema_version": CONTEXT_ASSEMBLY_SCHEMA_VERSION,
                "scope": scope,
                "task": task,
            }
        )
    )


def _item_payload(item: PackedContextItem) -> dict[str, object]:
    return {
        "candidate_id": item.candidate_id,
        "entity_ids": item.entity_ids,
        "episode_ids": item.episode_ids,
        "kind": item.kind,
        "occurred_at": item.occurred_at,
        "product_id": item.product_id,
        "record_ids": item.record_ids,
        "task_score": item.task_score,
        "text": item.text,
        "trust_state": item.trust_state,
    }


def _task_score(task: str, text: str, task_tags: tuple[str, ...]) -> int:
    task_terms = set(_terms(task))
    if not task_terms:
        return 0
    content_terms = set(_terms(text))
    content_terms.update(term for tag in task_tags for term in _terms(tag))
    return len(task_terms & content_terms)


def _terms(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TERM_RE.finditer(value))


def _parse_time(value: object, field: str) -> tuple[datetime, str]:
    text = _required(value, field)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    normalized = parsed.astimezone(timezone.utc)
    return normalized, normalized.isoformat().replace("+00:00", "Z")


def _refs(values: object, field: str) -> tuple[str, ...]:
    refs = _optional_refs(values, field)
    if not refs:
        raise ValueError(f"{field} must not be empty")
    return refs


def _optional_refs(values: object, field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or values is None:
        raise TypeError(f"{field} must be a tuple of strings")
    try:
        refs = tuple(sorted({_required(value, field) for value in values}))
    except TypeError as exc:
        raise TypeError(f"{field} must be an iterable of strings") from exc
    return refs


def _required(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _count(token_counter: Callable[[str], int], rendered: str) -> int:
    result = token_counter(rendered)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError("token_counter must return a non-negative integer")
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
