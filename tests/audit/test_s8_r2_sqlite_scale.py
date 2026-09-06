"""R2: namespace-scoped structured retrieval ignores unrelated vector growth."""

from contextlib import contextmanager

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.runtime import SeamRuntime


@pytest.fixture()
def runtime(tmp_path):
    runtime = SeamRuntime(
        tmp_path / "r2-sqlite.db",
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    )
    try:
        runtime.store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=f"ent:{ns}:{scope}",
                        kind=RecordKind.ENT,
                        ns=ns,
                        scope=scope,
                        attrs={"name": "Fixture"},
                    )
                    for ns, scope in (
                        ("selected", "thread"), ("selected", "other"), ("other", "thread")
                    )
                ]
            )
        )
        yield runtime
    finally:
        runtime.close()


def _record(record_id, text, *, ns="selected", scope="thread"):
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns=ns,
        scope=scope,
        attrs={"subject": f"ent:{ns}:{scope}", "predicate": "contains", "object": text},
    )


def _vectors(runtime, entries):
    # Synthetic model names keep semantic matches out of these SQL fixtures;
    # the public hybrid request still executes its real semantic adapter.
    with runtime.store._pool.checkout() as connection:
        connection.executemany(
            "insert into vector_index "
            "(record_id, model_name, dimension, source_text, namespace, scope, "
            "vector_json, updated_at) values (?, ?, 1, ?, ?, ?, '[1.0]', ?)",
            [
                (record.id, model, text, record.ns, record.scope, record.updated_at)
                for record, model, text in entries
            ],
        )
        connection.commit()


def _retrieve(runtime, query="needle", *, scope="thread", **kwargs):
    # SQL is a leg, not a public mode: hybrid exercises it via the public seam.
    return runtime.retrieve(
        query,
        mode="hybrid",
        ns="selected",
        scope=scope,
        budget=10,
        include_trace=True,
        **kwargs,
    )


def _sql_vm_counter(runtime, monkeypatch):
    """Count actual SQL-leg VM instructions, excluding the other hybrid leg."""
    work = {"steps": 0, "statements": 0}
    original = runtime.store._pool.checkout_physical

    @contextmanager
    def instrumented_checkout():
        with original() as connection:
            measuring = False

            def trace(statement):
                nonlocal measuring
                measuring = statement.lstrip().lower().startswith("with record_rows as")
                if measuring:
                    work["statements"] += 1

            def progress():
                if measuring:
                    work["steps"] += 1
                return 0

            connection.set_trace_callback(trace)
            connection.set_progress_handler(progress, 1)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)
                connection.set_trace_callback(None)

    monkeypatch.setattr(runtime.store._pool, "checkout_physical", instrumented_checkout)
    return work


@pytest.mark.parametrize("scope", [None, "thread"])
def test_fixed_namespace_sql_work_stays_flat_as_other_namespace_grows(
    runtime, monkeypatch, scope
):
    selected = [_record(f"clm:selected-{index}", "needle") for index in range(4)]
    runtime.store.persist_ir(IRBatch(selected))
    _vectors(
        runtime,
        [(record, "r2-model", "needle") for record in selected[:3]],
    )
    # Resolve lazy runtime setup before measuring steady-state retrieval work.
    _retrieve(runtime, scope=scope)
    work = _sql_vm_counter(runtime, monkeypatch)

    def measured():
        work.update(steps=0, statements=0)
        result = _retrieve(runtime, scope=scope)
        assert work["statements"] == 1, "the public request must execute measured SQL"
        assert work["steps"] > 0
        assert result.trace["legs"]["vector"] == []
        return result, work["steps"]

    baseline, baseline_steps = measured()
    expected = [candidate.to_dict() for candidate in baseline.candidates]
    assert [candidate.record.id for candidate in baseline.candidates] == [
        record.id for record in selected
    ]
    measurements = [(0, baseline_steps)]
    previous_size = 0
    for size in (256, 4096):
        unrelated = [
            _record(f"clm:unrelated-{index:05d}", "needle", ns="other")
            for index in range(previous_size, size)
        ]
        runtime.store.persist_ir(IRBatch(unrelated))
        _vectors(
            runtime,
            [
                (record, model, "needle")
                for record in unrelated
                for model in ("r2-model-a", "r2-model-z")
            ],
        )
        result, steps = measured()
        measurements.append((size, steps))
        assert [candidate.to_dict() for candidate in result.candidates] == expected
        assert result.trace["legs"]["sql"] == baseline.trace["legs"]["sql"]
        assert result.trace["fusion"]["candidate_set_sha256"] == (
            baseline.trace["fusion"]["candidate_set_sha256"]
        )
        previous_size = size

    # A small fixed allowance accommodates SQLite opcode variation while
    # rejecting even one pass over the unrelated records or their vectors.
    max_steps = baseline_steps + 128
    print(f"scope={scope!r}; unrelated_records/sql_vm_steps={measurements}; cap={max_steps}")
    assert all(steps <= max_steps for _, steps in measurements), measurements


