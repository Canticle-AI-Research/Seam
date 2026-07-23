from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.vector import (
    LEGACY_VECTOR_TEXT_VERSION,
    VECTOR_TEXT_VERSION,
    SQLiteVectorIndex,
)


class _CountingEmbedding:
    name = "counting-vector-text"
    dimension = 2

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0]


@pytest.mark.parametrize(
    ("kind", "attrs", "expected"),
    [
        (
            RecordKind.CLM,
            {
                "zeta": ["tail-1", {"b": "nested-b", "a": "nested-a"}, 9],
                "object": "object",
                "predicate": "predicate",
                "subject": "subject",
                "alpha": {"z": "alpha-z", "a": "alpha-a", "count": 2},
            },
            "CLM subject predicate object alpha-a alpha-z tail-1 nested-a nested-b",
        ),
        (
            RecordKind.STA,
            {
                "zeta": "last",
                "fields": {"z": "field-z", "a": ["field-1", "field-2"]},
                "target": "target",
            },
            "STA target field-1 field-2 field-z last",
        ),
        (
            RecordKind.EVT,
            {
                "object": "object",
                "action": "action",
                "actor": "actor",
                "detail": {"second": "detail-2", "first": "detail-1"},
            },
            "EVT actor action object detail-1 detail-2",
        ),
        (
            RecordKind.REL,
            {
                "dst": "destination",
                "predicate": "predicate",
                "src": "source",
                "aliases": ["alias-2", "alias-1"],
            },
            "REL source predicate destination alias-2 alias-1",
        ),
    ],
)
def test_v2_generic_render_is_stable_across_json_roundtrip(
    kind: RecordKind,
    attrs: dict[str, object],
    expected: str,
) -> None:
    record = MIRLRecord(id=f"{kind.value.lower()}:1", kind=kind, attrs=attrs)
    reloaded = MIRLRecord.from_dict(
        json.loads(json.dumps(record.to_dict(), sort_keys=True))
    )

    assert SQLiteVectorIndex.render_record_text(record) == expected
    assert SQLiteVectorIndex.render_record_text(reloaded) == expected


def test_raw_content_render_remains_byte_exact() -> None:
    content = "  Alice:\nPreserve every byte.  "
    raw = MIRLRecord(
        id="raw:exact",
        kind=RecordKind.RAW,
        attrs={"source_ref": "unit://raw", "content": content},
    )

    assert SQLiteVectorIndex.render_record_text(raw) == content


def test_raw_fallback_render_is_stable_across_json_roundtrip() -> None:
    raw = MIRLRecord(
        id="raw:fallback",
        kind=RecordKind.RAW,
        attrs={
            "zeta": {"b": "last", "a": "first"},
            "source_ref": "unit://raw",
        },
    )
    reloaded = MIRLRecord.from_dict(
        json.loads(json.dumps(raw.to_dict(), sort_keys=True))
    )

    assert SQLiteVectorIndex.render_record_text(raw) == (
        SQLiteVectorIndex.render_record_text(reloaded)
    )


@pytest.mark.parametrize(
    ("policy", "attrs", "expected"),
    [
        (
            "grounded-clm/1",
            {
                "object": "surfing",
                "predicate": "likes",
                "subject_label": "John",
                "subject": "ent:john",
            },
            "John likes surfing",
        ),
        (
            "grounded-clm/2",
            {
                "object": "surfing",
                "predicate": "likes",
                "subject_label": "John",
            },
            "John likes surfing",
        ),
        (
            "sentence-grounded-clm/1",
            {"predicate": "ignored", "object": "John likes surfing."},
            "John likes surfing.",
        ),
        (
            "multi-speaker-grounded/1",
            {"object": "Sara enjoys painting.", "subject_label": "Sara"},
            "Sara enjoys painting.",
        ),
        (
            "grounded-clm/1",
            {"object": "", "predicate": "likes", "subject_label": "John"},
            "CLM likes John",
        ),
    ],
)
def test_grounded_clm_render_branches_remain_byte_exact(
    policy: str,
    attrs: dict[str, object],
    expected: str,
) -> None:
    record = MIRLRecord(
        id=f"clm:{policy}",
        kind=RecordKind.CLM,
        ext={"derived_fact_policy": policy},
        attrs=attrs,
    )
    reloaded = MIRLRecord.from_dict(
        json.loads(json.dumps(record.to_dict(), sort_keys=True))
    )

    assert SQLiteVectorIndex.render_record_text(record) == expected
    assert SQLiteVectorIndex.render_record_text(reloaded) == expected


