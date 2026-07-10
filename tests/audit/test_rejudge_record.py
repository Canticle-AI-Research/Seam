"""Regression tests for the PAID re-judge replay harness (PR 2 of the
cat1/cat3 -> 0.80 program, HISTORY#371/#372 follow-up).

All tests exercise the dry-run / merge / provenance / budget-guard machinery
with no network calls and no spend. The paid ``rejudge()`` path is exercised
with a stub Judge injected via monkeypatch, never a real provider client.
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

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


def test_source_record_provenance_hashes_match_real_file_bytes(tmp_path):
    """Provenance must carry the EXACT sha256 of the input file bytes, not the
    parsed content -- so it can catch even a whitespace-only edit."""
    path = _write_record(tmp_path, "r.json", [_case("c1")])
    expected = hashlib.sha256(open(path, "rb").read()).hexdigest()
    prov = rr._source_record_provenance([path])
    assert prov == [{"path": path, "sha256": expected}]


def test_estimate_rejudge_cost_no_client_no_network(tmp_path, monkeypatch):
    """The dry-run estimate must work with zero credentials in the environment
    -- proof that no judge client is ever constructed on this path."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = _write_record(tmp_path, "r.json", [
        _case("c1"), _case("c2", generated_answer=""),  # one empty -> skipped
    ])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    estimate = rr.estimate_rejudge_cost(cases, source_records, judge_model="gpt-4o-mini", prompt_version="judge/2")
    assert estimate["dry_run"] is True
    assert estimate["record_cases_total"] == 2
    assert estimate["cases_to_rejudge"] == 1  # c2's empty answer is never judged
    assert estimate["cases_skipped_empty_answer"] == 1
    assert estimate["max_estimated_cost_usd"] is not None
    assert estimate["max_estimated_cost_usd"] > 0
    # full-pass projection includes the stored judge/1 base tokens, not just the delta
    assert estimate["max_estimated_total_input_tokens"] >= estimate["stored_judge1_tokens_used_as_base"]["prompt_total"]


def test_estimate_provenance_fields_present_and_correct(tmp_path):
    path = _write_record(tmp_path, "r.json", [_case("c1")])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    estimate = rr.estimate_rejudge_cost(
        cases, source_records, judge_name="openai", judge_model="gpt-4o-mini", prompt_version="judge/2"
    )
    prov = estimate["provenance"]
    assert prov["source_records"] == source_records
    assert prov["judge_name"] == "openai"
    assert prov["judge_model"] == "gpt-4o-mini"
    assert prov["prompt_version"] == "judge/2"
    assert prov["judge1_prompt_version"] == "judge/1"
    assert prov["max_cost_usd"] is None  # not spending yet
    # code_git_sha is either a short hex sha or None (no git available); both valid
    assert prov["code_git_sha"] is None or re.fullmatch(r"[0-9a-f]{7,40}", prov["code_git_sha"])
    # UTC timestamp is ISO-8601 and parseable
    assert prov["timestamp_utc"].endswith("+00:00") or prov["timestamp_utc"].endswith("Z")


def test_estimate_unknown_model_returns_none_cost(tmp_path):
    path = _write_record(tmp_path, "r.json", [_case("c1")])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    estimate = rr.estimate_rejudge_cost(cases, source_records, judge_model="mystery-model-9000")
    assert estimate["max_estimated_cost_usd"] is None  # never fabricated


class _StubRejudgeJudge:
    """A fake Judge that flips 'Paris' -> correct/grounded and everything else
    -> incorrect, so verdict-change detection is exercised deterministically.
    ``last_usage`` defaults to small realistic values but is overridable so
    tests can simulate actual usage diverging from the stored-token projection."""
    name = "stub"

    def __init__(self, model=None, prompt_version="judge/2", usage=None):
        self.model = model
        self.prompt_version = prompt_version
        self.last_groundedness = None
        self._usage = usage or {"prompt_tokens": 150, "completion_tokens": 20}
        self.last_usage = None

    def score(self, *, question, gold, pred):
        self.last_usage = dict(self._usage)
        if pred.strip().lower() == gold.strip().lower():
            self.last_groundedness = "grounded"
            return JudgeVerdict("correct", 1.0, "matches gold", self.name, self.model)
        self.last_groundedness = "contradicts"
        return JudgeVerdict("incorrect", 0.0, "does not match", self.name, self.model)


