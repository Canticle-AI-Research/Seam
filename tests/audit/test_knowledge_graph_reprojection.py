from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from seam_runtime.knowledge_graph import (
    project_canonical_records_in_batches,
    project_records,
    query_graph,
    rebuild_knowledge_graph_from_canonical,
)
from seam_runtime.migrations import (
    DatabaseIntegrityError,
    KnowledgeGraphProjectionVersionError,
    MigrationError,
    UnsupportedDatabaseVersionError,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.reference_contracts import (
    VIRTUAL_REFS_EXTENSION,
    CanonicalReferenceIntegrityError,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.storage import SQLiteStore

REBUILD_STEP = "rebuild-knowledge-graph-4-to-5-from-canonical"
TYPED_REFERENCE_STEP = "typed-knowledge-references"
RELEVANT_TABLES = (
    "document_status",
    "ir_records",
    "seam_projection_versions",
    "knowledge_graph_meta",
    "knowledge_nodes",
    "knowledge_edges",
    "knowledge_episodes",
    "knowledge_node_episodes",
    "knowledge_edge_episodes",
    "knowledge_node_terms",
    "knowledge_node_vectors",
    "identity_merges",
    "identity_merge_evidence",
)
DERIVED_GRAPH_TABLES = (
    "knowledge_nodes",
    "knowledge_edges",
    "knowledge_episodes",
    "knowledge_node_episodes",
    "knowledge_edge_episodes",
    "knowledge_node_terms",
    "knowledge_node_vectors",
)


def _table_hashes(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        hashes: dict[str, str] = {}
        for table in RELEVANT_TABLES:
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            rows = (
                connection.execute(f'select * from "{table}" order by rowid').fetchall() if schema is not None else []
            )
            payload = json.dumps(
                {"schema": schema[0] if schema is not None else None, "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return hashes


def _logical_graph_rows(
    connection: sqlite3.Connection,
) -> dict[str, list[tuple[object, ...]]]:
    rows_by_table: dict[str, list[tuple[object, ...]]] = {}
    for table in DERIVED_GRAPH_TABLES:
        rows = [tuple(row) for row in connection.execute(f'select * from "{table}"').fetchall()]
        rows_by_table[table] = sorted(
            rows,
            key=lambda row: json.dumps(row, sort_keys=True, default=str),
        )
    return rows_by_table


def _downgrade_graph_marker(path: Path, version: str = "knowledge-graph/4") -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update seam_projection_versions set projection_version = ? where projection_name = 'knowledge_graph'",
            (version,),
        )
        connection.execute(
            "update knowledge_graph_meta set value = ? where key = 'projection_version'",
            (version,),
        )
        connection.commit()


def _stable_graph_view(payload: dict[str, object]) -> dict[str, object]:
    """Exclude only the response-generation clock from view equivalence."""

    return {key: value for key, value in payload.items() if key != "generated_at"}


def _fixture_views(
    connection: sqlite3.Connection,
    fixture: dict[str, object],
) -> dict[str, object]:
    return {
        "current": _stable_graph_view(query_graph(connection, namespace="tenant-a", scope="thread", limit=1000)),
        "history": _stable_graph_view(
            query_graph(
                connection,
                namespace="tenant-a",
                scope="thread",
                include_history=True,
                limit=1000,
            )
        ),
        "at": _stable_graph_view(
            query_graph(
                connection,
                root_id=str(fixture["old_episode_id"]),
                at=str(fixture["views"]["at"]["query"]["at"]),
                limit=1000,
            )
        ),
    }


def _build_reprojection_fixture(path: Path) -> dict[str, object]:
    runtime = SeamRuntime(path)
    try:
        first = runtime.ingest_text(
            "Alice owns alpha.",
            source_ref="test://s3/evolving",
            ns="tenant-a",
            scope="thread",
            agent_id="codex",
        )
        second = runtime.ingest_text(
            "Alice owns beta.",
            source_ref="test://s3/evolving",
            ns="tenant-a",
            scope="thread",
            agent_id="codex",
        )
        old_raw_id = next(record_id for record_id in first.stored_ids if record_id.startswith("raw:"))
        active_raw_id = next(record_id for record_id in second.stored_ids if record_id.startswith("raw:"))
        with runtime.store._pool.checkout() as connection:
            active_entity_id = str(
                connection.execute(
                    "select id from ir_records where kind = 'ENT' and ns = ? and scope = ? order by id limit 1",
                    ("tenant-a", "thread"),
                ).fetchone()[0]
            )

        # S4 closes required canonical references. Keep the fixture's semantic
        # endpoints explicit instead of relying on derived unresolved nodes.
        runtime.store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id="ent:s3-shared",
                        kind=RecordKind.ENT,
                        ns="tenant-a",
                        scope="thread",
                        attrs={"entity_type": "thing", "label": "shared"},
                    ),
                    MIRLRecord(
                        id="ent:s3-deleted-only",
                        kind=RecordKind.ENT,
                        ns="tenant-a",
                        scope="thread",
                        attrs={"entity_type": "thing", "label": "deleted only"},
                    ),
                ]
            )
        )

        # One semantic edge has two independent episode supports. Superseding
        # the old document must not expire it while the second episode is live.
        shared = MIRLRecord(
            id="rel:s3-shared-support",
            kind=RecordKind.REL,
            ns="tenant-a",
            scope="thread",
            evidence=[old_raw_id, active_raw_id],
            attrs={
                "src": active_entity_id,
                "predicate": "owns",
                "dst": "ent:s3-shared",
            },
            ext={"agent_id": "codex"},
        )
        runtime.store.persist_ir(IRBatch([shared]))

        lifecycle_record = MIRLRecord(
            id="clm:s3-lifecycle-excluded",
            kind=RecordKind.CLM,
            ns="tenant-a",
            scope="thread",
            attrs={
                "subject": "ent:s3-deleted-only",
                "predicate": "owns",
                "object": "deleted-only-value",
            },
        )
        runtime.store.persist_ir(IRBatch([lifecycle_record]))
        operation = runtime.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[lifecycle_record.id],
            idempotency_key="s3-reprojection-lifecycle",
            actor="test",
        )
        applied = runtime.apply_scoped_delete(
            tenant_id="tenant-a",
            operation_id=str(operation["operation_id"]),
            actor="test",
        )
        assert applied["state"] == "applied"

        with runtime.store._pool.checkout() as connection:
            old_episode = connection.execute(
                "select id, recorded_at, expired_at from knowledge_episodes where source_record_id = ?",
                (old_raw_id,),
            ).fetchone()
            shared_edge = connection.execute(
                "select id, status, expired_at from knowledge_edges "
                "where source_record_id = ? and edge_kind = 'semantic'",
                (shared.id,),
            ).fetchone()
            shared_episode_statuses = connection.execute(
                "select ep.status from knowledge_edge_episodes ee "
                "join knowledge_episodes ep on ep.id = ee.episode_id "
                "where ee.edge_id = ? order by ep.status",
                (shared_edge["id"],),
            ).fetchall()

        at = str(old_episode["recorded_at"])
        views = {
            "current": _stable_graph_view(
                runtime.store.knowledge_graph(namespace="tenant-a", scope="thread", limit=1000)
            ),
            "history": _stable_graph_view(
                runtime.store.knowledge_graph(
                    namespace="tenant-a",
                    scope="thread",
                    include_history=True,
                    limit=1000,
                )
            ),
            "at": _stable_graph_view(runtime.store.knowledge_graph(root_id=str(old_episode["id"]), at=at, limit=1000)),
        }
        return {
            "old_raw_id": old_raw_id,
            "old_episode_id": str(old_episode["id"]),
            "old_expired_at": str(old_episode["expired_at"]),
            "shared_edge_id": str(shared_edge["id"]),
            "shared_edge_state": (str(shared_edge["status"]), shared_edge["expired_at"]),
            "shared_episode_statuses": [str(row[0]) for row in shared_episode_statuses],
            "lifecycle_record_id": lifecycle_record.id,
            "views": views,
        }
    finally:
        runtime.close()


