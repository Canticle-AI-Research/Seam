"""Tests for the optional ``score_batch`` Judge path and runner batch mode.

These tests never touch the network: the Anthropic / OpenAI clients are
replaced with fakes, and the runner is exercised through a recording fake
judge that implements ``score_batch``.
"""
from __future__ import annotations

import io
import json
import types

import pytest

from benchmarks.external.common.judge import (
    ClaudeJudge,
    JudgeBatchItem,
    JudgeVerdict,
    OpenAIJudge,
    StubJudge,
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


# ---------- in-memory test adapter + cases -------------------------------------

class _GeneratedAnswerAdapter:
    name = "minimal"

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def reset(self, scope_id: str) -> None:
        self._store.pop(scope_id, None)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        self._store[scope_id] = turn.text

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        return AdapterAnswer(retrieved_context=self._store.get(scope_id, ""), generated_answer="blue")


class _FailingScopeAdapter(_GeneratedAnswerAdapter):
    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        if scope_id == "case-1":
            raise RuntimeError("429 rate limit exceeded")
        super().ingest_turn(scope_id, turn)


def _cases(n: int = 3) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id=f"case-{i}",
            conversation=(ConversationTurn(speaker="A", text=f"Fact {i}: blue"),),
            question=f"Color {i}?",
            gold_answer="blue",
            category="test",
        )
        for i in range(n)
    ]


# ---------- recording / failing batch judges -----------------------------------

class _RecordingBatchJudge:
    name = "recording-batch"
    model = "recording-batch-1"

    def __init__(self) -> None:
        self.sync_calls = 0
        self.batch_calls: list[list[JudgeBatchItem]] = []

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        self.sync_calls += 1
        return JudgeVerdict("correct", 1.0, "sync", self.name, self.model)

    def score_batch(self, items: list[JudgeBatchItem]) -> dict[str, JudgeVerdict | Exception]:
        self.batch_calls.append(list(items))
        return {
            item.custom_id: JudgeVerdict("correct", 1.0, "batch", self.name, self.model)
            for item in items
        }


class _MixedBatchJudge(_RecordingBatchJudge):
    """Returns verdict for some, Exception for others, missing for the last."""

    def score_batch(self, items: list[JudgeBatchItem]) -> dict[str, JudgeVerdict | Exception]:
        self.batch_calls.append(list(items))
        result: dict[str, JudgeVerdict | Exception] = {}
        for i, item in enumerate(items):
            if i == 0:
                result[item.custom_id] = JudgeVerdict(
                    "correct", 1.0, "ok", self.name, self.model
                )
            elif i == 1:
                result[item.custom_id] = ValueError("simulated parse failure")
            # i == 2: omit entirely
        return result


class _RaisingBatchJudge(_RecordingBatchJudge):
    def score_batch(self, items):  # noqa: ARG002
        raise RuntimeError("submit blew up")


class _FlakySyncJudge(_RecordingBatchJudge):
    def score(self, *, question, gold, pred) -> JudgeVerdict:  # noqa: ARG002
        self.sync_calls += 1
        if self.sync_calls == 1:
            raise RuntimeError("429 rate limit exceeded")
        return JudgeVerdict("correct", 1.0, "retried", self.name, self.model)


# ---------- runner-level tests --------------------------------------------------

def test_judge_batch_defers_to_score_batch_when_supported() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(3)
    judge = _RecordingBatchJudge()

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=judge,
        judge_batch=True,
    )

    assert judge.sync_calls == 0
    assert len(judge.batch_calls) == 1
    submitted = judge.batch_calls[0]
    assert [item.custom_id for item in submitted] == [c.case_id for c in cases]
    assert all(item.pred == "blue" for item in submitted)
    assert all(case["judge"]["rationale"] == "batch" for case in report["cases"])


def test_judge_batch_disabled_uses_sync_path() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(2)
    judge = _RecordingBatchJudge()

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=judge,
        judge_batch=False,
    )

    assert judge.sync_calls == len(cases)
    assert judge.batch_calls == []
    assert all(case["judge"]["rationale"] == "sync" for case in report["cases"])


def test_sync_judge_retries_transient_rate_limits(monkeypatch) -> None:
    import benchmarks.external.common.provider_retry as provider_retry

    monkeypatch.setattr(provider_retry.time, "sleep", lambda _delay: None)
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(1)
    judge = _FlakySyncJudge()

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=judge,
        judge_batch=False,
    )

    assert judge.sync_calls == 2
    assert report["cases"][0]["judge"]["rationale"] == "retried"


