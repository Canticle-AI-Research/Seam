"""Public compatibility retrieval preserves ranking with bounded live payloads.

The meter isolates the compatibility leg from final provenance/current reads.
Counts measure live decoded records and SQL payload pages, not total work:
exact scoring still scans the selected namespace and retains context metadata.
"""

import json
import weakref
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from seam_runtime.bm25 import BM25Index
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status, iter_textual_fields
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.retrieval import RetrievalFlags, search_batch
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import search_vector_adapter


@pytest.fixture()
def runtime(tmp_path):
    runtime = SeamRuntime(
        tmp_path / "r2-legacy.db",
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    )
    try:
        runtime.store.persist_ir(IRBatch([MIRLRecord(
            id="ent:fixture", kind=RecordKind.ENT, ns="selected", scope="thread",
            attrs={"label": "Fixture"},
        )]))
        yield runtime
    finally:
        runtime.close()


def _claim(record_id, text, *, ns="selected", scope="thread", **kwargs):
    return MIRLRecord(
        id=record_id, kind=RecordKind.CLM, ns=ns, scope=scope,
        attrs={"subject": "ent:fixture", "predicate": "notes", "object": text}, **kwargs,
    )


def _retrieve(runtime, query="needle", **kwargs):
    return runtime.retrieve(
        query, ns="selected", scope="thread", budget=5,
        ranking_policy="legacy-weighted/1", include_trace=True, **kwargs,
    )


def _leg_materialization_meter(runtime, monkeypatch):
    meter = {"active": False, "live": 0, "peak": 0, "constructed": 0,
             "payload_page": 0, "unbounded_fetchall": 0}
    adapter = runtime._retrieval_orchestrator_cached().legacy_weighted_adapter
    original_search = adapter.search
    original_decode = MIRLRecord.from_dict
    original_checkout = runtime.store._pool.checkout

    def search(*args, **kwargs):
        meter["active"] = True
        try:
            return original_search(*args, **kwargs)
        finally:
            meter["active"] = False

    def release():
        meter["live"] -= 1

    def decode(cls, data):
        record = original_decode(data)
        if meter["active"]:
            meter["constructed"] += 1
            meter["live"] += 1
            meter["peak"] = max(meter["peak"], meter["live"])
            weakref.finalize(record, release)
        return record

    class Cursor:
        def __init__(self, cursor, unbounded):
            self.cursor, self.unbounded = cursor, unbounded

        def fetchall(self):
            rows = self.cursor.fetchall()
            meter["payload_page"] = max(meter["payload_page"], len(rows))
            if self.unbounded:
                meter["unbounded_fetchall"] += 1
            return rows

        def fetchmany(self, size):
            rows = self.cursor.fetchmany(size)
            meter["payload_page"] = max(meter["payload_page"], len(rows))
            return rows

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, *args, **kwargs):
            cursor = self.connection.execute(sql, *args, **kwargs)
            normalized = " ".join(sql.lower().split())
            if meter["active"] and normalized.startswith(
                "select payload_json from ir_records"
            ):
                return Cursor(cursor, " limit " not in normalized and " id in " not in normalized)
            return cursor

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def checkout():
        with original_checkout() as connection:
            yield Connection(connection)

    monkeypatch.setattr(adapter, "search", search)
    monkeypatch.setattr(MIRLRecord, "from_dict", classmethod(decode))
    monkeypatch.setattr(runtime.store._pool, "checkout", checkout)
    return meter


