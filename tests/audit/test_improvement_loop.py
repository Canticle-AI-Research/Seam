"""H2 self-improvement loop: proposer core + the orchestration cycle.

Uses synthetic scorers (which ignore the runtime and key off the flags / store
state) so the propose -> apply -> confirm -> revert machinery is exercised
deterministically without ingesting a corpus. The real free scorers
(SelfProbeScorer, a future free-LoCoMo scorer) implement the same protocol.
"""

from __future__ import annotations

import pytest

from benchmarks.external.common.adjudication import (
    AdjudicatedCase,
    AdjudicatedScorer,
    AdjudicationOverlay,
)
from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.self_improve import (
    Candidate,
    RatchetGateEvidence,
    ScoreReport,
    candidate_levers,
    evaluate_candidates,
    select_best_improvement,
)
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_loop import run_improvement_cycle


def _store(tmp_path):
    return SQLiteStore(tmp_path / "loop.db")


def _strict_non_evaluation_gates():
    return [
        RatchetGateEvidence(
            name=f"{family}:verified",
            family=family,
            passed=True,
            refs=(f"probe:{family}:1",),
        )
        for family in ("integrity", "trust", "temporal", "provenance", "holdout")
    ]


class _FlagFnScorer:
    """Aggregate is a pure function of flags; optional per-category map."""

    def __init__(self, fn, name="fake", cat_fn=None):
        self.name = name
        self._fn = fn
        self._cat_fn = cat_fn

    def score(self, runtime, flags=None):
        return ScoreReport(
            scorer=self.name,
            aggregate=self._fn(flags),
            n=10,
            per_category=self._cat_fn(flags) if self._cat_fn else {},
        )


# ---- candidate_levers --------------------------------------------------------


def test_candidate_levers_covers_booleans_and_weights():
    cands = candidate_levers(RetrievalFlags())
    changes = [c.change for c in cands]
    # boolean/enum levers present (baseline has them off)
    assert {"semantic_zero_no_vector": True} in changes
    assert {"bm25_all_kinds": True} in changes
    assert {"fusion": "rrf"} in changes
    # each weight channel perturbed up and down
    fields = {k for c in cands for k in c.change}
    assert {"w_lexical", "w_semantic", "w_graph", "w_temporal"} <= fields
    # no negative weights proposed
    for c in cands:
        for k, v in c.change.items():
            if k.startswith("w_"):
                assert v >= 0


def test_candidate_levers_skips_already_set_levers():
    cands = candidate_levers(RetrievalFlags(bm25_all_kinds=True, fusion="rrf"))
    changes = [c.change for c in cands]
    assert {"bm25_all_kinds": True} not in changes
    assert {"fusion": "rrf"} not in changes
    assert {"semantic_zero_no_vector": True} in changes


def test_candidate_levers_profile_knobs_are_opt_in():
    # Default OFF: the profile knobs (search_top_k/context_budget) are not proposed
    # unless profile_levers=True, because a bigger budget games self-probe/recall.
    base = RetrievalFlags()
    assert not any(c.label.startswith("profile=") for c in candidate_levers(base))
    cands = candidate_levers(base, profile_levers=True)
    profiles = {c.label: c.change for c in cands if c.label.startswith("profile=")}
    assert profiles["profile=compact"] == {"search_top_k": 100, "context_budget": 8000}
    assert profiles["profile=broad"] == {"search_top_k": 300, "context_budget": 60000}


def test_candidate_levers_profile_skips_current_preset():
    # Already at the compact knee -> only the other preset is a candidate.
    base = RetrievalFlags(search_top_k=100, context_budget=8000)
    labels = {c.label for c in candidate_levers(base, profile_levers=True)}
    assert "profile=compact" not in labels
    assert "profile=broad" in labels


def test_candidate_levers_answer_policies_are_opt_in_and_versioned():
    base = RetrievalFlags()
    assert not any("conversation_adapter" in c.change for c in candidate_levers(base))
    cands = candidate_levers(base, answer_policy_levers=True)
    changes = [candidate.change for candidate in cands]
    assert {"conversation_adapter": "conversation/1"} in changes
    assert {"inference_policy": "inference/high-confidence/1"} in changes


# ---- evaluate_candidates -----------------------------------------------------


def test_per_category_regression_blocks_improvement():
    base = RetrievalFlags()
    # aggregate improves under bm25_all, but category "B" regresses -> not an improvement
    def agg(fl):
        return 0.9 if fl.bm25_all_kinds else 0.5

    def cats(fl):
        return {"A": (0.9 if fl.bm25_all_kinds else 0.5), "B": (0.2 if fl.bm25_all_kinds else 0.5)}

    scorer = _FlagFnScorer(agg, cat_fn=cats)
    cand = Candidate("bm25", {"bm25_all_kinds": True}, RetrievalFlags(bm25_all_kinds=True))
    evals = evaluate_candidates(None, [scorer], [cand], base)
    assert evals[0].is_improvement is False
    assert "B" in evals[0].reason