def test_judge_batch_falls_back_to_sync_when_judge_lacks_score_batch() -> None:
    """A judge without score_batch must still work when judge_batch=True."""
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(2)
    stub = StubJudge()

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=stub,
        judge_batch=True,
    )

    assert all(case["judge"]["verdict"] == "abstain" for case in report["cases"])


def test_judge_batch_partial_failures_become_per_case_errors() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(3)

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=_MixedBatchJudge(),
        judge_batch=True,
    )

    assert report["cases"][0]["judge"]["verdict"] == "correct"
    assert "simulated parse failure" in report["cases"][1]["judge"]["error"]
    assert "no entry" in report["cases"][2]["judge"]["error"]


def test_judge_batch_submission_failure_marks_every_case_as_error() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(2)

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=_RaisingBatchJudge(),
        judge_batch=True,
    )

    for case in report["cases"]:
        assert "judge batch failed" in case["judge"]["error"]
        assert "submit blew up" in case["judge"]["error"]


def test_grouped_runner_records_scope_crashes_and_checkpoints(monkeypatch) -> None:
    import benchmarks.external.common.provider_retry as provider_retry

    monkeypatch.setattr(provider_retry.time, "sleep", lambda _delay: None)
    monkeypatch.setenv("SEAM_BENCH_PROVIDER_MAX_RETRIES", "2")
    checkpoints: list[tuple[int, int, list[str]]] = []
    cases = _cases(2)

    report = run_benchmark_grouped(
        adapter=_FailingScopeAdapter(),
        cases=cases,
        scope_id=lambda c: c.case_id,
        checkpoint=lambda rows, completed, total: checkpoints.append(
            (completed, total, [row["case_id"] for row in rows])
        ),
    )

    assert [case["case_id"] for case in report["cases"]] == ["case-0", "case-1"]
    assert report["cases"][0]["scores"]["answer_f1"] == 1.0
    failed = report["cases"][1]
    assert failed["scores"] == {
        "context_recall": 0.0,
        "answer_em": 0.0,
        "answer_f1": 0.0,
    }
    assert failed["error"]["stage"] == "scope"
    assert "429 rate limit" in failed["error"]["message"]
    assert checkpoints[-1] == (2, 2, ["case-0", "case-1"])


def test_judge_batch_preserves_case_order_under_parallel_workers() -> None:
    cases = _cases(6)
    judge = _RecordingBatchJudge()

    report = run_benchmark_parallel(
        adapter_factory=_GeneratedAnswerAdapter,
        adapter_name="minimal",
        cases=cases,
        judge_factory=lambda: judge,
        judge_batch=True,
        workers=3,
    )

    assert [c["case_id"] for c in report["cases"]] == [c.case_id for c in cases]
    assert judge.sync_calls == 0
    assert len(judge.batch_calls) == 1
    submitted = judge.batch_calls[0]
    assert sorted(item.custom_id for item in submitted) == sorted(c.case_id for c in cases)


def test_judge_batch_with_cross_judge_applies_to_both() -> None:
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(2)
    primary = _RecordingBatchJudge()
    cross = _RecordingBatchJudge()

    report = run_benchmark_grouped(
        adapter=adapter,
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=primary,
        judge_cross=cross,
        judge_batch=True,
    )

    assert len(primary.batch_calls) == 1
    assert len(cross.batch_calls) == 1
    assert report["scores"]["judge_cross_agreement_rate"] == 1.0


def test_judge_batch_integrity_hash_excludes_judge_fields() -> None:
    """Stable integrity hash must be the same whether judge ran sync or batch."""
    adapter = _GeneratedAnswerAdapter()
    cases = _cases(2)

    sync_report = run_benchmark_grouped(
        adapter=_GeneratedAnswerAdapter(),
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=_RecordingBatchJudge(),
        judge_batch=False,
    )
    batch_report = run_benchmark_grouped(
        adapter=_GeneratedAnswerAdapter(),
        cases=cases,
        scope_id=lambda c: c.case_id,
        judge=_RecordingBatchJudge(),
        judge_batch=True,
    )

    assert sync_report["integrity_hash"] == batch_report["integrity_hash"]


# ---------- ClaudeJudge.score_batch with a fake anthropic client ---------------