@pytest.mark.parametrize("fusion", ["weighted", "rrf"])
def test_public_legacy_ranking_stays_exact_as_live_payloads_stay_bounded(
    runtime, monkeypatch, fusion
):
    flags = RetrievalFlags(fusion=fusion)
    runtime.store.persist_ir(IRBatch([
        _claim(f"clm:a-{index}", "needle") for index in range(5)
    ]))
    _retrieve(runtime, flags=flags)  # Resolve lazy setup outside the meter.
    meter = _leg_materialization_meter(runtime, monkeypatch)
    measurements = []
    previous = 0
    for size in (32, 512, 2048):
        runtime.store.persist_ir(IRBatch([
            _claim(f"clm:z-{index:05d}", "irrelevant", ext={"padding": "x" * 4096})
            for index in range(previous, size)
        ]))
        batch = runtime.store.load_ir(ns="selected", scope="thread")
        oracle = search_batch(batch, "needle", scope="thread", namespace="selected",
                              limit=5, flags=flags)
        expected = [(c.record.id, c.score, sorted(c.reasons)) for c in oracle.candidates]
        del oracle, batch
        meter.update(peak=0, constructed=0, payload_page=0, unbounded_fetchall=0)
        actual = _retrieve(runtime, flags=flags)
        assert [(c.record.id, c.score, c.reasons) for c in actual.candidates] == expected
        assert [c.record.id for c in actual.candidates] == [f"clm:a-{i}" for i in range(5)]
        assert set(actual.trace["legs"]) == {"legacy_weighted"}
        measurements.append({"corpus": size + 6, **{k: meter[k] for k in (
            "peak", "constructed", "payload_page", "unbounded_fetchall"
        )}})
        del actual
        previous = size
    print(f"fusion={fusion}; compatibility_materialization={measurements}")
    assert all(m["constructed"] >= m["corpus"] for m in measurements)
    assert all(m["peak"] <= 140 for m in measurements), measurements
    assert all(0 < m["payload_page"] <= 128 for m in measurements), measurements
    assert all(m["unbounded_fetchall"] == 0 for m in measurements), measurements


def _oracle(runtime, query, *, flags, include_raw=False, budget=100,
            ns="selected", scope="thread", **temporal):
    batch = runtime.store.load_ir(ns=ns, scope=scope)
    bm25 = None
    if include_raw or flags.bm25_all_kinds:
        bm25 = BM25Index()
        for record in batch.records:
            if record.kind == RecordKind.RAW:
                content = record.attrs.get("content")
                text = content if isinstance(content, str) and content else ""
            elif flags.bm25_all_kinds:
                text = " ".join(iter_textual_fields(record))
            else:
                text = ""
            if text:
                bm25.add(record.id, text)
    vectors = search_vector_adapter(
        runtime.vector_adapter, query, limit=max(budget * 3, 10),
        namespace=ns, scope=scope,
    )
    result = search_batch(
        batch, query, scope=scope, namespace=batch.records[0].ns if batch.records else None,
        limit=budget, include_raw=include_raw, bm25_index=bm25,
        vector_scores=vectors, flags=flags, **temporal,
    )
    # The public merger sorts reason strings; the pure scorer uses channel order.
    return [(c.record.id, c.score, sorted(c.reasons)) for c in result.candidates], vectors


