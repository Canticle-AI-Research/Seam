"""Hermetic tests for the query-conditioned graph -> source-RAW selector."""

from __future__ import annotations

import sqlite3

import pytest

from seam_runtime.graph_source_selector import (
    GraphSourceSelection,
    select_graph_source_raw,
    tokenize_query,
)

# The selector reads only these columns.  The fixtures deliberately carry NO
# text/content column anywhere, so any attempt to read or invent source text
# would raise instead of silently passing.
_SCHEMA = """
create table knowledge_nodes (
    id text primary key, label text not null, kind text not null,
    ns text not null, scope text not null, status text not null
);
create table knowledge_edges (
    id text primary key, src_id text not null, dst_id text not null,
    predicate text not null, ns text not null, scope text not null,
    status text not null, expired_at text
);
create table knowledge_episodes (
    id text primary key, source_record_id text not null, ns text not null,
    scope text not null, status text not null, expired_at text
);
create table knowledge_edge_episodes (
    edge_id text not null, episode_id text not null,
    primary key (edge_id, episode_id)
);
"""


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


def _node(conn, node_id, label, *, kind="entity", ns="n", scope="s", status="active"):
    conn.execute(
        "insert into knowledge_nodes (id, label, kind, ns, scope, status) "
        "values (?,?,?,?,?,?)",
        (node_id, label, kind, ns, scope, status),
    )


def _episode(conn, episode_id, raw_id, *, ns="n", scope="s", status="active", expired_at=None):
    conn.execute(
        "insert into knowledge_episodes "
        "(id, source_record_id, ns, scope, status, expired_at) values (?,?,?,?,?,?)",
        (episode_id, raw_id, ns, scope, status, expired_at),
    )


def _edge(
    conn,
    edge_id,
    src,
    dst,
    episode_id,
    *,
    predicate="knows",
    ns="n",
    scope="s",
    status="active",
    expired_at=None,
):
    conn.execute(
        "insert into knowledge_edges "
        "(id, src_id, dst_id, predicate, ns, scope, status, expired_at) "
        "values (?,?,?,?,?,?,?,?)",
        (edge_id, src, dst, predicate, ns, scope, status, expired_at),
    )
    conn.execute(
        "insert into knowledge_edge_episodes (edge_id, episode_id) values (?,?)",
        (edge_id, episode_id),
    )


def _two_seed_graph() -> sqlite3.Connection:
    conn = _connect()
    _node(conn, "ent:alice", "Alice")
    _node(conn, "ent:bob", "Bob")
    _node(conn, "ent:carol", "Carol")
    _node(conn, "ent:dave", "Dave")
    # R1 is corroborated by two distinct query nodes (alice and bob).
    _episode(conn, "ep1", "raw:R1")
    _episode(conn, "ep2", "raw:R1")
    _edge(conn, "e1", "ent:alice", "ent:carol", "ep1", predicate="knows")
    _edge(conn, "e2", "ent:bob", "ent:carol", "ep2", predicate="likes")
    # R2 is reached only by alice -> a single noisy adjacency.
    _episode(conn, "ep3", "raw:R2")
    _edge(conn, "e3", "ent:alice", "ent:dave", "ep3", predicate="owns")
    conn.commit()
    return conn


def test_two_independent_paths_select_one_source_raw_with_exact_id() -> None:
    conn = _two_seed_graph()
    result = select_graph_source_raw(conn, "alice bob", ns="n", scope="s")

    assert [s.source_record_id for s in result] == ["raw:R1"]
    selection = result[0]
    assert isinstance(selection, GraphSourceSelection)
    assert selection.agreement == 2
    assert selection.seed_ids == ("ent:alice", "ent:bob")
    assert selection.edge_ids == ("e1", "e2")
    assert {p.episode_id for p in selection.paths} == {"ep1", "ep2"}
    # Every returned path resolves to the exact source RAW id, no other.
    assert {p.source_record_id for p in selection.paths} == {"raw:R1"}


def test_single_noisy_adjacency_is_rejected() -> None:
    conn = _two_seed_graph()
    result = select_graph_source_raw(conn, "alice bob", ns="n", scope="s")
    # raw:R2 is reached only by alice (agreement 1) and must not appear.
    assert "raw:R2" not in {s.source_record_id for s in result}