def test_additive_schema_migration_stamps_legacy_without_embedding(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    source_text = "CLM old source"
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    vector_json = json.dumps([1.0, 0.0])
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            create table vector_index (
                record_id text not null,
                model_name text not null,
                dimension integer not null,
                source_text text not null,
                source_hash text not null default '',
                namespace text not null default '',
                scope text not null default '',
                vector_json text not null,
                updated_at text not null,
                primary key (record_id, model_name)
            )
            """
        )
        connection.execute(
            """
            insert into vector_index (
                record_id, model_name, dimension, source_text, source_hash,
                namespace, scope, vector_json, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "clm:legacy",
                "counting-vector-text",
                2,
                source_text,
                source_hash,
                "local.default",
                "project",
                vector_json,
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.commit()

    model = _CountingEmbedding()
    index = SQLiteVectorIndex(str(path), model)
    index.ensure_schema()

    assert model.calls == []
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            """
            select source_text, source_hash, render_version, vector_json
            from vector_index where record_id = 'clm:legacy'
            """
        ).fetchone()
    assert row == (
        source_text,
        source_hash,
        LEGACY_VECTOR_TEXT_VERSION,
        vector_json,
    )


def test_legacy_rows_fail_closed_then_full_index_upgrades_once(tmp_path) -> None:
    path = tmp_path / "upgrade.db"
    model = _CountingEmbedding()
    index = SQLiteVectorIndex(str(path), model)
    index.ensure_schema()
    record = MIRLRecord(
        id="clm:upgrade",
        kind=RecordKind.CLM,
        attrs={
            "object": "object",
            "predicate": "predicate",
            "subject": "subject",
        },
    )
    rendered = SQLiteVectorIndex.render_record_text(record)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            insert into vector_index (
                record_id, model_name, dimension, source_text, source_hash,
                render_version, namespace, scope, vector_json, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                model.name,
                model.dimension,
                "different legacy text",
                "different legacy hash",
                LEGACY_VECTOR_TEXT_VERSION,
                record.ns,
                record.scope,
                json.dumps([1.0, 0.0]),
                record.updated_at,
            ),
        )
        connection.commit()

    assert index.stale_records([record]) == [
        {"record_id": record.id, "reason": "render_version_changed"}
    ]
    assert index.search("query") == {}

    calls_before_upgrade = len(model.calls)
    index.index_records([record])
    assert model.calls[calls_before_upgrade:] == [rendered]
    assert index.stale_records([record]) == []
    assert index.search("query") == {record.id: 1.0}

    calls_before_second_index = len(model.calls)
    index.index_records([record])
    assert len(model.calls) == calls_before_second_index

    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            """
            select source_text, source_hash, render_version
            from vector_index where record_id = ?
            """,
            (record.id,),
        ).fetchone()
    assert row == (
        rendered,
        hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        VECTOR_TEXT_VERSION,
    )


def test_new_rows_are_stamped_with_v2(tmp_path) -> None:
    model = _CountingEmbedding()
    index = SQLiteVectorIndex(str(tmp_path / "new.db"), model)
    record = MIRLRecord(
        id="evt:new",
        kind=RecordKind.EVT,
        attrs={"object": "result", "action": "created", "actor": "agent"},
    )

    index.index_records([record])

    with closing(index._connect()) as connection:
        row = connection.execute(
            "select render_version from vector_index where record_id = ?",
            (record.id,),
        ).fetchone()
    assert row["render_version"] == VECTOR_TEXT_VERSION
