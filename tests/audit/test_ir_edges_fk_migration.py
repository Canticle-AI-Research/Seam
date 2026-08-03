"""P3 Fix 7 — ir_edges orphan cleanup on open."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from seam_runtime.knowledge_graph import PROJECTION_VERSION


def _orphan_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "select count(*) from ir_edges "
        "where (src_id like 'clm:%' and src_id not in (select id from ir_records)) "
        "   or (dst_id like 'clm:%' and dst_id not in (select id from ir_records))"
    ).fetchone()[0]


def test_orphan_cleanup_on_init(tmp_path: Path) -> None:
    """Orphan edges with record-ID-style src/dst are removed on store open."""
    db_path = str(tmp_path / "test_orphan.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table ir_records (
            id text primary key,
            kind text not null,
            ns text not null,
            scope text not null,
            status text not null,
            conf real not null,
            t0 text,
            t1 text,
            created_at text not null,
            updated_at text not null,
            payload_json text not null
        );
        create table ir_edges (
            id integer primary key autoincrement,
            src_id text not null,
            edge_type text not null,
            dst_id text not null
        );
        create table knowledge_graph_meta (
            key text primary key,
            value text not null
        );
        insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json)
        values ('clm:rec_a', 'CLM', 'test', 'thread', 'active', 0.9, '2024-01-01', '2024-01-01',
        '{"id":"clm:rec_a","kind":"CLM","attrs":{"subject":"clm:rec_a","predicate":"ref","object":"clm:rec_b"}}');
        insert into ir_records (id, kind, ns, scope, status, conf, created_at, updated_at, payload_json)
        values ('clm:rec_b', 'CLM', 'test', 'thread', 'active', 0.9, '2024-01-01', '2024-01-01',
        '{"id":"clm:rec_b","kind":"CLM","attrs":{"subject":"clm:rec_b"}}');
        -- legit edge between two existing records
        insert into ir_edges (src_id, edge_type, dst_id) values ('clm:rec_a', 'ref', 'clm:rec_b');
        -- orphan edge: src is a record ID that doesn't exist
        insert into ir_edges (src_id, edge_type, dst_id) values ('clm:rec_c', 'ref', 'clm:rec_b');
        -- legacy endpoint typing is absent, so unknown endpoints fail closed
        insert into ir_edges (src_id, edge_type, dst_id) values ('ent:turn:abc', 'date', 'clm:rec_a');
        """
    )
    conn.execute(
        "insert into knowledge_graph_meta (key, value) values (?, ?)",
        ("projection_version", PROJECTION_VERSION),
    )
    conn.commit()
    conn.close()

    # Opening the store triggers _cleanup_orphan_edges
    from seam_runtime.storage import SQLiteStore

    SQLiteStore(db_path).close()

    conn2 = sqlite3.connect(db_path)
    orphan = _orphan_count(conn2)
    assert orphan == 0, f"orphan edges should be removed, got {orphan}"

    # Legit edge survives
    legit = conn2.execute(
        "select count(*) from ir_edges where src_id = 'clm:rec_a'"
    ).fetchone()[0]
    assert legit == 1, "legit edge should survive"

    # An untyped legacy endpoint is not silently guessed to be virtual.
    virt = conn2.execute(
        "select count(*) from ir_edges where src_id = 'ent:turn:abc'"
    ).fetchone()[0]
    assert virt == 0, "untyped legacy endpoint should fail closed"

    conn2.close()
