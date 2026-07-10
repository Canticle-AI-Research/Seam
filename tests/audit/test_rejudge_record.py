"""Regression tests for the PAID re-judge replay harness (PR 2 of the
cat1/cat3 -> 0.80 program, HISTORY#371 follow-up).

All tests exercise the dry-run / merge / judge-1-vs-2 machinery with no
network calls and no spend. The paid ``rejudge()`` path is exercised with a
stub Judge injected via monkeypatch, never a real provider client.
"""
from __future__ import annotations

import json

from benchmarks.external.common.judge import (
    DEFAULT_JUDGE_PROMPT,
    JUDGE_PROMPT_V2,
    JudgeVerdict,
)
from tools.h2 import rejudge_record as rr


def _write_record(tmp_path, name, cases):
    path = tmp_path / name
    path.write_text(json.dumps({"run": {}, "totals": {}, "cases": cases}))
    return str(path)


def _case(case_id, **overrides):
    base = {
        "case_id": case_id,
        "category": "1",
        "question": "What is the capital of France?",
        "gold_answer": "Paris",
        "generated_answer": "Paris",
        "verdict": "correct",
        "judge_score": 1.0,
        "judge_rationale": "matches gold",
        "judge_model": "gpt-4o-mini",
        "judge": {"prompt_tokens": 150, "completion_tokens": 20, "cost_usd": 0.0001},
    }
    base.update(overrides)
    return base


def test_load_cases_later_record_overrides_by_case_id(tmp_path):
    """Mirrors the real token-budget-fix reconciliation: a later record's rows
    for the same case_id replace the earlier record's rows."""
    main = _write_record(tmp_path, "main.json", [
        _case("c1", generated_answer=""),  # the "stuck" empty answer
        _case("c2"),
    ])
    fix = _write_record(tmp_path, "fix.json", [
        _case("c1", generated_answer="Paris", verdict="correct", judge_score=1.0),
    ])
    merged = rr._load_cases([main, fix])
    assert list(merged.keys()) == ["c1", "c2"]  # first-appearance order preserved
    assert merged["c1"].generated_answer == "Paris"  # overridden, not the stuck empty
    assert merged["c2"].generated_answer == "Paris"


def test_prompt_char_delta_is_positive_and_deterministic():
    delta = rr._prompt_char_delta("judge/2")
    assert delta > 0
    # judge/1 vs itself is zero
    assert rr._prompt_char_delta("judge/1") == 0
    # deterministic: recomputing gives the same value
    assert rr._prompt_char_delta("judge/2") == delta


def test_estimate_rejudge_cost_no_client_no_network(tmp_path, monkeypatch):
    """The dry-run estimate must work with zero credentials in the environment
    -- proof that no judge client is ever constructed on this path."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cases = rr._load_cases([_write_record(tmp_path, "r.json", [
        _case("c1"), _case("c2", generated_answer=""),  # one empty -> skipped
    ])])
    estimate = rr.estimate_rejudge_cost(cases, judge_model="gpt-4o-mini", prompt_version="judge/2")
    assert estimate["dry_run"] is True
    assert estimate["record_cases_total"] == 2
    assert estimate["cases_to_rejudge"] == 1  # c2's empty answer is never judged
    assert estimate["cases_skipped_empty_answer"] == 1
    assert estimate["max_estimated_cost_usd"] is not None
    assert estimate["max_estimated_cost_usd"] > 0
    # full-pass projection includes the stored judge/1 base tokens, not just the delta
    assert estimate["max_estimated_total_input_tokens"] >= estimate["stored_judge1_tokens_used_as_base"]["prompt_total"]


def test_estimate_unknown_model_returns_none_cost(tmp_path):
    cases = rr._load_cases([_write_record(tmp_path, "r.json", [_case("c1")])])
    estimate = rr.estimate_rejudge_cost(cases, judge_model="mystery-model-9000")
    assert estimate["max_estimated_cost_usd"] is None  # never fabricated


class _StubRejudgeJudge:
    """A fake Judge that flips 'Paris' -> correct/grounded and everything else
    -> incorrect, so verdict-change detection is exercised deterministically."""
    name = "stub"

    def __init__(self, model=None, prompt_version="judge/2"):
        self.model = model
        self.prompt_version = prompt_version
        self.last_groundedness = None

    def score(self, *, question, gold, pred):
        if pred.strip().lower() == gold.strip().lower():
            self.last_groundedness = "grounded"
            return JudgeVerdict("correct", 1.0, "matches gold", self.name, self.model)
        self.last_groundedness = "contradicts"
        return JudgeVerdict("incorrect", 0.0, "does not match", self.name, self.model)


def test_rejudge_preserves_original_alongside_new(tmp_path, monkeypatch):
    """The original judge/1 verdict must be preserved unchanged alongside the
    new judge/2 verdict -- this is a replay, not an overwrite."""
    monkeypatch.setattr(rr, "build_judge", lambda name, model, **kw: _StubRejudgeJudge(model, **kw))
    cases = rr._load_cases([_write_record(tmp_path, "r.json", [
        _case("c1", verdict="incorrect", judge_score=0.0, generated_answer="Paris"),  # v1 was wrong, v2 fixes it
        _case("c2", verdict="correct", judge_score=1.0, generated_answer="London",
               gold_answer="Paris", question="What is the capital of France?"),  # stays wrong either way
    ])])
    report = rr.rejudge(cases, judge_name="openai", judge_model="gpt-4o-mini", prompt_version="judge/2")
    assert report["n_cases"] == 2
    rows = {r["case_id"]: r for r in report["cases"]}
    c1 = rows["c1"]
    assert c1["original"]["verdict"] == "incorrect"       # preserved, untouched
    assert c1["original"]["prompt_version"] == "judge/1"
    assert c1["rejudged"]["verdict"] == "correct"          # new verdict, judge/2
    assert c1["rejudged"]["groundedness"] == "grounded"
    assert c1["verdict_changed"] is True

    c2 = rows["c2"]
    assert c2["original"]["verdict"] == "correct"
    assert c2["rejudged"]["verdict"] == "incorrect"
    assert c2["verdict_changed"] is True
    assert report["n_verdicts_changed"] == 2


def test_rejudge_empty_answer_skips_judge_call_certain_incorrect(tmp_path, monkeypatch):
    """Mirrors JudgedLocomoScorer: an empty generated answer is certain-incorrect
    and must never trigger a judge call."""
    calls = []
    class _NeverCalledJudge(_StubRejudgeJudge):
        def score(self, *, question, gold, pred):
            calls.append(pred)
            return super().score(question=question, gold=gold, pred=pred)
    monkeypatch.setattr(rr, "build_judge", lambda name, model, **kw: _NeverCalledJudge(model, **kw))
    cases = rr._load_cases([_write_record(tmp_path, "r.json", [
        _case("c1", generated_answer=""),
    ])])
    report = rr.rejudge(cases, judge_name="openai", judge_model="gpt-4o-mini")
    assert calls == []  # judge never invoked for the empty answer
    row = report["cases"][0]
    assert row["rejudged"]["verdict"] == "incorrect"
    assert row["rejudged"]["groundedness"] == "na"


def test_judge_prompt_v2_contains_alias_and_groundedness_instructions():
    """Pin the prompt-2 contract fixes so a future edit can't silently drop them."""
    assert "LeBron" in JUDGE_PROMPT_V2
    assert "groundedness" in JUDGE_PROMPT_V2
    assert "must NOT lower the verdict" in JUDGE_PROMPT_V2
    # judge/1 must remain byte-identical to before (no accidental cross-edit)
    assert "groundedness" not in DEFAULT_JUDGE_PROMPT