def test_guarded_reprojection_is_history_equivalent_and_has_zero_resurrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-equivalence.sqlite3"
    fixture = _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    # The stacked S4 branch normally creates KG/6 topology. Rebuild once with
    # the versioned KG/5 projector so the synthetic KG/4 fixture represents
    # the legacy reference semantics S3 is required to preserve exactly.
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        rebuild_knowledge_graph_from_canonical(connection)
        connection.commit()
        fixture["views"] = _fixture_views(connection, fixture)
    _downgrade_graph_marker(path)

    def stop_after_s3(step, _connection) -> None:
        if step.name == TYPED_REFERENCE_STEP:
            raise RuntimeError("inspect exact S3 checkpoint before S4")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(
            path,
            _migration_failure_injector=stop_after_s3,
            _migration_backup_dir=tmp_path / "checkpoint-backups",
        )

    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        assert (
            connection.execute(
                "select projection_version from seam_projection_versions where projection_name = 'knowledge_graph'"
            ).fetchone()[0]
            == "knowledge-graph/5"
        )
        assert (
            connection.execute("select value from knowledge_graph_meta where key = 'projection_version'").fetchone()[0]
            == "knowledge-graph/5"
        )
        assert _fixture_views(connection, fixture) == fixture["views"]

    runtime = SeamRuntime(path)
    try:
        assert runtime.store.migration_result.applied_steps == (TYPED_REFERENCE_STEP,)

        with runtime.store._pool.checkout() as connection:
            episodes = connection.execute(
                "select source_record_id, status, expired_at from knowledge_episodes"
            ).fetchall()
            shared_edge = connection.execute(
                "select status, expired_at from knowledge_edges where id = ?",
                (fixture["shared_edge_id"],),
            ).fetchone()
            shared_episode_statuses = connection.execute(
                "select ep.status from knowledge_edge_episodes ee "
                "join knowledge_episodes ep on ep.id = ee.episode_id "
                "where ee.edge_id = ? order by ep.status",
                (fixture["shared_edge_id"],),
            ).fetchall()
            lifecycle_rows = connection.execute(
                "select id from knowledge_nodes where id = ? union all "
                "select source_record_id from knowledge_edges where source_record_id = ?",
                (fixture["lifecycle_record_id"], fixture["lifecycle_record_id"]),
            ).fetchall()

        assert not {str(row["source_record_id"]) for row in episodes if row["status"] == "active"} & {
            str(fixture["old_raw_id"])
        }
        assert tuple(shared_edge) == fixture["shared_edge_state"] == ("asserted", None)
        assert (
            [str(row[0]) for row in shared_episode_statuses]
            == (fixture["shared_episode_statuses"])
            == ["active", "superseded"]
        )
        assert lifecycle_rows == []
    finally:
        runtime.close()


