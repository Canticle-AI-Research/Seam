from __future__ import annotations

import sqlite3
from pathlib import Path

from seam_runtime.knowledge_graph import (
    GRAPH_NODE_VECTOR_TEXT_VERSION,
    VECTORIZABLE_NODE_KINDS,
    node_vector_source_hash,
    node_vector_status,
    pending_node_vectors,
    render_node_text,
    store_node_vectors,
)
from seam_runtime.public_api import remember
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.retrieval_orchestrator.adapters import (
    GraphNodeSemanticAdapter,
)
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.retrieval_policy import rank_normalized_contribution
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import SeamSDK


def _runtime(tmp_path: Path) -> SeamRuntime:
    return SeamRuntime(tmp_path / "graph-node-vectors.db")


def _model_name(runtime: SeamRuntime) -> str:
    model = runtime.embedding_model
    return getattr(model, "name", "") or model.__class__.__name__


def test_render_node_text_is_stable_across_property_order() -> None:
    """Stored and recomputed hashes must agree, so render order cannot vary."""
    first = render_node_text("entity", "Priya", {"b": 2, "a": "x"})
    second = render_node_text("entity", "Priya", {"a": "x", "b": 2})
    assert first == second == "entity Priya x 2"


def test_render_node_text_omits_projection_bookkeeping() -> None:
    """Keys shared by every node of a kind dilute the label that discriminates."""
    rendered = render_node_text(
        "entity",
        "Devon",
        {
            "attrs": {"entity_type": "entity", "label": "Devon"},
            "epistemic_basis": "explicit",
            "record_kind": "ENT",
            "ext": {},
            "facets": {},
        },
    )
    assert rendered == "entity Devon"


def test_render_node_text_keeps_semantic_attrs() -> None:
    rendered = render_node_text(
        "value",
        "shellfish allergy",
        {"attrs": {"object": "Devon is allergic to shellfish"}},
    )
    assert "Devon is allergic to shellfish" in rendered


def test_source_hash_binds_text_model_and_render_version() -> None:
    """A model swap with unchanged text must not silently reuse an old vector."""
    text = "entity Devon"
    assert node_vector_source_hash(text, "model-a") != node_vector_source_hash(text, "model-b")
    assert node_vector_source_hash(text, "model-a") != node_vector_source_hash("entity Devi", "model-a")


def test_ingest_projects_node_vectors_to_full_coverage(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish and keeps an EpiPen in his desk."})
    name = _model_name(runtime)

    status = runtime.store.node_vector_status(name)
    assert status["vectorizable_nodes"] > 0
    assert status["current_vectors"] == status["vectorizable_nodes"]
    assert status["pending_nodes"] == 0
    assert status["coverage"] == 1.0
    assert status["render_version"] == GRAPH_NODE_VECTOR_TEXT_VERSION


def test_projection_is_idempotent(tmp_path: Path) -> None:
    """Re-running must embed nothing, or every ingest pays for the whole graph."""
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "The CI pipeline takes 14 minutes on average."})
    assert runtime.project_node_vectors()["embedded"] == 0


def test_new_memories_extend_coverage_without_reindex(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "The CI pipeline takes 14 minutes on average."})
    name = _model_name(runtime)
    before = runtime.store.node_vector_status(name)["vectorizable_nodes"]

    remember(runtime, {"text": "Marcus blocks his mornings for deep work."})
    after = runtime.store.node_vector_status(name)
    assert after["vectorizable_nodes"] > before
    assert after["pending_nodes"] == 0


def test_legacy_render_version_fails_closed(tmp_path: Path) -> None:
    """A row on an older contract is pending, never served as if current.

    Mixing render contracts inside one index makes similarity scores
    incomparable in a way no downstream ranking can detect.
    """
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Rosa's dog Biscuit needs medication twice daily."})
    name = _model_name(runtime)
    assert runtime.store.node_vector_status(name)["pending_nodes"] == 0

    connection = sqlite3.connect(runtime.store.path)
    try:
        connection.execute(
            "update knowledge_node_vectors set render_version = ? where model_name = ?",
            ("graph-node-vector-text/0", name),
        )
        connection.commit()
        status = node_vector_status(connection, name)
        assert status["legacy_vectors"] > 0
        assert status["current_vectors"] == 0
        assert status["pending_nodes"] == status["vectorizable_nodes"]
        assert all(entry["reason"] == "stale" for entry in pending_node_vectors(connection, name))
    finally:
        connection.close()