def test_sql_preserves_source_max_payload_fallback_scores_and_id_ties(runtime):
    texts = {
        "clm:vector-hit-b": "no lexical overlap",
        "clm:vector-hit-a": "no lexical overlap",
        "clm:vector-miss": "needle",
        "clm:case-max": "no lexical overlap",
        "clm:fallback": "needle",
        "clm:empty-source": "needle",
    }
    records = {record_id: _record(record_id, text) for record_id, text in texts.items()}
    runtime.store.persist_ir(
        IRBatch(
            [
                *records.values(),
                _record("clm:other-namespace", "needle", ns="other"),
                _record("clm:other-scope", "needle", scope="other"),
            ]
        )
    )
    _vectors(
        runtime,
        [
            (records["clm:vector-hit-b"], "r2-model-z", "aaa irrelevant"),
            (records["clm:vector-hit-b"], "r2-model-a", "needle"),
            (records["clm:vector-hit-a"], "r2-model-a", "aaa irrelevant"),
            (records["clm:vector-hit-a"], "r2-model-z", "needle"),
            (records["clm:vector-miss"], "r2-model-a", "needle"),
            (records["clm:vector-miss"], "r2-model-z", "zzzz absent"),
            # MAX is case sensitive and happens before lower(), as before R2.
            (records["clm:case-max"], "r2-model-a", "Zulu absent"),
            (records["clm:case-max"], "r2-model-z", "needle"),
            (records["clm:empty-source"], "r2-model-a", ""),
        ],
    )

    result = _retrieve(runtime)

    expected_ids = [
        "clm:case-max", "clm:fallback", "clm:vector-hit-a", "clm:vector-hit-b"
    ]
    assert [candidate.record.id for candidate in result.candidates] == expected_ids
    assert result.trace["legs"]["vector"] == []
    assert [hit["record_id"] for hit in result.trace["legs"]["sql"]] == expected_ids
    assert [hit["score"] for hit in result.trace["legs"]["sql"]] == pytest.approx(
        [1.72] * len(expected_ids)
    )


@pytest.mark.parametrize(
    ("query", "admitted"),
    [
        ("unmatched", False),
        ("unmatched ns:selected", False),
        ("unmatched scope:thread", False),
        ("unmatched ns:selected scope:thread", True),
        ("", True),
    ],
)
def test_sql_preserves_query_authored_boundary_tail(runtime, query, admitted):
    runtime.store.persist_ir(
        IRBatch(
            [
                _record("clm:boundary", "different content"),
                _record("clm:wrong-ns", "different content", ns="other"),
                _record("clm:wrong-scope", "different content", scope="other"),
            ]
        )
    )

    result = _retrieve(runtime, query)

    assert [candidate.record.id for candidate in result.candidates] == (
        ["clm:boundary"] if admitted else []
    )
    assert [hit["score"] for hit in result.trace["legs"]["sql"]] == pytest.approx(
        [0.95] if admitted else []
    )
