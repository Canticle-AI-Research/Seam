"""Full-run record capture (HISTORY#366): pricing, reasoning-split, failure
classification, and an end-to-end capture through JudgedLocomoScorer with a
fake adapter + stub judge (no network, no spend)."""
from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from benchmarks.external.common import pricing
from benchmarks.external.common.judge import JudgeVerdict
from benchmarks.external.common.run_record import (
    RunRecord,
    classify_failure,
    external_mount_ready,
    split_reasoning,
)
from benchmarks.external.common.types import AdapterAnswer, BenchmarkCase
from benchmarks.external.locomo.judged_scorer import JudgedLocomoScorer
from seam_runtime.retrieval import RetrievalFlags


def test_pricing_known_unknown_and_override(monkeypatch):
    monkeypatch.delenv("SEAM_BENCH_PRICING_JSON", raising=False)
    cost = pricing.estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == 0.15 + 0.60
    # prefix match
    assert pricing.estimate_cost_usd("gpt-4o-mini-2026-99", 1_000_000, 0) == 0.15
    # unknown model -> None (never fabricated)
    assert pricing.estimate_cost_usd("mystery-model", 100, 100) is None
    # missing tokens -> None
    assert pricing.estimate_cost_usd("gpt-4o-mini", None, 10) is None
    # env override
    monkeypatch.setenv("SEAM_BENCH_PRICING_JSON", json.dumps({"mystery-model": {"input": 1.0, "output": 2.0}}))
    assert pricing.estimate_cost_usd("mystery-model", 1_000_000, 1_000_000) == 3.0


def test_split_reasoning():
    assert split_reasoning(None) == ("", None)
    assert split_reasoning("just an answer") == ("just an answer", None)
    visible, trace = split_reasoning("<think>step one\nstep two</think>\nFinal answer")
    assert visible == "Final answer"
    assert trace == "step one\nstep two"


def test_classify_failure():
    assert classify_failure("correct", 0.1) == "answered_correct"
    assert classify_failure("abstain", 0.9) == "abstained"
    assert classify_failure("incorrect", 0.9) == "answerer_miss"   # evidence present, wrong
    assert classify_failure("incorrect", 0.1) == "retrieval_miss"  # evidence missing
    assert classify_failure("incorrect", None) == "unknown"


class _FakeRuntime:
    def __init__(self):
        self._retrieval_flags = None
        self.store = None


class _FakeAdapter:
    """Returns a canned AdapterAnswer per case; one carries a <think> trace and
    token usage so the record captures reasoning + cost."""

    budget = 2000

    def __init__(self):
        self._rt = _FakeRuntime()

    def _runtime(self, scope):
        return self._rt

    def answer(self, scope, question):
        if "capital" in question:
            raw = "<think>France's capital is Paris.</think>\nParis"
            ctx = "The capital of France is Paris."
            diag = {"provider": "ollama", "model": "gpt-4o-mini", "raw_response": raw,
                    "prompt_tokens": 1000, "completion_tokens": 5, "candidate_count": 3}
            return AdapterAnswer(retrieved_context=ctx, generated_answer="Paris",
                                 retrieval_latency_ms=12.0, answer_latency_ms=34.0,
                                 answerer_diagnostics=diag)
        # a case where the evidence is NOT in context -> retrieval_miss
        diag = {"provider": "openai", "model": "gpt-4o-mini", "raw_response": "Blue",
                "prompt_tokens": 800, "completion_tokens": 3, "candidate_count": 1}
        return AdapterAnswer(retrieved_context="Unrelated snippet about weather.",
                             generated_answer="Blue", retrieval_latency_ms=8.0,
                             answer_latency_ms=20.0, answerer_diagnostics=diag)


class _StubJudge:
    name = "stub"
    model = "gpt-4o-mini"  # a priced model so the judge-cost path is exercised

    def __init__(self):
        self.last_usage = None

    def score(self, *, question, gold, pred):
        self.last_usage = {"prompt_tokens": 200, "completion_tokens": 10}
        if pred.lower() in gold.lower():
            return JudgeVerdict("correct", 1.0, "matches gold", self.name, self.model)
        return JudgeVerdict("incorrect", 0.0, "does not match", self.name, self.model)


