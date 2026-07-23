"""Query-conditioned graph -> source-RAW selector with concept agreement.

The legacy graph retrieval leg (``SQLiteGraphAdapter``) seeds lexically, expands
immediate neighbors, and scores lexical overlap plus a degree bonus.  It never
uses the fact that ``knowledge_edges`` carry a ``source_record_id`` and that
``knowledge_edge_episodes`` map edges to immutable RAW episodes.  That means a
single noisy adjacency can promote a source RAW as readily as genuinely
corroborated evidence.

This module adds a separate, auditable selector that returns *exact source RAW
record ids* only when at least ``min_agreement`` distinct indexed graph concepts
match distinct query terms and corroborate the same RAW episode through current,
in-scope edges. It invents no source text: it returns ids plus a deterministic
evidence trace (matched concept/token pairs, seed nodes, supporting edges,
episode ids, source record ids, agreement count, and a stable score/tie order).
Resolving the returned ids back to RAW memory text stays with the caller so the
primary RAW lane owns the wording.

The selector is pure over a SQLite connection and never mutates the graph.  It
is intentionally not wired into the default retrieval path; a default-off caller
composes the selected RAW ids into a non-displacing PACK.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from .identity_resolution import resolve_canonical
from .knowledge_graph import tokenize_graph_term

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

# Only query-named *concept* nodes may seed corroboration. The projector writes
# their explicit canonical terms and aliases to ``knowledge_node_terms``. The
# content-bearing assertion/source kinds never enter that identity index.
CONCEPT_SEED_KINDS = (
    "entity",
    "value",
    "agent",
    "symbol",
)

_DEFAULT_MIN_AGREEMENT = 2
_DEFAULT_LIMIT = 3
_DEFAULT_MAX_SEEDS = 200


@dataclass(frozen=True)
class GraphSourcePath:
    """One independent concept -> graph/mention -> episode -> RAW path."""

    seed_id: str
    path_kind: str
    edge_id: str
    predicate: str
    episode_id: str
    source_record_id: str


@dataclass(frozen=True)
class GraphSourceSelection:
    """A source RAW corroborated across independent graph concepts/query terms.

    ``agreement`` is a maximum one-to-one matching between supporting concept
    nodes and distinct query tokens. One long label cannot count as multiple
    concepts, and duplicate nodes matching the same query token cannot inflate
    the score. ``matched_pairs`` exposes the exact concept/token assignment.

    ``folded_aliases`` records ``(alias_node_id, canonical_node_id)`` pairs when
    identity resolution (graph maturity G3) collapsed an accepted-merge alias
    seed onto its canonical before corroboration. Empty on the default
    identity-unaware path, so the off-path selection is byte-identical.
    """

    source_record_id: str
    agreement: int
    edge_count: int
    covered_tokens: tuple[str, ...]
    matched_pairs: tuple[tuple[str, str], ...]
    seed_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    score: float
    paths: tuple[GraphSourcePath, ...] = field(default_factory=tuple)
    folded_aliases: tuple[tuple[str, str], ...] = ()


def tokenize_query(text: str) -> list[str]:
    """Unicode-normalized, deduplicated query tokens."""

    return list(tokenize_graph_term(text))


def _seed_nodes(
    connection: sqlite3.Connection,
    tokens: Sequence[str],
    *,
    ns: str | None,
    scope: str | None,
    max_seeds: int,
) -> dict[str, frozenset[str]]:
    """Return ``{seed_node_id: covered query tokens}`` from the term index."""

    if not tokens:
        return {}
    where = [
        f"n.status not in ({','.join('?' for _ in EXCLUDED_STATUSES)})",
        f"n.kind in ({','.join('?' for _ in CONCEPT_SEED_KINDS)})",
        f"t.token in ({','.join('?' for _ in tokens)})",
    ]
    params: list[object] = [*EXCLUDED_STATUSES, *CONCEPT_SEED_KINDS, *tokens]
    if ns is not None:
        where.append("n.ns = ? and t.ns = ?")
        params.extend([ns, ns])
    if scope is not None:
        where.append("n.scope = ? and t.scope = ?")
        params.extend([scope, scope])
    sql = (
        "select n.id, t.token from knowledge_nodes n "
        "join knowledge_node_terms t on t.node_id = n.id "
        f"where {' and '.join(where)} "
        "order by n.id, t.token limit ?"
    )
    params.append(max_seeds * max(1, len(tokens)))
    rows = connection.execute(sql, params).fetchall()
    mutable: dict[str, set[str]] = {}
    for row in rows:
        mutable.setdefault(str(row["id"]), set()).add(str(row["token"]))
    return {
        node_id: frozenset(mutable[node_id])
        for node_id in sorted(mutable)[:max_seeds]
    }


def _resolve_seed_identity(
    connection: sqlite3.Connection,
    seeds: dict[str, frozenset[str]],
    *,
    ns: str | None,
    scope: str | None,
) -> tuple[dict[str, frozenset[str]], tuple[tuple[str, str], ...]]:
    """Collapse accepted-merge alias seeds onto their canonical identity.

    Graph maturity G3: an alias node's query-matched tokens are re-attributed to
    its canonical node so an alias query reaches the canonical's evidence, and an
    alias plus its canonical stop counting as two independent concepts for one
    identity. Only ACCEPTED merges fold (``resolve_canonical`` follows accepted
    links only); merges are scope-bound, so nothing folds without a concrete
    ns/scope. Returns the remapped seeds and the ``(alias, canonical)`` pairs
    folded, for the audit trace.
    """

    remapped: dict[str, set[str]] = {}
    folded: list[tuple[str, str]] = []
    for node_id, tokens in seeds.items():
        canonical = resolve_canonical(connection, node_id, ns=ns, scope=scope)
        remapped.setdefault(canonical, set()).update(tokens)
        if canonical != node_id:
            folded.append((node_id, canonical))
    frozen = {cid: frozenset(toks) for cid, toks in remapped.items()}
    return frozen, tuple(sorted(folded))


def _maximum_concept_token_matching(
    seeds: dict[str, frozenset[str]],
) -> tuple[tuple[str, str], ...]:
    """Deterministic maximum matching between concept nodes and query tokens."""

    token_to_seed: dict[str, str] = {}

    def assign(seed_id: str, seen_tokens: set[str]) -> bool:
        for token in sorted(seeds.get(seed_id, ())):
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            incumbent = token_to_seed.get(token)
            if incumbent is None or assign(incumbent, seen_tokens):
                token_to_seed[token] = seed_id
                return True
        return False

    for seed_id in sorted(seeds):
        assign(seed_id, set())
    return tuple(sorted((seed_id, token) for token, seed_id in token_to_seed.items()))


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
                        path_kind="edge",
                        edge_id=edge_id,
                        predicate=predicate,
                        episode_id=episode_id,
                        source_record_id=source_record_id,
                    )
                )
    mention_where = [
        f"ep.status not in ({status_placeholders})",
        "ep.expired_at is null",
        f"ne.node_id in ({seed_placeholders})",
    ]
    mention_params: list[object] = [*EXCLUDED_STATUSES, *seed_ids]
    if ns is not None:
        mention_where.append("ep.ns = ?")
        mention_params.append(ns)
    if scope is not None:
        mention_where.append("ep.scope = ?")
        mention_params.append(scope)
    mention_rows = connection.execute(
        "select ne.node_id as node_id, ep.id as episode_id, "
        "ep.source_record_id as source_record_id "
        "from knowledge_node_episodes ne "
        "join knowledge_episodes ep on ep.id = ne.episode_id "
        f"where {' and '.join(mention_where)}",
        mention_params,
    ).fetchall()
    for row in mention_rows:
        seed_id = str(row["node_id"] or "")
        episode_id = str(row["episode_id"] or "")
        source_record_id = str(row["source_record_id"] or "")
        if not seed_id or not episode_id or not source_record_id:
            continue
        material = "\x1f".join((seed_id, episode_id, source_record_id))
        paths.append(
            GraphSourcePath(
                seed_id=seed_id,
                path_kind="mention",
                edge_id=f"mention:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}",
                predicate="mentions",
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
    resolve_identity: bool = False,
) -> list[GraphSourceSelection]:
    """Select source RAW ids corroborated by multiple query-matched seed nodes.

    A source RAW is returned only when a one-to-one matching of at least
    ``min_agreement`` concept nodes and query tokens reaches it through current,
    in-scope edges and episodes. Results are ranked by agreement, then supporting edge count, then
    source record id, so ties are fully deterministic.  The selector reads only;
    it never writes, and it returns ids and provenance, never source text.

    When ``resolve_identity`` is set (graph maturity G3), accepted-merge alias
    seeds are folded onto their canonical identity before corroboration so an
    alias query reaches the canonical's evidence. Default-off: with the flag
    unset, or with no accepted merges, the result is byte-identical to the
    identity-unaware path.
    """

    if min_agreement < 1:
        raise ValueError("min_agreement must be >= 1")
    if max_seeds < 0:
        raise ValueError("max_seeds must be >= 0")
    if limit <= 0 or max_seeds == 0:
        return []
    tokens = tokenize_query(query)
    if not tokens:
        return []
    seeds = _seed_nodes(
        connection, tokens, ns=ns, scope=scope, max_seeds=max_seeds
    )
    folded_pairs: tuple[tuple[str, str], ...] = ()
    if resolve_identity:
        seeds, folded_pairs = _resolve_seed_identity(
            connection, seeds, ns=ns, scope=scope
        )
    if len(_maximum_concept_token_matching(seeds)) < min_agreement:
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
        matched_pairs = _maximum_concept_token_matching(
            {seed_id: seeds[seed_id] for seed_id in seed_ids}
        )
        agreement = len(matched_pairs)
        if agreement < min_agreement:
            continue
        covered = {token for _, token in matched_pairs}
        edge_ids = tuple(sorted({path.edge_id for path in raw_paths}))
        ordered_paths = tuple(
            sorted(
                set(raw_paths),
                key=lambda p: (p.seed_id, p.edge_id, p.episode_id),
            )
        )
        # Score is a deterministic function of the evidence only: token
        # agreement dominates, supporting-edge breadth is a bounded tiebreak.
        score = float(agreement) + min(0.9, 0.1 * len(edge_ids))
        seed_set = set(seed_ids)
        selection_folded = tuple(
            (alias, canonical)
            for alias, canonical in folded_pairs
            if canonical in seed_set
        )
        selections.append(
            GraphSourceSelection(
                source_record_id=source_record_id,
                agreement=agreement,
                edge_count=len(edge_ids),
                covered_tokens=tuple(sorted(covered)),
                matched_pairs=matched_pairs,
                seed_ids=seed_ids,
                edge_ids=edge_ids,
                score=score,
                paths=ordered_paths,
                folded_aliases=selection_folded,
            )
        )

    selections.sort(
        key=lambda s: (-s.agreement, -s.edge_count, s.source_record_id)
    )
    return selections[:limit]
