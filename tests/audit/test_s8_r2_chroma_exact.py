"""Real Chroma exact acquisition at the public runtime boundary."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Event

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator.adapters import ChromaSemanticAdapter
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.runtime import SeamRuntime

pytestmark = pytest.mark.external


class _FixedEmbedding:
    name = "r2-chroma-fixed/1"
    dimension = 2

    def __init__(self, *, swapped=False):
        self.swapped = swapped

    def embed(self, text):
        if "a-value" in text:
            return [0.0, 1.0] if self.swapped else [1.0, 0.0]
        if "b-value" in text:
            return [1.0, 0.0] if self.swapped else [0.0, 1.0]
        if "near-loser" in text:
            return [1.0, 1.00000001]
        if "near-winner" in text:
            return [1.0, 1.0]
        return [1.0, 0.0]


@pytest.fixture()
def runtime(tmp_path):
    import chromadb
    from chromadb.config import Settings

    runtime = SeamRuntime(
        tmp_path / "canonical.db", embedding_model=_FixedEmbedding(), allow_pgvector_env=False,
    )
    directory = tmp_path / "chroma"
    client = chromadb.PersistentClient(
        path=str(directory), settings=Settings(anonymized_telemetry=False),
    )
    adapter = ChromaSemanticAdapter(
        runtime.store, runtime.embedding_model, persist_directory=str(directory), client=client,
    )
    runtime._retrieval_orchestrator_cached().semantic_adapter = adapter
    runtime.store.persist_ir(IRBatch([
        MIRLRecord(id="ent:subject", kind=RecordKind.ENT, ns="selected", scope="thread", attrs={"name": "Subject"}),
    ]))
    try:
        yield runtime, adapter
    finally:
        runtime.close()


def _record(record_id, text="tie-value"):
    return MIRLRecord(
        id=record_id, kind=RecordKind.CLM, ns="selected", scope="thread",
        attrs={"subject": "ent:subject", "predicate": "observed", "object": text},
    )


def _retrieve(runtime, *, budget=3, query="query"):
    return runtime.retrieve(
        query, mode="vector", ns="selected", scope="thread", budget=budget, include_trace=True,
    )


def test_real_chroma_exact_selects_smallest_ids_beyond_ann_cutoff(runtime):
    runtime, adapter = runtime
    records = [_record(f"clm:{index:04d}") for index in reversed(range(256))]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))

    result = _retrieve(runtime)

    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:0000", "clm:0001", "clm:0002",
    ]


def test_real_chroma_default_raw_exclusion_applies_before_cutoff(runtime):
    runtime, adapter = runtime
    records = [
        MIRLRecord(
            id="raw:a", kind=RecordKind.RAW, ns="selected", scope="thread",
            attrs={"content": "a-value"},
        ),
        _record("clm:z", "near-winner"),
    ]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))

    assert [candidate.record.id for candidate in _retrieve(runtime, budget=1).candidates] == ["clm:z"]
    included = runtime.retrieve(
        "query", mode="vector", ns="selected", scope="thread", budget=1, include_raw=True,
    )
    assert [candidate.record.id for candidate in included.candidates] == ["raw:a"]
    adapter.delete_records(["raw:a"])
    assert [candidate.record.id for candidate in _retrieve(runtime, budget=1).candidates] == ["clm:z"]


@pytest.mark.parametrize(("shared_canonical", "different_hint", "separate_client"), [
    (True, False, False), (False, False, False), (False, True, False), (False, True, True),
])
def test_public_chroma_read_locks_projection_before_opening_canonical_snapshot(
    runtime, monkeypatch, tmp_path, request, shared_canonical, different_hint, separate_client,
):
    runtime, adapter = runtime
    records = [_record("clm:a", "a-value"), _record("clm:b", "b-value")]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))
    writer_store = runtime.store
    if not shared_canonical:
        other_runtime = SeamRuntime(
            tmp_path / "other-canonical.db", embedding_model=_FixedEmbedding(),
            allow_pgvector_env=False,
        )
        request.addfinalizer(other_runtime.close)
        other_runtime.store.persist_ir(runtime.store.load_ir())
        writer_store = other_runtime.store
    writer_client = adapter.client
    if separate_client:
        import chromadb

        writer_client = chromadb.PersistentClient(
            path=adapter.persist_directory, settings=adapter.client.get_settings(),
        )
    writer = ChromaSemanticAdapter(
        writer_store, _FixedEmbedding(swapped=True),
        persist_directory=str(tmp_path / "unused-hint") if different_hint else adapter.persist_directory,
        client=writer_client,
    )
    original_snapshot = runtime.store.read_snapshot
    attempted = Event()
    done = Event()
    started = False
    writer_future = None

    def replace_originals():
        attempted.set()
        writer.sync_batch(IRBatch(records))
        done.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        @contextmanager
        def snapshot_with_writer():
            nonlocal started, writer_future
            with original_snapshot() as connection:
                if not started:
                    started = True
                    writer_future = executor.submit(replace_originals)
                    assert attempted.wait(2)
                    # A correctly ordered read lock keeps this writer pending
                    # until the public read releases its canonical snapshot.
                    done.wait(0.5)
                yield connection

        monkeypatch.setattr(runtime.store, "read_snapshot", snapshot_with_writer)
        result = _retrieve(runtime, budget=1)
        assert writer_future is not None
        writer_future.result(timeout=5)

    assert [candidate.record.id for candidate in result.candidates] == ["clm:a"]
    assert done.is_set(), "the pending writer must proceed after read release"
    assert [candidate.record.id for candidate in _retrieve(runtime, budget=1).candidates] == ["clm:b"]


def test_real_chroma_exact_uses_original_precision_without_sqlite_vectors(runtime):
    runtime, adapter = runtime
    records = [_record("clm:a", "near-loser"), _record("clm:z", "near-winner")]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))
    assert runtime.vector_adapter.search("query", namespace="selected", scope="thread") == {}

    result = _retrieve(runtime, budget=1)
    hits = adapter.search(build_plan("query", namespace="selected", scope="thread", mode="vector"), limit=2)

    assert [candidate.record.id for candidate in result.candidates] == ["clm:z"]
    assert [hit.record.id for hit in hits] == ["clm:z", "clm:a"]
    assert [hit.score for hit in hits] == [
        0.7071067811865475 + 0.1, 0.7071067776510136 + 0.1,
    ]


def test_real_chroma_exact_acquisition_uses_bounded_canonical_id_pages(runtime, monkeypatch):
    runtime, adapter = runtime
    records = [_record(f"clm:{index:04d}") for index in range(300)]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))
    collection = adapter._collection()
    original_get = type(collection).get
    pages = []

    def get(self, *args, **kwargs):
        assert kwargs.get("ids"), "exact acquisition must be driven by canonical IDs"
        assert "offset" not in kwargs
        pages.append(len(kwargs["ids"]))
        return original_get(self, *args, **kwargs)

    monkeypatch.setattr(type(collection), "get", get)
    result = _retrieve(runtime)

    assert [candidate.record.id for candidate in result.candidates] == ["clm:0000", "clm:0001", "clm:0002"]
    assert sum(pages) == 300
    assert max(pages) <= 128


def test_real_chroma_fixed_slice_work_stays_scoped_under_unrelated_growth(runtime, monkeypatch):
    runtime, adapter = runtime
    selected = [
        _record("clm:a", "a-value"), _record("clm:b", "a-value"),
        _record("clm:c", "near-winner"), _record("clm:d", "near-loser"),
        *[_record(f"clm:zero-{index:04d}", "b-value") for index in range(60)],
    ]
    runtime.store.persist_ir(IRBatch(selected))
    adapter.sync_batch(IRBatch(selected))
    other_model = _FixedEmbedding()
    other_model.name = "r2-chroma-unrelated-model/1"
    other_adapter = ChromaSemanticAdapter(
        runtime.store, other_model, persist_directory=adapter.persist_directory,
        collection_name="r2_unrelated_model", client=adapter.client,
    )
    collection = adapter._collection()
    other_collection = other_adapter._collection()
    original_get = type(collection).get
    original_checkout = type(runtime.store._pool).checkout_physical
    original_iter_ir = runtime.store.iter_ir
    work = None

    @contextmanager
    def checkout(self):
        with original_checkout(self) as connection:
            sample = work
            if sample is not None:
                sample["canonical_snapshots"] += 1

                def step():
                    sample["canonical_vm_steps"] += 1
                    return 0

                connection.set_progress_handler(step, 1)
            try:
                yield connection
            finally:
                if sample is not None:
                    connection.set_progress_handler(None, 0)

    def iter_ir(*args, **kwargs):
        for record in original_iter_ir(*args, **kwargs):
            if work is not None:
                work["canonical_rows"] += 1
            yield record

    def get(self, *args, **kwargs):
        if work is not None:
            assert self.name == collection.name, "another model's collection must not be read"
            assert kwargs.get("ids"), "exact acquisition must use canonical IDs"
            assert "offset" not in kwargs
        response = original_get(self, *args, **kwargs)
        if work is not None:
            work["requested_pages"].append(list(kwargs["ids"]))
            work["returned_pages"].append(list(response["ids"]))
        return response

    monkeypatch.setattr(type(runtime.store._pool), "checkout_physical", checkout)
    monkeypatch.setattr(runtime.store, "iter_ir", iter_ir)
    monkeypatch.setattr(type(collection), "get", get)
    plan = build_plan("query", namespace="selected", scope="thread", mode="vector")
    selected_ids = {record.id for record in selected}
    expected_direct = [
        ("clm:a", 1.1), ("clm:b", 1.1),
        ("clm:c", 0.7071067811865475 + 0.1),
        ("clm:d", 0.7071067776510136 + 0.1),
    ]
    baseline = {}
    measurements = []
    previous_count = 0
    for count in (0, 128, 1024):
        if count:
            namespace_noise = [
                replace(_record(f"clm:namespace-{index:04d}"), ns="other")
                for index in range(previous_count, count)
            ]
            scope_noise = [
                replace(_record(f"clm:scope-{index:04d}"), scope="other")
                for index in range(previous_count, count)
            ]
            runtime.store.persist_ir(IRBatch(namespace_noise + scope_noise))
            adapter.sync_batch(IRBatch(namespace_noise + scope_noise))
            # Chroma embedding spaces live in separate collections. These
            # records are outside the target canonical namespace as well.
            other_adapter.sync_batch(IRBatch(namespace_noise))
        previous_count = count
        assert collection.count() == len(selected) + 2 * count
        assert other_collection.count() == count

        for boundary in ("direct", "public"):
            work = {
                "canonical_vm_steps": 0, "canonical_snapshots": 0,
                "canonical_rows": 0, "requested_pages": [], "returned_pages": [],
            }
            if boundary == "direct":
                hits = adapter.search(plan, limit=4)
                actual = [(hit.record.id, hit.score) for hit in hits]
                assert actual == expected_direct
            else:
                result = _retrieve(runtime, budget=4)
                actual = [(candidate.record.id, candidate.score) for candidate in result.candidates]
                assert [record_id for record_id, _ in actual] == [
                    record_id for record_id, _ in expected_direct
                ]
            sample, work = work, None
            assert actual == baseline.setdefault(boundary, actual)
            requested = [record_id for page in sample["requested_pages"] for record_id in page]
            returned = [record_id for page in sample["returned_pages"] for record_id in page]
            assert len(requested) == len(returned) == len(selected)
            assert set(requested) == set(returned) == selected_ids
            assert max(map(len, sample["requested_pages"])) <= 128
            assert max(map(len, sample["returned_pages"])) <= 128
            assert sample["canonical_rows"] == len(selected) + 1  # The unindexed subject ENT.
            assert sample["canonical_snapshots"] == 1
            assert sample["canonical_vm_steps"] > 0
            measurements.append({
                "boundary": boundary, "unrelated_namespace_rows": count,
                "unrelated_scope_rows": count, "separate_model_collection_rows": count,
                "canonical_vm_steps": sample["canonical_vm_steps"],
                "canonical_rows": sample["canonical_rows"],
                "requested_page_sizes": list(map(len, sample["requested_pages"])),
                "returned_page_sizes": list(map(len, sample["returned_pages"])),
                "ids_and_scores": actual,
            })

    print(f"chroma_fixed_slice_growth_measurements={measurements}")
    for boundary in ("direct", "public"):
        steps = [row["canonical_vm_steps"] for row in measurements if row["boundary"] == boundary]
        # VM opcodes measure canonical work independently from returned Chroma
        # pages. Neither may hide a scan of the growing unrelated boundaries.
        assert max(steps) < 2 * min(steps), (boundary, measurements)


def test_real_chroma_exact_missing_coverage_cannot_shorten_results(runtime):
    runtime, adapter = runtime
    records = [_record("clm:a"), _record("clm:b")]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))
    adapter.delete_records(["clm:b"])

    with pytest.raises(RuntimeError, match="coverage is incomplete"):
        _retrieve(runtime)

    adapter.delete_records(["clm:a"])
    with pytest.raises(RuntimeError, match="coverage is incomplete"):
        _retrieve(runtime)


def test_real_chroma_never_synced_collection_stays_empty_until_explicit_sync(runtime):
    runtime, adapter = runtime
    record = _record("clm:a")
    runtime.store.persist_ir(IRBatch([record]))
    assert _retrieve(runtime).candidates == []
    adapter.sync_batch(IRBatch([record]))
    assert [candidate.record.id for candidate in _retrieve(runtime).candidates] == ["clm:a"]


@pytest.mark.parametrize(("field", "value"), [
    ("source_hash", "changed"), ("vector_text_version", "old"),
    ("model_name", "other-model"), ("dimension", 3),
    ("vector_original_version", "old"), ("vector_original_json", "[1.0,0.5]"),
    ("ns", "other"), ("scope", "other"),
])
def test_real_chroma_exact_detects_projection_metadata_drift(runtime, field, value):
    runtime, adapter = runtime
    record = _record("clm:a")
    runtime.store.persist_ir(IRBatch([record]))
    adapter.sync_batch(IRBatch([record]))
    adapter._collection().update(ids=[record.id], metadatas=[{field: value}])

    with pytest.raises(RuntimeError, match="projection is stale"):
        _retrieve(runtime)


def test_real_chroma_approximate_is_explicit_and_isolates_model_metadata(runtime):
    runtime, adapter = runtime
    records = [_record("clm:a"), _record("clm:b")]
    runtime.store.persist_ir(IRBatch(records))
    adapter.sync_batch(IRBatch(records))
    adapter.search_mode = "approximate"
    assert {candidate.record.id for candidate in _retrieve(runtime).candidates} == {"clm:a", "clm:b"}
    adapter._collection().update(ids=["clm:a"], metadatas=[{"model_name": "other-model"}])
    assert [candidate.record.id for candidate in _retrieve(runtime).candidates] == ["clm:b"]