def test_end_to_end_capture_through_scorer(tmp_path):
    cases_by_scope = OrderedDict()
    cases_by_scope["conv-1"] = [
        BenchmarkCase(case_id="c1", conversation=[], question="What is the capital of France?",
                      gold_answer="Paris", category="1"),
        BenchmarkCase(case_id="c2", conversation=[], question="What color is the sky?",
                      gold_answer="Azure", category="3"),
    ]
    scorer = JudgedLocomoScorer(adapter=_FakeAdapter(), judge=_StubJudge(),
                                cases_by_scope=cases_by_scope)
    recorder = RunRecord()
    recorder.set_meta(dataset_path="fake", split="dev",
                      prompts={"baseline": "Q: {question}\nContext: {context}\nA:"})
    report = scorer.score(None, flags=RetrievalFlags(), recorder=recorder, arm="baseline")

    assert report.n == 2
    assert len(recorder.cases) == 2
    c1 = next(c for c in recorder.cases if c["case_id"] == "c1")
    # reasoning trace captured + stripped from the visible answer
    assert c1["reasoning_trace"] == "France's capital is Paris."
    assert c1["generated_answer"] == "Paris"
    assert c1["verdict"] == "correct"
    assert c1["judge_rationale"] == "matches gold"
    assert c1["context_recall"] > 0  # "Paris" is in the context
    assert c1["failure_class"] == "answered_correct"
    # exact cost from captured tokens (gpt-4o-mini): 1000 in + 5 out, + judge 200/10
    assert c1["answerer"]["cost_usd"] is not None
    assert c1["judge"]["cost_usd"] is not None
    assert c1["latency_ms"]["answer"] == 34.0

    c2 = next(c for c in recorder.cases if c["case_id"] == "c2")
    # "Blue" not judged into gold -> incorrect; evidence absent -> retrieval_miss
    assert c2["verdict"] == "incorrect"
    assert c2["failure_class"] in ("retrieval_miss", "answerer_miss")

    totals = recorder.to_dict()["totals"]
    assert totals["n_case_rows"] == 2
    assert totals["cost_usd"]["total"] > 0
    assert "cat1:baseline" in totals["per_category_arm_judge_mean"]

    # both writers produce parseable artifacts
    jpath = recorder.write_json(str(tmp_path / "run.json"))
    doc = json.loads(open(jpath).read())
    assert doc["totals"]["n_case_rows"] == 2 and len(doc["cases"]) == 2
    tpath = recorder.write_training_jsonl(str(tmp_path / "train.jsonl"))
    rows = [json.loads(line) for line in open(tpath)]
    assert len(rows) == 2
    assert rows[0]["messages"][0]["role"] == "user"
    assert rows[0]["messages"][1]["role"] == "assistant"
    # the <think> trace is preserved in the training assistant turn for c1
    c1row = next(r for r in rows if r["case_id"] == "c1")
    assert "<think>" in c1row["messages"][1]["content"]


def test_run_paid_validation_writes_record(tmp_path):
    """The paid-validation path (what `seam improve validate` calls) writes the
    full JSON + training JSONL when given a record_path, capturing both arms."""
    from tools.h2.paid_validation import run_paid_validation

    cases_by_scope = OrderedDict()
    cases_by_scope["conv-1"] = [
        BenchmarkCase(case_id="c1", conversation=[], question="What is the capital of France?",
                      gold_answer="Paris", category="1"),
    ]
    adapter = _FakeAdapter()
    adapter._answerer = "openai"
    adapter._answerer_model = "gpt-4o-mini"
    scorer = JudgedLocomoScorer(adapter=adapter, judge=_StubJudge(), cases_by_scope=cases_by_scope)
    record_path = str(tmp_path / "rec.json")
    report = run_paid_validation(
        scorer, None,
        candidate_flags=RetrievalFlags(search_top_k=5),  # != baseline -> both arms run
        record_path=record_path,
    )
    assert "record" in report
    doc = json.loads(open(report["record"]["json"]).read())
    arms = {c["arm"] for c in doc["cases"]}
    assert arms == {"baseline", "candidate"}  # both arms captured
    assert doc["run"]["scorer"] == scorer.name
    rows = [json.loads(line) for line in open(report["record"]["training_jsonl"])]
    assert len(rows) == 2  # 1 case x 2 arms


