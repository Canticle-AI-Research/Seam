"""Contract tests for the SEAM mem0 harness adapter.

These tests verify the adapter shape and behaviour against a tiny in-repo
fixture. No network, upstream harness clone, or API keys required.
"""
import tempfile

import pytest


@pytest.fixture
def adapter():
    from benchmarks.external.mem0_harness.adapter import SeamMem0HarnessAdapter

    with tempfile.TemporaryDirectory() as tmp:
        yield SeamMem0HarnessAdapter(db_root=tmp)


class TestMem0HarnessAdapterContract:
    """Verify the adapter exposes the expected harness protocol."""

    def test_adapter_has_name(self, adapter):
        assert adapter.name == "seam"

    def test_add_ingests_messages_without_error(self, adapter):
        messages = [
            {"role": "user", "content": "My name is Alice and I live in Tokyo."},
            {"role": "assistant", "content": "Hello Alice! Tokyo is a beautiful city."},
        ]
        adapter.add(messages, user_id="test-user-1")

    def test_search_after_add_returns_results(self, adapter):
        messages = [
            {"role": "user", "content": "I work on machine learning systems at Acme Corp."},
            {"role": "assistant", "content": "That sounds interesting. What kind of ML?"},
            {"role": "user", "content": "Mostly NLP and memory systems."},
        ]
        adapter.add(messages, user_id="test-user-2")
        results = adapter.search("What does the user work on?", user_id="test-user-2", limit=5)
        assert isinstance(results, list)

    def test_search_returns_memoryresult_objects(self, adapter):
        messages = [
            {"role": "user", "content": "My favorite programming language is Rust."},
        ]
        adapter.add(messages, user_id="test-user-3")
        results = adapter.search("favorite programming language", user_id="test-user-3", limit=3)
        assert len(results) > 0
        result = results[0]
        assert result.id
        assert isinstance(result.memory, str)
        assert len(result.memory) > 0
        assert isinstance(result.score, float)

    def test_search_unknown_user_returns_empty(self, adapter):
        results = adapter.search("anything", user_id="nonexistent-user", limit=5)
        assert results == []

    def test_delete_clears_memory(self, adapter):
        messages = [{"role": "user", "content": "Secret message to be deleted."}]
        adapter.add(messages, user_id="test-delete")
        results_before = adapter.search("Secret", user_id="test-delete", limit=5)
        assert len(results_before) > 0

        adapter.delete(user_id="test-delete")
        results_after = adapter.search("Secret", user_id="test-delete", limit=5)
        assert results_after == []

    def test_multiple_users_isolated(self, adapter):
        adapter.add(
            [{"role": "user", "content": "Alice's data: she likes coffee."}],
            user_id="alice",
        )
        adapter.add(
            [{"role": "user", "content": "Bob's data: he likes tea."}],
            user_id="bob",
        )
        alice_results = adapter.search("coffee", user_id="alice", limit=5)
        bob_results = adapter.search("coffee", user_id="bob", limit=5)
        assert len(alice_results) > 0
        # Bob's results should not match "coffee" better than Alice's.
        alice_best = max(r.score for r in alice_results)
        bob_best = max(r.score for r in bob_results) if bob_results else 0.0
        assert alice_best >= bob_best, (
            f"Alice's best coffee score ({alice_best}) should be >= Bob's ({bob_best})"
        )

    def test_add_handles_empty_messages(self, adapter):
        adapter.add([], user_id="empty-user")
        results = adapter.search("anything", user_id="empty-user", limit=5)
        assert results == []

    def test_adapter_cli_dry_run(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.mem0_harness.adapter", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "dry-run" in result.stdout.lower()
        assert "seam" in result.stdout.lower()