def _mixed_corpus():
    def record(record_id, kind, attrs, **kwargs):
        return MIRLRecord(id=record_id, kind=kind, ns="selected", scope="thread",
                          attrs=attrs, **kwargs)

    return [
        record("ent:ada", RecordKind.ENT, {"label": "Ada axolotl"}),
        record("ent:axolotl", RecordKind.ENT, {"label": "Other"}),
        record("ent:excluded", RecordKind.ENT, {"label": "sig sig axolotl"},
               status=Status.DEPRECATED),
        # Last symbol wins even when status excludes it as a current record.
        record("sym:a", RecordKind.SYM,
               {"symbol": "sig", "expansion": "wrong", "ambiguity": 0.0}),
        record("sym:z", RecordKind.SYM,
               {"symbol": "sig", "expansion": "Ada", "ambiguity": 0.0},
               status=Status.DEPRECATED),
        record("sym:ambiguous", RecordKind.SYM,
               {"symbol": "axolotl", "expansion": "wrong", "ambiguity": 0.9}),
        record("raw:live", RecordKind.RAW, {"content": "sig axolotl filler filler"}),
        record("raw:excluded", RecordKind.RAW, {"content": "sig sig sig axolotl"},
               status=Status.SUPERSEDED),
        record("raw:empty", RecordKind.RAW, {"content": "!!!"}),
        record("clm:ada", RecordKind.CLM,
               {"subject": "ent:ada", "predicate": "notes", "object": "Ada axolotl"},
               t0="2026-09-01T00:00:00.500000Z", evidence=["raw:live"]),
        record("clm:edge", RecordKind.CLM,
               {"subject": "ent:axolotl", "predicate": "mentions", "object": "clm:ada"}),
        record("rel:ada", RecordKind.REL,
               {"src": "ent:ada", "dst": "ent:axolotl", "predicate": "knows"},
               t0="2026-08-31T19:00:00.500000-05:00"),
        record("evt:offset", RecordKind.EVT,
               {"actor": "ent:ada", "summary": "Ada recorded sig"},
               t0="2026-09-01T02:00:00.500001+02:00"),
        record("evt:invalid", RecordKind.EVT,
               {"actor": "ent:ada", "summary": "axolotl"}, t0="invalid"),
        record("sta:naive", RecordKind.STA,
               {"target": "ent:ada", "fields": {"a": "sig", "z": "axolotl"}},
               t0="2026-09-01T00:00:00.500000"),
        *[record(f"clm:excluded-{status.value}", RecordKind.CLM,
                 {"subject": "ent:ada", "predicate": "notes", "object": "sig sig axolotl"},
                 status=status)
          for status in (Status.CONTRADICTED, Status.SUPERSEDED,
                         Status.DEPRECATED, Status.DELETED_SOFT)],
    ]


@pytest.mark.parametrize("fusion", ["weighted", "rrf"])
@pytest.mark.parametrize("include_raw,all_kinds", [(False, False), (True, False),
                                                 (False, True), (True, True)])
@pytest.mark.parametrize("entity_grounded", [False, True])
@pytest.mark.parametrize("vector_mode", ["absent", "absent-zero", "present", "present-zero"])
@pytest.mark.parametrize("temporal_mode", ["default", "reference", "window"])
def test_public_legacy_matches_full_batch_channels(
    runtime, fusion, include_raw, all_kinds, entity_grounded, vector_mode, temporal_mode
):
    records = _mixed_corpus()
    runtime.store.persist_ir(IRBatch(records))
    if vector_mode.startswith("present"):
        runtime.vector_adapter.index_records([r for r in records if r.id == "clm:ada"])
    flags = RetrievalFlags(
        fusion=fusion, rrf_k=17, bm25_all_kinds=all_kinds,
        entity_grounded_scoring=entity_grounded,
        semantic_zero_no_vector=vector_mode.endswith("zero"),
        w_lexical=0.37, w_semantic=0.31, w_graph=0.21, w_temporal=0.11,
    )
    temporal = {}
    if temporal_mode == "reference":
        temporal["temporal_reference"] = datetime(2026, 9, 1, 0, 0, 0, 500000)
    elif temporal_mode == "window":
        instant = datetime(2026, 9, 1, 0, 0, 0, 500000, tzinfo=UTC)
        temporal["temporal_window"] = (instant, instant)
    query = "sig sig axolotl"
    expected, vectors = _oracle(runtime, query, flags=flags, include_raw=include_raw, **temporal)
    assert bool(vectors) == vector_mode.startswith("present")
    actual = runtime.retrieve(
        query, ns="selected", scope="thread", budget=100,
        include_raw=include_raw, flags=flags, ranking_policy="legacy-weighted/1", **temporal,
    )
    assert [(c.record.id, c.score, c.reasons) for c in actual.candidates] == expected
    assert all("excluded" not in c.record.id for c in actual.candidates)
    assert {"CLM", "STA", "EVT", "REL"} <= {c.record.kind.value for c in actual.candidates}
    assert any("graph=1.00" in c.reasons for c in actual.candidates)
    ada = next(c for c in actual.candidates if c.record.id == "clm:ada")
    assert "lexical=1.00" in ada.reasons


