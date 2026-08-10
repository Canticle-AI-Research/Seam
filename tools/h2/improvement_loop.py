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

import hashlib
import inspect
import os
from dataclasses import asdict, is_dataclass
from typing import Mapping, Sequence

from seam_runtime.improvement_experiments import EXPERIMENT_METHOD, json_sha256
from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import (
    DEFAULT_NOISE_MARGIN,
    DEFAULT_REGRESS_TOL,
    CandidateEvaluation,
    RatchetGateEvidence,
    Scorer,
    ScoreReport,
    candidate_levers,
    evaluate_candidates,
    score_report_views,
    select_best_improvement,
    strict_ratchet_decision,
)
from seam_runtime.storage import SQLiteStore

MAX_EXPERIMENT_CANDIDATES = 128


def _source_sha256(value: object) -> str:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError):
        source = f"{getattr(value, '__module__', '')}:{getattr(value, '__qualname__', '')}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _case_id(value: object) -> str | None:
    case_id = getattr(value, "case_id", None)
    if not isinstance(case_id, str) or not case_id:
        return None
    return case_id


def _case_content_sha256(value: object) -> str:
    """Fingerprint case content without retaining its raw evaluator material."""

    if is_dataclass(value) and not isinstance(value, type):
        material: object = asdict(value)
    elif hasattr(value, "__dict__"):
        material = dict(vars(value))
    else:
        material = value
    try:
        return json_sha256(material)
    except (TypeError, ValueError):
        return hashlib.sha256(repr(material).encode("utf-8")).hexdigest()


def _scorer_case_contract(
    scorer: Scorer,
) -> tuple[tuple[str, ...], str, int, tuple[str, ...], str, int]:
    development: list[dict[str, str]] = []
    holdout: list[dict[str, str]] = []

    def add_cases(
        target: list[dict[str, str]], source: str, values: object
    ) -> None:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return
        for index, item in enumerate(values):
            target.append(
                {
                    "case_id": _case_id(item) or f"unbound:{index}",
                    "content_sha256": _case_content_sha256(item),
                    "source": source,
                }
            )

    for attribute in ("probes", "cases"):
        add_cases(development, attribute, getattr(scorer, attribute, ()))
    groups = getattr(scorer, "cases_by_scope", None)
    if isinstance(groups, Mapping):
        for scope, values in groups.items():
            add_cases(development, f"cases_by_scope:{scope}", values)
    add_cases(holdout, "holdout_probes", getattr(scorer, "holdout_probes", ()))

    def summarize(
        descriptors: list[dict[str, str]],
    ) -> tuple[tuple[str, ...], str, int]:
        ordered = sorted(
            descriptors,
            key=lambda item: (
                item["source"],
                item["case_id"],
                item["content_sha256"],
            ),
        )
        case_ids = tuple(
            sorted(
                {
                    item["case_id"]
                    for item in ordered
                    if not item["case_id"].startswith("unbound:")
                }
            )
        )
        return case_ids, json_sha256(ordered), len(ordered)

    development_ids, development_sha256, development_count = summarize(development)
    holdout_ids, holdout_sha256, holdout_count = summarize(holdout)
    return (
        development_ids,
        development_sha256,
        development_count,
        holdout_ids,
        holdout_sha256,
        holdout_count,
    )


def _scorer_contract(scorer: Scorer) -> dict[str, object]:
    (
        development,
        development_sha256,
        development_count,
        holdout,
        holdout_sha256,
        holdout_count,
    ) = _scorer_case_contract(scorer)
    implementation = f"{type(scorer).__module__}.{type(scorer).__qualname__}"
    budget = {
        name: value
        for name in ("budget", "limit", "hops")
        if isinstance((value := getattr(scorer, name, None)), int)
        and not isinstance(value, bool)
        and value >= 0
    }
    return {
        "name": scorer.name,
        "implementation": implementation,
        "implementation_sha256": _source_sha256(type(scorer)),
        "development_case_count": development_count,
        "development_case_ids_sha256": json_sha256(list(development)),
        "development_cases_sha256": development_sha256,
        "holdout_case_count": holdout_count,
        "holdout_case_ids_sha256": json_sha256(list(holdout)),
        "holdout_cases_sha256": holdout_sha256,
        "case_identity": (
            "pinned" if development_count or holdout_count else "unbound"
        ),
        "capabilities": {
            "answer_policy_safe": bool(getattr(scorer, "answer_policy_safe", False)),
            "graph_policy_safe": bool(getattr(scorer, "graph_policy_safe", False)),
            "profile_safe": bool(getattr(scorer, "profile_safe", False)),
        },
        "budget": budget,
    }


