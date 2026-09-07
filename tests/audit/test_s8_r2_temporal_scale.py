"""R2 temporal retrieval bounds payload acquisition at the public seam."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.runtime import SeamRuntime


@pytest.fixture()
def runtime(tmp_path):
    runtime = SeamRuntime(
        tmp_path / "r2-temporal.db",
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    )
    try:
        runtime.store.persist_ir(
            IRBatch([
                MIRLRecord(
                    id=f"ent:{ns}:{scope}", kind=RecordKind.ENT, ns=ns,
                    scope=scope, attrs={"name": "Fixture"},
                )
                for ns, scope in (
                    ("selected", "thread"), ("selected", "other"), ("other", "thread")
                )
            ])
        )
        yield runtime
    finally:
        runtime.close()


def _event(record_id, timestamp, *, ns="selected", scope="thread", **kwargs):
    return MIRLRecord(
        id=record_id,
        kind=kwargs.pop("kind", RecordKind.CLM),
        ns=ns,
        scope=scope,
        t0=timestamp,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        attrs=kwargs.pop("attrs", {
            "subject": f"ent:{ns}:{scope}", "predicate": "observed",
            "object": "event", "detail": "x" * 1024,
        }),
        **kwargs,
    )


def _retrieve(runtime, query="", budget=3, **kwargs):
    # An empty semantic-only request still executes its real vector adapter,
    # which has no matching vectors here; temporal is the only populated leg.
    return runtime.retrieve(
        query,
        mode="vector",
        ns="selected",
        scope="thread",
        budget=budget,
        include_trace=True,
        **kwargs,
    )


def _temporal_work(runtime, monkeypatch):
    """Observe real temporal work while excluding other legs/current reads."""
    work = {"active": False, "records": 0, "unbounded_loads": 0, "sql_steps": 0}
    adapter = runtime._retrieval_orchestrator_cached().temporal_adapter
    original_search = adapter.search
    original_from_dict = MIRLRecord.from_dict
    original_load = runtime.store.load_ir
    original_checkout = runtime.store._pool.checkout_physical

    def search(*args, **kwargs):
        work["active"] = True
        try:
            return original_search(*args, **kwargs)
        finally:
            work["active"] = False

    def from_dict(cls, value):
        if work["active"]:
            work["records"] += 1
        return original_from_dict(value)

    def load_ir(*args, **kwargs):
        if work["active"] and not kwargs.get("ids") and kwargs.get("limit") is None:
            work["unbounded_loads"] += 1
        return original_load(*args, **kwargs)

    @contextmanager
    def checkout():
        with original_checkout() as connection:
            def progress():
                if work["active"]:
                    work["sql_steps"] += 1
                return 0

            connection.set_progress_handler(progress, 1)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)

    monkeypatch.setattr(adapter, "search", search)
    monkeypatch.setattr(MIRLRecord, "from_dict", classmethod(from_dict))
    monkeypatch.setattr(runtime.store, "load_ir", load_ir)
    monkeypatch.setattr(runtime.store._pool, "checkout_physical", checkout)
    return work


@pytest.mark.parametrize("context", ["reference", "window"])
def test_temporal_payload_acquisition_stays_bounded_as_namespace_grows(
    runtime, monkeypatch, context
):
    selected = [
        _event(f"evt:selected-{index}", "2026-01-01T00:00:00Z")
        for index in range(8)
    ]
    runtime.store.persist_ir(IRBatch(selected))
    temporal = (
        {"temporal_reference": datetime(2026, 1, 1)}
        if context == "reference"
        else {"temporal_window": (datetime(2026, 1, 1), datetime(2026, 1, 1))}
    )
    _retrieve(runtime, **temporal)
    work = _temporal_work(runtime, monkeypatch)

    def measured():
        work.update(records=0, unbounded_loads=0, sql_steps=0)
        result = _retrieve(runtime, **temporal)
        assert result.trace["legs"]["vector"] == []
        assert [candidate.record.id for candidate in result.candidates] == [
            "evt:selected-0", "evt:selected-1", "evt:selected-2"
        ]
        assert all(hit["score"] == 1.0 for hit in result.trace["legs"]["temporal"])
        assert work["records"] > 0, "measure the executing temporal leg"
        assert work["sql_steps"] > 0, "measure actual database work separately"
        return result, {key: work[key] for key in ("records", "unbounded_loads", "sql_steps")}

    baseline, baseline_work = measured()
    expected = [candidate.to_dict() for candidate in baseline.candidates]
    measurements = [(0, baseline_work)]
    previous_size = 0
    for size in (128, 1024):
        runtime.store.persist_ir(
            IRBatch(
                [
                    _event(
                        f"evt:growth-{group}-{index:05d}",
                        "2025-01-01T00:00:00Z",
                        ns=ns,
                        scope=scope,
                    )
                    for index in range(previous_size, size)
                    for group, ns, scope in (
                        ("same", "selected", "thread"),
                        ("scope", "selected", "other"),
                        ("namespace", "other", "thread"),
                    )
                ]
            )
        )
        result, measured_work = measured()
        measurements.append((size, measured_work))
        assert [candidate.to_dict() for candidate in result.candidates] == expected
        assert result.trace["fusion"]["candidate_set_sha256"] == (
            baseline.trace["fusion"]["candidate_set_sha256"]
        )
        previous_size = size

    print(f"context={context}; growth_per_boundary/temporal_work={measurements}")
    # The vector-mode temporal leg requests max(budget, 5) candidates.
    # Timestamp scanning is database work; only payload acquisition is bounded.
    assert all(item["records"] <= 5 for _, item in measurements), measurements
    assert all(item["unbounded_loads"] == 0 for _, item in measurements), measurements


def test_temporal_reference_preserves_canonical_instants_decay_and_zero_cutoff(runtime):
    timestamps = {
        "a-offset": "2025-12-31T19:00:00-05:00",
        "b-naive": "2026-01-01T00:00:00",
        "c-z": "2026-01-01T00:00:00Z",
        "d-past": "2025-12-02T00:00:00Z",
        "e-future": "2026-01-31T00:00:00Z",
        "f-small": "2030-02-09T00:00:00Z",  # 1500 days, exp(-50) > 0
        "underflow": "9999-01-01T00:00:00Z",
        "invalid": "2026-02-30T00:00:00Z",
        "blank": "  ",
        "missing": None,
    }
    runtime.store.persist_ir(IRBatch([
        _event(f"clm:{key}", timestamp) for key, timestamp in timestamps.items()
    ]))

    result = _retrieve(
        runtime, budget=20,
        temporal_reference=datetime(2025, 12, 31, 19, tzinfo=timezone(timedelta(hours=-5))),
        # Reference retains its existing precedence when both are supplied.
        temporal_window=(datetime(2020, 1, 1), datetime(2020, 1, 2)),
    )

    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:a-offset", "clm:b-naive", "clm:c-z", "clm:d-past", "clm:e-future", "clm:f-small"
    ]
    assert [hit["score"] for hit in result.trace["legs"]["temporal"]] == [
        1.0, 1.0, 1.0, 0.367879, 0.367879, 0.0,
    ]
    assert result.candidates[-1].score > 0, "trace rounding must not suppress a positive hit"


def test_temporal_reference_preserves_subsecond_order_before_id_ties(runtime):
    runtime.store.persist_ir(IRBatch([
        _event("clm:a-further", "2026-01-01T00:00:00.000002Z"),
        _event("clm:z-nearest", "2026-01-01T00:00:00.000001Z"),
        _event("clm:y-equivalent", "2025-12-31T19:00:00.000001-05:00"),
    ]))

    result = _retrieve(runtime, temporal_reference=datetime(2026, 1, 1))

    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:y-equivalent", "clm:z-nearest", "clm:a-further"
    ]


@pytest.mark.parametrize("context", ["reference", "window"])
def test_temporal_excludes_nonstring_payload_timestamp_after_sqlite_text_coercion(
    runtime, context
):
    runtime.store.persist_ir(IRBatch([
        _event("clm:a-numeric", 20260101),
        _event("clm:b-compact-string", "20260101"),
        _event("clm:c-iso-string", "2026-01-01T00:00:00Z"),
    ]))
    temporal = (
        {"temporal_reference": datetime(2026, 1, 1)}
        if context == "reference"
        else {"temporal_window": (datetime(2026, 1, 1), datetime(2026, 1, 1))}
    )

    result = _retrieve(runtime, **temporal)

    # SQLite's TEXT column makes the integer look like a valid compact date.
    # Canonical parsing operates on the payload value and accepts only strings.
    expected = ["clm:b-compact-string", "clm:c-iso-string"]
    assert [candidate.record.id for candidate in result.candidates] == expected
    assert [hit["record_id"] for hit in result.trace["legs"]["temporal"]] == expected
    assert [hit["score"] for hit in result.trace["legs"]["temporal"]] == [1.0, 1.0]


def test_temporal_window_is_inclusive_and_excludes_invalid_or_outside_instants(runtime):
    runtime.store.persist_ir(IRBatch([
        _event("clm:c-end", "2026-01-01T00:00:00.000003Z"),
        _event("clm:a-start", "2025-12-31T19:00:00.000001-05:00"),
        _event("clm:b-inside", "2026-01-01T00:00:00.000002"),
        _event("clm:before", "2026-01-01T00:00:00.000000Z"),
        _event("clm:after", "2026-01-01T00:00:00.000004Z"),
        _event("clm:invalid", "invalid"),
    ]))

    result = _retrieve(runtime, budget=10, temporal_window=(
        datetime(2026, 1, 1, microsecond=1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, microsecond=3),
    ))

    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:a-start", "clm:b-inside", "clm:c-end"
    ]
    assert [hit["score"] for hit in result.trace["legs"]["temporal"]] == [1.0] * 3


@pytest.mark.parametrize("include_history", [False, True])
@pytest.mark.parametrize("include_raw", [False, True])
def test_temporal_kind_lifecycle_and_boundary_filters_precede_top_k(
    runtime, include_history, include_raw
):
    selected = []
    for kind in (RecordKind.CLM, RecordKind.EVT, RecordKind.STA, RecordKind.REL, RecordKind.RAW):
        attrs = {"subject": "ent:selected:thread", "predicate": "observed", "object": "event"}
        if kind is RecordKind.REL:
            attrs.update(src="ent:selected:thread", dst="ent:selected:thread")
        selected.append(_event(f"record:{kind.value}", "2026-01-01", kind=kind, attrs=attrs))
    historical = [
        _event(f"clm:history-{status.value}", "2026-01-01", status=status)
        for status in (Status.CONTRADICTED, Status.SUPERSEDED, Status.DEPRECATED, Status.DELETED_SOFT)
    ]
    runtime.store.persist_ir(IRBatch([
        *selected, *historical,
        _event("clm:outside-ns", "2026-01-01", ns="other"),
        _event("clm:outside-scope", "2026-01-01", scope="other"),
        _event("ent:excluded-kind", "2026-01-01", kind=RecordKind.ENT),
    ]))
    expected = [record.id for record in selected if include_raw or record.kind is not RecordKind.RAW]
    if include_history:
        expected.extend(record.id for record in historical)

    result = _retrieve(
        runtime, budget=20, include_raw=include_raw,
        graph_include_history=include_history, temporal_reference=datetime(2026, 1, 1),
    )

    assert [candidate.record.id for candidate in result.candidates] == sorted(expected)
    narrowed = _retrieve(
        runtime, query="kind:EVT,STA id:record:EVT,record:STA,record:CLM", budget=20,
        include_raw=include_raw, graph_include_history=include_history,
        temporal_reference=datetime(2026, 1, 1),
    )
    assert [candidate.record.id for candidate in narrowed.candidates] == ["record:EVT", "record:STA"]


@pytest.mark.parametrize(
    ("value", "filter_text"),
    [("ÄBC", "äbc"), (None, "none"), (True, "true"), (False, "false"),
     (123456789012345678901234567890, "123456789012345678901234567890"),
     ([True, None, "Ä"], "ä"), ({"Ä": True}, "ä")],
)
def test_temporal_attribute_filter_preserves_python_text_semantics(runtime, value, filter_text):
    runtime.store.persist_ir(IRBatch([
        _event("clm:match", "2026-01-01", attrs={
            "subject": "ent:selected:thread", "predicate": "ÄP", "object": value,
        }),
        _event("clm:miss", "2026-01-01"),
        _event("clm:missing-object", "2026-01-01", attrs={
            "subject": "ent:selected:thread", "predicate": "ÄP",
        }),
    ]))

    result = _retrieve(
        runtime, query=f"subject:ENT:SELECTED:THREAD predicate:äp object:{filter_text}",
        temporal_reference=datetime(2026, 1, 1),
    )

    assert [candidate.record.id for candidate in result.candidates] == ["clm:match"]
