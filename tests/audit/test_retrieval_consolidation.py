"""One-engine retrieval regressions.

The full runtime historically exposed ``search_ir`` while graph/reasoning work
grew in ``RetrievalOrchestrator``. These tests pin the consolidation contract:
the runtime compatibility method is only a result-shape adapter over the
orchestrator, and RAW/temporal/lens options reach that canonical engine.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benchmarks.external.locomo.run import build_adapter
from seam_runtime.bm25 import BM25Index
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, SearchResult, Status
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.retrieval import RetrievalFlags, search_batch
from seam_runtime.retrieval_orchestrator.adapters import SQLiteTemporalAdapter
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter, search_vector_adapter


def _runtime(tmp_path) -> SeamRuntime:
    path = tmp_path / "retrieval-consolidation.db"
    model = HashEmbeddingModel()
    return SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=SQLiteVectorAdapter(path, model),
        allow_pgvector_env=False,
    )


def _record(
    record_id: str,
    kind: RecordKind,
    text: str,
    *,
    t0: str | None = None,
    evidence: list[str] | None = None,
) -> MIRLRecord:
    attrs = (
        {"content": text}
        if kind == RecordKind.RAW
        else {"subject": "ent:test", "predicate": "notes", "object": text}
    )
    return MIRLRecord(
        id=record_id,
        kind=kind,
        ns="work",
        scope="thread",
        t0=t0,
        evidence=list(evidence or []),
        ext=(
            {}
            if kind is RecordKind.RAW
            else {VIRTUAL_REFS_EXTENSION: ["ent:test"]}
        ),
        attrs=attrs,
    )


def test_search_ir_is_a_compatibility_shape_over_canonical_retrieval(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record("raw:evidence", RecordKind.RAW, "Ada shipped the compiler."),
                    _record(
                        "clm:compiler",
                        RecordKind.CLM,
                        "Ada shipped the compiler.",
                        evidence=["raw:evidence"],
                    ),
                ]
            )
        )

        canonical = runtime.retrieve(
            "compiler shipped",
            ns="work",
            scope="thread",
            budget=10,
            include_raw=True,
            ranking_policy="legacy-weighted/1",
            include_trace=True,
        )
        compatible = runtime.search_ir(
            "compiler shipped",
            ns="work",
            scope="thread",
            budget=10,
            include_raw=True,
        )

        assert isinstance(compatible, SearchResult)
        assert [item.record.id for item in compatible.candidates] == [
            item.record.id for item in canonical.candidates
        ]
        assert [item.score for item in compatible.candidates] == [
            item.score for item in canonical.candidates
        ]
        assert canonical.trace is not None
        assert canonical.trace["plan"]["ranking_policy"] == "legacy-weighted/1"
        assert canonical.trace["plan"]["legs"] == [
            {"name": "legacy_weighted", "limit": 10}
        ]
        assert set(canonical.trace["legs"]) == {"legacy_weighted"}
        assert canonical.trace["fusion"]["normalization"] == {
            "method": "legacy_weighted"
        }
        claim = next(
            item
            for item in compatible.candidates
            if item.record.id == "clm:compiler"
        )
        assert [record.id for record in claim.evidence] == ["raw:evidence"]
        assert any(reason.startswith("lexical=") for reason in claim.reasons)
    finally:
        runtime.close()


def test_legacy_weighted_policy_preserves_raw_bm25_and_weighted_ranking(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record("raw:rare", RecordKind.RAW, "axolotl archive signal"),
                    _record("clm:rare", RecordKind.CLM, "axolotl archive signal"),
                    _record("clm:other", RecordKind.CLM, "ordinary weather note"),
                ]
            )
        )
        batch = runtime.store.load_ir(ns="work", scope="thread")
        bm25 = BM25Index()
        for record in batch.records:
            if record.kind == RecordKind.RAW:
                bm25.add(record.id, str(record.attrs["content"]))
        vector_scores = search_vector_adapter(
            runtime.vector_adapter,
            "axolotl",
            limit=30,
            namespace="work",
            scope="thread",
        )
        expected = search_batch(
            batch,
            query="axolotl",
            scope="thread",
            limit=10,
            vector_scores=vector_scores,
            namespace="work",
            include_raw=True,
            bm25_index=bm25,
        )
        actual = runtime.retrieve(
            "axolotl",
            ns="work",
            scope="thread",
            budget=10,
            include_raw=True,
            ranking_policy="legacy-weighted/1",
        )

        assert [candidate.record.id for candidate in actual.candidates] == [
            candidate.record.id for candidate in expected.candidates
        ]
        assert [candidate.score for candidate in actual.candidates] == [
            candidate.score for candidate in expected.candidates
        ]
        assert actual.candidates[0].sources == {
            "legacy_weighted": expected.candidates[0].score
        }
    finally:
        runtime.close()


def test_locomo_adapter_exposes_same_code_graph_ablation_modes(tmp_path) -> None:
    adapter = build_adapter(
        "seam",
        db_path=str(tmp_path),
        retrieval_mode="mix",
    )
    try:
        assert adapter.semantic_recovery_policy.to_dict()["retrieval_mode"] == "mix"
    finally:
        adapter.close()


def test_canonical_retrieval_honors_raw_and_lens_options(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record("raw:only", RecordKind.RAW, "private orchid signal"),
                ]
            )
        )

        without_raw = runtime.retrieve(
            "orchid",
            ns="work",
            scope="thread",
            budget=5,
            include_raw=False,
        )
        with_raw = runtime.retrieve(
            "orchid",
            ns="work",
            scope="thread",
            budget=5,
            include_raw=True,
            lens="recall.user",
            include_trace=True,
        )

        assert without_raw.candidates == []
        assert [item.record.id for item in with_raw.candidates] == ["raw:only"]
        assert with_raw.trace is not None
        assert with_raw.trace["plan"]["include_raw"] is True
        assert "lens" not in with_raw.trace["plan"]
    finally:
        runtime.close()


def test_canonical_retrieval_fuses_explicit_temporal_context(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record(
                        "clm:near",
                        RecordKind.CLM,
                        "Alice mentioned the event.",
                        t0="2024-04-15",
                    ),
                    _record(
                        "clm:far",
                        RecordKind.CLM,
                        "Alice mentioned the event.",
                        t0="2024-12-15",
                    ),
                ]
            )
        )

        result = runtime.retrieve(
            "Alice event",
            ns="work",
            scope="thread",
            budget=2,
            temporal_window=(datetime(2024, 3, 1), datetime(2024, 5, 31)),
            include_trace=True,
        )

        assert [item.record.id for item in result.candidates] == [
            "clm:near",
            "clm:far",
        ]
        assert "temporal" in result.candidates[0].sources
        assert "temporal" not in result.candidates[1].sources
        assert result.trace is not None
        assert result.trace["plan"]["temporal_window_applied"] is True
        assert "temporal_window" not in result.trace["plan"]
    finally:
        runtime.close()


def test_canonical_planner_normalizes_mixed_temporal_awareness(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        result = runtime.retrieve(
            "Alice event",
            budget=2,
            include_trace=True,
            temporal_window=(
                datetime(2024, 3, 1),
                datetime(2024, 5, 31, tzinfo=UTC),
            ),
        )
        assert result.trace is not None
        assert result.trace["plan"]["temporal_window_applied"] is True
    finally:
        runtime.close()


def test_canonical_planner_normalizes_reference_window_awareness_mismatch(
    tmp_path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        result = runtime.retrieve(
            "Alice event",
            budget=2,
            include_trace=True,
            temporal_reference=datetime(2024, 4, 15, tzinfo=UTC),
            temporal_window=(
                datetime(2024, 3, 1),
                datetime(2024, 5, 31),
            ),
        )
        assert result.trace is not None
        assert result.trace["plan"]["temporal_reference_applied"] is True
        assert result.trace["plan"]["temporal_window_applied"] is True
    finally:
        runtime.close()


def test_aware_temporal_inputs_normalize_to_store_contract(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record(
                        "clm:near",
                        RecordKind.CLM,
                        "Alice mentioned the event.",
                        t0="2024-04-15",
                    )
                ]
            )
        )

        window_result = runtime.retrieve(
            "Alice event",
            ns="work",
            scope="thread",
            budget=1,
            temporal_window=(
                datetime(2024, 3, 1, tzinfo=UTC),
                datetime(2024, 5, 31, tzinfo=UTC),
            ),
        )
        reference_result = runtime.retrieve(
            "Alice event",
            ns="work",
            scope="thread",
            budget=1,
            temporal_reference=datetime(2024, 4, 15, tzinfo=UTC),
        )
        plan = build_plan(
            "Alice event",
            temporal_reference=datetime(2024, 4, 15, tzinfo=UTC),
            temporal_window=(
                datetime(2024, 3, 1, tzinfo=UTC),
                datetime(2024, 5, 31, tzinfo=UTC),
            ),
        )

        assert window_result.candidates[0].record.id == "clm:near"
        assert reference_result.candidates[0].record.id == "clm:near"
        assert plan.temporal_reference is not None
        assert plan.temporal_reference.tzinfo is None
        assert plan.temporal_window is not None
        assert all(value.tzinfo is None for value in plan.temporal_window)
    finally:
        runtime.close()


def test_explicit_falsey_flags_never_fall_back_to_cached_flags(
    tmp_path, monkeypatch
) -> None:
    class FalseyFlags(RetrievalFlags):
        def __bool__(self) -> bool:
            return False

    runtime = _runtime(tmp_path)
    try:
        monkeypatch.setattr(
            runtime,
            "_retrieval_flags_cached",
            lambda: (_ for _ in ()).throw(AssertionError("unexpected fallback")),
        )
        orchestrator = runtime._retrieval_orchestrator_cached()
        flags = FalseyFlags()

        assert orchestrator.search("empty", budget=1, flags=flags).candidates == []
        assert orchestrator.decide("empty", budget=1, flags=flags).selected == []
    finally:
        runtime.close()


def test_canonical_planner_validates_explicit_zero_candidate_budget(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="budget must be positive"):
            runtime._retrieval_orchestrator_cached().plan(
                "Alice event",
                budget=2,
                candidate_budget=0,
            )
    finally:
        runtime.close()


def test_temporal_leg_honors_explicit_history_view(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        retired = _record(
            "clm:retired",
            RecordKind.CLM,
            "Alice mentioned the retired event.",
            t0="2024-04-15",
        )
        retired.status = Status.SUPERSEDED
        runtime.persist_ir(IRBatch([retired]))
        window = (datetime(2024, 3, 1), datetime(2024, 5, 31))
        current_plan = build_plan(
            "Alice event",
            budget=2,
            temporal_window=window,
        )
        history_plan = build_plan(
            "Alice event",
            budget=2,
            temporal_window=window,
            graph_include_history=True,
        )
        adapter = SQLiteTemporalAdapter(runtime.store)

        assert adapter.search(current_plan, limit=2) == []
        assert [hit.record.id for hit in adapter.search(history_plan, limit=2)] == [
            "clm:retired"
        ]
    finally:
        runtime.close()
