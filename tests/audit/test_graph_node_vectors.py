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
from seam_runtime.runtime import SeamRuntime


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
