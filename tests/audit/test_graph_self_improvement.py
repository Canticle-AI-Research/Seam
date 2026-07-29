from __future__ import annotations

import pytest

from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.self_improve import (
    REQUIRED_GRAPH_HOLDOUT_MOTIFS,
    GraphProbe,
    GraphProbeScorer,
    candidate_levers,
    split_graph_probes,
)
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_loop import run_improvement_cycle
from tools.h2.improvement_review import compute_apply_plan


class _GraphRuntime:
    def __init__(self, expected_by_query):
        self.expected_by_query = expected_by_query

    def knowledge_graph(self, *, query, semantic_seeds, **_options):
        nodes = []
        if semantic_seeds > 0:
            for node_id, assertable in self.expected_by_query[query]:
                nodes.append({"id": node_id, "assertable": assertable})
        return {"nodes": nodes}


def _probe(case_id: str, motif: str, *, action: str = "retrieve") -> GraphProbe:
    return GraphProbe(
        case_id=case_id,
        motif=motif,
        query=f"query {case_id}",
        expected_node_ids=(f"node:{case_id}",),
        expected_action=action,
        rationale="test",
    )


def test_graph_policy_candidates_are_visible_only_to_graph_safe_scorers():
    baseline = RetrievalFlags()
    assert not any(
        key.startswith("graph_semantic")
        for candidate in candidate_levers(baseline)
        for key in candidate.change
    )
    graph_candidates = candidate_levers(baseline, graph_policy_levers=True)
    assert [candidate.change for candidate in graph_candidates if "graph_semantic_seeds" in candidate.change] == [
        {"graph_semantic_seeds": 4},
        {"graph_semantic_seeds": 8},
        {"graph_semantic_seeds": 16},
        {"graph_semantic_seeds": 32},
    ]


def test_graph_probe_split_is_disjoint_and_preserves_required_holdout_motifs():
    probes = [
        _probe(f"{motif}-{index}", motif)
        for motif in [*REQUIRED_GRAPH_HOLDOUT_MOTIFS, "multi_hop"]
        for index in range(5)
    ]
    development, holdout = split_graph_probes(
        probes, sample_per_split=12
    )
    assert {probe.case_id for probe in development}.isdisjoint(
        probe.case_id for probe in holdout
    )
    assert REQUIRED_GRAPH_HOLDOUT_MOTIFS <= {
        probe.motif for probe in holdout
    }


def test_graph_ratchet_reports_an_unusable_holdout_split():
    scorer = GraphProbeScorer(
        [_probe("dev", "multi_hop")],
        [_probe("holdout", "provenance")],
    )
    with pytest.raises(ValueError, match="missing required motifs"):
        scorer.ratchet_gates(
            None,
            RetrievalFlags(),
            RetrievalFlags(graph_semantic_seeds=4),
            regress_tol=0.005,
        )


def test_graph_probe_scorer_rejects_empty_expected_ids():
    scorer = GraphProbeScorer(
        [
            GraphProbe(
                case_id="empty",
                motif="multi_hop",
                query="empty",
                expected_node_ids=(),
            )
        ],
        [],
    )
    with pytest.raises(ValueError, match="must not be empty"):
        scorer.score(_GraphRuntime({"empty": []}), RetrievalFlags())


def test_graph_probe_cycle_proposes_approves_and_applies_real_graph_policy(tmp_path):
    dev = [_probe("dev-multihop", "multi_hop")]
    holdout = [
        _probe("holdout-trust", "unsupported", action="abstain_or_qualify"),
        _probe("holdout-temporal", "temporal"),
        _probe("holdout-provenance", "provenance"),
    ]
    expected = {
        probe.query: [
            (probe.expected_node_ids[0], probe.expected_action != "abstain_or_qualify")
        ]
        for probe in [*dev, *holdout]
    }
    runtime = _GraphRuntime(expected)
    store = SQLiteStore(tmp_path / "graph-improve.db")
    scorer = GraphProbeScorer(dev, holdout)

    report = run_improvement_cycle(runtime, store, [scorer])
    assert report["graph_policy_levers"] is True
    assert report["proposed"]["change"] == {"graph_semantic_seeds": 4}
    assert report["proposed"]["ratchet"]["status"] == "pending_approval"
    proposal_id = report["proposed"]["proposal_id"]

    store.record_proposal_decision(
        proposal_id=proposal_id,
        status="approved",
        actor="operator",
        reason="all graph dev and holdout gates passed",
    )
    desired, applied, skipped = compute_apply_plan(store)
    assert skipped == []
    assert applied == [
        {
            "flag": "graph_semantic_seeds",
            "value": 4,
            "proposal_id": proposal_id,
        }
    ]
    store.replace_retrieval_flag_state(desired)
    effective = load_retrieval_flags(store, env={})
    assert effective.graph_semantic_seeds == 4
    assert scorer.score(runtime, effective).aggregate == 1.0
