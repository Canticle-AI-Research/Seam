"""Fair-comparison harness: the shared answerer wrapper.

A comparator adapter (mem0/zep) returns only retrieved context with
``generated_answer=None``. Without a shared answerer the runner scores it on an
empty prediction (~0 under the judge), which measures whether the adapter
generates an answer rather than the quality of its memory. These tests pin the
wrapper that holds the answerer constant across adapters. All hermetic: no
network, no API keys, no real provider calls.
"""

from __future__ import annotations

import pytest

from benchmarks.external.common.answerer import (
    SharedAnswererAdapter,
    build_answer_prompt,
    generate_short_answer,
)
from benchmarks.external.common.types import AdapterAnswer
from benchmarks.external.locomo.run import _maybe_wrap_answerer


class _FakeInner:
    """Minimal comparator stub that returns a fixed retrieved context."""

    name = "fake"

    def __init__(self, *, generated=None):
        self._answer = AdapterAnswer(
            retrieved_context="ctx text", generated_answer=generated
        )
        self.reset_calls: list[str] = []
        self.ingest_calls: list[tuple] = []
        self.closed = False

    def reset(self, scope_id):
        self.reset_calls.append(scope_id)

    def ingest_turn(self, scope_id, turn):
        self.ingest_calls.append((scope_id, turn))

    def answer(self, scope_id, question):
        return self._answer

    def close(self):
        self.closed = True


def _fake_generate(answerer, model, question, context, *, diag_out=None):
    if diag_out is not None:
        diag_out["called"] = True
    return f"ANS[{context}]"


def test_build_answer_prompt_includes_question_and_context():
    prompt = build_answer_prompt("Who paid?", "Alice paid the bill")
    assert "Who paid?" in prompt
    assert "Alice paid the bill" in prompt


def test_wrapper_generates_answer_for_null_answer_adapter():
    inner = _FakeInner(generated=None)
    wrapped = SharedAnswererAdapter(inner, "openai", None, _generate=_fake_generate)
    out = wrapped.answer("scope1", "q?")
    assert out.generated_answer == "ANS[ctx text]"
    # retrieved context (the memory layer under test) is preserved untouched
    assert out.retrieved_context == "ctx text"
    assert out.answerer_diagnostics == {"called": True}


def test_wrapper_retries_transient_provider_failures(monkeypatch):
    import benchmarks.external.common.provider_retry as provider_retry

    monkeypatch.setattr(provider_retry.time, "sleep", lambda _delay: None)
    calls = {"n": 0}

    def flaky_generate(answerer, model, question, context, *, diag_out=None):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 rate limit exceeded")
        return "recovered"

    inner = _FakeInner(generated=None)
    wrapped = SharedAnswererAdapter(inner, "openai", None, _generate=flaky_generate)

    out = wrapped.answer("scope1", "q?")

    assert calls["n"] == 2
    assert out.generated_answer == "recovered"


def test_wrapper_passes_through_when_adapter_already_generated():
    inner = _FakeInner(generated="already here")
    calls = []

    def _spy(*a, **k):
        calls.append(a)
        return "SHOULD-NOT-RUN"

    wrapped = SharedAnswererAdapter(inner, "openai", None, _generate=_spy)
    out = wrapped.answer("scope1", "q?")
    assert out.generated_answer == "already here"
    assert calls == []  # shared answerer not invoked for self-generating adapters


def test_wrapper_delegates_lifecycle_methods():
    inner = _FakeInner()
    wrapped = SharedAnswererAdapter(inner, "openai", None, _generate=_fake_generate)
    wrapped.reset("s")
    wrapped.ingest_turn("s", object())
    wrapped.close()
    assert inner.reset_calls == ["s"]
    assert len(inner.ingest_calls) == 1
    assert inner.closed is True
    assert wrapped.name == "fake"


def test_maybe_wrap_answerer_noop_without_answerer():
    inner = _FakeInner()
    assert _maybe_wrap_answerer(inner, None, None) is inner


def test_maybe_wrap_answerer_wraps_when_answerer_set():
    inner = _FakeInner()
    wrapped = _maybe_wrap_answerer(inner, "openai", "gpt-4o-mini")
    assert isinstance(wrapped, SharedAnswererAdapter)
    assert wrapped.name == "fake"


def test_generate_short_answer_dispatch_uses_shared_prompt(monkeypatch):
    import benchmarks.external.locomo.adapters.seam as seam

    captured: dict = {}

    def fake_ollama(model, prompt, **kw):
        captured["model"] = model
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(seam, "_ollama_short_answer", fake_ollama)
    out = generate_short_answer("ollama", None, "What happened?", "some context")
    assert out == "ok"
    assert captured["model"] == "qwen2.5:3b"
    assert "some context" in captured["prompt"]
    assert "What happened?" in captured["prompt"]


def test_generate_short_answer_rejects_unknown_answerer():
    with pytest.raises(ValueError):
        generate_short_answer("bogus", None, "q", "ctx")
