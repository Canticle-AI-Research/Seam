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

import json

import pytest

from benchmarks.external.common.runner import _build_report, _score_case
from benchmarks.external.common.types import AdapterAnswer, BenchmarkCase
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, SearchResult


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


@pytest.fixture
def runtime_factory():
    """Create transient runtimes and close every one even after assertion failure."""

    from seam_runtime.runtime import SeamRuntime

    runtimes = []

    def create(path):
        runtime = SeamRuntime(path, allow_pgvector_env=False)
        runtimes.append(runtime)
        return runtime

    try:
        yield create
    finally:
        for runtime in reversed(runtimes):
            runtime.close()

_FORBIDDEN_TRACE_KEYS = frozenset(
    {
        "answer",
        "api_key",
        "attrs",
        "authorization",
        "body",
        "completion",
        "content",
        "context",
        "cookie",
        "credential",
        "credentials",
        "filter",
        "filters",
        "generated_answer",
        "gold",
        "gold_answer",
        "graph_at",
        "graph_path",
        "ids",
        "kinds",
        "lens",
        "message",
        "namespace",
        "normalized_query",
        "object",
        "object_text",
        "password",
        "path",
        "payload",
        "predicate",
        "prompt",
        "query",
        "raw_text",
        "rationale",
        "reason",
        "reasons",
        "record",
        "records",
        "refresh_token",
        "retrieved_context",
        "secret",
        "secrets",
        "session",
        "source_ref",
        "scope",
        "subject",
        "text",
        "token",
    }
)
_SECRET_TRACE_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


def _trace_privacy_violations(
    value,
    *,
    sentinels: tuple[str, ...],
    path: str = "$",
) -> list[str]:
    """Return structural violation paths without echoing content-bearing values."""

    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized_key = str(key).casefold().replace("-", "_")
            if normalized_key in _FORBIDDEN_TRACE_KEYS or any(
                fragment in normalized_key
                for fragment in _SECRET_TRACE_KEY_FRAGMENTS
            ):
                violations.append(f"forbidden-key:{child_path}")
            violations.extend(
                _trace_privacy_violations(
                    child,
                    sentinels=sentinels,
                    path=child_path,
                )
            )
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            violations.extend(
                _trace_privacy_violations(
                    child,
                    sentinels=sentinels,
                    path=f"{path}[{index}]",
                )
            )
    elif isinstance(value, str) and any(sentinel in value for sentinel in sentinels):
        violations.append(f"sentinel-value:{path}")
    return violations


def test_trace_does_not_change_selection_or_order(tmp_path, runtime_factory):
    """include_trace must be inert on ranking.

    This is the property the ablation depends on: a traced arm and an untraced
    arm must produce identical ranked output for the same corpus and query.
    """
    rt = runtime_factory(tmp_path / "trace.db")
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
    assert [candidate.to_dict() for candidate in traced.candidates] == [
        candidate.to_dict() for candidate in untraced.candidates
    ]


def test_trace_does_not_change_internal_graph_paths(tmp_path, runtime_factory):
    rt = runtime_factory(tmp_path / "trace-graph-path.db")
    rt.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:alpha",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Alpha", "entity_type": "concept"},
                ),
                MIRLRecord(
                    id="ent:beta",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Beta", "entity_type": "concept"},
                ),
                MIRLRecord(
                    id="rel:alpha-beta",
                    kind=RecordKind.REL,
                    ns="work",
                    scope="thread",
                    attrs={
                        "src": "ent:alpha",
                        "predicate": "connects",
                        "dst": "ent:beta",
                    },
                ),
            ]
        )
    )

    kwargs = {
        "query": "Alpha",
        "ns": "work",
        "scope": "thread",
        "budget": 10,
        "mode": "graph",
        "graph_hops": 1,
    }
    untraced = rt.retrieve(**kwargs)
    traced = rt.retrieve(**kwargs, include_trace=True)

    assert any(candidate.graph_path for candidate in untraced.candidates)
    assert [candidate.to_dict() for candidate in traced.candidates] == [
        candidate.to_dict() for candidate in untraced.candidates
    ]


def test_exported_search_trace_is_recursively_content_free(
    tmp_path, runtime_factory
):
    rt = runtime_factory(tmp_path / "trace-privacy.db")
    private_corpus = [
        *CORPUS,
        "TRACE_SECRET_SENTINEL belongs only in a canonical record.",
    ]
    _ingest(rt, private_corpus)
    query = "TRACE_QUERY_SENTINEL TRACE_SECRET_SENTINEL Melanie cat"

    for mode in ("vector", "graph", "hybrid", "mix"):
        trace = rt.retrieve(
            query,
            budget=5,
            include_raw=True,
            include_trace=True,
            mode=mode,
        ).trace

        assert trace is not None
        assert trace["schema"] == "seam-retrieval-search-trace/1"
        assert trace["plan"]["mode"] == mode
        assert trace["plan"]["budget"] == 5
        assert trace["plan"]["candidate_budget"] == 5
        assert trace["plan"]["include_raw"] is True
        assert trace["plan"]["semantic_graph_seeding"] is False
        assert len(trace["fusion"]["candidate_set_sha256"]) == 64
        assert set(trace["leg_counts"]) == set(trace["legs"])
        for leg_name, hits in trace["legs"].items():
            assert all(set(hit) == {"rank", "record_id", "score"} for hit in hits)
            assert [hit["rank"] for hit in hits] == list(
                range(1, len(hits) + 1)
            )
            assert all(
                isinstance(hit["score"], (int, float))
                and not isinstance(hit["score"], bool)
                for hit in hits
            )
            assert trace["leg_counts"][leg_name]["retained"] == len(hits)

        violations = _trace_privacy_violations(
            trace,
            sentinels=(
                "TRACE_QUERY_SENTINEL",
                "TRACE_SECRET_SENTINEL",
                *private_corpus,
            ),
        )
        assert not violations, (
            f"trace privacy violations at paths only: {violations}"
        )


def test_trace_carries_per_leg_attribution(tmp_path, runtime_factory):
    """The trace must name the ranking policy and carry per-leg detail."""
    rt = runtime_factory(tmp_path / "trace.db")
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


def test_structural_only_mix_matches_hybrid_and_reports_content_free_graph_skip(
    tmp_path, runtime_factory
):
    rt = runtime_factory(tmp_path / "structural-only.db")
    _ingest(rt, CORPUS)
    query = "What is Melanie's cat called?"

    hybrid = rt.retrieve(
        query,
        budget=10,
        include_raw=True,
        include_trace=True,
        mode="hybrid",
    )
    mix = rt.retrieve(
        query,
        budget=10,
        include_raw=True,
        include_trace=True,
        mode="mix",
    )

    assert [candidate.to_dict() for candidate in mix.candidates] == [
        candidate.to_dict() for candidate in hybrid.candidates
    ]
    assert mix.trace["legs"]["graph"] == []
    assert mix.trace["graph_skipped_reason"] == "no_semantic_relation_edges"
    assert "graph_skipped_reason" not in hybrid.trace

    skip_receipt = json.dumps(
        {"graph_skipped_reason": mix.trace["graph_skipped_reason"]},
        sort_keys=True,
    )
    assert query not in skip_receipt
    assert all(text not in skip_receipt for text in CORPUS)


def test_search_ir_trace_reports_legacy_weighted_policy(tmp_path, runtime_factory):
    """The control arm must be self-identifying in its own artifact."""
    rt = runtime_factory(tmp_path / "trace.db")
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