def _rejudge(cases, source_records, monkeypatch, *, usage=None, **kwargs):
    monkeypatch.setattr(rr, "build_judge", lambda name, model, **kw: _StubRejudgeJudge(model, usage=usage, **kw))
    kwargs.setdefault("max_cost_usd", 10.0)  # generous default cap for tests not exercising the guard
    return rr.rejudge(cases, source_records, judge_name="openai", judge_model="gpt-4o-mini", **kwargs)


def test_rejudge_preserves_original_alongside_new(tmp_path, monkeypatch):
    """The original judge/1 verdict must be preserved unchanged alongside the
    new judge/2 verdict -- this is a replay, not an overwrite."""
    path = _write_record(tmp_path, "r.json", [
        _case("c1", verdict="incorrect", judge_score=0.0, generated_answer="Paris"),  # v1 was wrong, v2 fixes it
        _case("c2", verdict="correct", judge_score=1.0, generated_answer="London",
               gold_answer="Paris", question="What is the capital of France?"),  # stays wrong either way
    ])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    report = _rejudge(cases, source_records, monkeypatch, prompt_version="judge/2")

    assert report["n_cases"] == 2
    rows = {r["case_id"]: r for r in report["cases"]}
    c1 = rows["c1"]
    assert c1["original"]["verdict"] == "incorrect"       # preserved, untouched
    assert c1["original"]["prompt_version"] == "judge/1"
    assert c1["rejudged"]["verdict"] == "correct"          # new verdict, judge/2
    assert c1["rejudged"]["groundedness"] == "grounded"
    assert c1["verdict_changed"] is True
    # per-case actual token usage + cost captured from the judge's last_usage
    assert c1["rejudged"]["prompt_tokens"] == 150
    assert c1["rejudged"]["completion_tokens"] == 20
    assert c1["rejudged"]["cost_usd"] is not None and c1["rejudged"]["cost_usd"] > 0

    c2 = rows["c2"]
    assert c2["original"]["verdict"] == "correct"
    assert c2["rejudged"]["verdict"] == "incorrect"
    assert c2["verdict_changed"] is True
    assert report["n_verdicts_changed"] == 2
    assert report["n_cases_judged"] == 2

    # aggregate actual token/cost totals
    assert report["actual_tokens"]["prompt_total"] == 300  # 150 x 2
    assert report["actual_tokens"]["completion_total"] == 40  # 20 x 2
    assert report["actual_cost_usd"]["total"] > 0


def test_rejudge_provenance_carries_max_cost_usd(tmp_path, monkeypatch):
    path = _write_record(tmp_path, "r.json", [_case("c1")])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    report = _rejudge(cases, source_records, monkeypatch, max_cost_usd=1.0)
    assert report["provenance"]["source_records"] == source_records
    assert report["provenance"]["max_cost_usd"] == 1.0
    assert report["provenance"]["judge_model"] == "gpt-4o-mini"


def test_rejudge_requires_max_cost_usd_keyword():
    """max_cost_usd has no default -- omitting it is a TypeError, reinforcing
    fail-closed at the function-signature level, not just the CLI."""
    with pytest.raises(TypeError):
        rr.rejudge({}, [], judge_name="openai", judge_model="gpt-4o-mini")  # type: ignore[call-arg]


def test_rejudge_empty_answer_skips_judge_call_certain_incorrect(tmp_path, monkeypatch):
    """Mirrors JudgedLocomoScorer: an empty generated answer is certain-incorrect
    and must never trigger a judge call."""
    calls = []
    class _NeverCalledJudge(_StubRejudgeJudge):
        def score(self, *, question, gold, pred):
            calls.append(pred)
            return super().score(question=question, gold=gold, pred=pred)
    monkeypatch.setattr(rr, "build_judge", lambda name, model, **kw: _NeverCalledJudge(model, **kw))
    path = _write_record(tmp_path, "r.json", [_case("c1", generated_answer="")])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    report = rr.rejudge(cases, source_records, judge_name="openai", judge_model="gpt-4o-mini", max_cost_usd=10.0)
    assert calls == []  # judge never invoked for the empty answer
    row = report["cases"][0]
    assert row["rejudged"]["verdict"] == "incorrect"
    assert row["rejudged"]["groundedness"] == "na"
    assert row["rejudged"]["cost_usd"] == 0.0