def test_typed_projection_is_graph_equivalent_across_agent_batch_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s4-agent-batch-equivalence.sqlite3"
    raw = MIRLRecord(
        id="raw:m-agent-boundary",
        kind=RecordKind.RAW,
        attrs={
            "content": "batch-independent attribution",
            "source_ref": "test://s4/agent-boundary",
        },
    )
    fillers = [
        MIRLRecord(
            id=f"prov:m-agent-boundary-filler-{index:03d}",
            kind=RecordKind.PROV,
            attrs={
                "entity": raw.id,
                "activity": "bounded lookup filler",
            },
        )
        for index in range(499)
    ]
    alpha = MIRLRecord(
        id="prov:a-alpha-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "alpha"},
    )
    beta = MIRLRecord(
        id="prov:z-beta-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "beta"},
    )
    records = [raw, *fillers, alpha, beta]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch(records))
        with store._pool.checkout() as connection:
            # Canonical order is alpha, 499 filler PROVs, beta, RAW. Both the
            # PROV lookup and graph projection cross the real 500-row boundary:
            # beta shares RAW's batch while globally earlier alpha does not.
            project_records(
                connection,
                sorted(records, key=lambda record: record.id),
            )
            full_projection = _logical_graph_rows(connection)
            assert (
                connection.execute(
                    "select agent_id from knowledge_nodes where id = ?",
                    (raw.id,),
                ).fetchone()[0]
                == "alpha"
            )

            connection.execute("delete from prov_log")
            lookup_execute_calls = 0
            lookup_executemany_batches: list[int] = []

            class TrackingConnection:
                def execute(self, statement: str, parameters=()):
                    nonlocal lookup_execute_calls
                    if statement.startswith("insert or ignore into seam_canonical_prov_agents"):
                        lookup_execute_calls += 1
                    return connection.execute(statement, parameters)

                def executemany(self, statement: str, parameters):
                    rows = list(parameters)
                    if statement.startswith("insert or ignore into seam_canonical_prov_agents"):
                        lookup_executemany_batches.append(len(rows))
                    return connection.executemany(statement, rows)

                def __getattr__(self, name: str):
                    return getattr(connection, name)

            project_canonical_records_in_batches(
                TrackingConnection(),  # type: ignore[arg-type]
                batch_size=500,
            )
            batched_projection = _logical_graph_rows(connection)
            assert (
                connection.execute(
                    "select agent_id from knowledge_nodes where id = ?",
                    (raw.id,),
                ).fetchone()[0]
                == "alpha"
            )
            assert (
                connection.execute(
                    "select agent_id from knowledge_episodes where source_record_id = ?",
                    (raw.id,),
                ).fetchone()[0]
                == "alpha"
            )
            assert batched_projection == full_projection
            assert lookup_execute_calls == 0
            assert lookup_executemany_batches == [1, 1]
            connection.commit()
    finally:
        store.close()