class _FakeAnthropicBatchEntry:
    def __init__(self, custom_id: str, text: str, *, errored: bool = False) -> None:
        self.custom_id = custom_id
        if errored:
            self.result = types.SimpleNamespace(
                type="errored",
                error=types.SimpleNamespace(message="rate limited"),
            )
        else:
            content_block = types.SimpleNamespace(text=text, type="text")
            message = types.SimpleNamespace(content=[content_block])
            self.result = types.SimpleNamespace(type="succeeded", message=message)


class _FakeAnthropicBatches:
    def __init__(self, *, entries: list[_FakeAnthropicBatchEntry]) -> None:
        self._entries = entries
        self.created_with: list[list[dict]] = []
        self._batch_id = "batch_fake_1"
        self._poll_count = 0

    def create(self, *, requests):
        self.created_with.append(list(requests))
        return types.SimpleNamespace(id=self._batch_id, processing_status="in_progress")

    def retrieve(self, batch_id):  # noqa: ARG002
        # First retrieve says in_progress, subsequent say ended (exercises the loop).
        self._poll_count += 1
        status = "ended" if self._poll_count >= 1 else "in_progress"
        return types.SimpleNamespace(id=self._batch_id, processing_status=status)

    def results(self, batch_id):  # noqa: ARG002
        return iter(self._entries)


class _FakeAnthropicMessages:
    def __init__(self, batches) -> None:
        self.batches = batches


class _FakeAnthropicClient:
    def __init__(self, *, entries: list[_FakeAnthropicBatchEntry]) -> None:
        self.messages = _FakeAnthropicMessages(_FakeAnthropicBatches(entries=entries))