def test_budget_guard_preflight_refuses_all_calls_when_projection_exceeds_cap(tmp_path, monkeypatch):
    """Fail-closed pre-flight: if the FULL projected cost already exceeds the
    cap, refuse to make even the first call."""
    calls = []
    class _CountingJudge(_StubRejudgeJudge):
        def score(self, *, question, gold, pred):
            calls.append(pred)
            return super().score(question=question, gold=gold, pred=pred)
    monkeypatch.setattr(rr, "build_judge", lambda name, model, **kw: _CountingJudge(model, **kw))
    path = _write_record(tmp_path, "r.json", [
        _case("c1", judge={"prompt_tokens": 100_000, "completion_tokens": 5_000}),
        _case("c2", judge={"prompt_tokens": 100_000, "completion_tokens": 5_000}),
    ])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    with pytest.raises(RuntimeError, match="fail-closed|exceeds"):
        rr.rejudge(cases, source_records, judge_name="openai", judge_model="gpt-4o-mini", max_cost_usd=0.000001)
    assert calls == []  # zero judge calls made


def test_budget_guard_aborts_mid_run_when_actual_usage_exceeds_projection(tmp_path, monkeypatch):
    """The guard must also catch a runaway ACTUAL cost that the (necessarily
    approximate) pre-call projection under-estimated: stored judge/1 tokens are
    tiny (so the pre-flight projection and each per-case pre-check pass easily),
    but the stub's REAL last_usage for every call is huge. The guard must stop
    authorizing further calls the moment the running actual cost would exceed
    the cap -- bounding the overshoot to at most the one already-in-flight call
    whose actual cost could not have been known before it returned."""
    monkeypatch.setattr(
        rr, "build_judge",
        lambda name, model, **kw: _StubRejudgeJudge(
            model, usage={"prompt_tokens": 1_000_000, "completion_tokens": 100_000}, **kw
        ),
    )
    path = _write_record(tmp_path, "r.json", [
        _case("c1", judge={"prompt_tokens": 10, "completion_tokens": 5}),
        _case("c2", judge={"prompt_tokens": 10, "completion_tokens": 5}, generated_answer="London",
              gold_answer="Paris", question="What is the capital of France?"),
        _case("c3", judge={"prompt_tokens": 10, "completion_tokens": 5}, generated_answer="Berlin",
              gold_answer="Paris", question="What is the capital of France?"),
    ])
    cases = rr._load_cases([path])
    source_records = rr._source_record_provenance([path])
    # cap comfortably above the tiny pre-flight PROJECTION (so it does not refuse
    # up front) but well below the cost of two REAL calls at 1M/100K tokens each
    # (~$0.21/call on gpt-4o-mini).
    report = rr.rejudge(cases, source_records, judge_name="openai", judge_model="gpt-4o-mini", max_cost_usd=0.05)

    assert report["n_cases_judged"] == 1  # only the first call was authorized
    assert report["budget_guard"]["budget_exhausted"] is True
    assert len(report["budget_guard"]["cases_skipped_budget_guard"]) == 2
    assert report["actual_cost_usd"]["total"] > 0.05  # the one in-flight call did exceed the cap
    skipped_rows = [r for r in report["cases"] if r["skipped_budget_guard"]]
    assert len(skipped_rows) == 2
    for row in skipped_rows:
        assert row["rejudged"] is None
        assert row["verdict_changed"] is None


def test_judge_prompt_v2_contains_alias_and_groundedness_instructions():
    """Pin the prompt-2 contract fixes so a future edit can't silently drop them."""
    assert "LeBron" in JUDGE_PROMPT_V2
    assert "groundedness" in JUDGE_PROMPT_V2
    assert "must NOT lower the verdict" in JUDGE_PROMPT_V2
    # judge/1 must remain byte-identical to before (no accidental cross-edit)
    assert "groundedness" not in DEFAULT_JUDGE_PROMPT