def test_live_provenance_changes_refresh_raw_node_and_episode_attribution(
    tmp_path: Path,
) -> None:
    path = tmp_path / "s4-live-provenance-refresh.sqlite3"
    raw_a = MIRLRecord(
        id="raw:live-provenance-a",
        kind=RecordKind.RAW,
        attrs={
            "content": "first source",
            "source_ref": "test://s4/live-provenance-a",
        },
    )
    raw_b = MIRLRecord(
        id="raw:live-provenance-b",
        kind=RecordKind.RAW,
        attrs={
            "content": "second source",
            "source_ref": "test://s4/live-provenance-b",
        },
    )
    later = MIRLRecord(
        id="prov:z-later-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw_a.id, "activity": "observed", "agent": "later"},
    )
    earlier = MIRLRecord(
        id="prov:a-earlier-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw_a.id, "activity": "observed", "agent": "earlier"},
    )

    def attribution(store: SQLiteStore, raw_id: str) -> tuple[object, object]:
        with store._pool.checkout() as connection:
            return (
                connection.execute(
                    "select agent_id from knowledge_nodes where id = ?",
                    (raw_id,),
                ).fetchone()[0],
                connection.execute(
                    "select agent_id from knowledge_episodes "
                    "where source_record_id = ?",
                    (raw_id,),
                ).fetchone()[0],
            )

    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([raw_a, raw_b]))
        assert attribution(store, raw_a.id) == (None, None)

        store.persist_ir(IRBatch([later]))
        assert attribution(store, raw_a.id) == ("later", "later")

        store.persist_ir(IRBatch([earlier]))
        assert attribution(store, raw_a.id) == ("earlier", "earlier")

        invalid_update = MIRLRecord.from_dict(earlier.to_dict())
        invalid_update.attrs["entity"] = "raw:private-missing-provenance-target"
        with pytest.raises(CanonicalReferenceIntegrityError) as raised:
            store.persist_ir(IRBatch([invalid_update]))
        assert "private-missing-provenance-target" not in str(raised.value)
        assert attribution(store, raw_a.id) == ("earlier", "earlier")

        moved = MIRLRecord.from_dict(earlier.to_dict())
        moved.attrs["entity"] = raw_b.id
        moved.attrs["agent"] = "moved"
        store.persist_ir(IRBatch([moved]))
        assert attribution(store, raw_a.id) == ("later", "later")
        assert attribution(store, raw_b.id) == ("moved", "moved")

        store.delete_ir([moved.id])
        assert attribution(store, raw_a.id) == ("later", "later")
        assert attribution(store, raw_b.id) == (None, None)

        store.delete_ir([later.id])
        assert attribution(store, raw_a.id) == (None, None)
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        assert attribution(reopened, raw_a.id) == (None, None)
        assert attribution(reopened, raw_b.id) == (None, None)
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("raw_ext", "source_ref", "expected_agent"),
    [
        ({"agent_id": "explicit"}, "test://s4/explicit-agent", "explicit"),
        ({}, "agent://source-agent/session", "source-agent"),
    ],
)
def test_explicit_raw_agent_precedes_late_canonical_provenance(
    tmp_path: Path,
    raw_ext: dict[str, object],
    source_ref: str,
    expected_agent: str,
) -> None:
    path = tmp_path / f"s4-explicit-raw-{expected_agent}.sqlite3"
    raw = MIRLRecord(
        id=f"raw:explicit-precedence-{expected_agent}",
        kind=RecordKind.RAW,
        attrs={"content": "explicit attribution", "source_ref": source_ref},
        ext=raw_ext,
    )
    provenance = MIRLRecord(
        id=f"prov:late-{expected_agent}",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "fallback"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([raw]))
        store.persist_ir(IRBatch([provenance]))
        with store._pool.checkout() as connection:
            assert connection.execute(
                "select agent_id from knowledge_nodes where id = ?",
                (raw.id,),
            ).fetchone()[0] == expected_agent
            assert connection.execute(
                "select agent_id from knowledge_episodes where source_record_id = ?",
                (raw.id,),
            ).fetchone()[0] == expected_agent
    finally:
        store.close()


