from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from benchmarks.external.common.judge import (
    ClaudeJudge,
    JudgeVerdict,
    OpenAIJudge,
    StubJudge,
    build_judge,
)
from benchmarks.external.common.runner import (
    run_benchmark,
    run_benchmark_grouped,
    run_benchmark_parallel,
)
from benchmarks.external.common.types import (
    AdapterAnswer,
    BenchmarkCase,
    ConversationTurn,
)


class _MinimalAdapter:
    """In-memory adapter for testing judge integration without SEAM runtime."""
    name = "minimal"
    _store: dict[str, str]

    def __init__(self):
        self._store = {}

    def reset(self, scope_id: str) -> None:
        self._store.pop(scope_id, None)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        self._store[scope_id] = turn.text

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        ctx = self._store.get(scope_id, "")
        return AdapterAnswer(retrieved_context=ctx)


class _ErrorJudge:
    """Judge that always raises — tests error handling."""
    name = "error"
    model = "error-1"

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        raise RuntimeError("simulated judge failure")


class _RecordingJudge:
    name = "recording"
    model = "recording-1"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        self.calls.append({"question": question, "gold": gold, "pred": pred})
        return JudgeVerdict("correct", 1.0, "recorded", self.name, self.model)


class _GeneratedAnswerAdapter(_MinimalAdapter):
    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        ctx = self._store.get(scope_id, "")
        return AdapterAnswer(retrieved_context=ctx, generated_answer="blue")


class _CountingAdapter(_MinimalAdapter):
    def __init__(self):
        super().__init__()
        self.reset_calls: list[str] = []
        self.ingest_calls: list[tuple[str, str]] = []

    def reset(self, scope_id: str) -> None:
        self.reset_calls.append(scope_id)
        super().reset(scope_id)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        self.ingest_calls.append((scope_id, turn.text))
        super().ingest_turn(scope_id, turn)


def _minimal_cases(n: int = 2) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id=f"test-{i}",
            conversation=(ConversationTurn(speaker="A", text=f"Fact {i}: the sky is blue"),),
            question=f"What color is the sky in fact {i}?",
            gold_answer="blue",
            category="test",
        )
        for i in range(n)
    ]


# --- build_judge tests ---

def test_build_judge_none() -> None:
    assert build_judge(None) is None


def test_build_judge_none_string() -> None:
    assert build_judge("none") is None


def test_build_judge_stub() -> None:
    j = build_judge("stub")
    assert isinstance(j, StubJudge)
    v = j.score(question="q", gold="g", pred="p")
    assert v.verdict == "abstain"
    assert v.score == 0.0


def test_build_judge_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown judge"):
        build_judge("unknown")


# --- missing dep / missing API key tests ---

def test_claude_judge_missing_dep(monkeypatch) -> None:
    """Without a local key, fail before any provider request."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="anthropic package|ANTHROPIC_API_KEY"):
        ClaudeJudge()


def test_openai_judge_missing_dep(monkeypatch) -> None:
    """Without a local key, fail before any provider request."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="openai package|OPENAI_API_KEY"):
        OpenAIJudge()


# --- lazy import test ---

