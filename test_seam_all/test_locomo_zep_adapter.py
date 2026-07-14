from __future__ import annotations

import os
import subprocess
import sys
import types as _types

import pytest

from benchmarks.external.common.runner import run_benchmark
from benchmarks.external.common.types import (
    BenchmarkCase,
    ConversationTurn,
)


class _StubZepUser:
    def __init__(self, parent):
        self._parent = parent

    def add(self, user_id: str) -> None:
        self._parent.users.add(user_id)
        self._parent.messages.setdefault(user_id, [])

    def delete(self, user_id: str) -> None:
        self._parent.users.discard(user_id)
        self._parent.messages.pop(user_id, None)
        # Also clean any thread_ids that map to this user.
        stale = [tid for tid, uid in self._parent.threads.items() if uid == user_id]
        for tid in stale:
            self._parent.threads.pop(tid, None)


class _StubZepThread:
    def __init__(self, parent):
        self._parent = parent

    def create(self, *, thread_id: str, user_id: str) -> None:
        self._parent.threads[thread_id] = user_id
        self._parent.messages.setdefault(user_id, [])

    def add_messages(self, thread_id: str, *, messages) -> None:
        user_id = self._parent.threads[thread_id]
        self._parent.messages.setdefault(user_id, []).extend(messages)


class _StubZepEpisode:
    def __init__(self, parent):
        self._parent = parent

    def get_by_user_id(self, user_id: str, *, lastn: int | None = None):
        # Stub processing is synchronous: every ingested message is an
        # already-processed episode.
        msgs = self._parent.messages.get(user_id, [])
        if lastn is not None:
            msgs = msgs[-lastn:]
        episodes = [_types.SimpleNamespace(processed=True) for _ in msgs]
        return _types.SimpleNamespace(episodes=episodes)


class _StubZepGraph:
    def __init__(self, parent):
        self._parent = parent
        self.episode = _StubZepEpisode(parent)

    def search(self, *, query: str, user_id: str, scope: str, limit: int):
        if scope == "edges":
            edges = [
                _types.SimpleNamespace(
                    fact=_content(m), valid_at=None, invalid_at=None
                )
                for m in self._parent.messages.get(user_id, [])[:limit]
            ]
            return _types.SimpleNamespace(edges=edges, nodes=None)
        return _types.SimpleNamespace(edges=None, nodes=[])


def _content(message) -> str:
    if isinstance(message, dict):
        return message["content"]
    return message.content


class _StubZep:
    def __init__(self, **kw):
        self.users: set[str] = set()
        self.threads: dict[str, str] = {}
        self.messages: dict[str, list] = {}
        self.user = _StubZepUser(self)
        self.thread = _StubZepThread(self)
        self.graph = _StubZepGraph(self)


def _build_adapter(search_limit: int = 8) -> object:
    from benchmarks.external.locomo.adapters.zep import ZepLocomoAdapter

    return ZepLocomoAdapter(search_limit=search_limit, _client=_StubZep())


def _sample_turn(speaker: str = "Alice", text: str = "Hello world.") -> ConversationTurn:
    return ConversationTurn(speaker=speaker, text=text)


# -- Constructor tests --------------------------------------------------


def test_constructs_with_stub() -> None:
    adapter = _build_adapter()
    assert adapter.name == "zep"


def test_missing_dep_raises_clear_error(monkeypatch) -> None:
    """Without zep-cloud/zep-python, or without API keys, constructor raises RuntimeError."""
    from benchmarks.external.locomo.adapters.zep import ZepLocomoAdapter

    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    # Remove both candidates from sys.modules so imports fail
    for key in list(sys.modules.keys()):
        if key.startswith("zep"):
            monkeypatch.delitem(sys.modules, key, raising=False)
    with pytest.raises(RuntimeError):
        ZepLocomoAdapter()


def test_missing_key_and_url_raises_clear_error(monkeypatch) -> None:
    """Without ZEP_API_KEY or ZEP_API_URL, constructor raises RuntimeError."""
    from benchmarks.external.locomo.adapters.zep import ZepLocomoAdapter

    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_URL", raising=False)

    # Inject a fake zep_cloud module so the import succeeds.
    fake_zep_cloud = _types.ModuleType("zep_cloud")
    fake_client = _types.ModuleType("zep_cloud.client")
    fake_client.Zep = _StubZep
    fake_zep_cloud.client = fake_client
    monkeypatch.setitem(sys.modules, "zep_cloud", fake_zep_cloud)
    monkeypatch.setitem(sys.modules, "zep_cloud.client", fake_client)

    with pytest.raises(RuntimeError, match="ZEP_API_KEY"):
        ZepLocomoAdapter()


