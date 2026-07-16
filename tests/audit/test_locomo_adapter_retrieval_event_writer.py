"""H2 slice 2: SeamLocomoAdapter writes retrieval_event rows when enabled.

The adapter is the canonical live producer of retrieval-outcome events
(see docs/roadmap/CONTEXT_STREAMS.md section 12.5). These tests pin the
opt-in contract, the payload shape, and the "diagnostic write must not
break the benchmark" guardrail.

Tests avoid the heavy default embedding model by monkeypatching
``_open_runtime`` to return a FakeRuntime that exposes a real SQLiteStore
as ``.store`` (so write_retrieval_event hits the real append-only path).
"""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.external.locomo import run as locomo_run
from benchmarks.external.locomo.adapters import seam as seam_adapter
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.storage import SQLiteStore


@dataclass
class _FakeRecord:
    id: str
    evidence: list[str] | None = None
    prov: list[str] | None = None
    kind: object = None
    attrs: dict | None = None


@dataclass
class _FakeCandidate:
    record: _FakeRecord
    score: float
    reasons: list[str]


@dataclass
class _FakeResult:
    candidates: list[_FakeCandidate]


class _FakeRuntime:
    """Just enough surface for SeamLocomoAdapter.answer() to write events.

    Holds a real SQLiteStore so the append-only contract is exercised.
    """

    def __init__(self, store: SQLiteStore, candidates: list[_FakeCandidate] | None = None) -> None:
        self.store = store
        self._candidates = candidates if candidates is not None else []

    def ingest_conversation_turn(self, **_kwargs):
        return None

    def search_ir(self, query, **_kwargs):
        return _FakeResult(candidates=list(self._candidates))

    def pack_ir(self, *_args, **_kwargs):
        class _Pack:
            def to_dict(self):
                return {}

        return _Pack()


def _install_fake_runtime(monkeypatch, store: SQLiteStore, candidates=None):
    rt = _FakeRuntime(store, candidates=candidates)
    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._open_runtime",
        lambda _db_path: rt,
    )
    return rt


def _default_candidates() -> list[_FakeCandidate]:
    return [
        _FakeCandidate(_FakeRecord("raw:turn:001"), 0.91, ["lexical=0.4", "semantic=0.8"]),
        _FakeCandidate(_FakeRecord("raw:turn:002"), 0.42, ["semantic=0.42"]),
        _FakeCandidate(_FakeRecord("raw:turn:003"), 0.05, ["graph=0.05"]),
    ]


def test_default_off_writes_no_event(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, _default_candidates())
    # Make sure no inherited env flag forces recording on.
    monkeypatch.delenv("SEAM_RECORD_RETRIEVAL_EVENTS", raising=False)
    monkeypatch.delenv("SEAM_RUN_ID", raising=False)

    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)
    adapter.answer("scope", "what happened?")

    assert store.count_retrieval_events() == 0


def test_constructor_flag_enables_writer_and_event_round_trips(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, _default_candidates())
    monkeypatch.delenv("SEAM_RECORD_RETRIEVAL_EVENTS", raising=False)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path),
        budget=2000,
        record_retrieval_events=True,
        run_id="run-test-explicit",
    )
    adapter.answer("conv-7", "who came to dinner?")

    events = store.iter_retrieval_events(run_id="run-test-explicit")
    assert len(events) == 1
    event = events[0]
    assert event["scope"] == "locomo:conv-7"
    assert event["query"] == "who came to dinner?"
    assert event["candidate_ids"] == ["raw:turn:001", "raw:turn:002", "raw:turn:003"]
    assert event["ranks"] == [1, 2, 3]
    assert event["scores"] == [0.91, 0.42, 0.05]
    assert event["reasons"] == ["lexical=0.4, semantic=0.8", "semantic=0.42", "graph=0.05"]
    assert event["source_kind"] == "live"
    assert event["stale_source"] is False
    # No answerer was configured, so generated answer + judge stay null.
    assert event["answer"] is None
    assert event["judge_score"] is None
    assert event["context_recall"] is None
    # context_hash is the sha256 of retrieved_context; empty context -> null.
    assert event["context_hash"] is None  # FakeRuntime returns no RAW records
    extra = event["extra"] or {}
    assert "top_score" in extra
    assert extra["top_score"] == 0.91
    assert "retrieval_latency_ms" in extra


def test_env_var_enables_writer_without_constructor_flag(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, _default_candidates())
    monkeypatch.setenv("SEAM_RECORD_RETRIEVAL_EVENTS", "1")
    monkeypatch.setenv("SEAM_RUN_ID", "run-from-env")

    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)
    adapter.answer("scope-env", "anything?")

    events = store.iter_retrieval_events(run_id="run-from-env")
    assert len(events) == 1
    assert events[0]["scope"] == "locomo:scope-env"