def test_changed_node_text_marks_the_row_stale(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Theo is colorblind, so avoid red-green as the only signal."})
    name = _model_name(runtime)

    connection = sqlite3.connect(runtime.store.path)
    try:
        connection.execute(
            "update knowledge_node_vectors set source_hash = ? where model_name = ?",
            ("0" * 64, name),
        )
        connection.commit()
        pending = pending_node_vectors(connection, name)
        assert pending
        assert all(entry["reason"] == "stale" for entry in pending)
    finally:
        connection.close()


def test_only_vectorizable_kinds_are_projected(tmp_path: Path) -> None:
    """Episodes and edges are reachable through nodes; embedding them duplicates signal."""
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Priya joined the company on June 12th 2021."})
    name = _model_name(runtime)

    connection = sqlite3.connect(runtime.store.path)
    try:
        kinds = {
            row[0]
            for row in connection.execute(
                "select n.kind from knowledge_nodes n "
                "join knowledge_node_vectors v on v.node_id = n.id "
                "where v.model_name = ?",
                (name,),
            ).fetchall()
        }
    finally:
        connection.close()
    assert kinds
    assert kinds <= VECTORIZABLE_NODE_KINDS


def test_identical_node_text_reuses_a_stored_vector(tmp_path: Path) -> None:
    """A boundary-only move must stay a metadata update, never a re-embed.

    ``source_hash`` binds text, model, and render contract but not ns/scope, so
    the same node under a different boundary is the same point in vector space.
    Embedding is the one step that can cost a provider call.
    """
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Priya joined the company on June 12th 2021."})
    name = _model_name(runtime)

    connection = sqlite3.connect(runtime.store.path)
    try:
        hashes = [
            row[0]
            for row in connection.execute(
                "select source_hash from knowledge_node_vectors where model_name = ?",
                (name,),
            ).fetchall()
        ]
    finally:
        connection.close()

    assert hashes
    reusable = runtime.store.reusable_node_vectors(name, hashes)
    assert set(reusable) == set(hashes)
    assert all(vector for vector in reusable.values())
    assert runtime.store.reusable_node_vectors(name, ["0" * 64]) == {}


def test_search_ranks_by_similarity_with_a_deterministic_tiebreak(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish and keeps an EpiPen in his desk."})
    remember(runtime, {"text": "The CI pipeline takes 14 minutes on average."})
    name = _model_name(runtime)

    vector = runtime.embedding_model.embed("continuous integration build duration")
    first = runtime.store.search_node_vectors(vector, name, limit=10)
    second = runtime.store.search_node_vectors(vector, name, limit=10)
    assert first == second
    assert first == sorted(first, key=lambda item: (-item[1], item[0]))


def test_search_respects_the_namespace_boundary_before_top_k(tmp_path: Path) -> None:
    """Filtering after top-K would let a cutoff leak across a tenant boundary."""
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish."})
    name = _model_name(runtime)

    vector = runtime.embedding_model.embed("allergy")
    assert runtime.store.search_node_vectors(vector, name, ns="no-such-namespace") == []
    assert runtime.store.search_node_vectors(vector, name, scope="no-such-scope") == []


def test_search_excludes_legacy_render_versions(tmp_path: Path) -> None:
    """Scores from a superseded contract are not comparable with current ones."""
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Marcus blocks his mornings for deep work."})
    name = _model_name(runtime)
    # The default embedder is lexical, so the probe must share tokens with the
    # node text or it scores zero and the precondition never holds.
    vector = runtime.embedding_model.embed("Marcus deep work mornings")
    assert runtime.store.search_node_vectors(vector, name, limit=10)

    connection = sqlite3.connect(runtime.store.path)
    try:
        connection.execute(
            "update knowledge_node_vectors set render_version = ? where model_name = ?",
            ("graph-node-vector-text/0", name),
        )
        connection.commit()
    finally:
        connection.close()
    assert runtime.store.search_node_vectors(vector, name, limit=10) == []


def test_min_score_floor_filters_weak_matches(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Rosa's dog Biscuit needs medication twice daily."})
    name = _model_name(runtime)

    vector = runtime.embedding_model.embed("veterinary medication schedule")
    assert runtime.store.search_node_vectors(vector, name, limit=10, min_score=0.99) == []


def test_graph_node_vectors_are_an_explicit_rank_normalized_fusion_leg(
    monkeypatch, tmp_path: Path
) -> None:
    """G3 node semantics must be auditable in fusion, not an invisible seed."""

    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "20")
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_MIN_SCORE", "0")
    runtime = _runtime(tmp_path)
    remember(
        runtime,
        {
            "text": (
                "Devon is allergic to shellfish and keeps an EpiPen in his desk."
            )
        },
    )

    decision = RetrievalOrchestrator(runtime).decide(
        "Devon shellfish allergy",
        budget=10,
        mode="mix",
        graph_hops=1,
        semantic_graph_seeding=True,
    )
    assert decision.leg_hits["graph_node"]
    candidates = [
        candidate
        for candidate in decision.ranked
        if "graph_node" in candidate.sources
    ]
    assert candidates
    for candidate in candidates:
        rank = candidate.source_ranks["graph_node"]
        assert candidate.sources["graph_node"] == rank_normalized_contribution(rank)
        assert any(
            reason.startswith("graph_node:graph_node_semantic=")
            for reason in candidate.reasons
        )

    session = SeamSDK(runtime=runtime).start_reasoning(
        "Find allergy evidence."
    )
    recorded = session.retrieve(
        "Devon shellfish allergy",
        budget=10,
        mode="mix",
        graph_hops=1,
        semantic_graph_seeding=True,
    )
    detail = session.retrieval(str(recorded.reasoning["retrieval_id"]))
    assert detail["latency_ms"]["graph_node"] is not None


def test_graph_node_seeds_require_an_admissible_backing_record(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "20")
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish."})
    plan = build_plan(
        "kind:EVT Devon shellfish allergy",
        mode="mix",
        semantic_graph_seeding=True,
    )

    seed_ids, hits = GraphNodeSemanticAdapter(
        runtime.store, runtime.embedding_model
    ).search(plan, limit=20)

    assert seed_ids == []
    assert hits == []


def test_semantic_seeding_is_off_by_default(monkeypatch, tmp_path: Path) -> None:
    """On a weak embedder every node scores alike, so a permissive default would
    inject noise seeds and cost precision. The lever ships off until measured."""
    monkeypatch.delenv("SEAM_GRAPH_SEMANTIC_SEEDS", raising=False)
    monkeypatch.delenv("SEAM_GRAPH_SEMANTIC_MIN_SCORE", raising=False)
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish and keeps an EpiPen in his desk."})

    query = "who cannot eat prawns or crab"
    lexical = runtime.store.knowledge_graph(query=query, limit=50)
    default = runtime.knowledge_graph(query=query, limit=50)
    assert len(default.get("nodes") or []) == len(lexical.get("nodes") or [])


def test_semantic_seeding_reaches_nodes_lexical_seeding_cannot(
    monkeypatch, tmp_path: Path
) -> None:
    """Lexical seeding structurally cannot reach a node sharing no query tokens."""
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "20")
    monkeypatch.delenv("SEAM_GRAPH_SEMANTIC_MIN_SCORE", raising=False)
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish and keeps an EpiPen in his desk."})

    query = "who cannot eat prawns or crab"
    assert not (runtime.store.knowledge_graph(query=query, limit=50).get("nodes") or [])
    assert runtime.knowledge_graph(query=query, limit=50).get("nodes")


def test_semantic_seeds_respect_the_namespace_boundary(monkeypatch, tmp_path: Path) -> None:
    """A semantic seed must clear the same boundary filters as a lexical one."""
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "20")
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Devon is allergic to shellfish."})

    result = runtime.knowledge_graph(
        query="who cannot eat prawns", namespace="no-such-namespace", limit=50
    )
    assert not (result.get("nodes") or [])