def _score_report_payload(report: ScoreReport) -> dict[str, object]:
    per_case = [
        {"case_id": case_id, "score": score}
        for case_id, score in sorted(report.per_case.items())
    ]
    return {
        "aggregate": report.aggregate,
        "n": report.n,
        "per_category": [
            {"category": category, "score": score}
            for category, score in sorted(report.per_category.items())
        ],
        "per_case": per_case,
        "per_case_sha256": json_sha256(per_case),
        "scorer": report.scorer,
    }


def _candidate_evaluation_payload(
    evaluation: CandidateEvaluation,
) -> dict[str, object]:
    return {
        "candidate": {
            "change": evaluation.candidate.change,
            "flags_sha256": json_sha256(asdict(evaluation.candidate.flags)),
            "label": evaluation.candidate.label,
        },
        "evaluation": {
            "category_deltas": [
                {
                    "categories": [
                        {"category": category, "delta": delta}
                        for category, delta in sorted(deltas.items())
                    ],
                    "scorer": scorer,
                }
                for scorer, deltas in sorted(evaluation.category_deltas.items())
            ],
            "deltas": [
                {"delta": delta, "scorer": scorer}
                for scorer, delta in sorted(evaluation.deltas.items())
            ],
            "floor_progress": evaluation.floor_progress,
            "is_improvement": evaluation.is_improvement,
            "reason": evaluation.reason,
            "reports": [
                _score_report_payload(report)
                for _, report in sorted(evaluation.reports.items())
            ],
            "views": [
                {
                    "reports": [
                        {
                            "report": _score_report_payload(report),
                            "view": name,
                        }
                        for name, report in sorted(views.items())
                    ],
                    "scorer": scorer,
                }
                for scorer, views in sorted(evaluation.report_views.items())
            ],
        },
    }