def test_min_agreement_one_admits_the_single_adjacency() -> None:
    conn = _two_seed_graph()
    result = select_graph_source_raw(
        conn, "alice bob", ns="n", scope="s", min_agreement=1
    )
    assert {s.source_record_id for s in result} == {"raw:R1", "raw:R2"}
    # raw:R1 still ranks first: higher agreement wins.
    assert result[0].source_record_id == "raw:R1"


def test_single_edge_between_two_query_nodes_counts_as_agreement_two() -> None:
    conn = _connect()
    _node(conn, "ent:alice", "Alice")
    _node(conn, "ent:bob", "Bob")
    _episode(conn, "ep1", "raw:R1")
    _edge(conn, "e1", "ent:alice", "ent:bob", "ep1", predicate="married_to")
    conn.commit()
    result = select_graph_source_raw(conn, "alice bob", ns="n", scope="s")
    assert [s.source_record_id for s in result] == ["raw:R1"]
    assert result[0].agreement == 2
    assert result[0].edge_count == 1


def test_contradicted_superseded_expired_and_cross_scope_are_excluded() -> None:
    conn = _connect()
    _node(conn, "ent:alice", "Alice")
    _node(conn, "ent:bob", "Bob")
    _node(conn, "ent:carol", "Carol")
    # Two seeds both point at raw:R3, but every supporting edge/episode is
    # non-current or cross-scope, so R3 must not be selected.
    _episode(conn, "ep_ok", "raw:R3")
    _episode(conn, "ep_contra", "raw:R3", status="contradicted")
    _episode(conn, "ep_expired", "raw:R3", expired_at="2020-01-01T00:00:00Z")
    _episode(conn, "ep_scope", "raw:R3", scope="other")
    _edge(conn, "e_super", "ent:alice", "ent:carol", "ep_ok", status="superseded")
    _edge(conn, "e_exp", "ent:bob", "ent:carol", "ep_ok", expired_at="2020-01-01T00:00:00Z")
    _edge(conn, "e_contra_ep", "ent:alice", "ent:carol", "ep_contra")
    _edge(conn, "e_exp_ep", "ent:bob", "ent:carol", "ep_expired")
    _edge(conn, "e_scope", "ent:alice", "ent:carol", "ep_ok", scope="other")
    _edge(conn, "e_ns", "ent:bob", "ent:carol", "ep_ok", ns="other")
    conn.commit()
    result = select_graph_source_raw(conn, "alice bob carol", ns="n", scope="s")
    assert result == []


def test_one_concept_across_multiple_nodes_does_not_inflate_agreement() -> None:
    # "Carol" is a single query term represented as both an entity and a value
    # node, both grounding raw:R1.  Agreement counts distinct query tokens, so
    # this stays at 1 and is rejected at the default threshold.
    conn = _connect()
    _node(conn, "ent:carol", "Carol", kind="entity")
    _node(conn, "value:carol", "Carol", kind="value")
    _node(conn, "ent:hub", "Hub", kind="entity")
    _episode(conn, "ep1", "raw:R1")
    _episode(conn, "ep2", "raw:R1")
    _edge(conn, "e1", "ent:carol", "ent:hub", "ep1")
    _edge(conn, "e2", "value:carol", "ent:hub", "ep2")
    conn.commit()
    assert select_graph_source_raw(conn, "carol", ns="n", scope="s") == []
    admitted = select_graph_source_raw(conn, "carol", ns="n", scope="s", min_agreement=1)
    assert [s.source_record_id for s in admitted] == ["raw:R1"]
    assert admitted[0].agreement == 1
    assert admitted[0].covered_tokens == ("carol",)