@pytest.mark.parametrize("prov_log_state", ["missing", "empty", "stale"])
def test_guarded_reprojection_recovers_raw_agent_from_canonical_prov(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prov_log_state: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / f"s4-canonical-prov-{prov_log_state}.sqlite3"
    raw = MIRLRecord(
        id=f"raw:canonical-prov-{prov_log_state}",
        kind=RecordKind.RAW,
        attrs={
            "content": "canonical provenance survives specialized projection drift",
            "source_ref": "test://s4/canonical-prov",
        },
    )
    alpha = MIRLRecord(
        id="prov:a-canonical-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "alpha"},
    )
    beta = MIRLRecord(
        id="prov:z-canonical-agent",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "beta"},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([raw, alpha, beta]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update knowledge_graph_meta set value = 'knowledge-graph/4' where key = 'projection_version'"
        )
        if prov_log_state == "missing":
            connection.execute("drop table prov_log")
        elif prov_log_state == "empty":
            connection.execute("delete from prov_log")
        else:
            connection.execute(
                "update prov_log set agent = 'stale-agent' where id = ?",
                (alpha.id,),
            )
        rebuild_knowledge_graph_from_canonical(connection)
        assert (
            connection.execute(
                "select agent_id from knowledge_nodes where id = ?",
                (raw.id,),
            ).fetchone()[0]
            == "alpha"
        )
        assert (
            connection.execute(
                "select agent_id from knowledge_episodes where source_record_id = ?",
                (raw.id,),
            ).fetchone()[0]
            == "alpha"
        )
        connection.commit()


@pytest.mark.parametrize(
    ("raw_ext", "source_ref", "expected_agent"),
    [
        ({"agent_id": "explicit-ext"}, "test://s4/explicit", "explicit-ext"),
        ({}, "agent://explicit-source/session", "explicit-source"),
    ],
)
def test_canonical_prov_fallback_preserves_explicit_raw_agent_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_ext: dict[str, str],
    source_ref: str,
    expected_agent: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / f"s4-explicit-agent-{expected_agent}.sqlite3"
    raw = MIRLRecord(
        id=f"raw:explicit-agent-{expected_agent}",
        kind=RecordKind.RAW,
        ext=raw_ext,
        attrs={"content": "explicit attribution wins", "source_ref": source_ref},
    )
    canonical_prov = MIRLRecord(
        id=f"prov:canonical-{expected_agent}",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "canonical"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([raw, canonical_prov]))
        with store._pool.checkout() as connection:
            connection.execute("delete from prov_log")
            project_canonical_records_in_batches(connection, batch_size=1)
            assert (
                connection.execute(
                    "select agent_id from knowledge_nodes where id = ?",
                    (raw.id,),
                ).fetchone()[0]
                == expected_agent
            )
            assert (
                connection.execute(
                    "select agent_id from knowledge_episodes where source_record_id = ?",
                    (raw.id,),
                ).fetchone()[0]
                == expected_agent
            )
            connection.commit()
    finally:
        store.close()


def test_malformed_canonical_prov_attribution_is_content_free_and_non_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s4-malformed-canonical-prov.sqlite3"
    raw_id = "raw:private-attribution-source"
    prov_id = "prov:private-attribution-record"
    raw = MIRLRecord(
        id=raw_id,
        kind=RecordKind.RAW,
        attrs={"content": "private content", "source_ref": "test://private"},
    )
    provenance = MIRLRecord(
        id=prov_id,
        kind=RecordKind.PROV,
        attrs={"entity": raw_id, "activity": "observed", "agent": "alpha"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([raw, provenance]))
        with store._pool.checkout() as connection:
            before = _logical_graph_rows(connection)
            connection.execute(
                "update ir_records set payload_json = ? where id = ?",
                ("{" + raw_id, prov_id),
            )
            caplog.set_level("WARNING", logger="seam_runtime.knowledge_graph")
            with pytest.raises(
                KnowledgeGraphProjectionVersionError,
                match="invalid canonical MIRL payload",
            ) as raised:
                project_canonical_records_in_batches(connection)

            diagnostics = f"{raised.value}\n{caplog.text}"
            assert raw_id not in diagnostics
            assert prov_id not in diagnostics
            assert hashlib.sha256(prov_id.encode("utf-8")).hexdigest() in caplog.text
            assert _logical_graph_rows(connection) == before
            connection.rollback()
    finally:
        store.close()


def test_batched_canonical_projection_rejects_later_malformed_virtual_metadata_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s4-batched-malformed-virtual.sqlite3"
    metadata_secret = "private-batched-virtual-metadata"
    valid_first = MIRLRecord(
        id="meta:a-valid-before-malformed",
        kind=RecordKind.META,
        attrs={"key": "batch", "value": "first"},
    )
    malformed_later = MIRLRecord(
        id="meta:z-private-malformed-virtual",
        kind=RecordKind.META,
        ext={VIRTUAL_REFS_EXTENSION: []},
        attrs={"key": "batch", "value": "second"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([valid_first, malformed_later]))
        with store._pool.checkout() as connection:
            payload = malformed_later.to_dict()
            payload["ext"][VIRTUAL_REFS_EXTENSION] = metadata_secret
            connection.execute(
                "update ir_records set payload_json = ? where id = ?",
                (json.dumps(payload, sort_keys=True), malformed_later.id),
            )
            connection.commit()
            before_graph = _logical_graph_rows(connection)

            connection.execute("begin immediate")
            with pytest.raises(
                CanonicalReferenceIntegrityError,
                match="virtual reference declaration",
            ) as raised:
                project_canonical_records_in_batches(connection, batch_size=1)
            diagnostics = str(raised.value)
            assert malformed_later.id not in diagnostics
            assert metadata_secret not in diagnostics
            connection.rollback()

            assert _logical_graph_rows(connection) == before_graph
    finally:
        store.close()


def test_direct_projection_rejects_duplicate_ids_before_graph_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s4-duplicate-projector-id.sqlite3"
    private_id = "ent:private-duplicate-projector-id"
    original = MIRLRecord(
        id=private_id,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "original"},
    )
    replacement = MIRLRecord(
        id=private_id,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "replacement"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([original]))
        with store._pool.checkout() as connection:
            before = _logical_graph_rows(connection)
            with pytest.raises(ValueError, match="unique record identifiers") as raised:
                project_records(connection, [original, replacement])
            assert private_id not in str(raised.value)
            assert _logical_graph_rows(connection) == before
    finally:
        store.close()


def test_direct_projection_rejects_malformed_virtual_metadata_before_graph_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s4-malformed-virtual-direct-projection.sqlite3"
    metadata_secret = "private-direct-projection-virtual-metadata"
    seed = MIRLRecord(
        id="ent:direct-projection-seed",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "seed"},
    )
    valid_first = MIRLRecord(
        id="ent:direct-projection-valid-first",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "valid first"},
    )
    malformed_second = MIRLRecord(
        id="meta:private-direct-projection-malformed",
        kind=RecordKind.META,
        ext={VIRTUAL_REFS_EXTENSION: metadata_secret},
        attrs={"key": "metadata", "value": "invalid"},
    )
    before_records = deepcopy(
        [
            valid_first.to_dict(),
            malformed_second.to_dict(),
        ]
    )

    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([seed]))
        with store._pool.checkout() as connection:
            before_graph = _logical_graph_rows(connection)
            with pytest.raises(
                CanonicalReferenceIntegrityError,
                match="virtual reference declaration",
            ) as raised:
                project_records(connection, [valid_first, malformed_second])

            diagnostics = str(raised.value)
            assert malformed_second.id not in diagnostics
            assert metadata_secret not in diagnostics
            assert _logical_graph_rows(connection) == before_graph
            assert [valid_first.to_dict(), malformed_second.to_dict()] == before_records
    finally:
        store.close()


