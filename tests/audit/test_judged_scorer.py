"""PAID judged LoCoMo scorer + paid-validation orchestration: mechanism only.

CI-safe: every test uses a fake/counting judge and a monkeypatched generator -
no answerer client, no judge client, no API call, no spend. The paid execution
path itself is operator-gated behind `seam improve validate --confirm-paid`
and is exercised only by the operator.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass

import pytest

from benchmarks.external.common.dataset import QUICKSTART_FIXTURE_PATH, load_locomo_cases
from benchmarks.external.common.judge import JudgeVerdict
from benchmarks.external.common.types import BenchmarkCase, ConversationTurn
from benchmarks.external.locomo.judged_scorer import (
    JudgedLocomoScorer,
    VALIDATION_PASSES,
    build_locomo_holdout_scorer,
    estimate_locomo_paid_validation,
)
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.cli import run_cli
from seam_runtime.retrieval import RetrievalFlags
from seam_runtime.self_improve import ScoreReport
from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, HOLDOUT, assign_one
from tools.h2.paid_validation import run_paid_validation


class FakeJudge:
    """Free deterministic stand-in: correct iff the gold appears in the answer."""

    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = 0

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        self.calls += 1
        verdict = "correct" if gold.lower() in pred.lower() else "incorrect"
        return JudgeVerdict(verdict, 1.0 if verdict == "correct" else 0.0,
                            "fake", self.name, self.model)


class FlakyJudge(FakeJudge):
    """Fails the first call, then behaves like FakeJudge."""

    def __init__(self, failures: int = 1):
        super().__init__()
        self.failures = failures

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        if self.failures > 0:
            self.failures -= 1
            self.calls += 1
            raise RuntimeError("transient judge failure")
        return super().score(question=question, gold=gold, pred=pred)


TURNS = (
    ConversationTurn(speaker="Ana", text="The project deadline is Friday, March 7."),
    ConversationTurn(speaker="Ben", text="We store everything in Postgres."),
    ConversationTurn(speaker="Ana", text="The standup moved to 9:30 am."),
)

CASES = [
    BenchmarkCase(case_id="conv-j::q0", conversation=TURNS,
                  question="When is the project deadline?", gold_answer="Friday", category="1"),
    BenchmarkCase(case_id="conv-j::q1", conversation=TURNS,
                  question="What database do they use?", gold_answer="Postgres", category="2"),
]


def _build_adapter(tmp_path, generate):
    adapter = SeamLocomoAdapter(db_path=str(tmp_path / "loc"), keep_db=True, answerer=None)
    adapter.reset("conv-j")
    for turn in TURNS:
        adapter.ingest_turn("conv-j", turn)
    # Bypass the paid client: mark the adapter as generating and substitute a
    # deterministic generator with the production signature.
    adapter._answerer = "test"
    adapter._generate_answer = generate
    return adapter


def test_judged_scorer_scores_and_restores_flags(tmp_path):
    def generate(question, context, diag_out=None):
        return "Friday" if "deadline" in question else "MySQL"

    adapter = _build_adapter(tmp_path, generate)
    judge = FakeJudge()
    scorer = JudgedLocomoScorer(
        adapter=adapter, judge=judge,
        cases_by_scope=OrderedDict({"conv-j": CASES}),
    )
    rt = adapter._runtime("conv-j")
    previous = rt._retrieval_flags

    report = scorer.score(None, flags=RetrievalFlags())

    assert isinstance(report, ScoreReport)
    assert report.scorer == "locomo_judged"
    assert report.n == 2
    assert report.per_case == {"conv-j::q0": 1.0, "conv-j::q1": 0.0}
    assert report.aggregate == pytest.approx(0.5)
    assert report.per_category == {"1": 1.0, "2": 0.0}
    assert judge.calls == 2
    assert scorer.last_run == {
        "verdict_counts": {"correct": 1, "incorrect": 1},
        "judge_calls": 2,
        "judge_retries": 0,
        "empty_answers": 0,
    }
    # flag override is restored after the pass
    assert rt._retrieval_flags is previous
    adapter.close()


def test_context_budget_applied_to_adapter_during_pass_and_restored(tmp_path):
    """The fix: score() applies flags.context_budget to the adapter's char-trim
    budget for the pass (so a 'broad' candidate actually feeds the wider context,
    not the same trimmed window as compact), and restores it after. Without this
    the judged compact-vs-broad A/B is confounded."""
    seen = {}

    def generate(question, context, diag_out=None):
        seen["budget_during_pass"] = adapter.budget
        return "Friday"

    adapter = _build_adapter(tmp_path, generate)
    original_budget = adapter.budget
    scorer = JudgedLocomoScorer(
        adapter=adapter, judge=FakeJudge(),
        cases_by_scope=OrderedDict({"conv-j": CASES[:1]}),
    )
    scorer.score(None, flags=RetrievalFlags(context_budget=60000))
    assert seen["budget_during_pass"] == 60000  # applied during the pass
    assert adapter.budget == original_budget    # restored after
    adapter.close()


def test_context_budget_none_leaves_adapter_budget_unchanged(tmp_path):
    """A baseline candidate (context_budget=None) must not touch the trim."""
    seen = {}

    def generate(question, context, diag_out=None):
        seen["budget_during_pass"] = adapter.budget
        return "Friday"

    adapter = _build_adapter(tmp_path, generate)
    original_budget = adapter.budget
    scorer = JudgedLocomoScorer(
        adapter=adapter, judge=FakeJudge(),
        cases_by_scope=OrderedDict({"conv-j": CASES[:1]}),
    )
    scorer.score(None, flags=RetrievalFlags())  # context_budget=None
    assert seen["budget_during_pass"] == original_budget  # unchanged during pass
    assert adapter.budget == original_budget              # and after
    adapter.close()


def test_empty_answer_scores_zero_without_judge_call(tmp_path):
    adapter = _build_adapter(tmp_path, lambda question, context, diag_out=None: "")
    judge = FakeJudge()
    scorer = JudgedLocomoScorer(
        adapter=adapter, judge=judge,
        cases_by_scope=OrderedDict({"conv-j": CASES}),
    )
    report = scorer.score(None, flags=RetrievalFlags())
    assert report.aggregate == 0.0
    assert judge.calls == 0  # no paying the judge to confirm an empty answer
    assert scorer.last_run["empty_answers"] == 2
    assert scorer.last_run["verdict_counts"] == {"incorrect": 2}
    adapter.close()


def test_judge_transient_failure_retried_then_hard_failure_raises(tmp_path):
    adapter = _build_adapter(tmp_path, lambda question, context, diag_out=None: "Friday")
    one_case = OrderedDict({"conv-j": CASES[:1]})

    flaky = FlakyJudge(failures=1)
    scorer = JudgedLocomoScorer(adapter=adapter, judge=flaky,
                                cases_by_scope=one_case, judge_retries=1)
    report = scorer.score(None, flags=RetrievalFlags())
    assert report.per_case == {"conv-j::q0": 1.0}
    assert scorer.last_run["judge_retries"] == 1

    dead = FlakyJudge(failures=99)
    scorer_dead = JudgedLocomoScorer(adapter=adapter, judge=dead,
                                     cases_by_scope=one_case, judge_retries=1)
    with pytest.raises(RuntimeError, match="conv-j::q0"):
        scorer_dead.score(None, flags=RetrievalFlags())
    adapter.close()


def test_build_holdout_scorer_validates_before_any_side_effect():
    # invalid answerer fails before the (nonexistent) dataset is even opened
    with pytest.raises(ValueError, match="generating answerer"):
        build_locomo_holdout_scorer("/nonexistent/locomo.json", answerer="none")
    # judge 'none' is the free tier's job
    with pytest.raises(ValueError, match="real judge"):
        build_locomo_holdout_scorer("/nonexistent/locomo.json",
                                    answerer="openai", judge="none")


def test_build_holdout_scorer_filters_to_holdout_split(tmp_path):
    cases = load_locomo_cases(QUICKSTART_FIXTURE_PATH)
    expected = [
        c.case_id for c in cases
        if assign_one(c.case_id, salt=DEFAULT_SALT, ratio=DEFAULT_RATIO) == HOLDOUT
    ]
    if not expected:
        pytest.fail("quickstart fixture has no holdout cases; pick a bigger fixture")
    adapter, scorer = build_locomo_holdout_scorer(
        str(QUICKSTART_FIXTURE_PATH),
        judge_instance=FakeJudge(),
        db_path=str(tmp_path / "loc"),
        keep_db=True,
    )
    try:
        scored_ids = [c.case_id for group in scorer.cases_by_scope.values() for c in group]
        assert scored_ids == expected
    finally:
        adapter.close()


def test_estimate_counts_without_ingesting():
    estimate = estimate_locomo_paid_validation(str(QUICKSTART_FIXTURE_PATH), split=None)
    assert estimate["cases"] == 10
    assert estimate["scopes"] == 3
    assert estimate["passes"] == VALIDATION_PASSES
    assert estimate["answerer_calls_max"] == VALIDATION_PASSES * 10
    assert estimate["judge_calls_max"] == VALIDATION_PASSES * 10
    assert estimate["total_paid_calls_max"] == 2 * VALIDATION_PASSES * 10

    holdout = estimate_locomo_paid_validation(str(QUICKSTART_FIXTURE_PATH))
    assert holdout["split"] == "holdout"
    assert 0 < holdout["cases"] < 10


@dataclass
class _ScriptedScorer:
    """Scorer protocol stand-in returning scripted aggregates per pass."""

    aggregates: list
    name: str = "scripted"

    def __post_init__(self):
        self.flags_seen = []
        self.last_run = {"judge_calls": 1}

    def score(self, runtime, flags=None) -> ScoreReport:
        self.flags_seen.append(flags)
        return ScoreReport(scorer=self.name, aggregate=self.aggregates[len(self.flags_seen) - 1],
                           n=4, per_category={"1": 0.5}, per_case={})


def test_run_paid_validation_verdicts():
    improved = run_paid_validation(
        _ScriptedScorer([0.50, 0.60]), None,
        candidate_flags=RetrievalFlags(w_lexical=1.1),
    )
    assert improved["verdict"] == "improved"
    assert improved["delta"] == pytest.approx(0.10)
    assert improved["baseline"]["aggregate"] == pytest.approx(0.50)
    assert improved["candidate"]["aggregate"] == pytest.approx(0.60)
    assert improved["candidate_flags"]["w_lexical"] == pytest.approx(1.1)

    regressed = run_paid_validation(
        _ScriptedScorer([0.50, 0.40]), None,
        candidate_flags=RetrievalFlags(semantic_zero_no_vector=True),
    )
    assert regressed["verdict"] == "regressed"

    noise = run_paid_validation(
        _ScriptedScorer([0.50, 0.51]), None,
        candidate_flags=RetrievalFlags(w_lexical=1.1),
    )
    assert noise["verdict"] == "within-noise"


def test_run_paid_validation_skips_candidate_pass_when_equal_to_baseline():
    scorer = _ScriptedScorer([0.50, 0.99])
    report = run_paid_validation(scorer, None, candidate_flags=RetrievalFlags())
    assert report["verdict"] == "no-candidate-state"
    assert report["candidate"] is None
    assert len(scorer.flags_seen) == 1  # second (paid) pass skipped


def test_cli_validate_dry_run_makes_no_paid_path(tmp_path, capsys):
    """Without --confirm-paid the CLI prints the estimate and never builds an
    adapter, a client, or ingests a conversation."""
    db = str(tmp_path / "s.db")
    run_cli(["--db", db, "improve", "validate",
             "--locomo-dataset", str(QUICKSTART_FIXTURE_PATH), "--split", "all"])
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["cases"] == 10
    assert out["total_paid_calls_max"] == 40
    assert "confirm-paid" in out["note"]


def test_cli_validate_rejects_bad_flags_json(tmp_path, capsys):
    db = str(tmp_path / "s.db")
    run_cli(["--db", db, "improve", "validate",
             "--locomo-dataset", str(QUICKSTART_FIXTURE_PATH),
             "--flags", '{"not_a_flag": 1}'])
    out = json.loads(capsys.readouterr().out)
    assert "invalid --flags" in out["error"]