@pytest.mark.parametrize("fusion", ["weighted", "rrf"])
def test_public_bm25_corpus_growth_keeps_live_payloads_bounded(runtime, monkeypatch, fusion):
    runtime.store.persist_ir(IRBatch([_claim("clm:needle", "needle")]))
    flags = RetrievalFlags(fusion=fusion, bm25_all_kinds=True)
    meter = _leg_materialization_meter(runtime, monkeypatch)
    observations = []
    previous = 0
    for size in (32, 1024):
        runtime.store.persist_ir(IRBatch([
            MIRLRecord(id=f"raw:z-{i:05d}", kind=RecordKind.RAW, ns="selected", scope="thread",
                       attrs={"content": "haystack " * 100},
                       status=Status.DEPRECATED if i % 2 else Status.ASSERTED)
            for i in range(previous, size)
        ]))
        expected, _ = _oracle(runtime, "needle", flags=flags, include_raw=True, budget=5)
        meter.update(peak=0, constructed=0, payload_page=0, unbounded_fetchall=0)
        actual = _retrieve(runtime, flags=flags, include_raw=True)
        assert [(c.record.id, c.score, c.reasons) for c in actual.candidates] == expected
        observations.append({"corpus": size + 2, **{k: meter[k] for k in (
            "peak", "constructed", "payload_page", "unbounded_fetchall"
        )}})
        del actual
        previous = size
    print(f"fusion={fusion}; bm25_materialization={observations}")
    assert all(m["peak"] <= 140 and m["payload_page"] <= 128 for m in observations)
    assert all(m["unbounded_fetchall"] == 0 for m in observations)


@pytest.mark.parametrize("field,value", [("attrs", []), ("evidence", {}),
                                        ("prov", "invalid"), ("ext", []), ("conf", "invalid")])
def test_public_legacy_still_validates_non_candidate_payloads(runtime, field, value):
    record = MIRLRecord(id="sym:corrupt", kind=RecordKind.SYM, ns="selected", scope="thread",
                        attrs={"symbol": "x", "expansion": "needle", "ambiguity": 0.0},
                        status=Status.DEPRECATED)
    runtime.store.persist_ir(IRBatch([record]))
    payload = record.to_dict()
    payload[field] = value
    with runtime.store._pool.checkout() as connection:
        connection.execute("update ir_records set payload_json = ? where id = ?",
                           (json.dumps(payload), record.id))
        connection.commit()
    with pytest.raises((TypeError, ValueError)):
        _retrieve(runtime)


def test_public_unfiltered_legacy_uses_first_rows_namespace_for_symbols(runtime):
    runtime.store.persist_ir(IRBatch([
        MIRLRecord(id="ent:root", kind=RecordKind.ENT, ns="work.child", scope="thread",
                   attrs={"label": "Root"}),
        MIRLRecord(id="clm:000-first", kind=RecordKind.CLM, ns="work.child", scope="thread",
                   status=Status.DEPRECATED,
                   attrs={"subject": "ent:root", "predicate": "notes", "object": "past"}),
        MIRLRecord(id="sym:parent", kind=RecordKind.SYM, ns="work", scope="thread",
                   attrs={"symbol": "sig", "expansion": "needle", "ambiguity": 0.0}),
        MIRLRecord(id="sym:selected", kind=RecordKind.SYM, ns="selected", scope="thread",
                   attrs={"symbol": "sig", "expansion": "wrong", "ambiguity": 0.0}),
        _claim("clm:target", "needle"),
    ]))
    flags = RetrievalFlags()
    expected, _ = _oracle(runtime, "sig", ns=None, flags=flags, budget=10)
    actual = runtime.retrieve("sig", scope="thread", budget=10, flags=flags,
                              ranking_policy="legacy-weighted/1")
    assert [(c.record.id, c.score, c.reasons) for c in actual.candidates] == expected
    assert [c.record.id for c in actual.candidates] == ["clm:target"]
    assert "lexical=1.00" in actual.candidates[0].reasons
