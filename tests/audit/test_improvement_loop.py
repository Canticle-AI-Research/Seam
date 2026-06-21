"""H2 self-improvement loop: proposer core + the orchestration cycle.

Uses synthetic scorers (which ignore the runtime and key off the flags / store
state) so the propose -> apply -> confirm -> revert machinery is exercised
deterministically without ingesting a corpus. The real free scorers
(SelfProbeScorer, a future free-LoCoMo scorer) implement the same protocol.
"""

from __future__ import annotations

from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.self_improve import (
    Candidate,
    ScoreReport,
    candidate_levers,
    evaluate_candidates,
    select_best_improvement,
)
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_loop import run_improvement_cycle


def _store(tmp_path):
    return SQLiteStore(tmp_path / "loop.db")


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


def test_cycle_proposes_and_auto_applies_improvement(tmp_path):
    store = _store(tmp_path)
    scorer = _FlagFnScorer(lambda fl: 0.9 if fl.bm25_all_kinds else 0.5)

    report = run_improvement_cycle(None, store, [scorer], auto_approve=True)

    assert report["proposed"] is not None
    assert report["proposed"]["change"] == {"bm25_all_kinds": True}
    assert report["applied"] is True
    assert report["reverted"] is False
    assert load_retrieval_flags(store, env={}).bm25_all_kinds is True


class _ProfileSafeScorer:
    """A dilution-sensitive fake (profile_safe=True): aggregate is a function of
    flags so the loop's profile-lever gating can be exercised model-free."""

    profile_safe = True

    def __init__(self, fn, name="aq"):
        self.name = name
        self._fn = fn

    def score(self, runtime, flags=None):
        return ScoreReport(scorer=self.name, aggregate=self._fn(flags), n=10)


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


def test_cycle_auto_reverts_on_post_apply_regression(tmp_path):
    store = _store(tmp_path)
    scorer = _RevertScorer(store)

    report = run_improvement_cycle(None, store, [scorer], auto_approve=True)

    assert report["proposed"] is not None      # it looked like an improvement
    assert report["reverted"] is True           # ...but confirm regressed
    assert report["applied"] is False
    # flag state backed out -> baseline restored
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()