def test_module_level_does_not_import_zep_sdk() -> None:
    """Importing the adapter module must not eagerly load zep_cloud or zep_python."""
    zep_before = {k for k in sys.modules if k.startswith("zep")}

    import benchmarks.external.locomo.adapters.zep  # noqa: F811, F401

    zep_after = {k for k in sys.modules if k.startswith("zep")}
    newly_loaded = zep_after - zep_before
    assert not newly_loaded, (
        f"Importing the zep adapter should not load zep SDK modules; got {newly_loaded}"
    )


# -- Protocol tests -----------------------------------------------------


def test_ingest_turn_and_answer() -> None:
    adapter = _build_adapter()
    scope = "case-z1"
    adapter.reset(scope)
    adapter.ingest_turn(
        scope, ConversationTurn(speaker="Alice", text="My favorite color is blue.")
    )
    adapter.ingest_turn(
        scope, ConversationTurn(speaker="Bob", text="I have a dog named Max.")
    )

    answer = adapter.answer(scope, "What is Alice's favorite color?")
    assert answer.retrieved_context, "retrieved_context should not be empty"
    assert "blue" in answer.retrieved_context.lower()
    assert answer.generated_answer is None


def test_reset_clears_scope_state() -> None:
    adapter = _build_adapter()
    scope = "case-z2"
    adapter.reset(scope)
    adapter.ingest_turn(
        scope, ConversationTurn(speaker="Alice", text="Secret code: XYZ-123.")
    )

    answer_before = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" in answer_before.retrieved_context.lower()

    adapter.reset(scope)
    answer_after = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" not in answer_after.retrieved_context.lower()


def test_scopes_are_isolated() -> None:
    adapter = _build_adapter()
    scope_a = "scope-za"
    scope_b = "scope-zb"

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
    scope = "case-z3"
    adapter.reset(scope)
    adapter.ingest_turn(scope, ConversationTurn(speaker="Alice", text="Test fact."))

    answer = adapter.answer(scope, "What was the fact?")
    assert answer.retrieval_latency_ms >= 0
    assert answer.answer_latency_ms == 0.0


def test_close_cleans_up(monkeypatch) -> None:
    """close() should clear thread state without raising."""
    adapter = _build_adapter()
    scope = "case-z4"
    adapter.reset(scope)
    adapter.close()
    assert not adapter._threads


# -- Runner integration -------------------------------------------------


def _minimal_cases(n: int = 2) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id=f"test-zep-{i}",
            conversation=(
                ConversationTurn(speaker="Alice", text=f"Fact {i}: the sky is blue"),
            ),
            question=f"What color is the sky in fact {i}?",
            gold_answer="blue",
            category="test",
        )
        for i in range(n)
    ]


def test_run_benchmark_with_stub_zep() -> None:
    adapter = _build_adapter()
    cases = _minimal_cases(2)
    report = run_benchmark(adapter=adapter, cases=cases)
    assert report["adapter"] == "zep"
    assert report["scores"]["context_recall_mean"] == 1.0
    assert len(report["cases"]) == 2


def test_integrity_hash_stable_with_stub_zep() -> None:
    a = _build_adapter()
    b = _build_adapter()
    cases = _minimal_cases(2)
    r1 = run_benchmark(adapter=a, cases=cases)
    r2 = run_benchmark(adapter=b, cases=cases)
    assert r1["integrity_hash"] == r2["integrity_hash"]


# -- CLI smoke -----------------------------------------------------------


def test_cli_quickstart_zep_flag_accepted() -> None:
    """Verify --adapter zep is a valid choice in the argparse parser."""
    result = subprocess.run(
        [sys.executable, "-m", "benchmarks.external.locomo.run", "--help"],
        capture_output=True,
        text=True,
    )
    assert "zep" in result.stdout


def test_cli_quickstart_zep_no_sdk(tmp_path) -> None:
    """--adapter zep fails safely when the optional SDK is unavailable.

    Keep this hermetic even in an all-extras development environment by
    shadowing the installed package with a temporary module that raises on
    import.  Removing Zep credentials is defense-in-depth against a broken
    shadow accidentally reaching the real service.
    """
    blocked_sdk = tmp_path / "zep_cloud"
    blocked_sdk.mkdir()
    (blocked_sdk / "__init__.py").write_text(
        'raise ImportError("simulated missing zep-cloud SDK")\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(tmp_path), env.get("PYTHONPATH", "")) if part
    )
    env.pop("ZEP_API_KEY", None)
    env.pop("ZEP_API_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.external.locomo.run",
            "--quickstart",
            "--adapter",
            "zep",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "zep" in result.stderr.lower()


# -- Combined adapter+judge smoke ----------------------------------------


def test_combined_zep_adapter_with_stub_judge() -> None:
    from benchmarks.external.common.judge import StubJudge

    adapter = _build_adapter()
    cases = _minimal_cases(2)
    report = run_benchmark(adapter=adapter, cases=cases, judge=StubJudge())
    assert report["adapter"] == "zep"
    assert report["scores"]["judge_score_mean"] == 0.0
    assert report["cases"][0]["judge"]["verdict"] == "abstain"
