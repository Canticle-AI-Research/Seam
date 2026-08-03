"""Orphan edge cleanup for all prefixes, not just clm:.

The _cleanup_orphan_edges method must remove edges where EITHER endpoint
(src_id or dst_id) is missing from ir_records, regardless of prefix.
"""

from contextlib import closing

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.storage import SQLiteStore


def test_orphan_edge_cleanup_non_clm_prefix():
    """Create a record and an edge referencing it, delete the record,
    reopen the store (which triggers _cleanup_orphan_edges), and verify
    the edge is gone. Uses a non-clm prefix (rel:) to prove the fix
    covers all prefixes."""
    store = SQLiteStore(":memory:")

    source = _entity("ent:turn:1")
    target = _entity("ent:claim:1")
    rel = MIRLRecord(
        id="rel:1",
        kind=RecordKind.REL,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"src": source.id, "predicate": "references", "dst": target.id},
    )
    store.persist_ir(IRBatch([source, target, rel]))

    # Verify edge exists.
    edges = _dump_edges(store)
    assert (source.id, "references", target.id) in edges

    # Delete one endpoint directly via SQL (simulating a record removal
    # that bypasses the normal delete_ir path).
    with closing(store._connect()) as conn:
        conn.execute("delete from ir_records where id = ?", (source.id,))
        conn.commit()

    # `:memory:` connections aren't shared across SQLiteStore instances, so
    # reopening can't be simulated by constructing a second store here;
    # call the cleanup method directly on the existing connection instead.
    with closing(store._connect()) as conn:
        store._cleanup_orphan_edges(conn)
        conn.commit()

    edges_after = _dump_edges(store)
    assert (source.id, "references", target.id) not in edges_after, (
        f"Orphan edge survived cleanup: {edges_after}"
    )


def test_orphan_edge_cleanup_prov_edge():
    """A prov edge whose src record is deleted should be cleaned up."""
    store = SQLiteStore(":memory:")

    rec = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"subject": "ent:user:1", "predicate": "likes", "object": "ent:thing:1"},
        prov=["prov:1"],
    )
    provenance = MIRLRecord(
        id="prov:1",
        kind=RecordKind.PROV,
        ns="test",
        scope="test",
        attrs={"entity": "ent:user:1", "activity": "observed"},
    )
    store.persist_ir(
        IRBatch(
            [
                _entity("ent:user:1"),
                _entity("ent:thing:1"),
                provenance,
                rec,
            ]
        )
    )

    edges = _dump_edges(store)
    assert ("clm:1", "prov", "prov:1") in edges

    # Delete the record.
    with closing(store._connect()) as conn:
        conn.execute("delete from ir_records where id = ?", ("clm:1",))
        conn.commit()

    with closing(store._connect()) as conn:
        store._cleanup_orphan_edges(conn)
        conn.commit()

    edges_after = _dump_edges(store)
    assert ("clm:1", "prov", "prov:1") not in edges_after


def test_orphan_edge_cleanup_evidence_edge():
    """An evidence edge whose src record is deleted should be cleaned up."""
    store = SQLiteStore(":memory:")

    rec = MIRLRecord(
        id="clm:2",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"subject": "ent:user:2", "predicate": "knows", "object": "ent:fact:1"},
        evidence=["span:42"],
    )
    raw = _raw("raw:evidence-42")
    span = _span("span:42", raw)
    store.persist_ir(
        IRBatch(
            [
                _entity("ent:user:2"),
                _entity("ent:fact:1"),
                raw,
                span,
                rec,
            ]
        )
    )

    edges = _dump_edges(store)
    assert ("clm:2", "evidence", "span:42") in edges

    with closing(store._connect()) as conn:
        conn.execute("delete from ir_records where id = ?", ("clm:2",))
        conn.commit()

    with closing(store._connect()) as conn:
        store._cleanup_orphan_edges(conn)
        conn.commit()

    edges_after = _dump_edges(store)
    assert ("clm:2", "evidence", "span:42") not in edges_after


def test_orphan_edge_cleanup_both_endpoints_missing():
    """Edge where both src and dst are missing from ir_records should be removed."""
    store = SQLiteStore(":memory:")

    # Manually insert a record and edge, then delete the record.
    with closing(store._connect()) as conn:
        conn.execute(
            "insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("sym:1", "sym", "test", "test", "active", 1.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "{}"),
        )
        conn.execute(
            "insert into ir_edges (src_id, edge_type, dst_id) values (?, ?, ?)",
            ("sym:1", "alias", "sym:2"),
        )
        conn.commit()

    edges = _dump_edges(store)
    assert ("sym:1", "alias", "sym:2") in edges

    with closing(store._connect()) as conn:
        conn.execute("delete from ir_records where id = ?", ("sym:1",))
        conn.commit()

    with closing(store._connect()) as conn:
        store._cleanup_orphan_edges(conn)
        conn.commit()

    edges_after = _dump_edges(store)
    assert ("sym:1", "alias", "sym:2") not in edges_after


def test_valid_edges_survive_cleanup():
    """Edges where both endpoints exist in ir_records should NOT be removed."""
    store = SQLiteStore(":memory:")

    rec1 = MIRLRecord(
        id="rel:10",
        kind=RecordKind.REL,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"src": "clm:10", "predicate": "links", "dst": "clm:20"},
    )
    rec2 = MIRLRecord(
        id="clm:10",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"subject": "clm:10", "predicate": "links", "object": "clm:20"},
    )
    rec3 = MIRLRecord(
        id="clm:20",
        kind=RecordKind.CLM,
        ns="test",
        scope="test",
        status=Status.ASSERTED,
        conf=1.0,
        attrs={"subject": "clm:20", "predicate": "links", "object": "clm:10"},
    )
    store.persist_ir(IRBatch([rec1, rec2, rec3]))

    edges_before = _dump_edges(store)
    assert ("clm:10", "links", "clm:20") in edges_before

    with closing(store._connect()) as conn:
        store._cleanup_orphan_edges(conn)
        conn.commit()

    edges_after = _dump_edges(store)
    assert ("clm:10", "links", "clm:20") in edges_after, (
        f"Valid edge was incorrectly removed: {edges_after}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(record_id: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.ENT,
        ns="test",
        scope="test",
        attrs={"label": record_id, "entity_type": "fixture"},
    )


def _raw(record_id: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        ns="test",
        scope="test",
        attrs={"content": f"source for {record_id}"},
    )


def _span(record_id: str, raw: MIRLRecord) -> MIRLRecord:
    content = str(raw.attrs["content"])
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.SPAN,
        ns="test",
        scope="test",
        attrs={
            "raw_id": raw.id,
            "start": 0,
            "end": len(content),
            "text": content,
        },
    )

def _dump_edges(store: SQLiteStore) -> set[tuple[str, str, str]]:
    """Return all (src_id, edge_type, dst_id) triples currently in ir_edges."""
    with closing(store._connect()) as conn:
        rows = conn.execute(
            "select src_id, edge_type, dst_id from ir_edges order by id"
        ).fetchall()
    return {(row[0], row[1], row[2]) for row in rows}
