"""Tests for the SEAM-augmented /chat endpoint validation and key resolution.

These cover the free, no-network paths only: request validation and the
no-API-key guard. Actual provider calls (which cost money / need a running local
model) are not exercised here.
"""
import pytest
from fastapi.testclient import TestClient

import seam_runtime.server as srv
from seam_runtime.server import create_app_from_env, _seam_chat_system_prompt


class TestChatEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_chat.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        # Default to the no-Docker SQLite vector adapter; tests that want a broken
        # backend set SEAM_PGVECTOR_DSN explicitly.
        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        # Ensure no ambient provider keys leak into the no-key test.
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    def _client(self):
        return TestClient(create_app_from_env())

    def test_chat_requires_message(self):
        resp = self._client().post("/chat", json={"model": "gpt-4o-mini"})
        assert resp.status_code == 400

    def test_chat_requires_model(self):
        resp = self._client().post("/chat", json={"message": "hello"})
        assert resp.status_code == 400

    def test_chat_no_key_for_cloud_provider_is_clear_error(self):
        resp = self._client().post("/chat", json={
            "message": "what does alice prefer?",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "env_key": "OPENAI_API_KEY",
        })
        assert resp.status_code == 400
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    def test_chat_browser_key_overrides_env_absence(self, monkeypatch):
        # With an explicit (bogus) key the key-guard passes, so the request reaches
        # the provider call and fails there (502), not at validation (400).
        resp = self._client().post("/chat", json={
            "message": "hi",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "env_key": "OPENAI_API_KEY",
            "api_key": "invalid-test-key-not-real",
            "use_memory": False,
        })
        assert resp.status_code == 502

    def test_system_prompt_includes_context_and_instruction(self):
        prompt = _seam_chat_system_prompt("[clm:1] Alice prefers dark mode")
        assert "SEAM" in prompt
        assert "[clm:1]" in prompt
        empty = _seam_chat_system_prompt("")
        assert "No relevant SEAM memory" in empty

    def test_chat_injects_retrieved_memory_into_prompt(self, monkeypatch):
        """Regression: memory_used must reflect injected content, and the retrieved
        record text must actually reach the system prompt.

        MIRL records carry no plain ``text`` field (content lives in ``attrs``); an
        earlier version read ``record.text`` and silently injected nothing while
        still reporting memory_used > 0.
        """
        captured: dict = {}

        def fake_provider(*, provider, base_url, api_key, model, messages, **kw):
            captured["system"] = next((m["content"] for m in messages if m["role"] == "system"), "")
            return "stubbed-reply"

        monkeypatch.setattr(srv, "_call_chat_provider", fake_provider)
        client = self._client()
        seed = client.post("/compile", json={
            "text": "Alice prefers dark mode and drinks oat milk lattes.", "persist": True})
        assert seed.status_code == 200

        resp = client.post("/chat", json={
            "message": "what does alice prefer?", "model": "gpt-4o-mini",
            "provider": "OpenAI", "base_url": "https://api.openai.com/v1",
            "api_key": "stub", "use_memory": True, "budget": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_used"] >= 1
        assert "memory_error" not in body
        # The injected context is non-empty and carries the retrieved record content.
        assert "No relevant SEAM memory" not in captured["system"]
        assert "Retrieved SEAM memory" in captured["system"]
        assert "alice" in captured["system"].lower()

    def test_chat_persists_user_and_assistant_turns_by_default(self, monkeypatch):
        monkeypatch.setattr(srv, "_call_chat_provider", lambda **kw: "Alice prefers dark mode.")
        client = self._client()

        resp = client.post("/chat", json={
            "message": "Remember that Alice prefers dark mode.",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "stub",
            "use_memory": False,
        })

        assert resp.status_code == 200
        body = resp.json()
        stored_ids = body["persisted_memory"]["stored_ids"]
        assert stored_ids
        assert body["persisted_memory"]["turn_source_refs"]["user"].startswith("chat://")
        assert body["persisted_memory"]["turn_source_refs"]["assistant"].startswith("chat://")

        search = client.get("/search", params={"query": "Alice dark mode", "budget": 5})
        assert search.status_code == 200
        payload = search.json()
        serialized = str(payload).lower()
        assert "alice prefers dark mode" in serialized

    def test_chat_can_disable_turn_persistence(self, monkeypatch):
        monkeypatch.setattr(srv, "_call_chat_provider", lambda **kw: "The reply should stay transient.")
        client = self._client()

        resp = client.post("/chat", json={
            "message": "This chat turn should not persist.",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "stub",
            "use_memory": False,
            "persist_chat": False,
        })

        assert resp.status_code == 200
        assert "persisted_memory" not in resp.json()
        search = client.get("/search", params={"query": "transient reply", "budget": 5})
        assert search.status_code == 200
        assert "transient reply" not in str(search.json()["candidates"]).lower()

    def test_chat_degrades_when_memory_backend_unavailable(self, monkeypatch):
        """Regression: a retrieval/backend failure must degrade to a no-memory answer
        (200 + memory_error), not surface as a raw 500."""
        monkeypatch.setenv(
            "SEAM_PGVECTOR_DSN",
            "host=127.0.0.1 port=55432 dbname=seam user=seam password=nope",
        )
        monkeypatch.setattr(srv, "_call_chat_provider", lambda **kw: "stubbed-reply")
        resp = self._client().post("/chat", json={
            "message": "hi", "model": "gpt-4o-mini", "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1", "api_key": "stub",
            "use_memory": True, "budget": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"] == "stubbed-reply"
        assert body["memory_used"] == 0
        assert "memory_error" in body