def test_select_best_picks_largest_total_gain():
    base = RetrievalFlags()
    s = _FlagFnScorer(lambda fl: 0.5 + (0.3 if fl.bm25_all_kinds else 0.0) + (0.1 if fl.semantic_zero_no_vector else 0.0))
    cands = [
        Candidate("bm25", {"bm25_all_kinds": True}, RetrievalFlags(bm25_all_kinds=True)),
        Candidate("sz", {"semantic_zero_no_vector": True}, RetrievalFlags(semantic_zero_no_vector=True)),
    ]
    best = select_best_improvement(evaluate_candidates(None, [s], cands, base))
    assert best.candidate.change == {"bm25_all_kinds": True}


# ---- run_improvement_cycle ---------------------------------------------------


def test_cycle_proposes_but_auto_approve_cannot_bypass_operator(tmp_path):
    store = _store(tmp_path)
    scorer = _FlagFnScorer(lambda fl: 0.9 if fl.bm25_all_kinds else 0.5)

    report = run_improvement_cycle(
        None,
        store,
        [scorer],
        auto_approve=True,
        ratchet_gates=_strict_non_evaluation_gates(),
    )

    assert report["proposed"] is not None
    assert report["proposed"]["change"] == {"bm25_all_kinds": True}
    assert report["proposed"]["ratchet"]["status"] == "pending_approval"
    assert report["applied"] is False
    assert report["reverted"] is False
    assert load_retrieval_flags(store, env={}).bm25_all_kinds is False
    assert store.iter_improvement_proposals()[0]["latest_status"] == "pending"


class _ProfileSafeScorer:
    """A dilution-sensitive fake (profile_safe=True): aggregate is a function of
    flags so the loop's profile-lever gating can be exercised model-free."""

    profile_safe = True

    def __init__(self, fn, name="aq"):
        self.name = name
        self._fn = fn

    def score(self, runtime, flags=None):
        return ScoreReport(scorer=self.name, aggregate=self._fn(flags), n=10)


class _AnswerPolicySafeScorer(_ProfileSafeScorer):
    answer_policy_safe = True


def test_cycle_profile_levers_active_when_all_scorers_profile_safe(tmp_path):
    store = _store(tmp_path)
    # prefers the compact knee (top_k=100); only proposable when profile levers fire
    safe = _ProfileSafeScorer(lambda fl: 0.9 if fl.search_top_k == 100 else 0.5)

    report = run_improvement_cycle(None, store, [safe], auto_approve=False)

    assert report["profile_levers"] is True
    assert report["proposed"]["change"] == {"search_top_k": 100, "context_budget": 8000}


def test_cycle_profile_levers_off_when_any_scorer_unsafe(tmp_path):
    store = _store(tmp_path)
    safe = _ProfileSafeScorer(lambda fl: 0.9 if fl.search_top_k == 100 else 0.5)
    unsafe = _FlagFnScorer(lambda fl: 0.7)  # no profile_safe attr -> treated unsafe

    report = run_improvement_cycle(None, store, [safe, unsafe], auto_approve=False)

    # A single profile-unsafe scorer disables the profile knobs (anti-gaming),
    # so the compact knee is never proposed even though `safe` would reward it.
    assert report["profile_levers"] is False
    assert report["proposed"] is None


def test_cycle_answer_policy_levers_require_answer_quality_scorers(tmp_path):
    store = _store(tmp_path)
    safe = _AnswerPolicySafeScorer(
        lambda flags: 0.9 if flags.conversation_adapter == "conversation/1" else 0.5
    )
    report = run_improvement_cycle(
        None,
        store,
        [safe],
        auto_approve=True,
        ratchet_gates=_strict_non_evaluation_gates(),
    )
    assert report["answer_policy_levers"] is True
    assert report["proposed"]["change"] == {"conversation_adapter": "conversation/1"}
    assert load_retrieval_flags(store, env={}).conversation_adapter == "off"
    [proposal] = store.iter_improvement_proposals()
    assert proposal["kind"] == "answer_policy"
    assert proposal["latest_status"] == "pending"


def test_category_floor_progress_can_select_small_aggregate_gain():
    base = RetrievalFlags()

    def aggregate(flags):
        return 0.503 if flags.conversation_adapter == "conversation/1" else 0.5

    def categories(flags):
        return {
            "cat1": 0.79 if flags.conversation_adapter == "conversation/1" else 0.77,
            "cat3": 0.6,
        }

    scorer = _FlagFnScorer(aggregate, cat_fn=categories)
    candidate = Candidate(
        "conversation",
        {"conversation_adapter": "conversation/1"},
        RetrievalFlags(conversation_adapter="conversation/1"),
    )
    [evaluation] = evaluate_candidates(
        None,
        [scorer],
        [candidate],
        base,
        category_floors={"cat1": 0.8, "cat3": 0.8},
    )
    assert evaluation.is_improvement is True
    assert evaluation.floor_progress == pytest.approx(0.02)
    assert "category-floor progress" in evaluation.reason