def test_reprojection_derives_supersession_from_document_status_not_stale_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-canonical-source.sqlite3"
    fixture = _build_reprojection_fixture(path)
    with closing(sqlite3.connect(path)) as connection:
        deleted_at = connection.execute(
            "select deleted_at from document_status where document_id = ?",
            ("doc:" + str(fixture["old_raw_id"]).split(":", 2)[1],),
        ).fetchone()[0]
        # Deliberately corrupt only the disposable graph. The rebuild must not
        # carry this active row forward because document_status is authoritative.
        connection.execute(
            "update knowledge_episodes set status = 'active', expired_at = null where source_record_id = ?",
            (fixture["old_raw_id"],),
        )
        connection.commit()
    _downgrade_graph_marker(path)

    runtime = SeamRuntime(path)
    try:
        with runtime.store._pool.checkout() as connection:
            rebuilt = connection.execute(
                "select status, expired_at from knowledge_episodes where source_record_id = ?",
                (fixture["old_raw_id"],),
            ).fetchone()
        assert tuple(rebuilt) == ("superseded", deleted_at)
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "invalid_document_id",
    ["private-document-label", "doc:not-a-canonical-suffix"],
)
def test_reprojection_refuses_invalid_document_status_identifier_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    invalid_document_id: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-invalid-document-status.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update document_status set document_id = ? where deleted_at is not null",
            (invalid_document_id,),
        )
        connection.commit()
    before = _table_hashes(path)
    caplog.set_level("WARNING", logger="seam_runtime.knowledge_graph")

    with pytest.raises(DatabaseIntegrityError, match="invalid document identifier"):
        SQLiteStore(path)

    assert _table_hashes(path) == before
    assert invalid_document_id not in caplog.text
    assert hashlib.sha256(invalid_document_id.encode("utf-8")).hexdigest() in caplog.text