def _claude_judge_with_fake(monkeypatch, entries):
    """Construct ClaudeJudge bypassing the real anthropic import / API key check."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    judge = ClaudeJudge.__new__(ClaudeJudge)
    judge.model = "claude-haiku-test"
    judge.name = "claude"
    judge._client = _FakeAnthropicClient(entries=entries)
    return judge


def test_claude_judge_score_batch_parses_verdicts(monkeypatch) -> None:
    items = [
        JudgeBatchItem("c0", "q0", "blue", "blue"),
        JudgeBatchItem("c1", "q1", "blue", "red"),
    ]
    entries = [
        _FakeAnthropicBatchEntry("c0", '{"verdict": "correct", "rationale": "match"}'),
        _FakeAnthropicBatchEntry("c1", '{"verdict": "incorrect", "rationale": "mismatch"}'),
    ]
    judge = _claude_judge_with_fake(monkeypatch, entries)

    result = judge.score_batch(items, poll_seconds=0)

    assert isinstance(result["c0"], JudgeVerdict)
    assert result["c0"].verdict == "correct"
    assert result["c1"].verdict == "incorrect"


def test_claude_judge_score_batch_marks_failed_entries_as_exceptions(monkeypatch) -> None:
    items = [JudgeBatchItem("c0", "q", "g", "p")]
    entries = [_FakeAnthropicBatchEntry("c0", "", errored=True)]
    judge = _claude_judge_with_fake(monkeypatch, entries)

    result = judge.score_batch(items, poll_seconds=0)

    assert isinstance(result["c0"], Exception)
    assert "rate limited" in str(result["c0"])


def test_claude_judge_score_batch_rejects_duplicate_custom_ids(monkeypatch) -> None:
    items = [
        JudgeBatchItem("dup", "q", "g", "p"),
        JudgeBatchItem("dup", "q", "g", "p"),
    ]
    judge = _claude_judge_with_fake(monkeypatch, [])

    with pytest.raises(ValueError, match="duplicate custom_id"):
        judge.score_batch(items, poll_seconds=0)


def test_claude_judge_score_batch_empty_returns_empty(monkeypatch) -> None:
    judge = _claude_judge_with_fake(monkeypatch, [])
    assert judge.score_batch([], poll_seconds=0) == {}


# ---------- OpenAIJudge.score_batch with a fake openai client ------------------

class _FakeOpenAIFiles:
    def __init__(self, output_text: str = "", error_text: str = "") -> None:
        self.output_text = output_text
        self.error_text = error_text
        self.uploaded: list[bytes] = []

    def create(self, *, file, purpose):  # noqa: ARG002
        # file is a (name, fileobj) tuple
        name, fileobj = file
        self.uploaded.append(fileobj.read())
        return types.SimpleNamespace(id="file_input_1")

    def content(self, file_id):
        if file_id == "file_output_1":
            return self.output_text
        if file_id == "file_error_1":
            return self.error_text
        raise ValueError(f"unknown file id {file_id!r}")


class _FakeOpenAIBatches:
    def __init__(self, *, output_file_id="file_output_1", error_file_id=None, status="completed") -> None:
        self._status = status
        self._output_file_id = output_file_id
        self._error_file_id = error_file_id
        self.created_with: list[dict] = []

    def create(self, *, input_file_id, endpoint, completion_window):
        self.created_with.append(
            {"input_file_id": input_file_id, "endpoint": endpoint, "completion_window": completion_window}
        )
        return types.SimpleNamespace(id="batch_fake_oa")

    def retrieve(self, batch_id):  # noqa: ARG002
        return types.SimpleNamespace(
            id="batch_fake_oa",
            status=self._status,
            output_file_id=self._output_file_id,
            error_file_id=self._error_file_id,
        )


class _FakeOpenAIClient:
    def __init__(self, *, output_text: str, error_text: str = "") -> None:
        self.files = _FakeOpenAIFiles(output_text=output_text, error_text=error_text)
        self.batches = _FakeOpenAIBatches(error_file_id="file_error_1" if error_text else None)


def _openai_judge_with_fake(monkeypatch, *, output_text: str, error_text: str = ""):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    judge = OpenAIJudge.__new__(OpenAIJudge)
    judge.model = "gpt-4o-mini"
    judge.name = "openai"
    judge._client = _FakeOpenAIClient(output_text=output_text, error_text=error_text)
    return judge


def test_openai_judge_score_batch_parses_verdicts(monkeypatch) -> None:
    items = [
        JudgeBatchItem("c0", "q0", "blue", "blue"),
        JudgeBatchItem("c1", "q1", "blue", "red"),
    ]
    output_lines = [
        json.dumps({
            "custom_id": "c0",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{
                        "message": {
                            "content": json.dumps({"verdict": "correct", "rationale": "match"})
                        }
                    }]
                }
            }
        }),
        json.dumps({
            "custom_id": "c1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{
                        "message": {
                            "content": json.dumps({"verdict": "incorrect", "rationale": "mismatch"})
                        }
                    }]
                }
            }
        }),
    ]
    judge = _openai_judge_with_fake(monkeypatch, output_text="\n".join(output_lines) + "\n")

    result = judge.score_batch(items, poll_seconds=0)

    assert isinstance(result["c0"], JudgeVerdict)
    assert result["c0"].verdict == "correct"
    assert result["c1"].verdict == "incorrect"


def test_openai_judge_score_batch_routes_error_file_entries_to_exceptions(monkeypatch) -> None:
    items = [JudgeBatchItem("c0", "q", "g", "p")]
    error_text = json.dumps({"custom_id": "c0", "error": {"message": "invalid request"}}) + "\n"
    judge = _openai_judge_with_fake(monkeypatch, output_text="", error_text=error_text)

    result = judge.score_batch(items, poll_seconds=0)

    assert isinstance(result["c0"], Exception)
    assert "invalid request" in str(result["c0"])


def test_judge_batch_flag_parses_in_cli_help() -> None:
    """--judge-batch is exposed on the LoCoMo CLI; the parser accepts it."""
    import argparse
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.external.locomo.run", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--judge-batch" in result.stdout
    assert "Batch API" in result.stdout


def test_openai_judge_score_batch_uploads_jsonl_with_one_line_per_item(monkeypatch) -> None:
    items = [
        JudgeBatchItem("c0", "q0", "g0", "p0"),
        JudgeBatchItem("c1", "q1", "g1", "p1"),
    ]
    output_lines = [
        json.dumps({
            "custom_id": cid,
            "response": {
                "status_code": 200,
                "body": {"choices": [{"message": {"content": json.dumps({"verdict": "correct", "rationale": "ok"})}}]}
            }
        }) for cid in ("c0", "c1")
    ]
    judge = _openai_judge_with_fake(monkeypatch, output_text="\n".join(output_lines) + "\n")
    judge.score_batch(items, poll_seconds=0)

    uploaded = judge._client.files.uploaded[0].decode("utf-8")
    lines = [line for line in uploaded.split("\n") if line.strip()]
    assert len(lines) == 2
    decoded = [json.loads(line) for line in lines]
    assert [entry["custom_id"] for entry in decoded] == ["c0", "c1"]
    for entry in decoded:
        assert entry["method"] == "POST"
        assert entry["url"] == "/v1/chat/completions"
        assert entry["body"]["model"] == "gpt-4o-mini"