def test_category_floor_human_alias_matches_numeric_locomo_category():
    base = RetrievalFlags()
    scorer = _FlagFnScorer(
        lambda flags: 0.503 if flags.conversation_adapter == "conversation/1" else 0.5,
        cat_fn=lambda flags: {
            "1": 0.79 if flags.conversation_adapter == "conversation/1" else 0.77,
            "3": 0.6,
        },
    )
    candidate = Candidate(
        "conversation",
        {"conversation_adapter": "conversation/1"},
        RetrievalFlags(conversation_adapter="conversation/1"),
    )
    [evaluation] = evaluate_candidates(
        None,
        [scorer],
        [candidate],
        base,
        category_floors={"cat1": 0.8, "cat3": 0.8},
    )
    assert evaluation.floor_progress == pytest.approx(0.02)


def test_adjudicated_view_does_not_hide_raw_regression():
    class RawScorer:
        name = "raw"
        profile_safe = True
        answer_policy_safe = True

        def score(self, runtime, flags=None):  # noqa: ARG002
            candidate = flags.conversation_adapter == "conversation/1"
            per_case = {"a": 0.0 if candidate else 1.0, "b": 0.8 if candidate else 0.0}
            return ScoreReport(
                scorer=self.name,
                aggregate=sum(per_case.values()) / 2,
                n=2,
                per_category={"1": sum(per_case.values()) / 2},
                per_case=per_case,
            )

    scorer = AdjudicatedScorer(
        RawScorer(),
        AdjudicationOverlay(
            version="review/1",
            cases={
                "a": AdjudicatedCase(
                    case_id="a",
                    category="1",
                    score=0.0,
                    disposition="judge-correction",
                )
            },
        ),
        category_by_case={"a": "1", "b": "1"},
    )
    candidate = Candidate(
        "conversation",
        {"conversation_adapter": "conversation/1"},
        RetrievalFlags(conversation_adapter="conversation/1"),
    )
    [evaluation] = evaluate_candidates(
        None,
        [scorer],
        [candidate],
        RetrievalFlags(),
    )
    assert evaluation.deltas[scorer.name] == pytest.approx(0.4)
    assert evaluation.view_deltas[scorer.name]["raw"] == pytest.approx(-0.1)
    assert evaluation.is_improvement is False
    assert "/raw" in evaluation.reason


def test_cycle_scores_baseline_once(tmp_path):
    store = _store(tmp_path)

    class CountingScorer(_AnswerPolicySafeScorer):
        def __init__(self):
            super().__init__(lambda flags: 0.5)
            self.default_calls = 0

        def score(self, runtime, flags=None):
            if flags == RetrievalFlags():
                self.default_calls += 1
            return super().score(runtime, flags=flags)

    scorer = CountingScorer()
    run_improvement_cycle(None, store, [scorer], auto_approve=False)
    assert scorer.default_calls == 1


def test_cycle_no_headroom_proposes_nothing(tmp_path):
    store = _store(tmp_path)
    flat = _FlagFnScorer(lambda fl: 0.7)  # constant: nothing beats baseline

    report = run_improvement_cycle(None, store, [flat], auto_approve=True)

    assert report["proposed"] is None
    assert report["applied"] is False
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()


def test_cycle_propose_only_does_not_apply(tmp_path):
    store = _store(tmp_path)
    scorer = _FlagFnScorer(lambda fl: 0.9 if fl.bm25_all_kinds else 0.5)

    report = run_improvement_cycle(None, store, [scorer], auto_approve=False)

    assert report["proposed"] is not None
    assert report["applied"] is False
    # proposal written but pending; nothing applied
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()


class _RevertScorer:
    """Improvement appears during candidate eval (no applied state yet) but the
    post-apply confirm regresses - keyed on whether apply has written flag state,
    so it is deterministic without relying on call counts. Exercises the ratchet."""

    name = "revert"

    def __init__(self, store):
        self._store = store

    def score(self, runtime, flags=None):
        applied = bool(self._store.iter_retrieval_flag_state())
        if applied:
            agg = 0.0  # post-apply measurement did not hold -> regression
        else:
            agg = 0.9 if (flags and flags.bm25_all_kinds) else 0.5
        return ScoreReport(scorer=self.name, aggregate=agg, n=10)


def test_cycle_auto_approve_never_mutates_applied_state(tmp_path):
    store = _store(tmp_path)
    scorer = _RevertScorer(store)

    report = run_improvement_cycle(None, store, [scorer], auto_approve=True)

    assert report["proposed"] is not None      # it looked like an improvement
    assert report["reverted"] is False
    assert report["applied"] is False
    assert report["proposed"]["ratchet"]["status"] == "rejected"
    # No pre-approval mutation occurs, so no revert is needed.
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()


def test_candidate_levers_include_temporal_and_conversation_v2():
    base = RetrievalFlags()
    assert not any("temporal_policy" in c.change for c in candidate_levers(base))
    cands = candidate_levers(base, answer_policy_levers=True)
    changes = [candidate.change for candidate in cands]
    assert {"temporal_policy": "temporal/1"} in changes
    assert {"conversation_adapter": "conversation/2"} in changes
    # already-applied levers are not re-proposed
    applied = RetrievalFlags(temporal_policy="temporal/1")
    re_changes = [
        c.change for c in candidate_levers(applied, answer_policy_levers=True)
    ]
    assert {"temporal_policy": "temporal/1"} not in re_changes
