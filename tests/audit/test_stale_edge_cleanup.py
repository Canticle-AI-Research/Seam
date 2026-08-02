"""Lane C -- stale CLM edge cleanup test.

When a CLM record is re-persisted with a different object (but same subject),
the old edge must be removed. CLM edges are keyed by subject, not record.id,
so the existing delete-on-src_id=record.id alone is insufficient.
"""

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.storage import SQLiteStore


def test_clm_stale_edge_cleanup_on_overwrite():
    """Persist clm:x(subject=ent:x)->ent:a, then overwrite with same id but
    object=ent:b; assert the ent:a edge is gone and only ent:b remains."""
    store = SQLiteStore(":memory:")

    # --- First persist: CLM with subject=ent:x, object=ent:a ---
    clm_v1 = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:x", "ent:a"]},
        attrs={"subject": "ent:x", "predicate": "related_to", "object": "ent:a"},
        prov=["raw:1"],
        evidence=["span:1"],
    )
    store.persist_ir(IRBatch([clm_v1]))

    # Verify edge exists: src=ent:x, type=related_to, dst=ent:a
    edges_v1 = _dump_edges(store)
    assert ("ent:x", "related_to", "ent:a") in edges_v1, (
        f"Expected edge (ent:x, related_to, ent:a) not found in: {edges_v1}"
    )

    # --- Second persist: same record id, same subject, different object ---
    clm_v2 = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:x", "ent:b"]},
        attrs={"subject": "ent:x", "predicate": "related_to", "object": "ent:b"},
        prov=["raw:2"],
        evidence=["span:2"],
    )
    store.persist_ir(IRBatch([clm_v2]))

    edges_v2 = _dump_edges(store)

    # Old edge must be gone.
    assert ("ent:x", "related_to", "ent:a") not in edges_v2, (
        f"Stale edge (ent:x, related_to, ent:a) survived overwrite: {edges_v2}"
    )

    # New edge must exist.
    assert ("ent:x", "related_to", "ent:b") in edges_v2, (
        f"Expected edge (ent:x, related_to, ent:b) not found in: {edges_v2}"
    )


def test_clm_stale_edge_cleanup_subject_change():
    """Persist clm:1(subject=ent:old)->obj, then overwrite with
    subject=ent:new; assert the old subject's edge is gone."""
    store = SQLiteStore(":memory:")

    clm_v1 = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:old", "target:1"]},
        attrs={"subject": "ent:old", "predicate": "relates_to", "object": "target:1"},
        prov=["raw:1"],
    )
    store.persist_ir(IRBatch([clm_v1]))

    edges_v1 = _dump_edges(store)
    assert ("ent:old", "relates_to", "target:1") in edges_v1

    clm_v2 = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:new", "target:2"]},
        attrs={"subject": "ent:new", "predicate": "relates_to", "object": "target:2"},
        prov=["raw:2"],
    )
    store.persist_ir(IRBatch([clm_v2]))

    edges_v2 = _dump_edges(store)

    # Old subject edge must be gone.
    assert ("ent:old", "relates_to", "target:1") not in edges_v2, (
        f"Stale edge for old subject survived: {edges_v2}"
    )

    # New subject edge must exist.
    assert ("ent:new", "relates_to", "target:2") in edges_v2, (
        f"Expected new subject edge not found in: {edges_v2}"
    )

    # prov edge (keyed by record.id=clm:1) must also be refreshed.
    assert ("clm:1", "prov", "raw:2") in edges_v2, (
        "Expected prov edge (clm:1, prov, raw:2) not found"
    )
    assert ("clm:1", "prov", "raw:1") not in edges_v2, (
        "Stale prov edge from v1 should be gone"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dump_edges(store: SQLiteStore) -> set[tuple[str, str, str]]:
    """Return all (src_id, edge_type, dst_id) triples currently in ir_edges."""
    from contextlib import closing
    with closing(store._connect()) as conn:
        rows = conn.execute(
            "select src_id, edge_type, dst_id from ir_edges order by id"
        ).fetchall()
    return {(row[0], row[1], row[2]) for row in rows}
