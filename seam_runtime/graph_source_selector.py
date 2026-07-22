"""Query-conditioned graph -> source-RAW selector with multi-node agreement.

The legacy graph retrieval leg (``SQLiteGraphAdapter``) seeds lexically, expands
immediate neighbors, and scores lexical overlap plus a degree bonus.  It never
uses the fact that ``knowledge_edges`` carry a ``source_record_id`` and that
``knowledge_edge_episodes`` map edges to immutable RAW episodes.  That means a
single noisy adjacency can promote a source RAW as readily as genuinely
corroborated evidence.

This module adds a separate, auditable selector that returns *exact source RAW
record ids* only when at least ``min_agreement`` distinct query-matched graph
nodes independently corroborate the same RAW episode through current, in-scope
edges.  It invents no source text: it returns ids plus a deterministic evidence
trace (seed nodes, supporting edges, episode ids, source record ids, agreement
count, and a stable score/tie order).  Resolving the returned ids back to RAW
memory text stays with the caller so the primary RAW lane owns the wording.

The selector is pure over a SQLite connection and never mutates the graph.  It
is intentionally not wired into the default retrieval path; a default-off caller
composes the selected RAW ids into a non-displacing PACK.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

# Lifecycle statuses that remove an edge, episode, or node from the current
# view.  Mirrors the exclusion set used by ``SQLiteGraphAdapter`` so this lane
# agrees with the dashboard's current-state semantics.
EXCLUDED_STATUSES = (
    "contradicted",
    "superseded",
    "deprecated",
    "deleted_soft",
    "refuted",
    "stale",
)

# Only query-named *concept* nodes may seed corroboration.  The content-bearing
# record kinds -- ``source`` (RAW), ``evidence`` (SPAN), ``claim`` (CLM), and
# ``provenance`` -- carry the observation/assertion text itself, and the current
# projection embeds that text in their labels.  Seeding on them would let a
# single turn's own content match every query token and inflate "agreement" into
# plain token presence.  Restricting seeds to concept kinds keeps agreement a
# count of distinct query concepts that independently ground the same RAW.
CONCEPT_SEED_KINDS = (
    "entity",
    "value",
    "agent",
    "event",
    "state",
    "relation",
    "symbol",
)

# Node kinds whose *label* is a short concept name safe to lexically match.
# Entity/relation/event/state labels can embed the originating turn text in the
# current projection, so those kinds are matched on their id (which carries the
# canonical surface form, e.g. ``ent:<hash>:alice:<turn>``) instead.  This keeps
# a single content-bearing label from covering unrelated query tokens.
_LABEL_SAFE_KINDS = frozenset({"value", "agent", "symbol"})

_DEFAULT_MIN_AGREEMENT = 2
_DEFAULT_LIMIT = 3
_DEFAULT_MAX_SEEDS = 200
_TOKEN_RE = re.compile(r"[a-z0-9_:-]+")


@dataclass(frozen=True)
class GraphSourcePath:
    """One independent (seed -> edge -> episode -> source RAW) support path."""

    seed_id: str
    edge_id: str
    predicate: str
    episode_id: str
    source_record_id: str


@dataclass(frozen=True)
class GraphSourceSelection:
    """A source RAW corroborated across >= ``min_agreement`` distinct query terms.

    ``agreement`` is the number of *distinct query tokens* that a supporting
    seed node covers, so one real-world concept represented by several nodes
    cannot inflate it.  ``seed_ids``/``edge_ids``/``paths`` carry the auditable
    provenance behind that count.
    """

    source_record_id: str
    agreement: int
    edge_count: int
    covered_tokens: tuple[str, ...]
    seed_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    score: float
    paths: tuple[GraphSourcePath, ...] = field(default_factory=tuple)


def tokenize_query(text: str) -> list[str]:
    """Lowercase, deduplicated query tokens (same shape as the graph adapter)."""

    seen: dict[str, None] = {}
    for token in _TOKEN_RE.findall(str(text).lower()):
        seen.setdefault(token, None)
    return list(seen)


def _seed_nodes(
    connection: sqlite3.Connection,
    tokens: Sequence[str],
    *,
    ns: str | None,
    scope: str | None,
    max_seeds: int,
) -> dict[str, frozenset[str]]:
    """Return ``{seed_node_id: covered query tokens}`` for concept nodes.

    A token is attributed to a node only through a trustworthy field: the node
    id for every kind, plus the label for short concept kinds
    (``_LABEL_SAFE_KINDS``).  Nodes with no attributed token are dropped.
    """

    if not tokens:
        return {}
    where = [
        f"status not in ({','.join('?' for _ in EXCLUDED_STATUSES)})",
        f"kind in ({','.join('?' for _ in CONCEPT_SEED_KINDS)})",
    ]
    params: list[object] = [*EXCLUDED_STATUSES, *CONCEPT_SEED_KINDS]
    if ns is not None:
        where.append("ns = ?")
        params.append(ns)
    if scope is not None:
        where.append("scope = ?")
        params.append(scope)
    token_clauses = []
    for token in tokens:
        token_clauses.append("instr(lower(id), ?) > 0 or instr(lower(label), ?) > 0")
        params.extend([token, token])
    where.append("(" + " or ".join(token_clauses) + ")")
    sql = (
        "select id, label, kind from knowledge_nodes "
        f"where {' and '.join(where)} "
        "order by id limit ?"
    )
    params.append(max_seeds)
    rows = connection.execute(sql, params).fetchall()
    seeds: dict[str, frozenset[str]] = {}
    for row in rows:
        node_id = str(row["id"])
        node_id_lower = node_id.lower()
        label_lower = str(row["label"] or "").lower()
        label_safe = str(row["kind"] or "") in _LABEL_SAFE_KINDS
        matched = {
            token
            for token in tokens
            if token in node_id_lower or (label_safe and token in label_lower)
        }
        if matched:
            seeds[node_id] = frozenset(matched)
    return seeds


def _support_paths(
    connection: sqlite3.Connection,
    seed_ids: Sequence[str],
    *,
    ns: str | None,
    scope: str | None,
) -> list[GraphSourcePath]:
    if not seed_ids:
        return []
    seed_set = set(seed_ids)
    seed_placeholders = ",".join("?" for _ in seed_ids)
    status_placeholders = ",".join("?" for _ in EXCLUDED_STATUSES)
    where = [
        "e.expired_at is null",
        f"e.status not in ({status_placeholders})",
        "ep.expired_at is null",
        f"ep.status not in ({status_placeholders})",
        f"(e.src_id in ({seed_placeholders}) or e.dst_id in ({seed_placeholders}))",
    ]
    params: list[object] = [*EXCLUDED_STATUSES, *EXCLUDED_STATUSES, *seed_ids, *seed_ids]
    if ns is not None:
        where.append("e.ns = ? and ep.ns = ?")
        params.extend([ns, ns])
    if scope is not None:
        where.append("e.scope = ? and ep.scope = ?")
        params.extend([scope, scope])
    sql = (
        "select e.id as edge_id, e.src_id as src_id, e.dst_id as dst_id, "
        "e.predicate as predicate, ep.id as episode_id, "
        "ep.source_record_id as source_record_id "
        "from knowledge_edges e "
        "join knowledge_edge_episodes kee on kee.edge_id = e.id "
        "join knowledge_episodes ep on ep.id = kee.episode_id "
        f"where {' and '.join(where)}"
    )
    rows = connection.execute(sql, params).fetchall()
    paths: list[GraphSourcePath] = []
    for row in rows:
        source_record_id = str(row["source_record_id"] or "")
        edge_id = str(row["edge_id"] or "")
        episode_id = str(row["episode_id"] or "")
        predicate = str(row["predicate"] or "")
        if not source_record_id or not edge_id or not episode_id:
            continue
        # An edge can be incident to a seed on either endpoint; each distinct
        # seed endpoint is an independent corroborating node for this RAW.
        for endpoint in (str(row["src_id"] or ""), str(row["dst_id"] or "")):
            if endpoint in seed_set:
                paths.append(
                    GraphSourcePath(
                        seed_id=endpoint,
                        edge_id=edge_id,
                        predicate=predicate,
                        episode_id=episode_id,
                        source_record_id=source_record_id,
                    )
                )
    return paths


def select_graph_source_raw(
    connection: sqlite3.Connection,
    query: str,
    *,
    ns: str | None = None,
    scope: str | None = None,
    min_agreement: int = _DEFAULT_MIN_AGREEMENT,
    limit: int = _DEFAULT_LIMIT,
    max_seeds: int = _DEFAULT_MAX_SEEDS,
) -> list[GraphSourceSelection]:
    """Select source RAW ids corroborated by multiple query-matched seed nodes.

    A source RAW is returned only when at least ``min_agreement`` distinct seed
    nodes reach it through current, in-scope edges and episodes.  Results are
    ranked by agreement (distinct seeds), then supporting edge count, then
    source record id, so ties are fully deterministic.  The selector reads only;
    it never writes, and it returns ids and provenance, never source text.
    """

    if min_agreement < 1:
        raise ValueError("min_agreement must be >= 1")
    if limit <= 0:
        return []
    tokens = tokenize_query(query)
    if not tokens:
        return []
    seeds = _seed_nodes(
        connection, tokens, ns=ns, scope=scope, max_seeds=max_seeds
    )
    # Distinct query tokens can never exceed the number of seeds, and agreement
    # counts distinct tokens, so too few seeds cannot reach the threshold.
    covered_by_all_seeds = set().union(*seeds.values()) if seeds else set()
    if len(covered_by_all_seeds) < min_agreement:
        return []
    paths = _support_paths(connection, list(seeds), ns=ns, scope=scope)
    if not paths:
        return []

    by_raw: dict[str, list[GraphSourcePath]] = {}
    for path in paths:
        by_raw.setdefault(path.source_record_id, []).append(path)

    selections: list[GraphSourceSelection] = []
    for source_record_id, raw_paths in by_raw.items():
        seed_ids = tuple(sorted({path.seed_id for path in raw_paths}))
        covered = set().union(*(seeds[seed] for seed in seed_ids))
        # Agreement is the count of distinct query tokens independently
        # corroborated, so one concept represented by several nodes cannot
        # inflate a single-term match into apparent multi-node agreement.
        if len(covered) < min_agreement:
            continue
        edge_ids = tuple(sorted({path.edge_id for path in raw_paths}))
        ordered_paths = tuple(
            sorted(
                set(raw_paths),
                key=lambda p: (p.seed_id, p.edge_id, p.episode_id),
            )
        )
        # Score is a deterministic function of the evidence only: token
        # agreement dominates, supporting-edge breadth is a bounded tiebreak.
        score = float(len(covered)) + min(0.9, 0.1 * len(edge_ids))
        selections.append(
            GraphSourceSelection(
                source_record_id=source_record_id,
                agreement=len(covered),
                edge_count=len(edge_ids),
                covered_tokens=tuple(sorted(covered)),
                seed_ids=seed_ids,
                edge_ids=edge_ids,
                score=score,
                paths=ordered_paths,
            )
        )

    selections.sort(
        key=lambda s: (-s.agreement, -s.edge_count, s.source_record_id)
    )
    return selections[:limit]
