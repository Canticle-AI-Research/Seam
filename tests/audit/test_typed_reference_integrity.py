"""Track S S4 typed-reference and orphan-integrity exit gate."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

import seam_runtime.identity_resolution as identity_resolution_module
import seam_runtime.migrations as migration_module
from seam_runtime.dsl import compile_dsl
from seam_runtime.knowledge_graph import project_records
from seam_runtime.migrations import (
    PROJECTION_TABLE,
    DatabaseIntegrityError,
    MigrationError,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.nl import compile_nl
from seam_runtime.reference_contracts import (
    FACET_REFERENCE_FIELDS,
    RECONCILIATION_REFERENCE_FIELDS,
    VIRTUAL_REFS_EXTENSION,
    CanonicalReferenceIntegrityError,
    CanonicalReferenceShapeError,
    remap_record_references,
    validate_record_reference_contract,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.storage import SQLiteStore

CORE_MIGRATION_TABLES = (
    "ir_records",
    "ir_edges",
    "ir_edge_sources",
    "seam_projection_versions",
)

REQUIRED_SCALAR_REFERENCE_POSITIONS = (
    "span.raw_id",
    "clm.subject",
    "evt.actor",
    "evt.subject",
    "rel.src",
    "rel.dst",
    "sta.target",
    "sta.subject",
    "flow.src",
    "flow.dst",
    "prov.entity",
)

REFERENCE_SHAPE_ANCHOR_ID = "ent:reference-shape-anchor"
REFERENCE_SHAPE_SECRET = "private-reference-shape-secret"

INVALID_REQUIRED_SCALARS = (
    ("none", None),
    ("empty", ""),
    ("blank", " \t"),
    ("leading-whitespace", f" {REFERENCE_SHAPE_ANCHOR_ID}"),
    ("trailing-whitespace", f"{REFERENCE_SHAPE_ANCHOR_ID} "),
    ("integer", 7),
    ("mapping", {REFERENCE_SHAPE_SECRET: REFERENCE_SHAPE_ANCHOR_ID}),
    ("empty-list", []),
    ("singleton-list", [REFERENCE_SHAPE_ANCHOR_ID]),
)

INVALID_REQUIRED_LISTS = (
    ("none-container", None),
    ("scalar-container", REFERENCE_SHAPE_ANCHOR_ID),
    ("tuple-container", (REFERENCE_SHAPE_ANCHOR_ID,)),
    ("mapping-container", {REFERENCE_SHAPE_SECRET: REFERENCE_SHAPE_ANCHOR_ID}),
    ("integer-container", 7),
    ("none-member", [None]),
    ("empty-member", [""]),
    ("blank-member", [" \t"]),
    ("leading-whitespace-member", [f" {REFERENCE_SHAPE_ANCHOR_ID}"]),
    ("trailing-whitespace-member", [f"{REFERENCE_SHAPE_ANCHOR_ID} "]),
    ("integer-member", [7]),
    ("mapping-member", [{REFERENCE_SHAPE_SECRET: REFERENCE_SHAPE_ANCHOR_ID}]),
    ("nested-list-member", [[REFERENCE_SHAPE_ANCHOR_ID]]),
)

INVALID_RECONCILIATION_POINTERS = (
    *INVALID_REQUIRED_SCALARS[:-2],
    *INVALID_REQUIRED_LISTS[2:],
)


def _table_hashes(path: Path, tables: tuple[str, ...]) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        hashes: dict[str, str] = {}
        for table in tables:
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            rows = (
                connection.execute(
                    f'select * from "{table}" order by rowid'
                ).fetchall()
                if schema is not None
                else []
            )
            payload = json.dumps(
                {"schema": schema[0] if schema is not None else None, "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return hashes


def _all_table_hashes(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        tables = tuple(
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' "
                "and name not like 'sqlite_%' order by name"
            )
        )
    return _table_hashes(path, tables)


def _connection_table_rows(
    connection: sqlite3.Connection,
    *,
    name_prefix: str,
) -> dict[str, tuple[tuple[object, ...], ...]]:
    tables = tuple(
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table' "
            "and name like ? order by name",
            (f"{name_prefix}%",),
        )
    )
    return {
        table: tuple(
            tuple(row)
            for row in connection.execute(
                f'select * from "{table}" order by rowid'
            ).fetchall()
        )
        for table in tables
    }


def _replace_required_scalar_position(
    record: MIRLRecord,
    position: str,
    value: object,
) -> None:
    record.attrs[position.split(".", 1)[1]] = value


def _record_for_reference_position(
    position: str,
    duplicate_id: str,
    anchor_id: str,
) -> MIRLRecord:
    record_id = "meta:remap-" + position.replace(".", "-")
    if position == "prov":
        return MIRLRecord(
            id=record_id,
            kind=RecordKind.META,
            prov=[duplicate_id],
            attrs={"key": "position", "value": "prov"},
        )
    if position == "evidence":
        return MIRLRecord(
            id=record_id,
            kind=RecordKind.META,
            evidence=[duplicate_id],
            attrs={"key": "position", "value": "evidence"},
        )
    if position == "span.raw_id":
        return MIRLRecord(
            id="span:remap-raw-id",
            kind=RecordKind.SPAN,
            attrs={"raw_id": duplicate_id, "start": 0, "end": 1, "text": "x"},
        )
    if position == "clm.subject":
        return MIRLRecord(
            id="clm:remap-subject",
            kind=RecordKind.CLM,
            attrs={
                "subject": duplicate_id,
                "predicate": "references",
                "object": anchor_id,
            },
        )
    if position == "clm.object":
        return MIRLRecord(
            id="clm:remap-object",
            kind=RecordKind.CLM,
            attrs={
                "subject": anchor_id,
                "predicate": "references",
                "object": duplicate_id,
            },
        )
    if position in {"evt.actor", "evt.subject", "evt.object"}:
        attrs = {"action": "observed", "object": anchor_id}
        if position == "evt.actor":
            attrs["actor"] = duplicate_id
        elif position == "evt.subject":
            attrs["subject"] = duplicate_id
        else:
            attrs.update({"actor": anchor_id, "object": duplicate_id})
        return MIRLRecord(
            id="evt:remap-" + position.rsplit(".", 1)[1],
            kind=RecordKind.EVT,
            attrs=attrs,
        )
    if position in {"rel.src", "rel.dst"}:
        return MIRLRecord(
            id="rel:remap-" + position.rsplit(".", 1)[1],
            kind=RecordKind.REL,
            attrs={
                "src": duplicate_id if position == "rel.src" else anchor_id,
                "predicate": "references",
                "dst": duplicate_id if position == "rel.dst" else anchor_id,
            },
        )
    if position in {"sta.target", "sta.subject"}:
        field = position.rsplit(".", 1)[1]
        return MIRLRecord(
            id="sta:remap-" + field,
            kind=RecordKind.STA,
            attrs={field: duplicate_id, "state": "active"},
        )
    if position == "pack.refs":
        return MIRLRecord(
            id="pack:remap-refs",
            kind=RecordKind.PACK,
            attrs={
                "mode": "lossless",
                "lens": "general",
                "refs": [duplicate_id],
                "payload": {},
            },
        )
    if position in {"flow.src", "flow.dst"}:
        return MIRLRecord(
            id="flow:remap-" + position.rsplit(".", 1)[1],
            kind=RecordKind.FLOW,
            attrs={
                "src": duplicate_id if position == "flow.src" else anchor_id,
                "op": "flows_to",
                "dst": duplicate_id if position == "flow.dst" else anchor_id,
            },
        )
    if position == "prov.entity":
        return MIRLRecord(
            id="prov:remap-entity",
            kind=RecordKind.PROV,
            attrs={
                "entity": duplicate_id,
                "activity": "remap",
                "agent": "test",
            },
        )
    if position == "ext.virtual_refs":
        return MIRLRecord(
            id="rel:remap-virtual-declaration",
            kind=RecordKind.REL,
            ext={VIRTUAL_REFS_EXTENSION: [duplicate_id]},
            attrs={
                "src": duplicate_id,
                "predicate": "references",
                "dst": anchor_id,
            },
        )
    if position.startswith("attrs.facets."):
        facet = position.rsplit(".", 1)[1]
        return MIRLRecord(
            id=record_id,
            kind=RecordKind.META,
            attrs={
                "key": "position",
                "value": facet,
                "facets": {facet: duplicate_id},
            },
        )
    if position.startswith(("attrs.", "ext.")):
        container_name, edge_type = position.split(".", 1)
        record = MIRLRecord(
            id=record_id,
            kind=RecordKind.META,
            attrs={"key": "position", "value": edge_type},
        )
        getattr(record, container_name)[edge_type] = [duplicate_id]
        return record
    raise AssertionError(f"unknown reference position: {position}")


def _downgrade_core_storage_to_v1(connection: sqlite3.Connection) -> None:
    connection.execute("drop table ir_edge_sources")
    connection.execute("alter table ir_edges drop column src_ref_type")
    connection.execute("alter table ir_edges drop column dst_ref_type")
    connection.execute(
        f"update {PROJECTION_TABLE} set projection_version = 'core-storage/1' "
        "where projection_name = 'core_storage'"
    )


def _build_core_v1_fixture(path: Path, records: list[MIRLRecord]) -> None:
    store = SQLiteStore(path)
    store.close()
    with closing(sqlite3.connect(path)) as connection:
        _downgrade_core_storage_to_v1(connection)
        connection.executemany(
            "insert into ir_records "
            "(id, kind, ns, scope, status, conf, t0, t1, created_at, "
            "updated_at, payload_json) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.id,
                    record.kind.value,
                    record.ns,
                    record.scope,
                    record.status.value,
                    record.conf,
                    record.t0,
                    record.t1,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")),
                )
                for record in records
            ],
        )
        connection.commit()


def _typed_edge_conflict_records(
    *,
    virtual_record_id: str,
    canonical_record_id: str,
) -> tuple[MIRLRecord, MIRLRecord]:
    source_id = "shared-conflict-source"
    target_id = "shared-conflict-target"
    attrs = {"src": source_id, "predicate": "conflicts-with", "dst": target_id}
    virtual = MIRLRecord(
        id=virtual_record_id,
        kind=RecordKind.REL,
        ext={VIRTUAL_REFS_EXTENSION: [source_id, target_id]},
        attrs=dict(attrs),
    )
    canonical = MIRLRecord(
        id=canonical_record_id,
        kind=RecordKind.REL,
        attrs=dict(attrs),
    )
    return virtual, canonical


def _assert_core_v1_rollback_without_contributors(
    path: Path,
    before_hashes: dict[str, str],
) -> None:
    assert _table_hashes(path, CORE_MIGRATION_TABLES) == before_hashes
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "select count(*) from sqlite_master "
            "where type = 'table' and name = 'ir_edge_sources'"
        ).fetchone()[0] == 0
        assert connection.execute("select count(*) from ir_edges").fetchone()[0] == 0
        assert connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone()[0] == "core-storage/1"


def _edge_rows(store: SQLiteStore) -> set[tuple[str, str, str, str, str]]:
    with closing(store._connect()) as connection:
        rows = connection.execute(
            "select src_id, src_ref_type, edge_type, dst_id, dst_ref_type "
            "from ir_edges"
        ).fetchall()
    return {tuple(str(value) for value in row) for row in rows}


def _edge_sources(
    store: SQLiteStore,
) -> set[tuple[str, str, str, str]]:
    with closing(store._connect()) as connection:
        rows = connection.execute(
            "select source_record_id, src_id, edge_type, dst_id "
            "from ir_edge_sources"
        ).fetchall()
    return {tuple(str(value) for value in row) for row in rows}


@pytest.mark.parametrize("bad_id", [123, "", " \t"])
def test_non_string_or_blank_record_id_cannot_mint_unreopenable_store(
    tmp_path: Path,
    bad_id: object,
) -> None:
    path = tmp_path / "invalid-record-id.db"
    malformed = MIRLRecord(
        id=bad_id,  # type: ignore[arg-type] - exercise runtime shape defense
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "invalid id"},
    )
    runtime = SeamRuntime(path, allow_pgvector_env=False)
    try:
        baseline = _all_table_hashes(path)
        report = runtime.verify_ir(IRBatch([malformed]))
        assert not report.valid
        assert {issue.code for issue in report.issues} >= {"invalid_record_id"}

        with pytest.raises(ValueError, match="invalid_record_id"):
            runtime.persist_ir(IRBatch([malformed]))
        with pytest.raises(
            ValueError,
            match="canonical record id must be a nonblank string",
        ):
            runtime.store.persist_ir(IRBatch([malformed]))
        with pytest.raises((TypeError, ValueError)):
            MIRLRecord.from_dict(malformed.to_dict())

        assert _all_table_hashes(path) == baseline
        assert runtime.store.load_ir().records == []
    finally:
        runtime.close()


@pytest.mark.parametrize("position", REQUIRED_SCALAR_REFERENCE_POSITIONS)
def test_persist_ir_rejects_every_malformed_required_scalar_without_mutation(
    tmp_path: Path,
    position: str,
) -> None:
    path = tmp_path / f"invalid-{position.replace('.', '-')}.db"
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "shape anchor"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([anchor]))
        baseline = _all_table_hashes(path)

        for case, bad_value in INVALID_REQUIRED_SCALARS:
            malformed = _record_for_reference_position(
                position,
                REFERENCE_SHAPE_ANCHOR_ID,
                REFERENCE_SHAPE_ANCHOR_ID,
            )
            _replace_required_scalar_position(
                malformed,
                position,
                deepcopy(bad_value),
            )
            before_record = deepcopy(malformed)

            with pytest.raises(
                CanonicalReferenceShapeError,
                match="^required reference value is invalid$",
            ) as raised:
                store.persist_ir(IRBatch([malformed]))

            diagnostics = str(raised.value)
            assert malformed.id not in diagnostics, case
            assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics, case
            assert REFERENCE_SHAPE_SECRET not in diagnostics, case
            assert malformed == before_record, case
            assert _all_table_hashes(path) == baseline, case
    finally:
        store.close()


@pytest.mark.parametrize("field", ["prov", "evidence", "pack.refs"])
def test_persist_ir_rejects_malformed_required_lists_without_mutation(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / f"invalid-{field.replace('.', '-')}.db"
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "shape anchor"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([anchor]))
        baseline = _all_table_hashes(path)

        for case, bad_value in INVALID_REQUIRED_LISTS:
            if field == "pack.refs":
                malformed = MIRLRecord(
                    id="pack:invalid-required-list",
                    kind=RecordKind.PACK,
                    attrs={
                        "mode": "exact",
                        "lens": "general",
                        "refs": deepcopy(bad_value),
                        "payload": {},
                    },
                )
            else:
                malformed = MIRLRecord(
                    id=f"meta:invalid-{field}-list",
                    kind=RecordKind.META,
                    attrs={"key": "shape", "value": field},
                )
                setattr(malformed, field, deepcopy(bad_value))
            before_record = deepcopy(malformed)

            with pytest.raises(
                CanonicalReferenceShapeError,
                match="^required reference value is invalid$",
            ) as raised:
                store.persist_ir(IRBatch([malformed]))

            diagnostics = str(raised.value)
            assert malformed.id not in diagnostics, case
            assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics, case
            assert REFERENCE_SHAPE_SECRET not in diagnostics, case
            assert malformed == before_record, case
            assert _all_table_hashes(path) == baseline, case
    finally:
        store.close()


@pytest.mark.parametrize(
    ("kind", "attrs"),
    [
        pytest.param(
            RecordKind.EVT,
            {
                "actor": REFERENCE_SHAPE_ANCHOR_ID,
                "subject": None,
                "action": "observed",
            },
            id="evt-invalid-secondary-subject",
        ),
        pytest.param(
            RecordKind.EVT,
            {
                "actor": None,
                "subject": REFERENCE_SHAPE_ANCHOR_ID,
                "action": "observed",
            },
            id="evt-invalid-preferred-actor",
        ),
        pytest.param(
            RecordKind.STA,
            {
                "target": REFERENCE_SHAPE_ANCHOR_ID,
                "subject": None,
                "state": "active",
            },
            id="sta-invalid-secondary-subject",
        ),
        pytest.param(
            RecordKind.STA,
            {
                "target": None,
                "subject": REFERENCE_SHAPE_ANCHOR_ID,
                "state": "active",
            },
            id="sta-invalid-preferred-target",
        ),
    ],
)
def test_required_aliases_do_not_silently_fall_through_invalid_supplied_values(
    kind: RecordKind,
    attrs: dict[str, object],
) -> None:
    record = MIRLRecord(id=f"{kind.value.lower()}:invalid-alias", kind=kind, attrs=attrs)

    with pytest.raises(
        CanonicalReferenceShapeError,
        match="^required reference value is invalid$",
    ):
        validate_record_reference_contract(record)


def test_flow_accepts_retrieval_operation_and_linked_reference_shapes() -> None:
    source = MIRLRecord(
        id="ent:flow-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:flow-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    retrieval = compile_dsl(
        "retrieve flow:retrieval-operation:\n"
        '  query "canonical memory"\n'
        "  lens general\n"
        "  budget 10"
    ).records[0]
    linked = MIRLRecord(
        id="flow:linked-reference-pair",
        kind=RecordKind.FLOW,
        attrs={"op": "flows_to", "src": source.id, "dst": target.id},
    )

    store = SQLiteStore(":memory:")
    try:
        store.persist_ir(IRBatch([retrieval, linked, target, source]))

        sources = _edge_sources(store)
        assert not any(row[0] == retrieval.id for row in sources)
        assert (
            linked.id,
            source.id,
            "flows_to",
            target.id,
        ) in sources
    finally:
        store.close()


@pytest.mark.parametrize("supplied_field", ["src", "dst"])
def test_flow_rejects_partial_linked_reference_pair(supplied_field: str) -> None:
    record = MIRLRecord(
        id=f"flow:partial-{supplied_field}",
        kind=RecordKind.FLOW,
        attrs={"op": "flows_to", supplied_field: REFERENCE_SHAPE_ANCHOR_ID},
    )

    with pytest.raises(
        CanonicalReferenceShapeError,
        match="^required reference value is invalid$",
    ):
        validate_record_reference_contract(record)


@pytest.mark.parametrize("location", ["attrs", "ext"])
@pytest.mark.parametrize("shape", ["scalar", "list"])
def test_all_reconciliation_pointers_accept_scalar_and_list_forms(
    location: str,
    shape: str,
) -> None:
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "shape anchor"},
    )
    pointer_values = {
        field: (
            REFERENCE_SHAPE_ANCHOR_ID
            if shape == "scalar"
            else [REFERENCE_SHAPE_ANCHOR_ID]
        )
        for field in RECONCILIATION_REFERENCE_FIELDS
    }
    record = MIRLRecord(
        id=f"meta:{location}-{shape}-reconciliation-pointers",
        kind=RecordKind.META,
        attrs={"key": "pointer-shape", "value": shape},
    )
    getattr(record, location).update(pointer_values)

    store = SQLiteStore(":memory:")
    try:
        store.persist_ir(IRBatch([record, anchor]))

        projected_pointer_types = {
            edge_type
            for source_id, _, edge_type, destination_id, _ in _edge_rows(store)
            if source_id == record.id
            and destination_id == anchor.id
            and edge_type in RECONCILIATION_REFERENCE_FIELDS
        }
        assert projected_pointer_types == set(RECONCILIATION_REFERENCE_FIELDS)
        stored = store.load_ir(ids=[record.id]).records[0]
        assert getattr(stored, location) == getattr(record, location)
    finally:
        store.close()


@pytest.mark.parametrize("location", ["attrs", "ext"])
@pytest.mark.parametrize("field", RECONCILIATION_REFERENCE_FIELDS)
def test_reconciliation_pointers_reject_every_invalid_shape_and_member(
    location: str,
    field: str,
) -> None:
    for case, bad_value in INVALID_RECONCILIATION_POINTERS:
        record = MIRLRecord(
            id=f"meta:invalid-{location}-{field}",
            kind=RecordKind.META,
            attrs={"key": "pointer", "value": field},
        )
        getattr(record, location)[field] = deepcopy(bad_value)
        before_record = deepcopy(record)

        with pytest.raises(
            CanonicalReferenceShapeError,
            match="^required reference value is invalid$",
        ) as raised:
            validate_record_reference_contract(record)

        diagnostics = str(raised.value)
        assert record.id not in diagnostics, case
        assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics, case
        assert REFERENCE_SHAPE_SECRET not in diagnostics, case
        assert record == before_record, case


def test_empty_required_lists_are_valid_and_optional_literals_remain_unconstrained() -> None:
    empty_lists = MIRLRecord(
        id="pack:empty-required-lists",
        kind=RecordKind.PACK,
        prov=[],
        evidence=[],
        attrs={
            "mode": "exact",
            "lens": "general",
            "refs": [],
            **{field: [] for field in RECONCILIATION_REFERENCE_FIELDS},
        },
        ext={field: [] for field in RECONCILIATION_REFERENCE_FIELDS},
    )
    validate_record_reference_contract(empty_lists)

    for optional_literal in (
        None,
        "",
        " literal:with-edge-whitespace ",
        7,
        {"nested": "literal"},
        ["literal"],
    ):
        claim = MIRLRecord(
            id="clm:optional-object-literal",
            kind=RecordKind.CLM,
            attrs={
                "subject": REFERENCE_SHAPE_ANCHOR_ID,
                "predicate": "describes",
                "object": deepcopy(optional_literal),
                "facets": {
                    facet: deepcopy(optional_literal)
                    for facet in FACET_REFERENCE_FIELDS
                },
            },
        )
        validate_record_reference_contract(claim)


def test_persist_reference_shape_failure_is_atomic_and_does_not_remap_inputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "required-shape-atomic-remap.db"
    canonical = MIRLRecord(
        id="ent:canonical-shape-atomic",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "Alice"},
    )
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "shape anchor"},
    )
    duplicate = MIRLRecord(
        id="ent:duplicate-shape-atomic",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": " alice "},
    )
    relation = MIRLRecord(
        id="rel:shape-atomic-remap",
        kind=RecordKind.REL,
        attrs={
            "src": duplicate.id,
            "predicate": "references",
            "dst": anchor.id,
        },
    )
    malformed = MIRLRecord(
        id="meta:private-shape-atomic-malformed",
        kind=RecordKind.META,
        attrs={
            "key": "shape",
            "value": "invalid",
            "supports": [anchor.id, {REFERENCE_SHAPE_SECRET: anchor.id}],
        },
    )
    incoming = IRBatch([duplicate, relation, malformed])
    before_inputs = deepcopy(incoming)

    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([canonical, anchor]))
        before_tables = _all_table_hashes(path)

        with pytest.raises(
            CanonicalReferenceShapeError,
            match="^required reference value is invalid$",
        ) as raised:
            store.persist_ir(incoming)

        diagnostics = str(raised.value)
        assert malformed.id not in diagnostics
        assert REFERENCE_SHAPE_SECRET not in diagnostics
        assert incoming == before_inputs
        assert _all_table_hashes(path) == before_tables
    finally:
        store.close()


def test_direct_graph_projection_prevalidates_entire_batch_before_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "required-shape-direct-projection.db"
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "original anchor"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([anchor]))
        replacement = MIRLRecord(
            id=anchor.id,
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "replacement anchor"},
        )
        malformed = MIRLRecord(
            id="meta:private-direct-projection-malformed",
            kind=RecordKind.META,
            attrs={
                "key": "shape",
                "value": "invalid",
                "supports": [REFERENCE_SHAPE_ANCHOR_ID, None],
            },
        )
        before_inputs = deepcopy([replacement, malformed])

        with closing(store._connect()) as connection:
            before_graph = _connection_table_rows(
                connection,
                name_prefix="knowledge_",
            )
            with pytest.raises(
                CanonicalReferenceShapeError,
                match="^required reference value is invalid$",
            ) as raised:
                project_records(connection, [replacement, malformed])

            diagnostics = str(raised.value)
            assert malformed.id not in diagnostics
            assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics
            assert [replacement, malformed] == before_inputs
            assert _connection_table_rows(
                connection,
                name_prefix="knowledge_",
            ) == before_graph
    finally:
        store.close()


def test_current_store_reopen_rejects_malformed_reference_shape_read_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "required-shape-current-reopen.db"
    anchor = MIRLRecord(
        id=REFERENCE_SHAPE_ANCHOR_ID,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "shape anchor"},
    )
    source = MIRLRecord(
        id="meta:private-current-shape-source",
        kind=RecordKind.META,
        attrs={
            "key": "shape",
            "value": "valid",
            "supports": anchor.id,
        },
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([anchor, source]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        payload = source.to_dict()
        payload["attrs"]["supports"] = {
            REFERENCE_SHAPE_SECRET: REFERENCE_SHAPE_ANCHOR_ID
        }
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), source.id),
        )
        connection.commit()

    before_bytes = path.read_bytes()
    before_tables = _all_table_hashes(path)
    backup_dir = tmp_path / "current-shape-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="invalid canonical payload reference",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert source.id not in diagnostics
    assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics
    assert REFERENCE_SHAPE_SECRET not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_tables
    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("field", "malformed_container"),
    [
        pytest.param("prov", "x", id="prov-scalar"),
        pytest.param(
            "evidence",
            {"x": REFERENCE_SHAPE_SECRET},
            id="evidence-mapping",
        ),
    ],
)
def test_current_store_reopen_rejects_raw_malformed_reference_containers(
    tmp_path: Path,
    field: str,
    malformed_container: object,
) -> None:
    path = tmp_path / f"raw-{field}-container-current-reopen.db"
    anchor = MIRLRecord(
        id="x",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "one-character anchor"},
    )
    source = MIRLRecord(
        id=f"meta:private-current-{field}-container",
        kind=RecordKind.META,
        attrs={"key": "shape", "value": "initially-valid"},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([anchor, source]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        payload = source.to_dict()
        payload[field] = deepcopy(malformed_container)
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), source.id),
        )
        connection.commit()

    before_bytes = path.read_bytes()
    before_tables = _all_table_hashes(path)
    backup_dir = tmp_path / f"raw-{field}-current-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="invalid canonical payload reference",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert source.id not in diagnostics
    assert REFERENCE_SHAPE_SECRET not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_tables
    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("field", "malformed_container"),
    [
        pytest.param("prov", "x", id="prov-scalar"),
        pytest.param(
            "evidence",
            {"x": REFERENCE_SHAPE_SECRET},
            id="evidence-mapping",
        ),
    ],
)
def test_core_storage_migration_rejects_raw_malformed_reference_containers(
    tmp_path: Path,
    field: str,
    malformed_container: object,
) -> None:
    path = tmp_path / f"raw-{field}-container-migration.db"
    fillers = [
        MIRLRecord(
            id=f"meta:a-raw-container-filler-{index:03d}",
            kind=RecordKind.META,
            attrs={"key": f"filler-{index:03d}", "value": "bounded"},
        )
        for index in range(500)
    ]
    anchor = MIRLRecord(
        id="x",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "one-character anchor"},
    )
    malformed = MIRLRecord(
        id=f"meta:z-private-migration-{field}-container",
        kind=RecordKind.META,
        attrs={"key": "shape", "value": "initially-valid"},
    )
    _build_core_v1_fixture(path, [*fillers, malformed, anchor])
    with closing(sqlite3.connect(path)) as connection:
        payload = malformed.to_dict()
        payload[field] = deepcopy(malformed_container)
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                malformed.id,
            ),
        )
        connection.commit()
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)

    with pytest.raises(MigrationError) as raised:
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / f"raw-{field}-migration-backups",
        )

    diagnostics = str(raised.value)
    assert malformed.id not in diagnostics
    assert REFERENCE_SHAPE_SECRET not in diagnostics
    _assert_core_v1_rollback_without_contributors(path, before_hashes)


def test_core_storage_migration_rejects_cross_batch_malformed_reference_shape(
    tmp_path: Path,
) -> None:
    path = tmp_path / "required-shape-cross-batch-migration.db"
    fillers = [
        MIRLRecord(
            id=f"meta:a-shape-filler-{index:03d}",
            kind=RecordKind.META,
            attrs={"key": f"filler-{index:03d}", "value": "bounded"},
        )
        for index in range(500)
    ]
    malformed = MIRLRecord(
        id="meta:z-private-cross-batch-shape",
        kind=RecordKind.META,
        attrs={
            "key": "shape",
            "value": "invalid",
            "supports": [
                REFERENCE_SHAPE_ANCHOR_ID,
                {REFERENCE_SHAPE_SECRET: REFERENCE_SHAPE_ANCHOR_ID},
            ],
        },
    )
    _build_core_v1_fixture(path, [*fillers, malformed])
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)

    with pytest.raises(MigrationError) as raised:
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / "cross-batch-shape-backups",
        )

    diagnostics = str(raised.value)
    assert malformed.id not in diagnostics
    assert REFERENCE_SHAPE_ANCHOR_ID not in diagnostics
    assert REFERENCE_SHAPE_SECRET not in diagnostics
    _assert_core_v1_rollback_without_contributors(path, before_hashes)


@pytest.mark.parametrize(
    "duplicate_case",
    ["same-payload", "different-payload", "different-kind"],
)
def test_persist_ir_rejects_duplicate_record_ids_without_table_changes(
    tmp_path: Path,
    duplicate_case: str,
) -> None:
    path = tmp_path / f"duplicate-record-{duplicate_case}.db"
    duplicate_id = "private-duplicate-record-id"
    first = MIRLRecord(
        id=duplicate_id,
        kind=RecordKind.META,
        attrs={"key": "first", "value": "same"},
    )
    if duplicate_case == "same-payload":
        second = MIRLRecord.from_dict(first.to_dict())
    elif duplicate_case == "different-payload":
        second = MIRLRecord(
            id=duplicate_id,
            kind=RecordKind.META,
            attrs={"key": "second", "value": "different"},
        )
    else:
        second = MIRLRecord(
            id=duplicate_id,
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "different kind"},
        )

    store = SQLiteStore(path)
    try:
        store.check_ready()
        before = _all_table_hashes(path)
        with pytest.raises(
            ValueError,
            match="IR batch contains duplicate record identifiers",
        ) as raised:
            store.persist_ir(IRBatch([first, second]))

        assert duplicate_id not in str(raised.value)
        assert _all_table_hashes(path) == before
    finally:
        store.close()


@pytest.mark.parametrize(
    "position",
    [
        "clm.subject",
        "clm.object",
        "evt.actor",
        "evt.subject",
        "evt.object",
        "rel.src",
        "rel.dst",
        "sta.target",
        "sta.subject",
        "pack.refs",
        "flow.src",
        "flow.dst",
        "prov.entity",
        *(f"attrs.{field}" for field in RECONCILIATION_REFERENCE_FIELDS),
        *(f"ext.{field}" for field in RECONCILIATION_REFERENCE_FIELDS),
        *(f"attrs.facets.{facet}" for facet in FACET_REFERENCE_FIELDS),
        "ext.virtual_refs",
    ],
)
def test_entity_reconciliation_remaps_every_declared_reference_position(
    position: str,
) -> None:
    canonical = MIRLRecord(
        id="ent:canonical-remap",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "Alice"},
    )
    anchor = MIRLRecord(
        id="ent:remap-anchor",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "Anchor"},
    )
    duplicate = MIRLRecord(
        id="ent:duplicate-remap",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "  alice  "},
    )
    referencing = _record_for_reference_position(
        position,
        duplicate.id,
        anchor.id,
    )

    store = SQLiteStore(":memory:")
    try:
        store.persist_ir(IRBatch([canonical, anchor]))
        report = store.persist_ir(IRBatch([duplicate, referencing]))

        assert report.stored_ids == [referencing.id]
        stored = store.load_ir(ids=[referencing.id]).records[0]
        assert duplicate.id not in json.dumps(stored.to_dict(), sort_keys=True)
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select count(*) from ir_records where id = ?",
                (duplicate.id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select count(*) from ir_edges where src_id = ? or dst_id = ?",
                (duplicate.id, duplicate.id),
            ).fetchone()[0] == 0
            remapped_edges = connection.execute(
                "select sources.src_id, sources.dst_id "
                "from ir_edge_sources sources "
                "where sources.source_record_id = ?",
                (referencing.id,),
            ).fetchall()
            remapped_graph_edges = connection.execute(
                "select src_id, dst_id from knowledge_edges "
                "where source_record_id = ?",
                (referencing.id,),
            ).fetchall()
        assert remapped_edges or remapped_graph_edges
        assert any(
            canonical.id in (str(row[0]), str(row[1])) for row in remapped_edges
        ) or any(
            canonical.id in (str(row[0]), str(row[1]))
            for row in remapped_graph_edges
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "position",
    ["prov", "evidence", "span.raw_id"],
)
def test_required_reference_positions_reject_wrong_canonical_target_kind(
    position: str,
    tmp_path: Path,
) -> None:
    wrong_target = MIRLRecord(
        id="ent:wrong-field-kind-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "Wrong target kind"},
    )
    referencing = _record_for_reference_position(
        position,
        wrong_target.id,
        wrong_target.id,
    )
    path = tmp_path / f"wrong-field-kind-{position.replace('.', '-')}.db"
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([wrong_target]))
        before = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="field contract",
        ) as raised:
            store.persist_ir(IRBatch([referencing]))
        assert wrong_target.id not in str(raised.value)
        assert _all_table_hashes(path) == before
    finally:
        store.close()


@pytest.mark.parametrize(
    "position",
    ["prov", "evidence", "span.raw_id"],
)
def test_typed_provenance_positions_reject_virtual_substitution(
    position: str,
    tmp_path: Path,
) -> None:
    virtual_id = "private-virtual-provenance-target"
    referencing = _record_for_reference_position(
        position,
        virtual_id,
        virtual_id,
    )
    referencing.ext[VIRTUAL_REFS_EXTENSION] = [virtual_id]
    path = tmp_path / f"virtual-field-kind-{position.replace('.', '-')}.db"
    store = SQLiteStore(path)
    try:
        before = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="field-kind contract",
        ) as raised:
            store.persist_ir(IRBatch([referencing]))
        assert virtual_id not in str(raised.value)
        assert _all_table_hashes(path) == before
    finally:
        store.close()


def test_typed_provenance_positions_accept_exact_canonical_kinds() -> None:
    raw = MIRLRecord(
        id="raw:typed-provenance-source",
        kind=RecordKind.RAW,
        attrs={"content": "typed provenance source"},
    )
    span = MIRLRecord(
        id="span:typed-provenance-source",
        kind=RecordKind.SPAN,
        attrs={"raw_id": raw.id, "start": 0, "end": 5, "text": "typed"},
    )
    provenance = MIRLRecord(
        id="prov:typed-provenance-source",
        kind=RecordKind.PROV,
        attrs={"entity": raw.id, "activity": "observed", "agent": "test"},
    )
    record = MIRLRecord(
        id="meta:typed-provenance-consumer",
        kind=RecordKind.META,
        prov=[provenance.id],
        evidence=[raw.id, span.id],
        attrs={"schema": "typed-provenance-test"},
    )
    store = SQLiteStore(":memory:")
    try:
        store.persist_ir(IRBatch([record, provenance, span, raw]))
        with closing(store._connect()) as connection:
            edge_types = {
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    "select edge_type, dst_ref_type from ir_edges "
                    "where src_id = ? order by edge_type, dst_id",
                    (record.id,),
                ).fetchall()
            }
        assert edge_types == {
            ("evidence", "RAW"),
            ("evidence", "SPAN"),
            ("prov", "PROV"),
        }
    finally:
        store.close()


@pytest.mark.parametrize(
    ("kind", "attrs"),
    [
        (
            RecordKind.EVT,
            {
                "actor": "ent:alias-primary",
                "subject": "ent:alias-conflict",
                "action": "observed",
            },
        ),
        (
            RecordKind.STA,
            {
                "target": "ent:alias-primary",
                "subject": "ent:alias-conflict",
                "fields": {"state": "ready"},
            },
        ),
    ],
)
def test_required_reference_aliases_cannot_diverge(
    kind: RecordKind,
    attrs: dict[str, object],
    tmp_path: Path,
) -> None:
    primary = MIRLRecord(
        id="ent:alias-primary",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "Primary"},
    )
    conflict = MIRLRecord(
        id="ent:alias-conflict",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "Conflict"},
    )
    record = MIRLRecord(
        id=f"{kind.value.lower()}:divergent-alias",
        kind=kind,
        attrs=attrs,
    )
    path = tmp_path / f"divergent-alias-{kind.value.lower()}.db"
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([primary, conflict]))
        before = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="aliases disagree",
        ):
            store.persist_ir(IRBatch([record]))
        assert _all_table_hashes(path) == before
    finally:
        store.close()


@pytest.mark.parametrize("facet", FACET_REFERENCE_FIELDS)
def test_entity_reconciliation_leaves_unmatched_optional_facets_literal(
    facet: str,
) -> None:
    literal = f"literal:{facet}:not-a-canonical-id"
    record = MIRLRecord(
        id=f"meta:literal-facet-{facet}",
        kind=RecordKind.META,
        attrs={"key": "facet", "value": facet, "facets": {facet: literal}},
    )
    before = record.to_dict()

    remap_record_references(
        record,
        {"ent:duplicate": "ent:canonical"},
    )

    assert record.to_dict() == before


def test_entity_reconciliation_does_not_remap_literal_payload_text() -> None:
    canonical = MIRLRecord(
        id="ent:canonical-literal",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": "Alice"},
    )
    duplicate = MIRLRecord(
        id="ent:duplicate-literal",
        kind=RecordKind.ENT,
        attrs={"entity_type": "person", "label": " alice "},
    )
    literal = MIRLRecord(
        id="meta:literal-remap-guard",
        kind=RecordKind.META,
        attrs={"key": "literal", "value": duplicate.id},
    )
    store = SQLiteStore(":memory:")
    try:
        store.persist_ir(IRBatch([canonical]))
        store.persist_ir(IRBatch([duplicate, literal]))

        stored = store.load_ir(ids=[literal.id]).records[0]
        assert stored.attrs["value"] == duplicate.id
        assert not any(
            duplicate.id in (edge[0], edge[3]) for edge in _edge_rows(store)
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    ("bad_declaration", "declaration_secret"),
    [
        pytest.param("private-virtual-string", "private-virtual-string", id="string"),
        pytest.param(("private-virtual-tuple",), "private-virtual-tuple", id="tuple"),
        pytest.param(None, "", id="null"),
        pytest.param([" "], "", id="blank-id"),
        pytest.param([7], "", id="non-string-id"),
    ],
)
@pytest.mark.parametrize("record_shape", ["canonical-endpoints", "no-endpoints"])
def test_persist_ir_rejects_malformed_virtual_reference_metadata_before_mutation(
    tmp_path: Path,
    bad_declaration: object,
    declaration_secret: str,
    record_shape: str,
) -> None:
    path = tmp_path / f"malformed-virtual-{record_shape}.db"
    source = MIRLRecord(
        id="ent:virtual-metadata-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:virtual-metadata-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    if record_shape == "canonical-endpoints":
        malformed = MIRLRecord(
            id="rel:private-malformed-virtual-metadata",
            kind=RecordKind.REL,
            ext={VIRTUAL_REFS_EXTENSION: bad_declaration},
            attrs={"src": source.id, "predicate": "links", "dst": target.id},
        )
    else:
        malformed = MIRLRecord(
            id="meta:private-malformed-virtual-metadata",
            kind=RecordKind.META,
            ext={VIRTUAL_REFS_EXTENSION: bad_declaration},
            attrs={"key": "metadata", "value": "invalid"},
        )
    before_record = malformed.to_dict()

    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target]))
        before_tables = _all_table_hashes(path)

        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="virtual reference declaration",
        ) as raised:
            store.persist_ir(IRBatch([malformed]))

        diagnostics = str(raised.value)
        assert malformed.id not in diagnostics
        if declaration_secret:
            assert declaration_secret not in diagnostics
        assert malformed.to_dict() == before_record
        assert _all_table_hashes(path) == before_tables
    finally:
        store.close()


@pytest.mark.parametrize("missing_case", ["one-sided", "self-loop"])
def test_persist_ir_rejects_missing_required_reference_before_writes(
    tmp_path: Path,
    missing_case: str,
) -> None:
    path = tmp_path / f"missing-required-{missing_case}.db"
    missing_id = "private-missing-required-reference"
    anchor = MIRLRecord(
        id="ent:required-reference-anchor",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "anchor"},
    )
    relation = MIRLRecord(
        id=f"rel:missing-required-{missing_case}",
        kind=RecordKind.REL,
        attrs={
            "src": missing_id,
            "predicate": "references",
            "dst": missing_id if missing_case == "self-loop" else anchor.id,
        },
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([anchor]))
        before = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="required canonical reference is missing",
        ) as raised:
            store.persist_ir(IRBatch([relation]))

        assert missing_id not in str(raised.value)
        assert relation.id not in str(raised.value)
        assert _all_table_hashes(path) == before
    finally:
        store.close()


def test_persist_ir_rejects_canonical_kind_change_without_table_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "canonical-kind-change.db"
    record_id = "private-canonical-kind-change"
    original = MIRLRecord(
        id=record_id,
        kind=RecordKind.META,
        attrs={"key": "kind", "value": "meta"},
    )
    replacement = MIRLRecord(
        id=record_id,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "replacement"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([original]))
        before = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="canonical record kind cannot change during persistence",
        ) as raised:
            store.persist_ir(IRBatch([replacement]))

        assert record_id not in str(raised.value)
        assert _all_table_hashes(path) == before
    finally:
        store.close()


def test_whole_message_colon_text_projects_only_literal_value_nodes() -> None:
    message = (
        "Meet at 09:30. Visit https://example.com/a:b. "
        "Keep arbitrary:key literal."
    )
    store = SQLiteStore(":memory:")
    try:
        batch = compile_nl(message, allow_env_extractor=False)
        store.persist_ir(batch)
        literal_claims = {
            str(record.attrs["object"])
            for record in batch.records
            if record.kind is RecordKind.CLM
        }
        assert literal_claims == {
            "Meet at 09:30.",
            "Visit https://example.com/a:b.",
            "Keep arbitrary:key literal.",
        }

        with closing(store._connect()) as connection:
            nodes = connection.execute(
                "select id, kind, properties_json from knowledge_nodes"
            ).fetchall()
        assert not literal_claims.intersection(str(row["id"]) for row in nodes)
        for literal in literal_claims:
            matches = [
                row
                for row in nodes
                if json.loads(str(row["properties_json"])).get("reference")
                == literal
            ]
            assert len(matches) == 1
            assert matches[0]["kind"] == "value"
            assert str(matches[0]["id"]).startswith("value:")
    finally:
        store.close()


def test_same_batch_and_stored_optional_references_resolve_as_records() -> None:
    store = SQLiteStore(":memory:")
    try:
        same_batch_target = MIRLRecord(
            id="ent:same-batch",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "same batch"},
        )
        same_batch_subject = MIRLRecord(
            id="ent:subject",
            kind=RecordKind.ENT,
            attrs={"entity_type": "person", "label": "subject"},
        )
        same_batch_claim = MIRLRecord(
            id="clm:same-batch",
            kind=RecordKind.CLM,
            attrs={
                "subject": same_batch_subject.id,
                "predicate": "references",
                "object": same_batch_target.id,
            },
        )
        # Put the claim first to prove resolution is independent of batch order.
        store.persist_ir(
            IRBatch([same_batch_claim, same_batch_target, same_batch_subject])
        )
        same_batch_edge = (
            same_batch_subject.id,
            "ENT",
            "references",
            same_batch_target.id,
            "ENT",
        )
        assert same_batch_edge in _edge_rows(store)

        stored_target = MIRLRecord(
            id="ent:stored",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "stored"},
        )
        store.persist_ir(IRBatch([stored_target]))
        stored_claim = MIRLRecord(
            id="clm:stored",
            kind=RecordKind.CLM,
            attrs={
                "subject": same_batch_subject.id,
                "predicate": "references",
                "object": stored_target.id,
            },
        )
        store.persist_ir(IRBatch([stored_claim]))

        edges = _edge_rows(store)
        assert (
            same_batch_subject.id,
            "ENT",
            "references",
            stored_target.id,
            "ENT",
        ) in edges
    finally:
        store.close()


def test_reference_lookup_ignores_unrelated_invalid_rows_but_fails_closed_when_referenced() -> None:
    store = SQLiteStore(":memory:")
    try:
        valid_target = MIRLRecord(
            id="ent:valid-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "valid"},
        )
        subject = MIRLRecord(
            id="ent:lookup-subject",
            kind=RecordKind.ENT,
            attrs={"entity_type": "person", "label": "subject"},
        )
        store.persist_ir(IRBatch([valid_target, subject]))
        with closing(store._connect()) as connection:
            connection.execute(
                "insert into ir_records "
                "(id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
                "values ('unrelated-corrupt-row', 'NOT_A_KIND', 'default', 'global', "
                "'asserted', 1.0, '2026-01-01T00:00:00Z', "
                "'2026-01-01T00:00:00Z', '{}')"
            )
            connection.commit()

        valid_claim = MIRLRecord(
            id="clm:valid-lookup",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "references",
                "object": valid_target.id,
            },
        )
        store.persist_ir(IRBatch([valid_claim]))
        assert (
            subject.id,
            "ENT",
            "references",
            valid_target.id,
            "ENT",
        ) in _edge_rows(store)

        corrupt_reference = MIRLRecord(
            id="clm:corrupt-lookup",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "references",
                "object": "unrelated-corrupt-row",
            },
        )
        try:
            store.persist_ir(IRBatch([corrupt_reference]))
        except CanonicalReferenceIntegrityError as exc:
            assert str(exc) == "stored canonical reference has an invalid MIRL kind"
            assert "unrelated-corrupt-row" not in str(exc)
        else:
            raise AssertionError("referenced invalid canonical kind did not fail closed")
    finally:
        store.close()


def test_orphan_sweep_is_kind_agnostic_and_checks_both_typed_endpoints() -> None:
    store = SQLiteStore(":memory:")
    try:
        anchor = MIRLRecord(
            id="ent:anchor",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "anchor"},
        )
        store.persist_ir(IRBatch([anchor]))
        with closing(store._connect()) as connection:
            for kind in RecordKind:
                missing = f"missing-{kind.value.lower()}"
                connection.execute(
                    "insert into ir_edges "
                    "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                    "values (?, ?, ?, ?, 'ENT')",
                    (missing, kind.value, f"src-{kind.value}", anchor.id),
                )
                connection.execute(
                    "insert into ir_edges "
                    "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                    "values (?, 'ENT', ?, ?, ?)",
                    (anchor.id, f"dst-{kind.value}", missing, kind.value),
                )
            store._cleanup_orphan_edges(connection)
            remaining = connection.execute(
                "select count(*) from ir_edges where edge_type like 'src-%' "
                "or edge_type like 'dst-%'"
            ).fetchone()[0]
        assert remaining == 0
    finally:
        store.close()


def test_orphan_sweep_rejects_wrong_kind_on_either_endpoint() -> None:
    store = SQLiteStore(":memory:")
    try:
        anchor = MIRLRecord(
            id="ent:typed-anchor",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "typed anchor"},
        )
        store.persist_ir(IRBatch([anchor]))
        with closing(store._connect()) as connection:
            connection.execute(
                "insert into ir_edges "
                "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                "values (?, 'CLM', 'wrong-src-kind', ?, 'ENT')",
                (anchor.id, anchor.id),
            )
            connection.execute(
                "insert into ir_edges "
                "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                "values (?, 'ENT', 'wrong-dst-kind', ?, 'RAW')",
                (anchor.id, anchor.id),
            )
            store._cleanup_orphan_edges(connection)
            assert connection.execute(
                "select count(*) from ir_edges where edge_type like 'wrong-%'"
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_explicit_virtual_entity_survives_reopen_and_repeat_cleanup(
    tmp_path,
) -> None:
    path = tmp_path / "virtual.db"
    virtual_id = "graph-only-turn-7"
    anchor = MIRLRecord(
        id="ent:anchor",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "anchor"},
    )
    relation = MIRLRecord(
        id="rel:virtual",
        kind=RecordKind.REL,
        ext={VIRTUAL_REFS_EXTENSION: [virtual_id]},
        attrs={"src": virtual_id, "predicate": "mentions", "dst": anchor.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([relation, anchor]))
    expected = (virtual_id, "virtual", "mentions", anchor.id, "ENT")
    assert expected in _edge_rows(store)
    store.close()

    for _ in range(2):
        reopened = SQLiteStore(path)
        try:
            with closing(reopened._connect()) as connection:
                reopened._cleanup_orphan_edges(connection)
                connection.commit()
            assert expected in _edge_rows(reopened)
        finally:
            reopened.close()


def test_claim_edge_ownership_isolated_when_subject_is_shared() -> None:
    store = SQLiteStore(":memory:")
    try:
        subject = MIRLRecord(
            id="ent:shared-subject",
            kind=RecordKind.ENT,
            attrs={"entity_type": "person", "label": "shared"},
        )
        first_target = MIRLRecord(
            id="ent:first-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "first"},
        )
        second_target = MIRLRecord(
            id="ent:second-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "second"},
        )
        replacement_target = MIRLRecord(
            id="ent:replacement-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "replacement"},
        )
        first_claim = MIRLRecord(
            id="clm:first-owner",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "first-edge",
                "object": first_target.id,
            },
        )
        second_claim = MIRLRecord(
            id="clm:second-owner",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "second-edge",
                "object": second_target.id,
            },
        )
        store.persist_ir(
            IRBatch(
                [
                    first_claim,
                    second_claim,
                    subject,
                    first_target,
                    second_target,
                    replacement_target,
                ]
            )
        )

        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=first_claim.id,
                        kind=RecordKind.CLM,
                        attrs={
                            "subject": subject.id,
                            "predicate": "replacement-edge",
                            "object": replacement_target.id,
                        },
                    )
                ]
            )
        )

        edges = _edge_rows(store)
        assert (
            subject.id,
            "ENT",
            "second-edge",
            second_target.id,
            "ENT",
        ) in edges
        assert (
            subject.id,
            "ENT",
            "replacement-edge",
            replacement_target.id,
            "ENT",
        ) in edges
        assert not any(row[2] == "first-edge" for row in edges)
        sources = _edge_sources(store)
        assert (
            second_claim.id,
            subject.id,
            "second-edge",
            second_target.id,
        ) in sources
    finally:
        store.close()


def test_relation_overwrite_removes_its_old_triple() -> None:
    store = SQLiteStore(":memory:")
    try:
        source = MIRLRecord(
            id="ent:rel-source",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "source"},
        )
        old_target = MIRLRecord(
            id="ent:rel-old-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "old"},
        )
        new_target = MIRLRecord(
            id="ent:rel-new-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "new"},
        )
        relation = MIRLRecord(
            id="rel:owned-overwrite",
            kind=RecordKind.REL,
            attrs={"src": source.id, "predicate": "links", "dst": old_target.id},
        )
        store.persist_ir(IRBatch([relation, source, old_target, new_target]))
        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=relation.id,
                        kind=RecordKind.REL,
                        attrs={
                            "src": source.id,
                            "predicate": "links",
                            "dst": new_target.id,
                        },
                    )
                ]
            )
        )

        edges = _edge_rows(store)
        assert (source.id, "ENT", "links", old_target.id, "ENT") not in edges
        assert (source.id, "ENT", "links", new_target.id, "ENT") in edges
    finally:
        store.close()


def test_core_storage_v1_migration_rebuilds_endpoint_types_idempotently(
    tmp_path,
) -> None:
    path = tmp_path / "typed-migration.db"
    source = MIRLRecord(
        id="ent:source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    replacement_target = MIRLRecord(
        id="ent:replacement",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "replacement"},
    )
    relation = MIRLRecord(
        id="rel:migrate",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    supporting_relation = MIRLRecord(
        id="rel:migrate-support",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(
        IRBatch(
            [
                relation,
                supporting_relation,
                target,
                replacement_target,
                source,
            ]
        )
    )
    store.close()

    connection = sqlite3.connect(path)
    _downgrade_core_storage_to_v1(connection)
    connection.commit()
    connection.close()

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-ir-edge-endpoints",
            "append-only-improvement-experiment-ledger",
        )
        expected = (source.id, "ENT", "links", target.id, "ENT")
        assert expected in _edge_rows(migrated)
        assert {
            row[0]
            for row in _edge_sources(migrated)
            if row[1:] == (source.id, "links", target.id)
        } == {relation.id, supporting_relation.id}
    finally:
        migrated.close()

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
        assert expected in _edge_rows(reopened)
        reopened.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=relation.id,
                        kind=RecordKind.REL,
                        attrs={
                            "src": source.id,
                            "predicate": "links",
                            "dst": replacement_target.id,
                        },
                    )
                ]
            )
        )
        assert expected in _edge_rows(reopened)
        assert (
            source.id,
            "ENT",
            "links",
            replacement_target.id,
            "ENT",
        ) in _edge_rows(reopened)
        reopened.delete_ir([relation.id])
        assert expected in _edge_rows(reopened)
        assert not any(
            row[3] == replacement_target.id for row in _edge_rows(reopened)
        )
    finally:
        reopened.close()

    repeated = SQLiteStore(path)
    try:
        assert repeated.migration_result.applied_steps == ()
        assert expected in _edge_rows(repeated)
        assert {
            row[0]
            for row in _edge_sources(repeated)
            if row[1:] == (source.id, "links", target.id)
        } == {supporting_relation.id}
    finally:
        repeated.close()


@pytest.mark.parametrize(
    ("corruption", "expected_message"),
    [
        ("missing", "edge with a missing canonical endpoint"),
        ("wrong-kind", "edge whose endpoint kind is inconsistent"),
        ("generic", "non-exact canonical endpoint type"),
        ("virtual", "canonical reference projection is inconsistent"),
    ],
)
def test_current_store_preflight_rejects_invalid_endpoints_read_only(
    tmp_path: Path,
    corruption: str,
    expected_message: str,
) -> None:
    path = tmp_path / f"invalid-current-endpoint-{corruption}.db"
    source = MIRLRecord(
        id="ent:private-endpoint-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:private-endpoint-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relation = MIRLRecord(
        id="rel:private-endpoint-owner",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "private-link", "dst": target.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([source, target, relation]))
    store.close()

    missing_id = "private-missing-endpoint"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("pragma foreign_keys = off")
        if corruption == "missing":
            connection.execute(
                "update ir_edge_sources set src_id = ? "
                "where source_record_id = ? and src_id = ? "
                "and edge_type = 'private-link' and dst_id = ?",
                (missing_id, relation.id, source.id, target.id),
            )
            connection.execute(
                "update ir_edges set src_id = ? where src_id = ? "
                "and edge_type = 'private-link' and dst_id = ?",
                (missing_id, source.id, target.id),
            )
        elif corruption == "wrong-kind":
            connection.execute(
                "update ir_edges set src_ref_type = 'CLM' where src_id = ? "
                "and edge_type = 'private-link' and dst_id = ?",
                (source.id, target.id),
            )
        elif corruption == "generic":
            connection.execute(
                "update ir_edges set src_ref_type = 'record' where src_id = ? "
                "and edge_type = 'private-link' and dst_id = ?",
                (source.id, target.id),
            )
        else:
            connection.execute(
                "update ir_edges set dst_ref_type = 'virtual' where src_id = ? "
                "and edge_type = 'private-link' and dst_id = ?",
                (source.id, target.id),
            )
        connection.commit()

    before_bytes = path.read_bytes()
    before_hashes = _all_table_hashes(path)
    backup_dir = tmp_path / f"invalid-endpoint-backups-{corruption}"
    with pytest.raises(DatabaseIntegrityError, match=expected_message) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert source.id not in diagnostics
    assert target.id not in diagnostics
    assert relation.id not in diagnostics
    assert missing_id not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_hashes
    assert not backup_dir.exists()


def test_current_store_reopen_rejects_missing_expected_edge_and_contributor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-expected-edge-and-contributor.db"
    source = MIRLRecord(
        id="ent:missing-projection-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "Source"},
    )
    target = MIRLRecord(
        id="ent:missing-projection-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "Target"},
    )
    relation = MIRLRecord(
        id="rel:missing-projection-owner",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([source, target, relation]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "delete from ir_edge_sources where source_record_id = ?",
            (relation.id,),
        )
        connection.execute(
            "delete from ir_edges where src_id = ? and edge_type = 'links' "
            "and dst_id = ?",
            (source.id, target.id),
        )
        connection.commit()

    before_bytes = path.read_bytes()
    before_hashes = _all_table_hashes(path)
    backup_dir = tmp_path / "missing-projection-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="canonical reference projection is inconsistent",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert source.id not in diagnostics
    assert target.id not in diagnostics
    assert relation.id not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_hashes
    assert not backup_dir.exists()


def test_delete_target_cleans_owned_edge_and_reopen_is_byte_stable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delete-target-reopen.db"
    source = MIRLRecord(
        id="ent:delete-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:delete-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relation = MIRLRecord(
        id="rel:delete-target-owner",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target, relation]))
        before_refusal = _all_table_hashes(path)
        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="delete would violate required canonical reference closure",
        ) as raised:
            store.delete_ir([target.id])

        diagnostics = str(raised.value)
        assert source.id not in diagnostics
        assert target.id not in diagnostics
        assert relation.id not in diagnostics
        assert _all_table_hashes(path) == before_refusal
        assert {record.id for record in store.load_ir(ids=[relation.id, target.id]).records} == {
            relation.id,
            target.id,
        }
        assert any(target.id in (edge[0], edge[3]) for edge in _edge_rows(store))
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
        assert {
            record.id
            for record in reopened.load_ir(ids=[relation.id, target.id]).records
        } == {relation.id, target.id}
        reopened.delete_ir([relation.id, target.id])
        assert reopened.load_ir(ids=[relation.id, target.id]).records == []
        assert not any(
            target.id in (edge[0], edge[3]) for edge in _edge_rows(reopened)
        )
        assert not any(
            source_row[0] == relation.id for source_row in _edge_sources(reopened)
        )
    finally:
        reopened.close()

    before_bytes = path.read_bytes()
    before_hashes = _all_table_hashes(path)
    repeated = SQLiteStore(path)
    try:
        assert repeated.migration_result.applied_steps == ()
        assert repeated.load_ir(ids=[relation.id, target.id]).records == []
    finally:
        repeated.close()

    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_hashes


@pytest.mark.parametrize(
    ("corruption", "expected_message"),
    [
        (
            "missing-source",
            "edge contributor without a canonical source record",
        ),
        (
            "missing-edge",
            "edge contributor without a derived edge",
        ),
    ],
)
def test_current_store_preflight_refuses_dangling_edge_contributors_read_only(
    tmp_path: Path,
    corruption: str,
    expected_message: str,
) -> None:
    path = tmp_path / f"dangling-edge-contributor-{corruption}.db"
    source = MIRLRecord(
        id="ent:private-preflight-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:private-preflight-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relation = MIRLRecord(
        id="rel:private-preflight-owner",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "private-link", "dst": target.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([source, target, relation]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("pragma foreign_keys = off")
        if corruption == "missing-source":
            connection.execute(
                "delete from ir_records where id = ?",
                (relation.id,),
            )
        else:
            connection.execute(
                "delete from ir_edges where src_id = ? "
                "and edge_type = ? and dst_id = ?",
                (source.id, "private-link", target.id),
            )
        connection.commit()

    before_bytes = path.read_bytes()
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)
    backup_dir = tmp_path / f"preflight-backups-{corruption}"
    with pytest.raises(DatabaseIntegrityError, match=expected_message) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert relation.id not in diagnostics
    assert source.id not in diagnostics
    assert target.id not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _table_hashes(path, CORE_MIGRATION_TABLES) == before_hashes
    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("corruption", "expected_problem"),
    [
        ("invalid", "invalid canonical MIRL payload"),
        ("mismatched", "mismatched canonical MIRL identifier"),
    ],
)
def test_core_storage_rebuild_redacts_canonical_ids_and_rolls_back(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    corruption: str,
    expected_problem: str,
) -> None:
    path = tmp_path / f"typed-core-redaction-{corruption}.db"
    stored_id = f"ent:private-core-record-{corruption}"
    payload_id = f"ent:private-payload-record-{corruption}"
    record = MIRLRecord(
        id=stored_id,
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "private"},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([record]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        _downgrade_core_storage_to_v1(connection)
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

    before = _table_hashes(path, CORE_MIGRATION_TABLES)
    caplog.set_level("WARNING", logger="seam_runtime.migrations")
    with pytest.raises(MigrationError, match=expected_problem) as raised:
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / f"backups-{corruption}",
        )

    diagnostics = f"{raised.value}\n{caplog.text}"
    assert stored_id not in diagnostics
    assert payload_id not in diagnostics
    assert "record_id_sha256=" in caplog.text
    assert hashlib.sha256(stored_id.encode("utf-8")).hexdigest() in caplog.text
    assert _table_hashes(path, CORE_MIGRATION_TABLES) == before


def test_core_rebuild_validates_edge_types_in_bounded_query_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "typed-edge-validation-chunks.db"
    source = MIRLRecord(
        id="ent:chunked-edge-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:chunked-edge-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relations = [
        MIRLRecord(
            id=f"rel:chunked-edge-{index:03d}",
            kind=RecordKind.REL,
            attrs={
                "src": source.id,
                "predicate": f"batched-link-{index:03d}",
                "dst": target.id,
            },
        )
        for index in range(301)
    ]
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([source, target, *relations]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        _downgrade_core_storage_to_v1(connection)
        connection.commit()

    verification_parameter_counts: list[int] = []
    per_edge_query_count = 0
    original_execute = migration_module.ProjectionMigrationConnection.execute
    old_per_edge_query = (
        "select src_ref_type, dst_ref_type from ir_edges "
        "where src_id = ? and edge_type = ? and dst_id = ?"
    )
    batched_query_prefix = (
        "select src_id, edge_type, dst_id, src_ref_type, dst_ref_type "
        "from ir_edges where (src_id, edge_type, dst_id) in"
    )

    def observe_execute(self, statement: str, parameters=()):
        nonlocal per_edge_query_count
        normalized = " ".join(statement.casefold().split())
        if normalized == old_per_edge_query:
            per_edge_query_count += 1
        if normalized.startswith(batched_query_prefix):
            verification_parameter_counts.append(len(parameters))
            assert len(parameters) <= 900 < 999
        return original_execute(self, statement, parameters)

    monkeypatch.setattr(
        migration_module.ProjectionMigrationConnection,
        "execute",
        observe_execute,
    )

    migrated = SQLiteStore(
        path,
        _migration_backup_dir=tmp_path / "chunked-edge-backups",
    )
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-ir-edge-endpoints",
            "append-only-improvement-experiment-ledger",
        )
        with closing(migrated._connect()) as connection:
            assert connection.execute(
                "select count(*) from ir_edges "
                "where edge_type like 'batched-link-%'"
            ).fetchone()[0] == 301
            assert connection.execute(
                "select count(*) from ir_edge_sources "
                "where source_record_id like 'rel:chunked-edge-%'"
            ).fetchone()[0] == 301
    finally:
        migrated.close()

    assert per_edge_query_count == 0
    assert verification_parameter_counts == [900, 3]


def test_core_rebuild_rejects_intra_batch_missing_canonical_reference(
    tmp_path: Path,
) -> None:
    path = tmp_path / "typed-edge-intra-batch-conflict.db"
    virtual, canonical = _typed_edge_conflict_records(
        virtual_record_id="rel:conflict-a-virtual",
        canonical_record_id="rel:conflict-b-record",
    )
    _build_core_v1_fixture(path, [virtual, canonical])
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)

    with pytest.raises(
        MigrationError,
        match="typed-edge rebuild found a missing canonical reference",
    ):
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / "intra-batch-conflict-backups",
        )

    _assert_core_v1_rollback_without_contributors(path, before_hashes)


def test_core_rebuild_rejects_cross_batch_missing_canonical_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "typed-edge-cross-batch-conflict.db"
    virtual, canonical = _typed_edge_conflict_records(
        virtual_record_id="rel:000-conflict-virtual",
        canonical_record_id="rel:999-conflict-record",
    )
    fillers = [
        MIRLRecord(
            id=f"meta:conflict-filler-{index:03d}",
            kind=RecordKind.META,
            attrs={"key": f"filler-{index:03d}", "value": "bounded"},
        )
        for index in range(499)
    ]
    _build_core_v1_fixture(path, [*fillers, virtual, canonical])
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)

    observed_batches: list[int] = []
    original_execute = migration_module.ProjectionMigrationConnection.execute

    class TrackingCanonicalCursor:
        def __init__(self, cursor) -> None:
            self._cursor = cursor

        def fetchmany(self, size: int | None = None):
            assert size == 500
            rows = self._cursor.fetchmany(size)
            observed_batches.append(len(rows))
            return rows

    def track_canonical_batches(self, statement: str, parameters=()):
        cursor = original_execute(self, statement, parameters)
        if " ".join(statement.casefold().split()) == (
            "select id, kind, payload_json from ir_records order by id"
        ):
            return TrackingCanonicalCursor(cursor)
        return cursor

    monkeypatch.setattr(
        migration_module.ProjectionMigrationConnection,
        "execute",
        track_canonical_batches,
    )

    with pytest.raises(
        MigrationError,
        match="typed-edge rebuild found a missing canonical reference",
    ):
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / "cross-batch-conflict-backups",
        )

    assert observed_batches == [500, 1]
    _assert_core_v1_rollback_without_contributors(path, before_hashes)


def test_core_rebuild_rejects_cross_batch_malformed_virtual_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "typed-edge-cross-batch-malformed-virtual.db"
    metadata_secret = "private-cross-batch-virtual-metadata"
    fillers = [
        MIRLRecord(
            id=f"meta:a-virtual-filler-{index:03d}",
            kind=RecordKind.META,
            attrs={"key": f"filler-{index:03d}", "value": "bounded"},
        )
        for index in range(500)
    ]
    malformed = MIRLRecord(
        id="meta:z-private-malformed-virtual-metadata",
        kind=RecordKind.META,
        ext={VIRTUAL_REFS_EXTENSION: metadata_secret},
        attrs={"key": "metadata", "value": "invalid"},
    )
    _build_core_v1_fixture(path, [*fillers, malformed])
    before_hashes = _table_hashes(path, CORE_MIGRATION_TABLES)

    observed_batches: list[int] = []
    original_execute = migration_module.ProjectionMigrationConnection.execute

    class TrackingCanonicalCursor:
        def __init__(self, cursor) -> None:
            self._cursor = cursor

        def fetchmany(self, size: int | None = None):
            assert size == 500
            rows = self._cursor.fetchmany(size)
            observed_batches.append(len(rows))
            return rows

    def track_canonical_batches(self, statement: str, parameters=()):
        cursor = original_execute(self, statement, parameters)
        if " ".join(statement.casefold().split()) == (
            "select id, kind, payload_json from ir_records order by id"
        ):
            return TrackingCanonicalCursor(cursor)
        return cursor

    monkeypatch.setattr(
        migration_module.ProjectionMigrationConnection,
        "execute",
        track_canonical_batches,
    )

    with pytest.raises(MigrationError) as raised:
        SQLiteStore(
            path,
            _migration_backup_dir=tmp_path / "malformed-virtual-backups",
        )

    diagnostics = str(raised.value)
    assert malformed.id not in diagnostics
    assert metadata_secret not in diagnostics
    assert observed_batches == [500, 1]
    _assert_core_v1_rollback_without_contributors(path, before_hashes)


def test_s4_rebuilds_use_deterministic_bounded_canonical_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "typed-bounded-rebuild.db"
    source = MIRLRecord(
        id="ent:batch-source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:batch-target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relation = MIRLRecord(
        id="rel:batch-cross-boundary",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    fillers = [
        MIRLRecord(
            id=f"ent:filler-{index:04d}",
            kind=RecordKind.ENT,
            status=Status.DELETED_SOFT,
            attrs={"entity_type": "filler", "label": f"filler {index}"},
        )
        for index in range(501)
    ]
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([source, target, relation, *fillers]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        _downgrade_core_storage_to_v1(connection)
        connection.execute(
            f"update {PROJECTION_TABLE} "
            "set projection_version = 'knowledge-graph/5' "
            "where projection_name = 'knowledge_graph'"
        )
        connection.execute(
            "update knowledge_graph_meta set value = 'knowledge-graph/5' "
            "where key = 'projection_version'"
        )
        connection.commit()

    canonical_scans = {
        "select id, kind, payload_json from ir_records order by id": "core",
        (
            "select id, kind, ns, scope, status, conf, t0, t1, created_at, "
            "updated_at, payload_json from ir_records order by id"
        ): "knowledge_graph",
    }
    observed_batches: dict[str, list[int]] = {
        "core": [],
        "knowledge_graph": [],
    }
    original_execute = migration_module.ProjectionMigrationConnection.execute

    class FetchManyOnlyCursor:
        def __init__(self, cursor, component: str) -> None:
            self._cursor = cursor
            self._component = component

        def fetchmany(self, size: int | None = None):
            assert size == 500
            rows = self._cursor.fetchmany(size)
            observed_batches[self._component].append(len(rows))
            return rows

        def fetchone(self):
            raise AssertionError("canonical migration scan must use fetchmany")

        def fetchall(self):
            raise AssertionError("canonical migration scan must not use fetchall")

        def __iter__(self):
            raise AssertionError("canonical migration scan must not materialize by iteration")

    def guarded_execute(self, statement: str, parameters=()):
        cursor = original_execute(self, statement, parameters)
        normalized = " ".join(statement.casefold().split())
        component = canonical_scans.get(normalized)
        if component is None:
            return cursor
        return FetchManyOnlyCursor(cursor, component)

    monkeypatch.setattr(
        migration_module.ProjectionMigrationConnection,
        "execute",
        guarded_execute,
    )
    identity_revalidations = 0
    original_apply_identity_merges = identity_resolution_module.apply_identity_merges

    def counted_apply_identity_merges(connection):
        nonlocal identity_revalidations
        identity_revalidations += 1
        return original_apply_identity_merges(connection)

    monkeypatch.setattr(
        identity_resolution_module,
        "apply_identity_merges",
        counted_apply_identity_merges,
    )

    migrated = SQLiteStore(
        path,
        _migration_backup_dir=tmp_path / "bounded-backups",
    )
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-ir-edge-endpoints",
            "append-only-improvement-experiment-ledger",
            "typed-knowledge-references",
        )
        with closing(migrated._connect()) as connection:
            assert connection.execute(
                "select projection_version from seam_projection_versions "
                "where projection_name = 'knowledge_graph'"
            ).fetchone()[0] == "knowledge-graph/6"
            assert connection.execute(
                "select value from knowledge_graph_meta "
                "where key = 'projection_version'"
            ).fetchone()[0] == "knowledge-graph/6"
            assert connection.execute(
                "select count(*) from ir_edges where src_id = ? "
                "and edge_type = 'links' and dst_id = ?",
                (source.id, target.id),
            ).fetchone()[0] == 1
            assert connection.execute(
                "select count(*) from ir_edge_sources where source_record_id = ?",
                (relation.id,),
            ).fetchone()[0] == 1
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (relation.id,),
            ).fetchone()[0] == 1
    finally:
        migrated.close()

    assert observed_batches == {
        "core": [500, 4, 0],
        "knowledge_graph": [500, 4, 0],
    }
    assert identity_revalidations == 1


def test_knowledge_graph_v5_migration_removes_colon_phantoms_idempotently(
    tmp_path,
) -> None:
    path = tmp_path / "typed-knowledge.db"
    batch = compile_nl("Meet at 09:30.", allow_env_extractor=False)
    claim = next(record for record in batch.records if record.kind is RecordKind.CLM)
    store = SQLiteStore(path)
    store.persist_ir(batch)
    store.close()

    phantom_id = "Meet at 09:30."
    connection = sqlite3.connect(path)
    connection.execute(
        "insert into knowledge_nodes "
        "select ?, 'concept', ?, ns, scope, status, confidence, valid_from, "
        "valid_to, created_at, updated_at, agent_id, ?, 1, ? "
        "from knowledge_nodes where id = ?",
        (
            phantom_id,
            phantom_id,
            claim.id,
            json.dumps({"reference": phantom_id}),
            claim.id,
        ),
    )
    connection.execute(
        "insert into knowledge_edges "
        "select 'kge:legacy-colon-phantom', src_id, ?, predicate, edge_kind, "
        "ns, scope, status, confidence, valid_from, valid_to, created_at, "
        "updated_at, expired_at, agent_id, source_record_id, properties_json "
        "from knowledge_edges where source_record_id = ? limit 1",
        (phantom_id, claim.id),
    )
    connection.execute(
        "insert into knowledge_node_vectors "
        "(node_id, model_name, dimension, source_text, source_hash, "
        "render_version, ns, scope, vector_json, updated_at) "
        "select ?, 'phantom-model', 1, ?, 'legacy-hash', "
        "'graph-node-vector-text/1', ns, scope, '[1.0]', updated_at "
        "from knowledge_nodes where id = ?",
        (phantom_id, phantom_id, phantom_id),
    )
    connection.execute(
        "update knowledge_graph_meta set value = 'knowledge-graph/5' "
        "where key = 'projection_version'"
    )
    connection.execute(
        f"update {PROJECTION_TABLE} set projection_version = 'knowledge-graph/5' "
        "where projection_name = 'knowledge_graph'"
    )
    connection.commit()
    connection.close()

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-knowledge-references",
        )
        with closing(migrated._connect()) as connection:
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (phantom_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select count(*) from knowledge_node_vectors where node_id = ?",
                (phantom_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select value from knowledge_graph_meta "
                "where key = 'projection_version'"
            ).fetchone()[0] == "knowledge-graph/6"
        assert migrated.search_node_vectors(
            [1.0],
            "phantom-model",
            limit=10,
        ) == []
    finally:
        migrated.close()

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
        with closing(reopened._connect()) as connection:
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (phantom_id,),
            ).fetchone()[0] == 0
    finally:
        reopened.close()