def test_run_id_auto_generated_when_unset(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, _default_candidates())
    monkeypatch.delenv("SEAM_RUN_ID", raising=False)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path),
        budget=2000,
        record_retrieval_events=True,
    )
    adapter.answer("scope-a", "q1")
    adapter.answer("scope-b", "q2")

    events = store.iter_retrieval_events()
    assert len(events) == 2
    run_ids = {ev["run_id"] for ev in events}
    # Same adapter instance -> same auto-generated run_id across calls.
    assert len(run_ids) == 1
    (rid,) = run_ids
    assert rid.startswith("seam-locomo-")


def test_empty_candidates_still_writes_event(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, candidates=[])  # search returns nothing
    monkeypatch.delenv("SEAM_RECORD_RETRIEVAL_EVENTS", raising=False)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path),
        budget=2000,
        search_top_k=20,  # pin explicitly so the diagnostics assert is default-independent
        record_retrieval_events=True,
        run_id="run-empty",
    )
    answer = adapter.answer("scope-empty", "question nobody asked")

    # Empty retrieval still returns a valid (empty) AdapterAnswer.
    assert answer.retrieved_context == ""
    events = store.iter_retrieval_events(run_id="run-empty")
    assert len(events) == 1
    event = events[0]
    assert event["candidate_ids"] == []
    assert event["ranks"] is None
    assert event["scores"] is None
    extra = event["extra"] or {}
    assert extra["answerer_diagnostics"] == answer.answerer_diagnostics
    assert extra["answerer_diagnostics"]["retrieval_policy"] == {
        "mode": "baseline",
        "context_char_budget": 2000,
        "search_top_k": 20,
        "rerank_top_k": 20,
    }


def test_writer_failure_does_not_break_answer(monkeypatch, tmp_path):
    store = SQLiteStore(tmp_path / "scope.db")
    _install_fake_runtime(monkeypatch, store, _default_candidates())

    def _boom(**_kwargs):
        raise RuntimeError("simulated SQLite write failure")

    monkeypatch.setattr(store, "write_retrieval_event", _boom)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path),
        budget=2000,
        record_retrieval_events=True,
        run_id="run-boom",
    )
    # Must not raise; instrumentation failures must not abort benchmark answers.
    answer = adapter.answer("scope", "hello?")
    assert answer is not None
    # And no row was written.
    assert store.count_retrieval_events() == 0


def test_env_truthy_helper_accepts_common_values():
    assert seam_adapter._env_truthy("1") is True
    assert seam_adapter._env_truthy("true") is True
    assert seam_adapter._env_truthy("YES") is True
    assert seam_adapter._env_truthy("on") is True
    assert seam_adapter._env_truthy("0") is False
    assert seam_adapter._env_truthy("false") is False
    assert seam_adapter._env_truthy("") is False
    assert seam_adapter._env_truthy(None) is False


def test_build_adapter_forwards_retrieval_event_writer_flags(tmp_path):
    adapter = locomo_run.build_adapter(
        "seam",
        db_path=str(tmp_path),
        record_retrieval_events=True,
        retrieval_event_run_id="run-build-adapter",
    )

    assert adapter._record_events is True
    assert adapter._run_id == "run-build-adapter"


def test_build_adapter_forwards_semantic_recovery_policy(tmp_path):
    adapter = locomo_run.build_adapter(
        "seam",
        db_path=str(tmp_path),
        context_budget=8000,
        search_top_k=100,
        rerank_top_k=40,
        semantic_recovery_mode="pack-budget-deep",
    )

    assert adapter.budget == 8000
    assert adapter._search_top_k == 100
    assert adapter._rerank_top_k == 40
    assert adapter.semantic_recovery_policy.to_dict() == {
        "mode": "pack-budget-deep",
        "context_char_budget": 8000,
        "search_top_k": 100,
        "rerank_top_k": 40,
    }


def test_cli_forwards_retrieval_event_writer_flags(monkeypatch, tmp_path):
    captured = {}

    def fake_run_benchmark_grouped(**kwargs):
        captured["adapter"] = kwargs["adapter"]
        return {"ok": True}

    monkeypatch.setattr(locomo_run, "run_benchmark_grouped", fake_run_benchmark_grouped)
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "0",
            "--db-path",
            str(tmp_path),
            "--record-retrieval-events",
            "--retrieval-event-run-id",
            "run-cli",
        ],
    )

    locomo_run.main()

    adapter = captured["adapter"]
    assert adapter._record_events is True
    assert adapter._run_id == "run-cli"


def test_cli_forwards_semantic_recovery_policy(monkeypatch, tmp_path):
    captured = {}

    def fake_run_benchmark_grouped(**kwargs):
        captured["adapter"] = kwargs["adapter"]
        return {"ok": True}

    monkeypatch.setattr(locomo_run, "run_benchmark_grouped", fake_run_benchmark_grouped)
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "0",
            "--db-path",
            str(tmp_path),
            "--semantic-recovery-mode",
            "pack-budget-deep",
            "--context-budget",
            "8000",
            "--search-top-k",
            "100",
            "--rerank-top-k",
            "40",
        ],
    )

    locomo_run.main()

    adapter = captured["adapter"]
    assert adapter.semantic_recovery_policy.to_dict() == {
        "mode": "pack-budget-deep",
        "context_char_budget": 8000,
        "search_top_k": 100,
        "rerank_top_k": 40,
    }
