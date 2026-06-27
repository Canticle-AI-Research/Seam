from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from benchmarks.external.common.runner import run_benchmark
from benchmarks.external.common.types import (
    AdapterAnswer,
    BenchmarkCase,
    ConversationTurn,
)


class _StubMem0:
    """In-memory stub for mem0.Memory with the subset of the API we use."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.last_top_k: int | None = None

    def add(self, messages: list[dict], user_id: str) -> None:
        self.store.setdefault(user_id, []).extend(messages)

    def search(self, query: str, *, filters: dict, top_k: int) -> dict:
        # mem0 2.x: user_id is passed inside filters, and limit is now top_k.
        self.last_top_k = top_k
        user_id = (filters or {}).get("user_id")
        items = [
            {"memory": m["content"], "score": 1.0}
            for m in self.store.get(user_id, [])
        ][:top_k]
        return {"results": items}

    def delete_all(self, user_id: str) -> None:
        self.store.pop(user_id, None)


class _FlakyMem0(_StubMem0):
    def __init__(self):
        super().__init__()
        self.add_calls = 0
        self.search_calls = 0

    def add(self, messages: list[dict], user_id: str) -> None:
        self.add_calls += 1
        if self.add_calls == 1:
            raise RuntimeError("429 rate limit exceeded")
        super().add(messages, user_id)

    def search(self, query: str, *, filters: dict, top_k: int) -> dict:
        self.search_calls += 1
        if self.search_calls == 1:
            raise RuntimeError("429 rate limit exceeded")
        return super().search(query, filters=filters, top_k=top_k)


def _build_adapter(search_limit: int = 8) -> object:
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    return Mem0LocomoAdapter(search_limit=search_limit, _memory=_StubMem0())


def _sample_turn(speaker: str = "Alice", text: str = "Hello world.") -> ConversationTurn:
    return ConversationTurn(speaker=speaker, text=text)


# -- Constructor tests --------------------------------------------------


def test_constructs_with_stub() -> None:
    adapter = _build_adapter()
    assert adapter.name == "mem0"


def test_missing_dep_raises_clear_error(monkeypatch) -> None:
    """Without mem0ai installed, constructor raises RuntimeError pointing at pip install."""
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    monkeypatch.setitem(sys.modules, "mem0", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"seam\[bench-mem0\]"):
        Mem0LocomoAdapter()


def test_missing_api_key_raises_clear_error(monkeypatch) -> None:
    """Without OPENAI_API_KEY, constructor raises RuntimeError."""
    import types as _types

    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Inject a fake mem0 module so the import succeeds and we reach the key check.
    fake_mem0 = _types.ModuleType("mem0")
    fake_mem0.Memory = type("Memory", (), {"from_config": classmethod(lambda cls, cfg: _StubMem0())})
    monkeypatch.setitem(sys.modules, "mem0", fake_mem0)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        Mem0LocomoAdapter()


def test_module_level_does_not_import_mem0ai() -> None:
    """Importing the adapter module must not load mem0ai into sys.modules."""
    import benchmarks.external.locomo.adapters.mem0  # noqa: F811

    assert "mem0ai" not in sys.modules


def test_constructs_with_config_overrides_no_key() -> None:
    """config_overrides with llm bypasses the OPENAI_API_KEY check."""
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    adapter = Mem0LocomoAdapter(
        config_overrides={"llm": {"provider": "openai", "config": {"api_key": "test"}}},
        _memory=_StubMem0(),
    )
    assert adapter.name == "mem0"


def test_mem0_config_pins_gpt4o_mini_by_default(monkeypatch) -> None:
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    monkeypatch.delenv("SEAM_BENCH_MEM0_LLM_MODEL", raising=False)
    cfg = Mem0LocomoAdapter._build_config("/tmp/mem0-test", None)
    assert cfg["llm"]["provider"] == "openai"
    assert cfg["llm"]["config"]["model"] == "gpt-4o-mini"


def test_mem0_config_model_env_override(monkeypatch) -> None:
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    monkeypatch.setenv("SEAM_BENCH_MEM0_LLM_MODEL", "gpt-4o")
    cfg = Mem0LocomoAdapter._build_config("/tmp/mem0-test", None)
    assert cfg["llm"]["config"]["model"] == "gpt-4o"


def test_mem0_search_limit_env_override(monkeypatch) -> None:
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    memory = _StubMem0()
    monkeypatch.setenv("SEAM_BENCH_MEM0_SEARCH_LIMIT", "32")
    adapter = Mem0LocomoAdapter(_memory=memory)
    scope = "case-search-limit"

    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="Depth fact."))
    adapter.answer(scope, "What fact?")

    assert adapter.search_limit == 32
    assert memory.last_top_k == 32


def test_build_adapter_passes_explicit_mem0_search_limit(monkeypatch) -> None:
    from benchmarks.external.locomo import run as locomo_run
    from benchmarks.external.locomo.adapters import mem0 as mem0_module

    captured: dict[str, int] = {}

    class _FakeMem0:
        name = "mem0"

        def __init__(self, *, search_limit: int = 8):
            captured["search_limit"] = search_limit

    monkeypatch.setattr(mem0_module, "Mem0LocomoAdapter", _FakeMem0)

    adapter = locomo_run.build_adapter("mem0", mem0_search_limit=64)

    assert adapter.name == "mem0"
    assert captured["search_limit"] == 64


# -- Protocol tests -----------------------------------------------------


def test_ingest_turn_and_answer() -> None:
    adapter = _build_adapter()
    scope = "case-1"
    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="My favorite color is blue."))
    adapter.ingest_turn(scope, ConversationTurn(speaker="Bob", text="I have a dog named Max."))

    answer = adapter.answer(scope, "What is Alice's favorite color?")
    assert answer.retrieved_context, "retrieved_context should not be empty"
    assert "blue" in answer.retrieved_context.lower()
    assert answer.generated_answer is None


def test_mem0_add_and_search_retry_transient_rate_limits(monkeypatch) -> None:
    import benchmarks.external.common.provider_retry as provider_retry
    from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

    monkeypatch.setattr(provider_retry.time, "sleep", lambda _delay: None)
    memory = _FlakyMem0()
    adapter = Mem0LocomoAdapter(_memory=memory)
    scope = "case-retry"

    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="Retry fact: teal."))
    answer = adapter.answer(scope, "What color?")

    assert memory.add_calls == 2
    assert memory.search_calls == 2
    assert "teal" in answer.retrieved_context.lower()


def test_reset_clears_scope_state() -> None:
    adapter = _build_adapter()
    scope = "case-2"
    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="Secret code: XYZ-123."))

    answer_before = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" in answer_before.retrieved_context.lower()

    adapter.reset(scope)
    answer_after = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" not in answer_after.retrieved_context.lower()


def test_scopes_are_isolated() -> None:
    adapter = _build_adapter()
    scope_a = "scope-a"
    scope_b = "scope-b"

    adapter.reset(scope_a)
    adapter.ingest_turn(scope_a, ConversationTurn(speaker="Alice", text="I live in Paris."))
    adapter.reset(scope_b)
    adapter.ingest_turn(scope_b, ConversationTurn(speaker="Bob", text="I live in Tokyo."))

    answer_a = adapter.answer(scope_a, "Where does Alice live?")
    answer_b = adapter.answer(scope_b, "Where does Bob live?")

    assert "paris" in answer_a.retrieved_context.lower()
    assert "tokyo" not in answer_a.retrieved_context.lower()
    assert "tokyo" in answer_b.retrieved_context.lower()
    assert "paris" not in answer_b.retrieved_context.lower()


def test_answer_retrieval_latency_populated() -> None:
    adapter = _build_adapter()
    scope = "case-3"
    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="Test fact."))

    answer = adapter.answer(scope, "What was the fact?")
    assert answer.retrieval_latency_ms >= 0
    assert answer.answer_latency_ms == 0.0


def test_close_cleans_temp_dir() -> None:
    """When constructed via stub, close is a no-op (no store_dir)."""
    adapter = _build_adapter()
    adapter.close()  # Should not raise


# -- Runner integration -------------------------------------------------


def _minimal_cases(n: int = 2) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id=f"test-mem0-{i}",
            conversation=(ConversationTurn(speaker="Alice", text=f"Fact {i}: the sky is blue"),),
            question=f"What color is the sky in fact {i}?",
            gold_answer="blue",
            category="test",
        )
        for i in range(n)
    ]


def test_run_benchmark_with_stub_mem0() -> None:
    adapter = _build_adapter()
    cases = _minimal_cases(2)
    report = run_benchmark(adapter=adapter, cases=cases)
    assert report["adapter"] == "mem0"
    assert report["scores"]["context_recall_mean"] == 1.0
    assert len(report["cases"]) == 2


def test_integrity_hash_stable_with_stub_mem0() -> None:
    a = _build_adapter()
    b = _build_adapter()
    cases = _minimal_cases(2)
    r1 = run_benchmark(adapter=a, cases=cases)
    r2 = run_benchmark(adapter=b, cases=cases)
    assert r1["integrity_hash"] == r2["integrity_hash"]


# -- CLI smoke -----------------------------------------------------------


def test_cli_quickstart_mem0_stub() -> None:
    """--adapter mem0 exits non-zero with a clear error and makes NO paid call.

    Run with no LLM key so the adapter fails fast at construction (missing mem0ai
    OR missing OPENAI_API_KEY) regardless of whether mem0ai is installed in the
    test env -- so this never executes a real mem0 quickstart (which would spend)."""
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--adapter", "mem0"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "mem0" in result.stderr.lower() or "openai_api_key" in result.stderr.lower()


def test_cli_quickstart_mem0_flag_accepted() -> None:
    """Verify --adapter mem0 is a valid choice in the argparse parser."""
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.external.locomo.run", "--help"],
        capture_output=True,
        text=True,
    )
    assert "mem0" in result.stdout