def test_claude_judge_does_not_import_anthropic_at_module_level() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import benchmarks.external.common.judge; print('anthropic' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


# --- runner integration tests ---

def test_run_benchmark_with_stub_judge() -> None:
    adapter = _MinimalAdapter()
    cases = _minimal_cases(2)
    adapter.reset(cases[0].case_id)
    adapter.ingest_turn(cases[0].case_id, cases[0].conversation[0])
    adapter.reset(cases[1].case_id)
    adapter.ingest_turn(cases[1].case_id, cases[1].conversation[0])

    report = run_benchmark(adapter=adapter, cases=cases, judge=StubJudge())
    assert report["scores"]["judge_score_mean"] == 0.0
    assert report["scores"]["judge_count"] == 2
    assert report["scores"]["abstain_count"] == 2
    assert report["cases"][0]["judge"]["verdict"] == "abstain"
    assert report["cases"][1]["judge"]["verdict"] == "abstain"


def test_retrieval_only_context_does_not_score_as_generated_answer() -> None:
    adapter = _MinimalAdapter()
    cases = _minimal_cases(1)

    report = run_benchmark(adapter=adapter, cases=cases)

    assert report["scores"]["context_recall_mean"] == 1.0
    assert report["scores"]["answer_em_mean"] == 0.0
    assert report["scores"]["answer_f1_mean"] == 0.0
    assert "retrieved_context" not in report["cases"][0]


def test_save_context_includes_retrieved_context_without_changing_integrity_hash() -> None:
    cases = _minimal_cases(1)

    default_report = run_benchmark(adapter=_MinimalAdapter(), cases=cases)
    context_report = run_benchmark(
        adapter=_MinimalAdapter(),
        cases=cases,
        save_context=True,
    )

    assert context_report["cases"][0]["retrieved_context"] == "Fact 0: the sky is blue"
    assert context_report["integrity_hash"] == default_report["integrity_hash"]


def test_generated_answer_scores_answer_metrics() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _minimal_cases(1)

    report = run_benchmark(adapter=adapter, cases=cases)

    assert report["scores"]["answer_em_mean"] == 1.0
    assert report["scores"]["answer_f1_mean"] == 1.0


def test_cross_judge_receives_real_question_gold_and_prediction() -> None:
    adapter = _GeneratedAnswerAdapter()
    primary = _RecordingJudge()
    cross = _RecordingJudge()
    cases = _minimal_cases(1)

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda case: case.case_id,
        judge=primary,
        judge_cross=cross,
    )

    assert report["scores"]["judge_cross_agreement_rate"] == 1.0
    assert cross.calls == [
        {
            "question": cases[0].question,
            "gold": cases[0].gold_answer,
            "pred": "blue",
        }
    ]


def test_judge_error_caught_per_case() -> None:
    adapter = _MinimalAdapter()
    cases = _minimal_cases(1)
    adapter.reset(cases[0].case_id)
    adapter.ingest_turn(cases[0].case_id, cases[0].conversation[0])

    report = run_benchmark(adapter=adapter, cases=cases, judge=_ErrorJudge())
    assert "error" in report["cases"][0].get("judge", {})
    assert "simulated judge failure" in report["cases"][0]["judge"]["error"]


def test_run_benchmark_without_judge_no_judge_fields() -> None:
    """Default path (no judge) must not have judge_score_mean in scores."""
    adapter = _MinimalAdapter()
    cases = _minimal_cases(1)
    adapter.reset(cases[0].case_id)
    adapter.ingest_turn(cases[0].case_id, cases[0].conversation[0])

    report = run_benchmark(adapter=adapter, cases=cases)
    assert "judge_score_mean" not in report["scores"]
    assert "judge" not in report["cases"][0]


def test_run_benchmark_parallel_preserves_case_order_and_scores() -> None:
    cases = _minimal_cases(4)
    completed: list[tuple[int, int]] = []

    report = run_benchmark_parallel(
        adapter_factory=_MinimalAdapter,
        adapter_name="minimal",
        cases=cases,
        judge_factory=StubJudge,
        workers=2,
        progress=lambda done, total: completed.append((done, total)),
    )

    assert [case["case_id"] for case in report["cases"]] == [case.case_id for case in cases]
    assert report["scores"]["context_recall_mean"] == 1.0
    assert report["scores"]["judge_score_mean"] == 0.0
    assert completed[-1] == (4, 4)


