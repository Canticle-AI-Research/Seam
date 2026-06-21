"""H2 self-improvement loop: the orchestration that ties the pieces together.

One ``run_improvement_cycle`` is the whole front-to-back loop:

1. resolve the current baseline flags (defaults < persisted applied-state),
2. generate candidate lever changes (``self_improve.candidate_levers``),
3. evaluate each against the supplied free scorers at fixed eval budget
   (``self_improve.evaluate_candidates`` - the no-regression gate),
4. write a proposal for the best genuine improvement (or nothing),
5. optionally (``auto_approve``) approve + apply it through the #289 reconcile,
   then RE-MEASURE and AUTO-REVERT if the applied state regressed any scorer.

The cycle is scorer-agnostic: the same machinery runs the always-on FREE loop
(self-probe + free-LoCoMo scorers) and an operator-triggered PAID validation
(judged scorers implementing the same ``Scorer`` protocol added to the list).
Free scorers never require a paid call; paid scorers are opt-in. The reversible
apply makes step 5 a ratchet - applied state can only move scores up or flat,
because anything that regresses is backed out in the same cycle.

This lives in tools/ (not seam_runtime/) because it orchestrates runtime +
scorers + the proposal store + the apply CLI; the pure evaluation logic it
calls lives in ``seam_runtime.self_improve``.
"""

from __future__ import annotations

from typing import Sequence

from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import (
    DEFAULT_NOISE_MARGIN,
    DEFAULT_REGRESS_TOL,
    Scorer,
    candidate_levers,
    evaluate_candidates,
    select_best_improvement,
)
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_review import compute_apply_plan


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
) -> dict:
    """Run one improvement cycle. Returns a structured report; writes at most one
    proposal, and (only under ``auto_approve``) applies/reverts it.

    ``runtime`` and ``store`` should share the same SQLite database so the
    applied flag state the cycle writes is what ``runtime.search_ir`` reads.
    """
    if not scorers:
        raise ValueError("at least one scorer is required")

    baseline = load_retrieval_flags(store)
    base_reports = {s.name: s.score(runtime, flags=baseline) for s in scorers}
    # The answerer-aware profile knobs (search_top_k/context_budget) are proposed
    # ONLY when every scorer is dilution-sensitive (profile_safe). A bigger budget
    # mechanically inflates the self-probe and context_recall scorers, so if either
    # is present the profile levers stay off (they'd be gamed); the answer-quality
    # / judged scorers set profile_safe=True, letting the loop tune the knee to the
    # configured answerer without that hazard.
    profile_levers = bool(scorers) and all(getattr(s, "profile_safe", False) for s in scorers)
    candidates = candidate_levers(baseline, weight_step=weight_step, profile_levers=profile_levers)
    evaluations = evaluate_candidates(
        runtime, scorers, candidates, baseline,
        noise_margin=noise_margin, regress_tol=regress_tol,
    )
    best = select_best_improvement(evaluations)

    report: dict = {
        "baseline": {name: round(r.aggregate, 6) for name, r in base_reports.items()},
        "n_candidates": len(candidates),
        "profile_levers": profile_levers,
        "proposed": None,
        "applied": False,
        "reverted": False,
    }

    if best is None:
        report["reason"] = "no candidate improved beyond noise without regression"
        return report

    proposal_id = store.write_improvement_proposal(
        kind="ranking_weight",
        summary=f"self-improve: {best.candidate.label}",
        rationale=best.reason,
        proposed_change={"flags": best.candidate.change},
    )
    report["proposed"] = {
        "proposal_id": proposal_id,
        "change": best.candidate.change,
        "deltas": {k: round(v, 6) for k, v in best.deltas.items()},
        "reason": best.reason,
    }

    if not auto_approve:
        return report

    store.record_proposal_decision(
        proposal_id=proposal_id, status="approved", actor=actor,
        reason="auto: dev-validated, no regression",
    )
    desired, _applied, _skipped = compute_apply_plan(store)
    store.replace_retrieval_flag_state(desired)
    report["applied"] = True

    # Ratchet: re-measure the full reconciled applied state; revert if any scorer
    # regressed past tolerance against the pre-cycle baseline.
    applied_flags = load_retrieval_flags(store)
    for scorer in scorers:
        post = scorer.score(runtime, flags=applied_flags)
        if post.aggregate < base_reports[scorer.name].aggregate - regress_tol:
            store.record_proposal_decision(
                proposal_id=proposal_id, status="rejected", actor=actor,
                reason=f"auto-revert: {scorer.name} regressed post-apply",
            )
            desired2, _a, _s = compute_apply_plan(store)
            store.replace_retrieval_flag_state(desired2)
            report["applied"] = False
            report["reverted"] = True
            report["revert_reason"] = f"{scorer.name} regressed post-apply"
            break

    return report
