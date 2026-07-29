"""H2 self-improvement loop: the orchestration that ties the pieces together.

One ``run_improvement_cycle`` is the whole front-to-back loop:

1. resolve the current baseline flags (defaults < persisted applied-state),
2. generate candidate lever changes (``self_improve.candidate_levers``),
3. evaluate each against the supplied free scorers at fixed eval budget
   (``self_improve.evaluate_candidates`` - the no-regression gate),
4. write a proposal for the best genuine improvement (or nothing),
5. run the strict multi-family ratchet and persist its evidence with the
   proposal: failures are append-only rejections and passes remain pending for
   an explicit operator approval.

The cycle is scorer-agnostic: the same machinery runs the always-on FREE loop
(self-probe + free-LoCoMo scorers) and an operator-triggered PAID validation
(judged scorers implementing the same ``Scorer`` protocol added to the list).
Free scorers never require a paid call; paid scorers are opt-in. ``auto_approve``
remains accepted for CLI compatibility but cannot bypass the operator gate.

This lives in tools/ (not seam_runtime/) because it orchestrates runtime +
scorers + the proposal store + the apply CLI; the pure evaluation logic it
calls lives in ``seam_runtime.self_improve``.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import (
    DEFAULT_NOISE_MARGIN,
    DEFAULT_REGRESS_TOL,
    RatchetGateEvidence,
    Scorer,
    candidate_levers,
    evaluate_candidates,
    score_report_views,
    select_best_improvement,
    strict_ratchet_decision,
)
from seam_runtime.storage import SQLiteStore


def run_improvement_cycle(
    runtime,
    store: SQLiteStore,
    scorers: Sequence[Scorer],
    *,
    auto_approve: bool = False,
    actor: str = "self_improve",
    noise_margin: float = DEFAULT_NOISE_MARGIN,
    regress_tol: float = DEFAULT_REGRESS_TOL,
    weight_step: float = 0.10,
    category_floors: Mapping[str, float] | None = None,
    ratchet_gates: Sequence[RatchetGateEvidence] = (),
) -> dict:
    """Run one improvement cycle and write at most one auditable proposal.

    ``runtime`` and ``store`` should share the same SQLite database so the
    applied flag state the cycle writes is what ``runtime.search_ir`` reads.
    Aggregate and category evidence are derived from the candidate evaluation.
    Callers must supply the integrity, trust, temporal, provenance, and holdout
    families through ``ratchet_gates``. Missing families reject the proposal;
    a full pass remains pending for an operator to approve and apply separately.
    """
    if not scorers:
        raise ValueError("at least one scorer is required")
    floors = dict(category_floors or {})
    invalid_keys = [key for key in floors if not isinstance(key, str) or not key]
    if invalid_keys:
        raise ValueError(f"category floor names must be non-empty strings: {invalid_keys!r}")
    invalid_floors = {
        key: value
        for key, value in floors.items()
        if isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= value <= 1.0
    }
    if invalid_floors:
        raise ValueError(f"category floors must be within [0, 1]: {invalid_floors!r}")

    baseline = load_retrieval_flags(store)
    base_reports = {}
    base_views = {}
    for scorer in scorers:
        report, views = score_report_views(scorer, runtime, baseline)
        base_reports[scorer.name] = report
        base_views[scorer.name] = views
    # The answerer-aware profile knobs (search_top_k/context_budget) are proposed
    # ONLY when every scorer is dilution-sensitive (profile_safe). A bigger budget
    # mechanically inflates the self-probe and context_recall scorers, so if either
    # is present the profile levers stay off (they'd be gamed); the answer-quality
    # / judged scorers set profile_safe=True, letting the loop tune the knee to the
    # configured answerer without that hazard.
    profile_levers = bool(scorers) and all(getattr(s, "profile_safe", False) for s in scorers)
    answer_policy_levers = bool(scorers) and all(
        getattr(s, "answer_policy_safe", False) for s in scorers
    )
    graph_policy_levers = bool(scorers) and all(
        getattr(s, "graph_policy_safe", False) for s in scorers
    )
    candidates = candidate_levers(
        baseline,
        weight_step=weight_step,
        profile_levers=profile_levers,
        answer_policy_levers=answer_policy_levers,
        graph_policy_levers=graph_policy_levers,
    )
    evaluations = evaluate_candidates(
        runtime, scorers, candidates, baseline,
        noise_margin=noise_margin, regress_tol=regress_tol,
        category_floors=floors,
        baseline_reports=base_reports,
        baseline_views=base_views,
    )
    best = select_best_improvement(evaluations)

    report: dict = {
        "baseline": {name: round(r.aggregate, 6) for name, r in base_reports.items()},
        "baseline_views": {
            scorer_name: {
                view_name: {
                    "aggregate": round(view.aggregate, 6),
                    "per_category": {
                        category: round(value, 6)
                        for category, value in sorted(view.per_category.items())
                    },
                }
                for view_name, view in sorted(views.items())
            }
            for scorer_name, views in base_views.items()
        },
        "n_candidates": len(candidates),
        "profile_levers": profile_levers,
        "answer_policy_levers": answer_policy_levers,
        "graph_policy_levers": graph_policy_levers,
        "category_floors": dict(sorted(floors.items())),
        "proposed": None,
        "applied": False,
        "reverted": False,
    }

    if best is None:
        report["reason"] = "no candidate improved beyond noise without regression"
        return report

    if {"graph_semantic_seeds", "graph_semantic_min_score"} & best.candidate.change.keys():
        proposal_kind = "graph_policy"
    elif {"conversation_adapter", "inference_policy"} & best.candidate.change.keys():
        proposal_kind = "answer_policy"
    else:
        proposal_kind = "ranking_weight"
    derived_gates: list[RatchetGateEvidence] = []
    for scorer_name, delta in sorted(best.deltas.items()):
        baseline_value = base_reports[scorer_name].aggregate
        derived_gates.append(RatchetGateEvidence(
            name=f"aggregate:{scorer_name}",
            family="aggregate",
            passed=delta >= -regress_tol,
            baseline=baseline_value,
            candidate=baseline_value + delta,
            threshold=baseline_value - regress_tol,
            details="candidate aggregate must not regress beyond tolerance",
            refs=(f"scorer:{scorer_name}",),
        ))
    category_refs: list[str] = []
    category_passed = True
    for scorer_name, deltas in sorted(best.category_deltas.items()):
        for category, delta in sorted(deltas.items()):
            category_refs.append(f"scorer:{scorer_name}:category:{category}")
            if delta < -regress_tol:
                category_passed = False
    derived_gates.append(RatchetGateEvidence(
        name="category:no-regression",
        family="category",
        passed=category_passed,
        threshold=-regress_tol,
        details="every measured category must remain within regression tolerance",
        refs=tuple(category_refs) or ("evaluation:no-category-breakdown",),
    ))
    scorer_gates: list[RatchetGateEvidence] = []
    for scorer in scorers:
        gate_builder = getattr(scorer, "ratchet_gates", None)
        if callable(gate_builder):
            scorer_gates.extend(
                gate_builder(
                    runtime,
                    baseline,
                    best.candidate.flags,
                    regress_tol=regress_tol,
                )
            )
    ratchet = strict_ratchet_decision(
        [*derived_gates, *scorer_gates, *ratchet_gates]
    )
    proposed_change = {
        "flags": best.candidate.change,
        "ratchet": ratchet.to_dict(),
    }
    proposal_id = store.write_improvement_proposal(
        kind=proposal_kind,
        summary=f"self-improve: {best.candidate.label}",
        rationale=best.reason,
        proposed_change=proposed_change,
        holdout_violation=any(gate.holdout_violation for gate in ratchet.evidence),
    )
    report["proposed"] = {
        "proposal_id": proposal_id,
        "change": best.candidate.change,
        "deltas": {k: round(v, 6) for k, v in best.deltas.items()},
        "score_view_deltas": {
            scorer_name: {
                view_name: round(value, 6)
                for view_name, value in sorted(views.items())
            }
            for scorer_name, views in best.view_deltas.items()
        },
        "floor_progress": round(best.floor_progress, 6),
        "reason": best.reason,
        "ratchet": ratchet.to_dict(),
    }

    report["auto_approve_requested"] = bool(auto_approve)
    if ratchet.status == "rejected":
        store.record_proposal_decision(
            proposal_id=proposal_id,
            status="rejected",
            actor=actor,
            reason="strict ratchet rejected: " + ", ".join(ratchet.failed_gates),
        )
    elif auto_approve:
        report["approval_required"] = (
            "auto-approve cannot bypass the strict ratchet operator gate"
        )

    return report
