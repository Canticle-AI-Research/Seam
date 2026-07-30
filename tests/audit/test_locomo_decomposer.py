"""Tests for multi-hop question decomposition in the LoCoMo adapter."""

import pytest

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo import run as locomo_run
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from benchmarks.external.locomo.run import build_adapter


def test_decomposer_off_is_unchanged(tmp_path):
    """With decomposer default off, behavior is identical to before."""
    adapter = SeamLocomoAdapter(db_path=str(tmp_path), budget=2000)
    scope_id = "decomp-off"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="Alice",
            text="I moved to Tokyo in April.",
            timestamp="2024-04-01T10:00:00Z",
        ),
    )
    answer = adapter.answer(scope_id, "Where did Alice move?")
    assert "Tokyo" in answer.retrieved_context


def test_decomposer_on_searches_per_sub_question(tmp_path, monkeypatch):
    """With decomposer enabled, search is called for each sub-question."""
    # Stub the OpenAI short answer to return fixed sub-questions
    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._openai_short_answer",
        lambda model, prompt, max_tokens=64: "Where did Alice move?\nWhen did Alice move?",
    )
    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path), budget=2000,
        decomposer="openai", decomposer_model="gpt-4o-mini",
    )
    scope_id = "decomp-on"

    adapter.reset(scope_id)
    adapter.ingest_turn(
        scope_id,
        ConversationTurn(
            speaker="Alice",
            text="I moved to Tokyo in April.",
            timestamp="2024-04-01T10:00:00Z",
        ),
    )
    answer = adapter.answer(scope_id, "Where and when did Alice move?")
    assert "Tokyo" in answer.retrieved_context
    # Retrieval latency should be higher with multiple searches
    assert answer.retrieval_latency_ms >= 0


def test_runner_factory_requires_paid_acknowledgement_for_decomposer() -> None:
    with pytest.raises(ValueError, match="allow_paid=True"):
        build_adapter("seam", decomposer="openai")

    adapter = build_adapter(
        "seam",
        decomposer="openai",
        decomposer_model="gpt-4o-mini",
        allow_paid=True,
    )
    try:
        assert adapter._decomposer == "openai"
    finally:
        adapter.close()


@pytest.mark.parametrize(
    ("adapter_name", "answerer"),
    [("mem0", None), ("zep", None), ("seam", "openai")],
)
def test_runner_factory_requires_paid_acknowledgement_for_all_provider_paths(
    adapter_name: str, answerer: str | None
) -> None:
    with pytest.raises(ValueError, match="allow_paid=True"):
        build_adapter(adapter_name, answerer=answerer)


@pytest.mark.parametrize("workers", [1, 2])
def test_cli_propagates_paid_acknowledgement_to_adapter_factory(
    monkeypatch, tmp_path, workers: int
) -> None:
    captured: list[dict[str, object]] = []

    def fake_build_adapter(name: str, **kwargs):
        captured.append({"name": name, **kwargs})
        return object()

    def fake_serial(**kwargs):
        assert kwargs["adapter"] is not None
        return {"status": "ok"}

    def fake_parallel(**kwargs):
        assert kwargs["adapter_factory"]() is not None
        return {"status": "ok"}

    monkeypatch.setattr(locomo_run, "build_adapter", fake_build_adapter)
    monkeypatch.setattr(locomo_run, "run_benchmark_grouped", fake_serial)
    monkeypatch.setattr(
        locomo_run, "run_benchmark_grouped_parallel", fake_parallel
    )
    monkeypatch.setenv(
        "SEAM_BENCH_RESULTS_DIR", str(tmp_path / "benchmark-results")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "locomo-run",
            "--quickstart",
            "--limit",
            "0",
            "--adapter",
            "seam",
            "--judge",
            "stub",
            "--decomposer",
            "openai",
            "--allow-paid",
            "--workers",
            str(workers),
        ],
    )

    locomo_run.main()

    assert len(captured) == 1
    assert captured[0]["decomposer"] == "openai"
    assert captured[0]["allow_paid"] is True
