from __future__ import annotations

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter


def test_ingest_and_answer(tmp_path) -> None:
    """Ingest turns with different facts, then answer a question about one fact."""
    db_path = str(tmp_path / "test.db")
    adapter = SeamLocomoAdapter(db_path=db_path)

    scope = "session-1"
    adapter.ingest_turn(
        scope,
        ConversationTurn(speaker="Alice", text="My favorite color is blue."),
    )
    adapter.ingest_turn(
        scope,
        ConversationTurn(speaker="Bob", text="I have a dog named Max."),
    )

    answer = adapter.answer(scope, "What is Alice's favorite color?")
    assert answer.retrieved_context, "retrieved_context should not be empty"

    # The retrieved context (MIRL JSON) should contain the fact Alice mentioned.
    assert "blue" in answer.retrieved_context.lower(), (
        f"expected 'blue' in retrieved context, got: {answer.retrieved_context[:300]!r}"
    )


def test_reset_clears_state(tmp_path) -> None:
    """After reset, previously ingested data is no longer retrievable."""
    db_path = str(tmp_path / "test.db")
    adapter = SeamLocomoAdapter(db_path=db_path)
    scope = "session-1"

    adapter.ingest_turn(
        scope,
        ConversationTurn(speaker="Alice", text="My secret code is XYZ-123."),
    )

    # Confirm the turn is retrievable.
    answer_before = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" in answer_before.retrieved_context.lower(), (
        f"expected 'xyz-123' in context before reset, "
        f"got: {answer_before.retrieved_context[:300]!r}"
    )

    # Reset and verify the data is gone.
    adapter.reset(scope)
    answer_after = adapter.answer(scope, "What is the secret code?")
    assert "xyz-123" not in answer_after.retrieved_context.lower(), (
        f"expected 'xyz-123' to be absent after reset, "
        f"got: {answer_after.retrieved_context[:300]!r}"
    )


def test_adapter_generated_answer_is_none(tmp_path) -> None:
    """After ingest+answer, AdapterAnswer.generated_answer is None (retrieval-only)."""
    db_path = str(tmp_path / "test.db")
    adapter = SeamLocomoAdapter(db_path=db_path)
    scope = "session-1"

    adapter.ingest_turn(
        scope,
        ConversationTurn(speaker="Alice", text="The meeting is at 3 PM."),
    )
    answer = adapter.answer(scope, "When is the meeting?")
    assert answer.generated_answer is None, (
        f"expected generated_answer=None, got {answer.generated_answer!r}"
    )
    assert answer.retrieved_context, "retrieved_context should not be empty"


def test_scopes_are_isolated(tmp_path) -> None:
    """Data ingested into different scopes does not leak across scopes."""
    db_path = str(tmp_path / "test.db")
    adapter = SeamLocomoAdapter(db_path=db_path)

    scope_a = "scope-a"
    scope_b = "scope-b"

    adapter.ingest_turn(
        scope_a,
        ConversationTurn(speaker="Alice", text="I live in Paris."),
    )
    adapter.ingest_turn(
        scope_b,
        ConversationTurn(speaker="Bob", text="I live in Tokyo."),
    )

    answer_a = adapter.answer(scope_a, "Where does Alice live?")
    answer_b = adapter.answer(scope_b, "Where does Bob live?")

    # Scope A should retrieve Paris, not Tokyo.
    assert "paris" in answer_a.retrieved_context.lower(), (
        f"scope_a should contain 'Paris', got: {answer_a.retrieved_context!r}"
    )
    assert "tokyo" not in answer_a.retrieved_context.lower(), (
        f"scope_a should not contain 'Tokyo', got: {answer_a.retrieved_context!r}"
    )

    # Scope B should retrieve Tokyo, not Paris.
    assert "tokyo" in answer_b.retrieved_context.lower(), (
        f"scope_b should contain 'Tokyo', got: {answer_b.retrieved_context!r}"
    )
    assert "paris" not in answer_b.retrieved_context.lower(), (
        f"scope_b should not contain 'Paris', got: {answer_b.retrieved_context!r}"
    )

    # The retrieved contexts should differ (different data in each scope).
    assert answer_a.retrieved_context != answer_b.retrieved_context, (
        "retrieved contexts for different scopes should not be identical"
    )