@pytest.mark.parametrize(
    ("corruption", "expected_problem"),
    [
        ("invalid", "invalid canonical MIRL payload"),
        ("mismatched", "mismatched canonical MIRL identifier"),
    ],
)
def test_typed_reference_rebuild_redacts_canonical_ids_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    corruption: str,
    expected_problem: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / f"s4-redaction-{corruption}.sqlite3"
    stored_id = f"ent:private-graph-record-{corruption}"
    payload_id = f"ent:private-graph-payload-{corruption}"
    record = MIRLRecord(
        id=stored_id,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "private"},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([record]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update seam_projection_versions "
            "set projection_version = 'knowledge-graph/5' "
            "where projection_name = 'knowledge_graph'"
        )
        connection.execute(
            "update knowledge_graph_meta set value = 'knowledge-graph/5' where key = 'projection_version'"
        )
        payload = record.to_dict()
        if corruption == "invalid":
            corrupt_payload = "{" + payload_id
        else:
            payload["id"] = payload_id
            corrupt_payload = json.dumps(payload, sort_keys=True)
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (corrupt_payload, stored_id),
        )
        connection.commit()

    before = _table_hashes(path)
    caplog.set_level("WARNING", logger="seam_runtime.migrations")
    with pytest.raises(
        DatabaseIntegrityError,
        match="invalid canonical payload reference",
    ) as raised:
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / f"s4-backups-{corruption}",
        )

    diagnostics = f"{raised.value}\n{caplog.text}"
    assert stored_id not in diagnostics
    assert payload_id not in diagnostics
    assert expected_problem in caplog.text
    assert "record_id_sha256=" in caplog.text
    assert hashlib.sha256(stored_id.encode("utf-8")).hexdigest() in caplog.text
    assert _table_hashes(path) == before