def test_external_mount_guard(tmp_path):
    # A normal local path is always ok.
    ok, _ = external_mount_ready(str(tmp_path / "records"))
    assert ok
    # On POSIX, a path under /media whose drive is NOT mounted (nonexistent
    # label) resolves to the root filesystem -> refused, so data never silently
    # lands on root. On Windows, "/media/..." is not an external-mount
    # convention and is treated as a normal local path.
    ok, msg = external_mount_ready("/media/nobody/NoSuchDrive1234/DATA")
    if os.name == "posix":
        assert not ok and "not mounted" in msg
    else:
        assert ok and msg == ""


def test_deepseek_answerer_folds_reasoning_into_think(monkeypatch):
    """DeepSeek's v4 models return reasoning in a separate reasoning_content
    field; the answerer must fold it into <think>...</think> raw_response and
    capture token usage (incl. served_model + cache_hit_tokens), so the record
    pipeline harvests the trace + exact cost."""
    from benchmarks.external.locomo.adapters import seam as seam_mod

    class _Msg:
        content = "Paris"
        reasoning_content = "The context says the capital of France is Paris."

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Usage:
        prompt_tokens = 1200
        completion_tokens = 4
        completion_tokens_details = None
        prompt_cache_hit_tokens = 200

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()
        model = "deepseek-v4-pro"  # server-reported; must match the requested id (no alias reroute)

    class _FakeClient:
        def __init__(self, *a, **k):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            return _Resp()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_FakeClient))
    diag: dict = {}
    answer = seam_mod._deepseek_short_answer("deepseek-v4-pro", "Q: capital of France?", diag_out=diag)

    assert answer == "Paris"
    assert diag["provider"] == "deepseek"
    assert diag["model"] == "deepseek-v4-pro"
    assert diag["served_model"] == "deepseek-v4-pro"  # would differ if DeepSeek rerouted the request
    assert diag["raw_response"] == "<think>The context says the capital of France is Paris.</think>\nParis"
    assert diag["prompt_tokens"] == 1200 and diag["completion_tokens"] == 4
    assert diag["cache_hit_tokens"] == 200
    # and the record pipeline extracts the trace from that raw_response
    visible, trace = split_reasoning(diag["raw_response"])
    assert visible == "Paris"
    assert trace == "The context says the capital of France is Paris."


def test_deepseek_pricing_present():
    # Real rates verified live against api-docs.deepseek.com/quick_start/pricing
    # 2026-07-09. deepseek-reasoner/deepseek-chat are DEPRECATED aliases and are
    # deliberately NOT in the price table -- always price the explicit v4 id.
    assert pricing.is_priced("deepseek-v4-pro")
    assert pricing.is_priced("deepseek-v4-flash")
    assert not pricing.is_priced("deepseek-reasoner")
    # all cache-miss: 1M in @ $0.435 + 1M out @ $0.87
    cost = pricing.estimate_cost_usd("deepseek-v4-pro", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.435 + 0.87)


def test_deepseek_pricing_cache_hit_split():
    # 800k cache-miss @ $0.435/1M + 200k cache-hit @ $0.003625/1M + 100k out @ $0.87/1M
    cost = pricing.estimate_cost_usd(
        "deepseek-v4-pro", prompt_tokens=1_000_000, completion_tokens=100_000, cache_hit_tokens=200_000
    )
    expected = (800_000 / 1_000_000) * 0.435 + (200_000 / 1_000_000) * 0.003625 + (100_000 / 1_000_000) * 0.87
    assert cost == pytest.approx(expected)
    # cache_hit_tokens omitted -> all prompt tokens price at the standard rate
    assert pricing.estimate_cost_usd("deepseek-v4-pro", 1_000_000, 0) == pytest.approx(0.435)