def test_run_benchmark_grouped_ingests_each_scope_once() -> None:
    adapter = _CountingAdapter()
    cases = [
        BenchmarkCase(
            case_id="conv-a::q0",
            conversation=(ConversationTurn(speaker="A", text="The code is blue"),),
            question="What color is the code?",
            gold_answer="blue",
            category="test",
        ),
        BenchmarkCase(
            case_id="conv-a::q1",
            conversation=(ConversationTurn(speaker="A", text="The code is blue"),),
            question="Repeat the color.",
            gold_answer="blue",
            category="test",
        ),
        BenchmarkCase(
            case_id="conv-b::q0",
            conversation=(ConversationTurn(speaker="A", text="The token is green"),),
            question="What color is the token?",
            gold_answer="green",
            category="test",
        ),
    ]

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda case: case.case_id.split("::", 1)[0],
        judge=StubJudge(),
    )

    assert [case["case_id"] for case in report["cases"]] == [case.case_id for case in cases]
    assert adapter.reset_calls == ["conv-a", "conv-b"]
    assert adapter.ingest_calls == [
        ("conv-a", "The code is blue"),
        ("conv-b", "The token is green"),
    ]
    assert report["scores"]["judge_count"] == 3


# --- CLI smoke ---

def test_cli_quickstart_with_stub_judge() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--judge", "stub"],
        capture_output=True,
        text=True,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "judge_score_mean" in data["scores"], f"keys: {list(data['scores'])}"


# --- malformed judge output tests ---

class _GarbageJudge:
    """Judge that returns unparseable text."""
    name = "garbage"
    model = "garbage-1"

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        # Return something that isn't valid JSON
        raise ValueError("judge returned unparseable JSON")


class _BadVerdictJudge:
    """Judge that returns an invalid verdict value."""
    name = "bad-verdict"
    model = "bad-1"

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        raise ValueError("judge returned invalid verdict")


def test_runner_captures_judge_parse_error_per_case():
    """Judge that raises ValueError with 'unparseable' is caught per case."""
    adapter = _MinimalAdapter()
    cases = _minimal_cases(2)

    report = run_benchmark(adapter=adapter, cases=cases, judge=_GarbageJudge())
    for case_entry in report["cases"]:
        assert "error" in case_entry.get("judge", {})
        assert "unparseable" in case_entry["judge"]["error"]
    assert "judge_score_mean" not in report["scores"]


def test_runner_captures_judge_invalid_verdict_per_case():
    """Judge that raises ValueError with 'invalid verdict' is caught per case."""
    adapter = _MinimalAdapter()
    cases = _minimal_cases(2)

    report = run_benchmark(adapter=adapter, cases=cases, judge=_BadVerdictJudge())
    for case_entry in report["cases"]:
        assert "error" in case_entry.get("judge", {})
        assert "invalid verdict" in case_entry["judge"]["error"]
    assert "judge_score_mean" not in report["scores"]


def test_cross_judge_error_caught_per_case():
    """Cross-judge that raises still produces per-case error entries."""
    adapter = _GeneratedAnswerAdapter()
    recording = _RecordingJudge()
    cases = _minimal_cases(2)

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda case: case.case_id,
        judge=recording,
        judge_cross=_ErrorJudge(),
    )

    for case_entry in report["cases"]:
        cross = case_entry.get("judge_cross", {})
        assert "error" in cross
        assert "simulated judge failure" in cross["error"]
    assert "judge_cross_agreement_rate" not in report["scores"]


def test_cross_judge_agreement_rate_excluded_when_cross_errors():
    """When cross-judge has errors, agreement rate is not computed."""
    adapter = _GeneratedAnswerAdapter()
    recording = _RecordingJudge()
    cases = _minimal_cases(2)

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda case: case.case_id,
        judge=recording,
        judge_cross=_ErrorJudge(),
    )

    assert "judge_cross_agreement_rate" not in report["scores"]


def test_stub_judge_always_abstains_with_zero_score():
    """StubJudge must never claim correctness on any input."""
    stub = StubJudge()
    for pred in ("correct answer", "wrong answer", "", "unknown"):
        v = stub.score(question="q", gold="g", pred=pred)
        assert v.verdict == "abstain", f"stub verdict for pred={pred!r}"
        assert v.score == 0.0, f"stub score for pred={pred!r}"
        assert "stub does not score correctness" in v.rationale


def test_cli_quickstart_with_parallel_stub_judge() -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "benchmarks.external.locomo.run",
            "--quickstart", "--judge", "stub", "--workers", "2",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert data["dataset"]["case_count"] == 10
    assert data["scores"]["judge_count"] == 10