def test_content_bearing_node_kinds_do_not_seed_agreement() -> None:
    # A claim/source/evidence node whose label embeds the whole turn text must
    # not count as an independent query concept, even though its label matches
    # both query tokens.  Only the two real concept nodes (alice, bob) seed.
    conn = _connect()
    _node(conn, "ent:alice", "Alice", kind="entity")
    _node(conn, "value:bob", "Bob", kind="value")
    _node(
        conn,
        "clm:turn1",
        "Alice went hiking with Bob at Rainier",
        kind="claim",
    )
    _node(conn, "raw:turn1-node", "Alice went hiking with Bob", kind="source")
    _episode(conn, "ep_a", "raw:R1")
    _episode(conn, "ep_b", "raw:R1")
    _edge(conn, "e_alice", "ent:alice", "raw:turn1-node", "ep_a")
    _edge(conn, "e_bob", "value:bob", "raw:turn1-node", "ep_b")
    # The claim node also links R1, but it must never be a seed.
    _episode(conn, "ep_c", "raw:R1")
    _edge(conn, "e_clm", "clm:turn1", "raw:turn1-node", "ep_c")
    conn.commit()
    result = select_graph_source_raw(conn, "alice bob", ns="n", scope="s")
    assert [s.source_record_id for s in result] == ["raw:R1"]
    # Agreement is exactly the two concept nodes, not the claim or source node.
    assert result[0].seed_ids == ("ent:alice", "value:bob")
    assert result[0].agreement == 2


def test_ties_are_deterministic_by_source_record_id() -> None:
    conn = _connect()
    _node(conn, "ent:alice", "Alice")
    _node(conn, "ent:bob", "Bob")
    _node(conn, "ent:zzz", "Zzz")
    # Two RAWs with identical agreement (2) and edge_count (2); tie breaks on id.
    for raw in ("raw:B", "raw:A"):
        e = raw.split(":")[1]
        _episode(conn, f"ep_{e}_1", raw)
        _episode(conn, f"ep_{e}_2", raw)
        _edge(conn, f"edge_{e}_1", "ent:alice", "ent:zzz", f"ep_{e}_1")
        _edge(conn, f"edge_{e}_2", "ent:bob", "ent:zzz", f"ep_{e}_2")
    conn.commit()
    result = select_graph_source_raw(conn, "alice bob zzz", ns="n", scope="s")
    assert [s.source_record_id for s in result] == ["raw:A", "raw:B"]
    # Stable across repeated calls.
    again = select_graph_source_raw(conn, "alice bob zzz", ns="n", scope="s")
    assert [s.source_record_id for s in again] == ["raw:A", "raw:B"]


def test_limit_caps_returned_selections() -> None:
    conn = _connect()
    _node(conn, "ent:alice", "Alice")
    _node(conn, "ent:bob", "Bob")
    _node(conn, "ent:hub", "Hub")
    for raw in ("raw:A", "raw:B", "raw:C", "raw:D"):
        e = raw.split(":")[1]
        _episode(conn, f"ep_{e}_1", raw)
        _episode(conn, f"ep_{e}_2", raw)
        _edge(conn, f"edge_{e}_1", "ent:alice", "ent:hub", f"ep_{e}_1")
        _edge(conn, f"edge_{e}_2", "ent:bob", "ent:hub", f"ep_{e}_2")
    conn.commit()
    result = select_graph_source_raw(conn, "alice bob hub", ns="n", scope="s", limit=2)
    assert len(result) == 2
    assert [s.source_record_id for s in result] == ["raw:A", "raw:B"]


def test_empty_query_and_too_few_seeds_return_nothing() -> None:
    conn = _two_seed_graph()
    assert select_graph_source_raw(conn, "", ns="n", scope="s") == []
    # Only one seed matches -> cannot reach the default agreement of two.
    assert select_graph_source_raw(conn, "alice", ns="n", scope="s") == []


def test_selection_exposes_no_source_text_field() -> None:
    conn = _two_seed_graph()
    result = select_graph_source_raw(conn, "alice bob", ns="n", scope="s")
    selection = result[0]
    fields = set(vars(selection))
    assert "memory" not in fields and "text" not in fields and "content" not in fields
    assert fields == {
        "source_record_id",
        "agreement",
        "edge_count",
        "covered_tokens",
        "seed_ids",
        "edge_ids",
        "score",
        "paths",
    }


@pytest.mark.parametrize(
    "query,expected",
    [("Alice BOB", ["alice", "bob"]), ("ent:carol-1", ["ent:carol-1"]), ("", [])],
)
def test_tokenize_query_lowercases_and_dedupes(query, expected) -> None:
    assert tokenize_query(query) == expected


def test_min_agreement_below_one_is_rejected() -> None:
    conn = _two_seed_graph()
    with pytest.raises(ValueError, match="min_agreement"):
        select_graph_source_raw(conn, "alice bob", min_agreement=0)