def test_failed_reprojection_rolls_back_every_relevant_table_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-failed.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    before = _table_hashes(path)

    def fail_after_rebuild(step, _connection) -> None:
        if step.name == REBUILD_STEP:
            raise RuntimeError("injected S3 rebuild failure")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(
            path,
            _migration_failure_injector=fail_after_rebuild,
            _migration_backup_dir=tmp_path / "backups",
        )

    assert _table_hashes(path) == before


def test_typed_reference_failure_preserves_resumable_kg5_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-s4-resume.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)

    def fail_after_typed_reprojection(step, _connection) -> None:
        if step.name == TYPED_REFERENCE_STEP:
            raise RuntimeError("injected S4 typed-reference failure")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(
            path,
            _migration_failure_injector=fail_after_typed_reprojection,
            _migration_backup_dir=tmp_path / "backups",
        )

    with closing(sqlite3.connect(path)) as connection:
        assert (
            connection.execute(
                "select projection_version from seam_projection_versions where projection_name = 'knowledge_graph'"
            ).fetchone()[0]
            == "knowledge-graph/5"
        )
        assert (
            connection.execute("select value from knowledge_graph_meta where key = 'projection_version'").fetchone()[0]
            == "knowledge-graph/5"
        )

    resumed = SQLiteStore(path)
    try:
        assert resumed.migration_result.applied_steps == (TYPED_REFERENCE_STEP,)
        with resumed._pool.checkout() as connection:
            assert (
                connection.execute(
                    "select value from knowledge_graph_meta where key = 'projection_version'"
                ).fetchone()[0]
                == "knowledge-graph/6"
            )
    finally:
        resumed.close()


def test_newer_reprojection_request_refuses_before_any_table_hash_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-newer.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path, "knowledge-graph/999")
    before = _table_hashes(path)

    with pytest.raises(UnsupportedDatabaseVersionError, match="no registered transition"):
        SQLiteStore(path)

    assert _table_hashes(path) == before


@pytest.mark.parametrize("missing_table", ["identity_merges", "identity_merge_evidence"])
def test_reprojection_refuses_missing_identity_ledger_before_any_table_hash_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_table: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / f"s3-missing-{missing_table}.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f'drop table "{missing_table}"')
        connection.commit()
    before = _table_hashes(path)

    with pytest.raises(DatabaseIntegrityError, match=missing_table):
        SQLiteStore(path)

    assert _table_hashes(path) == before


def test_direct_reprojection_refuses_missing_marker_table_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-missing-marker.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("drop table knowledge_graph_meta")
        connection.commit()
    before = _table_hashes(path)

    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(KnowledgeGraphProjectionVersionError, match="found 'missing'"):
            rebuild_knowledge_graph_from_canonical(connection)

    assert _table_hashes(path) == before
