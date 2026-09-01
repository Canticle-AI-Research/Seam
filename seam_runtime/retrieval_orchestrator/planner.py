from __future__ import annotations

import re
from datetime import datetime

from seam_runtime.temporal import normalize_datetime, normalize_timestamp

from .types import QueryFilters, QueryIntent, RetrievalLeg, RetrievalPlan

FILTER_PATTERN = re.compile(r"\b(?P<key>id|kind|ns|scope|predicate|subject|object):(?P<value>[^\s]+)")


RETRIEVAL_MODES = {"vector", "graph", "hybrid", "mix"}
RANKING_POLICIES = {"legacy-weighted/1", "reciprocal-rank-fusion/2"}


def _utc_naive(value: datetime) -> datetime:
    """Normalize an aware query timestamp to the store's UTC-naive contract."""

    return normalize_datetime(value)


def build_plan(
    query: str,
    scope: str | None = None,
    budget: int = 5,
    mode: str = "hybrid",
    *,
    namespace: str | None = None,
    graph_hops: int = 1,
    semantic_graph_seeding: bool = False,
    graph_at: str | None = None,
    graph_include_history: bool = False,
    lens: str = "general",
    include_raw: bool = False,
    temporal_window: tuple[datetime, datetime] | None = None,
    temporal_reference: datetime | None = None,
    ranking_policy: str = "reciprocal-rank-fusion/2",
) -> RetrievalPlan:
    mode = mode.lower().strip() or "hybrid"
    if mode not in RETRIEVAL_MODES:
        raise ValueError(f"Unsupported retrieval mode: {mode}")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("retrieval budget must be an integer")
    if budget < 1:
        raise ValueError("retrieval budget must be positive")
    if isinstance(graph_hops, bool) or not isinstance(graph_hops, int):
        raise TypeError("graph_hops must be an integer")
    if not 0 <= graph_hops <= 3:
        raise ValueError("graph_hops must be between 0 and 3")
    if not isinstance(semantic_graph_seeding, bool):
        raise TypeError("semantic_graph_seeding must be a boolean")
    if graph_at is not None:
        if not isinstance(graph_at, str) or not graph_at.strip():
            raise ValueError("graph_at must be a non-empty timestamp string when provided")
        if normalize_timestamp(graph_at) is None:
            raise ValueError("graph_at must be a valid ISO-8601 timestamp")
    if not isinstance(graph_include_history, bool):
        raise TypeError("graph_include_history must be a boolean")
    if not isinstance(lens, str) or not lens.strip():
        raise ValueError("retrieval lens must be a non-empty string")
    if not isinstance(include_raw, bool):
        raise TypeError("include_raw must be a boolean")
    if ranking_policy not in RANKING_POLICIES:
        raise ValueError(f"Unsupported retrieval ranking policy: {ranking_policy}")
    if temporal_window is not None:
        if (
            not isinstance(temporal_window, tuple)
            or len(temporal_window) != 2
            or not all(isinstance(value, datetime) for value in temporal_window)
        ):
            raise TypeError("temporal_window must be a pair of datetimes")
        temporal_window = tuple(_utc_naive(value) for value in temporal_window)
        if temporal_window[0] > temporal_window[1]:
            raise ValueError("temporal_window start must not follow its end")
    if temporal_reference is not None and not isinstance(
        temporal_reference, datetime
    ):
        raise TypeError("temporal_reference must be a datetime")
    if temporal_reference is not None:
        temporal_reference = _utc_naive(temporal_reference)
    filters = _extract_filters(query, scope=scope, namespace=namespace)
    normalized_query = _strip_filters(query)
    intent = _classify_intent(filters, normalized_query, mode)
    leg_limit = max(budget * 2, 5) if mode in {"hybrid", "mix"} else max(budget, 5)
    legs: list[RetrievalLeg] = []

    if ranking_policy == "legacy-weighted/1":
        legs.append(
            RetrievalLeg(
                name="legacy_weighted",
                # The original path bounded both its returned candidates and
                # vector top-K from this same requested depth.  Keep that
                # exact relationship while it serves as the behavioral
                # control for the graph ablation.
                limit=budget,
                rationale=(
                    "Preserve the versioned RAW/BM25/vector weighted baseline "
                    "inside the canonical retrieval engine"
                ),
            )
        )
    else:
        # An explicit mode="vector" means semantic-only: never inject the sql
        # leg, even when a pure-filter query classifies as STRUCTURED.
        if mode in {"hybrid", "mix"} or (
            intent == QueryIntent.STRUCTURED and mode != "vector"
        ):
            legs.append(
                RetrievalLeg(
                    name="sql",
                    limit=leg_limit,
                    rationale="Apply explicit field filters and lexical matching",
                )
            )
        if mode in {"vector", "hybrid", "mix"}:
            legs.append(
                RetrievalLeg(
                    name="vector",
                    limit=leg_limit,
                    rationale="Use embedding similarity for semantic recall",
                )
            )
        if mode in {"graph", "mix"}:
            legs.append(
                RetrievalLeg(
                    name="graph",
                    limit=leg_limit,
                    rationale=(
                        "Expand through MIRL entity/relation/provenance edges"
                    ),
                )
            )
        if temporal_window is not None or temporal_reference is not None:
            legs.append(
                RetrievalLeg(
                    name="temporal",
                    limit=leg_limit,
                    rationale=(
                        "Rank timestamped MIRL records against the explicit "
                        "temporal query context"
                    ),
                )
            )

    return RetrievalPlan(
        query=query,
        normalized_query=normalized_query,
        intent=intent,
        filters=filters,
        legs=legs,
        mode=mode,
        graph_hops=graph_hops,
        semantic_graph_seeding=semantic_graph_seeding,
        graph_at=graph_at,
        graph_include_history=graph_include_history,
        lens=lens.strip(),
        include_raw=include_raw,
        temporal_window=temporal_window,
        temporal_reference=temporal_reference,
        ranking_policy=ranking_policy,
    )


