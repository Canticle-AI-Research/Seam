"""Per-case, per-leg retrieval trace plumbing (HISTORY#504 follow-up).

The one-engine ranking A/B in HISTORY#503 measured a -0.010804 context-recall
regression but could not attribute it, because the full runner recorded no
per-leg evidence. These tests cover the artifact path that makes the
hybrid-versus-mix ablation attributable:

    orchestrator trace -> search_ir/retrieve -> adapter -> AdapterAnswer
    -> runner case record

The load-bearing property is that requesting a trace is *observational*: it must
not change which candidates are selected or how they are ordered, or the trace
would contaminate the very A/B it exists to explain.
"""

from __future__ import annotations

from benchmarks.external.common.runner import _build_report, _score_case
from benchmarks.external.common.types import AdapterAnswer, BenchmarkCase
from seam_runtime.mirl import SearchResult


def _ingest(rt, texts: list[str]) -> None:
    for index, text in enumerate(texts):
        rt.ingest_conversation_turn(
            text,
            source_ref=f"local://trace-{index}",
            ns="local.default",
            scope="thread",
        )


CORPUS = [
    "Melanie adopted a tabby cat named Pepper in March.",
    "Caroline started a pottery class on Tuesday evenings.",
    "Melanie's cat Pepper knocked over the pottery vase.",
    "Caroline sold three bowls at the spring craft fair.",
]


def test_trace_does_not_change_selection_or_order(tmp_path):
    """include_trace must be inert on ranking.

    This is the property the ablation depends on: a traced arm and an untraced
    arm must produce identical ranked output for the same corpus and query.
    """
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "trace.db", allow_pgvector_env=False)
    _ingest(rt, CORPUS)

    query = "What is Melanie's cat called?"

    untraced = rt.search_ir(query, budget=5, include_raw=True)
    traced = rt.search_ir(query, budget=5, include_raw=True, include_trace=True)

    assert untraced.trace is None
    assert traced.trace is not None

    assert [c.record.id for c in traced.candidates] == [
        c.record.id for c in untraced.candidates
    ]
    assert [round(c.score, 9) for c in traced.candidates] == [
        round(c.score, 9) for c in untraced.candidates
    ]


def test_trace_carries_per_leg_attribution(tmp_path):
    """The trace must name the ranking policy and carry per-leg detail."""
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "trace.db", allow_pgvector_env=False)
    _ingest(rt, CORPUS)

    result = rt.retrieve(
        "What is Melanie's cat called?",
        budget=5,
        include_raw=True,
        include_trace=True,
        mode="mix",
    )

    trace = result.trace
    assert trace is not None
    # Attribution requires all three: which plan ran, which legs contributed,
    # and what the fusion step selected.
    assert "plan" in trace and "legs" in trace and "fusion" in trace
    assert trace["fusion"]["policy"] == "reciprocal-rank-fusion/2"
    assert "selected_ids" in trace["fusion"]
    assert "legs" in trace["latency_ms"]


def test_search_ir_trace_reports_legacy_weighted_policy(tmp_path):
    """The control arm must be self-identifying in its own artifact."""
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "trace.db", allow_pgvector_env=False)
    _ingest(rt, CORPUS)

    result = rt.search_ir("pottery class", budget=5, include_trace=True)

    assert result.trace["fusion"]["policy"] == "legacy-weighted/1"
    assert result.trace["fusion"]["normalization"]["method"] == "legacy_weighted"


def test_search_result_to_dict_omits_trace_when_absent():
    """Existing exact-dict consumers must not see a new key."""
    assert SearchResult(query="q", candidates=[]).to_dict() == {
        "query": "q",
        "candidates": [],
    }
    assert SearchResult(query="q", candidates=[], trace={"a": 1}).to_dict()["trace"] == {
        "a": 1
    }


def test_adapter_emits_trace_only_when_requested(monkeypatch, tmp_path):
    """The adapter requests a trace only for the question actually asked."""
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    observed: list[bool] = []

    class FakeRuntime:
        def search_ir(self, query, **kwargs):
            observed.append(kwargs.get("include_trace"))

            class Result:
                candidates = []
                trace = {"fusion": {"policy": "legacy-weighted/1"}}

            return Result()

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._open_runtime",
        lambda _db_path, **_kwargs: FakeRuntime(),
    )

    off = SeamLocomoAdapter(db_path=str(tmp_path))
    assert off.answer("scope", "What happened?").retrieval_trace is None
    assert observed == [False]

    observed.clear()
    on = SeamLocomoAdapter(db_path=str(tmp_path), record_retrieval_trace=True)
    answer = on.answer("scope", "What happened?")
    assert observed == [True]
    assert answer.retrieval_trace == {"fusion": {"policy": "legacy-weighted/1"}}


def test_runner_persists_trace_and_excludes_it_from_integrity():
    """The trace reaches the case record but never the reproducibility hash.

    The trace carries wall-clock latency, so including it would make two
    byte-identical retrieval runs hash differently.
    """
    case = BenchmarkCase(
        case_id="c1",
        conversation=(),
        question="q?",
        gold_answer="a",
        category="1",
    )
    trace = {"fusion": {"policy": "mix"}, "latency_ms": {"total": 12.5}}

    def build(with_trace):
        return _score_case(
            case=case,
            answer=AdapterAnswer(
                retrieved_context="a",
                generated_answer="a",
                retrieval_trace=trace if with_trace else None,
            ),
            judge=None,
            save_context=False,
        )

    traced = build(True)
    assert traced["retrieval_trace"] == trace
    assert "retrieval_trace" not in build(False)

    # Same scores + same retrieval => same integrity hash regardless of trace.
    reports = [
        _build_report(
            adapter_name="seam",
            dataset_source="fixture",
            run_started_at="2026-07-30T00:00:00Z",
            elapsed=1.0,
            case_results=[dict(build(flag))],
        )
        for flag in (True, False)
    ]
    assert reports[0]["integrity_hash"] == reports[1]["integrity_hash"]

    # The exclusion is declared, not silent.
    assert "retrieval_trace" in reports[0]["integrity_hash_excludes"]
    assert "retrieval_trace" not in reports[1].get("integrity_hash_excludes", [])