def test_a_malformed_seeding_knob_falls_back_instead_of_failing(
    monkeypatch, tmp_path: Path
) -> None:
    """A bad env value must not take a graph query down."""
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "not-a-number")
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "The CI pipeline takes 14 minutes on average."})

    result = runtime.knowledge_graph(query="build duration", limit=50)
    assert isinstance(result.get("nodes"), list)


def test_seeding_failure_degrades_to_lexical(monkeypatch, tmp_path: Path) -> None:
    """A semantic seed is an additional way in, never a precondition."""
    monkeypatch.setenv("SEAM_GRAPH_SEMANTIC_SEEDS", "20")
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "The CI pipeline takes 14 minutes on average."})

    def _explode(_text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(runtime.embedding_model, "embed", _explode)
    lexical = runtime.store.knowledge_graph(query="pipeline", limit=50)
    degraded = runtime.knowledge_graph(query="pipeline", limit=50)
    assert len(degraded.get("nodes") or []) == len(lexical.get("nodes") or [])


def test_store_node_vectors_drops_rows_for_deleted_nodes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    remember(runtime, {"text": "Callum broke his wrist skiing in Vail."})
    name = _model_name(runtime)

    connection = sqlite3.connect(runtime.store.path)
    try:
        connection.execute("delete from knowledge_nodes")
        connection.commit()
        store_node_vectors(connection, name, [])
        connection.commit()
        remaining = connection.execute(
            "select count(*) from knowledge_node_vectors"
        ).fetchone()[0]
    finally:
        connection.close()
    assert remaining == 0