def _extract_filters(
    query: str,
    scope: str | None = None,
    namespace: str | None = None,
) -> QueryFilters:
    filters = QueryFilters(scope=scope, namespace=namespace)
    for match in FILTER_PATTERN.finditer(query):
        key = match.group("key")
        value = match.group("value")
        if key == "id":
            filters.ids.extend(_split_csv(value))
        elif key == "kind":
            filters.kinds.extend(item.upper() for item in _split_csv(value))
        elif key == "ns":
            if namespace is not None and value != namespace:
                raise ValueError("query namespace conflicts with the retrieval boundary")
            filters.namespace = value
        elif key == "scope":
            if scope is not None and value != scope:
                raise ValueError("query scope conflicts with the retrieval boundary")
            filters.scope = value
        elif key == "predicate":
            filters.predicate = value
        elif key == "subject":
            filters.subject = value
        elif key == "object":
            filters.object_text = value
    if len(filters.ids) > 64:
        raise ValueError("retrieval supports at most 64 id filters")
    if len(filters.kinds) > 32:
        raise ValueError("retrieval supports at most 32 kind filters")
    return filters


def _strip_filters(query: str) -> str:
    stripped = FILTER_PATTERN.sub(" ", query)
    return " ".join(part for part in stripped.split() if part)


def _classify_intent(filters: QueryFilters, normalized_query: str, mode: str) -> QueryIntent:
    if mode == "graph":
        return QueryIntent.GRAPH
    if mode == "mix":
        return QueryIntent.MIX
    has_filters = filters.active()
    semantic_terms = len(normalized_query.split())
    if has_filters and semantic_terms:
        return QueryIntent.HYBRID
    if has_filters:
        return QueryIntent.STRUCTURED
    return QueryIntent.SEMANTIC


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