def _record_experiment_failure(
    store: SQLiteStore,
    experiment_id: str | None,
    *,
    phase: str,
    error: BaseException,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Best-effort terminal evidence that never masks the original failure."""

    if experiment_id is None:
        return
    payload: dict[str, object] = {
        "error_type": type(error).__name__,
        "phase": phase,
    }
    if extra:
        payload.update(extra)
    try:
        store.append_improvement_experiment_event(
            experiment_id=experiment_id,
            event_kind="failed",
            payload=payload,
        )
    except BaseException:
        pass


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
    record_experiment: bool = True,
    experiment_id: str | None = None,
    experiment_label: str | None = None,
    max_candidates: int | None = None,
    code_revision: str | None = None,
) -> dict:
    """Run one improvement cycle and write at most one auditable proposal.

    ``runtime`` and ``store`` should share the same SQLite database so the
    applied flag state the cycle writes is what ``runtime.search_ir`` reads.
    Aggregate and category evidence are derived from the candidate evaluation.
    Callers must supply the integrity, trust, temporal, provenance, and holdout
    families through ``ratchet_gates``. Missing families reject the proposal;
    a full pass remains pending for an operator to approve and apply separately.

    By default the cycle also records an immutable evaluator definition and an
    append-only event for the baseline, every candidate, any linked proposal,
    and the terminal outcome. Counterfactual evaluation never mutates applied
    retrieval flags.
    """
    if not scorers:
        raise ValueError("at least one scorer is required")
    scorer_names = [getattr(scorer, "name", None) for scorer in scorers]
    if any(not isinstance(name, str) or not name for name in scorer_names):
        raise ValueError("every scorer must have a non-empty string name")
    if len(set(scorer_names)) != len(scorer_names):
        raise ValueError("scorer names must be unique within an improvement cycle")
    if max_candidates is not None and (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= MAX_EXPERIMENT_CANDIDATES
    ):
        raise ValueError(
            f"max_candidates must be within [1, {MAX_EXPERIMENT_CANDIDATES}]"
        )
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
    base_reports: dict[str, ScoreReport] = {}
    base_views: dict[str, dict[str, ScoreReport]] = {}
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
    all_candidates = candidate_levers(
        baseline,
        weight_step=weight_step,
        profile_levers=profile_levers,
        answer_policy_levers=answer_policy_levers,
        graph_policy_levers=graph_policy_levers,
    )
    if max_candidates is None:
        if len(all_candidates) > MAX_EXPERIMENT_CANDIDATES:
            raise ValueError(
                "candidate space exceeds the production safety cap; "
                f"pass max_candidates within [1, {MAX_EXPERIMENT_CANDIDATES}] "
                "to select an explicit truncation boundary"
            )
        candidates = all_candidates
    else:
        candidates = all_candidates[:max_candidates]
    candidate_space_truncated = len(candidates) < len(all_candidates)
    scorer_contracts = [_scorer_contract(scorer) for scorer in scorers]
    thresholds = {
        "category_floors": dict(sorted(floors.items())),
        "noise_margin": noise_margin,
        "regress_tol": regress_tol,
        "weight_step": weight_step,
    }
    evaluator_contract = {
        "candidate_generator_sha256": _source_sha256(candidate_levers),
        "candidate_evaluator_sha256": _source_sha256(evaluate_candidates),
        "cycle_sha256": _source_sha256(run_improvement_cycle),
        "ratchet_sha256": _source_sha256(strict_ratchet_decision),
        "scorers": scorer_contracts,
        "thresholds": thresholds,
    }
    evaluator_sha256 = json_sha256(evaluator_contract)
    dataset_sha256 = json_sha256(
        [
            {
                "development_case_count": contract["development_case_count"],
                "development_case_ids_sha256": contract[
                    "development_case_ids_sha256"
                ],
                "development_cases_sha256": contract[
                    "development_cases_sha256"
                ],
                "holdout_case_count": contract["holdout_case_count"],
                "holdout_case_ids_sha256": contract["holdout_case_ids_sha256"],
                "holdout_cases_sha256": contract["holdout_cases_sha256"],
                "name": contract["name"],
            }
            for contract in scorer_contracts
        ]
    )
    baseline_sha256 = json_sha256(asdict(baseline))
    definition = {
        "baseline_flags_sha256": baseline_sha256,
        "budget": {
            "candidate_count": len(candidates),
            "candidate_space_count": len(all_candidates),
            "max_candidates": max_candidates,
            "truncated": candidate_space_truncated,
        },
        "candidate_space": [
            {
                "change": candidate.change,
                "flags_sha256": json_sha256(asdict(candidate.flags)),
                "label": candidate.label,
            }
            for candidate in candidates
        ],
        "code_revision": code_revision
        or os.environ.get("SEAM_BUILD_REVISION", "unreported"),
        "evaluator": evaluator_contract,
        "label": experiment_label or "",
        "method": EXPERIMENT_METHOD,
    }
    resolved_experiment_id = None
    if record_experiment:
        resolved_experiment_id = store.create_improvement_experiment(
            lane="retrieval-policy",
            evaluator_sha256=evaluator_sha256,
            dataset_sha256=dataset_sha256,
            baseline_sha256=baseline_sha256,
            definition=definition,
            experiment_id=experiment_id,
        )
    try:
        for scorer in scorers:
            scorer_report, views = score_report_views(scorer, runtime, baseline)
            base_reports[scorer.name] = scorer_report
            base_views[scorer.name] = views
    except BaseException as exc:
        _record_experiment_failure(
            store,
            resolved_experiment_id,
            phase="baseline_evaluation",
            error=exc,
        )
        raise
    if resolved_experiment_id is not None:
        try:
            store.append_improvement_experiment_event(
                experiment_id=resolved_experiment_id,
                event_kind="baseline_evaluated",
                payload={
                    "reports": [
                        _score_report_payload(scorer_report)
                        for _, scorer_report in sorted(base_reports.items())
                    ],
                    "views": [
                        {
                            "reports": [
                                {
                                    "report": _score_report_payload(view),
                                    "view": view_name,
                                }
                                for view_name, view in sorted(views.items())
                            ],
                            "scorer": scorer_name,
                        }
                        for scorer_name, views in sorted(base_views.items())
                    ],
                },
            )
        except BaseException as exc:
            _record_experiment_failure(
                store,
                resolved_experiment_id,
                phase="baseline_evidence",
                error=exc,
            )
            raise

    def record_candidate(evaluation: CandidateEvaluation) -> None:
        if resolved_experiment_id is not None:
            store.append_improvement_experiment_event(
                experiment_id=resolved_experiment_id,
                event_kind="candidate_evaluated",
                payload=_candidate_evaluation_payload(evaluation),
            )

    try:
        evaluations = evaluate_candidates(
            runtime,
            scorers,
            candidates,
            baseline,
            noise_margin=noise_margin,
            regress_tol=regress_tol,
            category_floors=floors,
            baseline_reports=base_reports,
            baseline_views=base_views,
            on_evaluated=record_candidate,
        )
    except BaseException as exc:
        _record_experiment_failure(
            store,
            resolved_experiment_id,
            phase="candidate_evaluation",
            error=exc,
        )
        raise
    best = select_best_improvement(evaluations)

    report: dict = {
        "experiment_id": resolved_experiment_id,
        "experiment_recorded": resolved_experiment_id is not None,
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
        "candidate_space_count": len(all_candidates),
        "candidate_space_truncated": candidate_space_truncated,
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
        if resolved_experiment_id is not None:
            try:
                store.append_improvement_experiment_event(
                    experiment_id=resolved_experiment_id,
                    event_kind="completed",
                    payload={
                        "evaluated_candidates": len(evaluations),
                        "outcome": "no_change",
                        "proposal_id": None,
                    },
                )
            except BaseException as exc:
                _record_experiment_failure(
                    store,
                    resolved_experiment_id,
                    phase="experiment_completion",
                    error=exc,
                )
                raise
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
    try:
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
    except BaseException as exc:
        _record_experiment_failure(
            store,
            resolved_experiment_id,
            phase="ratchet_evaluation",
            error=exc,
        )
        raise
    proposed_change = {
        "flags": best.candidate.change,
        "ratchet": ratchet.to_dict(),
    }
    evidence_case_ids = sorted(
        {
            case_id
            for scorer_report in base_reports.values()
            for case_id in scorer_report.per_case
        }
    )
    try:
        proposal_id = store.write_improvement_proposal(
            kind=proposal_kind,
            summary=f"self-improve: {best.candidate.label}",
            rationale=best.reason,
            evidence_case_ids=evidence_case_ids or None,
            proposed_change=proposed_change,
            holdout_violation=any(
                gate.holdout_violation for gate in ratchet.evidence
            ),
            extra=(
                {
                    "dataset_sha256": dataset_sha256,
                    "evaluator_sha256": evaluator_sha256,
                    "experiment_id": resolved_experiment_id,
                }
                if resolved_experiment_id is not None
                else None
            ),
        )
    except BaseException as exc:
        _record_experiment_failure(
            store,
            resolved_experiment_id,
            phase="proposal_write",
            error=exc,
        )
        raise
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
    try:
        if ratchet.status == "rejected":
            store.record_proposal_decision(
                proposal_id=proposal_id,
                status="rejected",
                actor=actor,
                reason="strict ratchet rejected: " + ", ".join(ratchet.failed_gates),
            )
            outcome = "rejected"
        else:
            outcome = "pending_approval"
            if auto_approve:
                report["approval_required"] = (
                    "auto-approve cannot bypass the strict ratchet operator gate"
                )
    except BaseException as exc:
        _record_experiment_failure(
            store,
            resolved_experiment_id,
            phase="proposal_decision",
            error=exc,
            extra={"proposal_id": proposal_id},
        )
        raise

    if resolved_experiment_id is not None:
        selected_flags_sha256 = json_sha256(asdict(best.candidate.flags))
        try:
            store.append_improvement_experiment_event(
                experiment_id=resolved_experiment_id,
                event_kind="proposal_created",
                payload={
                    "candidate_flags_sha256": selected_flags_sha256,
                    "proposal_id": proposal_id,
                    "proposal_kind": proposal_kind,
                    "ratchet": ratchet.to_dict(),
                },
            )
            store.append_improvement_experiment_event(
                experiment_id=resolved_experiment_id,
                event_kind="completed",
                payload={
                    "evaluated_candidates": len(evaluations),
                    "outcome": outcome,
                    "proposal_id": proposal_id,
                    "selected_candidate_flags_sha256": selected_flags_sha256,
                },
            )
        except BaseException as exc:
            _record_experiment_failure(
                store,
                resolved_experiment_id,
                phase="experiment_completion",
                error=exc,
                extra={"proposal_id": proposal_id},
            )
            raise

    return report
