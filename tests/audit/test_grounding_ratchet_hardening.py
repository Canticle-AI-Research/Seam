from __future__ import annotations

import math
from argparse import Namespace

from seam_runtime.nl_extract import ground_extraction
from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.self_improve import (
    STRICT_RATCHET_FAMILIES,
    RatchetGateEvidence,
    ScoreReport,
    strict_ratchet_decision,
)
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_loop import run_improvement_cycle
from tools.h2.improvement_review import cmd_approve, compute_apply_plan


def _passing_non_evaluation_gates() -> list[RatchetGateEvidence]:
    return [
        RatchetGateEvidence(
            name=f"{family}:verified",
            family=family,
            passed=True,
            refs=(f"probe:{family}:1",),
        )
        for family in ("integrity", "trust", "temporal", "provenance", "holdout")
    ]


def _all_passing_gates() -> list[RatchetGateEvidence]:
    return [
        RatchetGateEvidence(
            name=f"{family}:verified",
            family=family,
            passed=True,
            refs=(f"probe:{family}:1",),
        )
        for family in sorted(STRICT_RATCHET_FAMILIES)
    ]


def test_grounding_requires_contiguous_ordered_spans_and_records_offsets() -> None:
    source = (
        "Mina deployed Orion on Tuesday in Helsinki because tests passed "
        "using the release tool, then monitored Orion."
    )
    extraction = ground_extraction(
        {
            "claims": [
                {
                    "subject": "mina",  # normalized case returns source text
                    "relation": "deployed",
                    "object": "Orion",
                    "when": "Tuesday",
                    "where": "Helsinki",
                    "why": "because tests passed",
                    "how": "using the release tool",
                    "then": "then monitored Orion",
                },
                {
                    "subject": "Mina",
                    "relation": "deployed",
                    "object": "tool release",  # same tokens, wrong order
                },
            ]
        },
        source,
    )

    assert len(extraction.claims) == 1
    claim = extraction.claims[0]
    assert claim.subject == "Mina"
    assert {span.field for span in claim.source_spans} == {
        "subject", "relation", "object", "when", "where", "why", "how", "then",
    }
    for span in claim.source_spans:
        assert source[span.start:span.end] == span.text
    assert claim.span_for("who").text == "Mina"
    assert claim.span_for("what").text == "Orion"
    assert claim.span_for("how").text == "using the release tool"


def test_grounding_drops_scattered_required_fields_and_ungrounded_facets() -> None:
    source = "Mina used the release safety tool after tests passed."
    extraction = ground_extraction(
        {
            "claims": [
                {
                    "subject": "Mina",
                    "relation": "used",
                    "object": "release tool",  # cannot jump over "safety"
                },
                {
                    "subject": "Mina",
                    "relation": "used",
                    "object": "the release safety tool",
                    "why": "tests release",  # scattered/reordered: omit facet
                },
            ]
        },
        source,
    )

    assert len(extraction.claims) == 1
    assert extraction.claims[0].obj == "the release safety tool"
    assert extraction.claims[0].why is None


def test_strict_ratchet_rejects_malformed_duplicate_unknown_and_holdout_gates() -> None:
    gates = _all_passing_gates()
    gates.extend(
        [
            RatchetGateEvidence(
                name="aggregate:verified",
                family="aggregate",
                passed=True,
                refs=("duplicate",),
            ),
            RatchetGateEvidence(
                name="mystery",
                family="unknown",
                passed=True,
                refs=("case:1",),
            ),
            RatchetGateEvidence(
                name="nonfinite",
                family="trust",
                passed=True,
                candidate=math.inf,
                refs=("case:2",),
            ),
            RatchetGateEvidence(
                name="blank-reference",
                family="temporal",
                passed=True,
                refs=("",),
            ),
            RatchetGateEvidence(
                name="holdout:leak",
                family="holdout",
                passed=True,
                refs=("case:holdout",),
                holdout_violation=True,
            ),
        ]
    )

    decision = strict_ratchet_decision(gates)
    assert decision.status == "rejected"
    assert "duplicate:aggregate:verified" in decision.failed_gates
    assert "invalid:mystery:unknown-family:unknown" in decision.failed_gates
    assert "invalid:nonfinite:non-finite-candidate" in decision.failed_gates
    assert "invalid:blank-reference:blank-refs" in decision.failed_gates
    assert "holdout-violation:holdout:leak" in decision.failed_gates


class _ImprovingScorer:
    name = "synthetic"

    def score(self, runtime, flags=None):  # noqa: ARG002
        improved = bool(flags and flags.bm25_all_kinds)
        return ScoreReport(
            scorer=self.name,
            aggregate=0.9 if improved else 0.5,
            n=1,
            per_category={"one": 0.9 if improved else 0.5},
        )


def test_cycle_rejects_missing_ratchet_families_and_never_auto_applies(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "rejected.db")
    report = run_improvement_cycle(
        None,
        store,
        [_ImprovingScorer()],
        auto_approve=True,
    )

    assert report["proposed"]["ratchet"]["status"] == "rejected"
    assert report["applied"] is False
    [proposal] = store.iter_improvement_proposals()
    assert proposal["latest_status"] == "rejected"
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()


def test_cycle_full_pass_stays_pending_until_operator_approval(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "pending.db")
    report = run_improvement_cycle(
        None,
        store,
        [_ImprovingScorer()],
        auto_approve=True,
        ratchet_gates=_passing_non_evaluation_gates(),
    )

    assert report["proposed"]["ratchet"]["status"] == "pending_approval"
    assert report["applied"] is False
    [proposal] = store.iter_improvement_proposals()
    assert proposal["latest_status"] == "pending"
    assert compute_apply_plan(store)[0] == {}

    args = Namespace(
        db=str(tmp_path / "pending.db"),
        proposal_id=proposal["proposal_id"],
        reason="operator reviewed strict ratchet evidence",
        actor="operator",
        json=True,
    )
    assert cmd_approve(args) == 0
    desired, _applied, skipped = compute_apply_plan(store)
    assert desired["bm25_all_kinds"][0] is True
    assert skipped == []


def test_operator_cannot_approve_a_ratchet_rejected_cycle(tmp_path, capsys) -> None:
    store = SQLiteStore(tmp_path / "blocked.db")
    run_improvement_cycle(None, store, [_ImprovingScorer()])
    [proposal] = store.iter_improvement_proposals()
    args = Namespace(
        db=str(tmp_path / "blocked.db"),
        proposal_id=proposal["proposal_id"],
        reason="attempted override",
        actor="operator",
        json=True,
    )
    assert cmd_approve(args) == 2
    assert "failed its strict ratchet" in capsys.readouterr().err
    assert store.iter_improvement_proposals()[0]["latest_status"] == "rejected"
