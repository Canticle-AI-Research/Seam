"""Regression test: max_degree aggregation correctly sums src+dst degree."""

import sqlite3


def test_max_degree_sums_both_endpoints():
    """A node with degree split across src_id and dst_id must report the sum."""
    c = sqlite3.connect(":memory:")
    c.execute("create table ir_edges (src_id text, dst_id text)")
    for _ in range(4):
        c.execute("insert into ir_edges values ('HUB', 'X')")
    for _ in range(4):
        c.execute("insert into ir_edges values ('Y', 'HUB')")
    for _ in range(5):
        c.execute("insert into ir_edges values ('DECOY', 'Z')")

    row = c.execute(
        "select node_id, total_deg from ("
        "  select node_id, sum(deg) as total_deg from ("
        "    select src_id as node_id, count(*) as deg from ir_edges group by src_id"
        "    union all"
        "    select dst_id as node_id, count(*) as deg from ir_edges group by dst_id"
        "  ) group by node_id"
        ") order by total_deg desc limit 1"
    ).fetchone()

    assert row is not None
    node_id, total_deg = row
    assert node_id == "HUB", f"Expected HUB as max-degree node, got {node_id}"
    assert total_deg == 8, f"Expected total_deg=8 (4 src + 4 dst), got {total_deg}"


def test_storage_stats_reports_correct_max_degree(tmp_path):
    """End-to-end: store.stats() returns the corrected max_degree field."""
    from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
    from seam_runtime.runtime import SeamRuntime

    db_path = str(tmp_path / "stats_max_degree.db")
    rt = SeamRuntime(db_path)

    records = [
        MIRLRecord(
            id="ent:HUB", kind=RecordKind.ENT,
            ns="test.ns", scope="thread", attrs={"entity_type": "node", "label": "hub"},
        ),
        MIRLRecord(
            id="ent:A", kind=RecordKind.ENT,
            ns="test.ns", scope="thread", attrs={"entity_type": "node", "label": "a"},
        ),
        MIRLRecord(
            id="ent:B", kind=RecordKind.ENT,
            ns="test.ns", scope="thread", attrs={"entity_type": "node", "label": "b"},
        ),
        MIRLRecord(
            id="ent:C", kind=RecordKind.ENT,
            ns="test.ns", scope="thread", attrs={"entity_type": "node", "label": "c"},
        ),
        MIRLRecord(
            id="ent:D", kind=RecordKind.ENT,
            ns="test.ns", scope="thread", attrs={"entity_type": "node", "label": "d"},
        ),
        MIRLRecord(
            id="rel:1", kind=RecordKind.REL,
            ns="test.ns", scope="thread",
            attrs={"src": "ent:HUB", "dst": "ent:A", "predicate": "related"},
        ),
        MIRLRecord(
            id="rel:2", kind=RecordKind.REL,
            ns="test.ns", scope="thread",
            attrs={"src": "ent:HUB", "dst": "ent:B", "predicate": "related"},
        ),
        MIRLRecord(
            id="rel:3", kind=RecordKind.REL,
            ns="test.ns", scope="thread",
            attrs={"src": "ent:HUB", "dst": "ent:C", "predicate": "related"},
        ),
        MIRLRecord(
            id="rel:4", kind=RecordKind.REL,
            ns="test.ns", scope="thread",
            attrs={"src": "ent:D", "dst": "ent:HUB", "predicate": "related"},
        ),
    ]
    rt.persist_ir(IRBatch(records))

    stats = rt.store.get_stats()
    assert stats["max_degree_node"] == "ent:HUB", (
        f"Expected ent:HUB as max-degree node, got {stats.get('max_degree_node')}"
    )
    assert stats["max_degree"] == 4, (
        f"Expected max_degree=4 (3 src + 1 dst), got {stats.get('max_degree')}"
    )
