"""Tests for the SEAM-augmented /chat endpoint validation and key resolution.

These cover free paths only. The loopback credential-boundary regression uses
a synthetic local HTTP listener; no paid or remote provider is contacted.
"""
import http.server
import json
import threading

import pytest
from fastapi.testclient import TestClient

import seam_runtime.server as srv
from seam_runtime.server import _seam_chat_system_prompt, create_app_from_env


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
        captured: dict[str, str] = {}

        def fake_provider(**kwargs):
            captured["api_key"] = kwargs["api_key"]
            return "explicit key accepted"

        monkeypatch.setattr(srv, "_validate_provider_base_url", lambda base_url: False)
        monkeypatch.setattr(srv, "_call_chat_provider", fake_provider)
        resp = self._client().post("/chat", json={
            "message": "hi",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "env_key": "OPENAI_API_KEY",
            "api_key": "invalid-test-key-not-real",
            "use_memory": False,
            "persist_chat": False,
        })
        assert resp.status_code == 200
        assert captured["api_key"] == "invalid-test-key-not-real"

    def test_chat_remote_builtin_resolves_only_its_bound_env_key(self, monkeypatch):
        captured: dict[str, str] = {}

        def fake_provider(**kwargs):
            captured["api_key"] = kwargs["api_key"]
            return "environment key accepted"

        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-key")
        monkeypatch.setattr(srv, "_validate_provider_base_url", lambda base_url: False)
        monkeypatch.setattr(srv, "_call_chat_provider", fake_provider)

        resp = self._client().post("/chat", json={
            "message": "hi",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "env_key": "OPENAI_API_KEY",
            "use_memory": False,
            "persist_chat": False,
        })

        assert resp.status_code == 200
        assert captured["api_key"] == "synthetic-provider-key"

    def test_chat_empty_base_url_uses_provider_specific_default(self, monkeypatch):
        captured: dict[str, str] = {}

        def fake_provider(**kwargs):
            captured["api_key"] = kwargs["api_key"]
            captured["base_url"] = kwargs["base_url"]
            return "environment key accepted"

        monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-anthropic-key")
        monkeypatch.setattr(srv, "_call_chat_provider", fake_provider)

        resp = self._client().post("/chat", json={
            "message": "hi",
            "model": "claude-test-model",
            "provider": "Anthropic",
            "base_url": "",
            "env_key": "ANTHROPIC_API_KEY",
            "use_memory": False,
            "persist_chat": False,
        })

        assert resp.status_code == 200
        assert captured == {
            "api_key": "synthetic-anthropic-key",
            "base_url": "",
        }

    @pytest.mark.parametrize("endpoint", ["/chat", "/chat/stream"])
    @pytest.mark.parametrize("env_key", ["SEAM_TEST_UNRELATED_VALUE", "ANTHROPIC_API_KEY"])
    def test_chat_rejects_unbound_env_key_before_provider_call(
        self, monkeypatch, endpoint, env_key
    ):
        monkeypatch.setenv(env_key, "synthetic-unrelated-value")
        monkeypatch.setattr(srv, "_validate_provider_base_url", lambda base_url: False)
        monkeypatch.setattr(
            srv,
            "_call_chat_provider",
            lambda **kwargs: pytest.fail("provider must not be called"),
        )

        resp = self._client().post(endpoint, json={
            "message": "hi",
            "model": "gpt-4o-mini",
            "provider": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "env_key": env_key,
            "use_memory": False,
            "persist_chat": False,
        })

        assert resp.status_code == 400
        assert "matching built-in chat provider" in resp.json()["detail"]

    def test_chat_loopback_never_forwards_request_selected_env_value(self, monkeypatch):
        canary_value = "synthetic-loopback-canary-value"
        monkeypatch.setenv("SEAM_TEST_LOOPBACK_CANARY", canary_value)
        received_authorization: list[str] = []

        class _LocalProvider(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib hook name
                received_authorization.append(self.headers.get("Authorization", ""))
                content_length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(content_length)
                body = json.dumps({
                    "choices": [{"message": {"content": "synthetic local reply"}}]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LocalProvider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        try:
            resp = self._client().post("/chat", json={
                "message": "hi",
                "model": "local-model",
                "provider": "local",
                "base_url": f"http://127.0.0.1:{provider.server_address[1]}/v1",
                "env_key": "SEAM_TEST_LOOPBACK_CANARY",
                "use_memory": False,
                "persist_chat": False,
            })
        finally:
            provider.shutdown()
            provider.server_close()
            thread.join(timeout=5)

        assert resp.status_code == 200
        assert received_authorization == ["Bearer local"]
        assert canary_value not in received_authorization[0]

    def test_chat_never_echoes_a_loopback_response_body(self, monkeypatch):
        """Regression: a loopback base_url is allowed unconditionally so local
        providers (Ollama) work, which means the target may be ANY service bound
        to 127.0.0.1. Echoing that service's response body into the 502 detail
        turned the allowance into a read primitive over every local service."""
        secret_body = "INTERNAL-ONLY-SECRET admin_token=must-never-be-echoed"

        class _InternalService(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib hook name
                content_length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(content_length)
                body = secret_body.encode("utf-8")
                self.send_response(403)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        service = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _InternalService)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            resp = self._client().post("/chat", json={
                "message": "hi",
                "model": "local-model",
                "provider": "local",
                "base_url": f"http://127.0.0.1:{service.server_address[1]}/v1",
                "use_memory": False,
                "persist_chat": False,
            })
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=5)

        assert resp.status_code == 502
        detail = str(resp.json()["detail"])
        assert "403" in detail, "the status code is still useful to the operator"
        assert "INTERNAL-ONLY-SECRET" not in detail
        assert "admin_token" not in detail
        assert secret_body not in resp.text

    def test_chat_loopback_connection_failure_reveals_no_response_content(self):
        """The non-HTTPError branch must not echo raw exception text for loopback
        targets either; the exception type alone keeps 'Ollama is not running'
        diagnosable without describing what is (or is not) listening."""
        # Port 9 (discard) is reserved and refuses TCP connections.
        resp = self._client().post("/chat", json={
            "message": "hi",
            "model": "local-model",
            "provider": "local",
            "base_url": "http://127.0.0.1:9/v1",
            "use_memory": False,
            "persist_chat": False,
        })

        assert resp.status_code == 502
        detail = str(resp.json()["detail"])
        assert detail.startswith("provider call failed: ")
        # A bare exception class name, not a rendered errno/address string.
        assert "127.0.0.1" not in detail
        assert ":9" not in detail

    @pytest.mark.parametrize(
        ("provider_name", "include_content_length"),
        [("local", True), ("Anthropic", False)],
    )
    def test_chat_caps_provider_responses_before_parse_or_persist(
        self,
        monkeypatch,
        provider_name,
        include_content_length,
    ):
        """Both provider schemas must honor the same allocation bound.

        The no-Content-Length case proves the bounded read, while the declared
        length case proves an oversized response is rejected before reading.
        """

        monkeypatch.setenv("SEAM_CHAT_MAX_RESPONSE_BYTES", "128")
        sentinel = "oversized-provider-turn-sentinel"

        class _OversizedProvider(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib hook name
                content_length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(content_length)
                if provider_name == "Anthropic":
                    payload = {
                        "content": [{"type": "text", "text": sentinel}],
                        "padding": "x" * 512,
                    }
                else:
                    payload = {
                        "choices": [{"message": {"content": sentinel}}],
                        "padding": "x" * 512,
                    }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if include_content_length:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        service = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OversizedProvider)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        client = self._client()
        try:
            resp = client.post("/chat", json={
                "message": "do not persist this failed turn",
                "model": "local-model",
                "provider": provider_name,
                "base_url": f"http://127.0.0.1:{service.server_address[1]}/v1",
                "use_memory": False,
            })
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=5)

        assert resp.status_code == 502
        assert resp.json()["detail"] == (
            "provider call failed: ChatProviderResponseTooLarge"
        )
        search = client.get("/search", params={"query": sentinel, "budget": 5})
        assert search.status_code == 200
        assert search.json()["candidates"] == []

    def test_chat_stream_caps_provider_response_before_answer_or_persist(
        self,
        monkeypatch,
    ):
        """The streaming surface shares the provider allocation bound."""

        monkeypatch.setenv("SEAM_CHAT_MAX_RESPONSE_BYTES", "128")
        sentinel = "oversized-stream-provider-sentinel"

        class _OversizedStreamingProvider(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib hook name
                content_length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(content_length)
                body = json.dumps(
                    {
                        "choices": [{"message": {"content": sentinel}}],
                        "padding": "x" * 512,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        service = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _OversizedStreamingProvider,
        )
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        client = self._client()
        try:
            response = client.post(
                "/chat/stream",
                json={
                    "message": "do not persist this failed streaming turn",
                    "model": "local-model",
                    "provider": "local",
                    "base_url": (
                        f"http://127.0.0.1:{service.server_address[1]}/v1"
                    ),
                    "use_memory": False,
                },
            )
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=5)

        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert events[-1]["event_type"] == "failure"
        assert events[-1]["payload"]["error_type"] == (
            "ChatProviderResponseTooLarge"
        )
        assert not any(
            event["event_type"] in {"answer_delta", "completion"}
            for event in events
        )
        assert sentinel not in response.text
        search = client.get("/search", params={"query": sentinel, "budget": 5})
        assert search.status_code == 200
        assert search.json()["candidates"] == []

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
            "text": "Alice prefers dark mode and drinks oat milk lattes.",
            "ns": "local.chat",
            "scope": "thread",
            "persist": True,
        })
        assert seed.status_code == 200

        resp = client.post("/chat", json={
            "message": "what does alice prefer?", "model": "gpt-4o-mini",
            "provider": "OpenAI", "base_url": "https://api.openai.com/v1",
            "api_key": "stub", "use_memory": True, "budget": 5,
            "ns": "local.chat", "scope": "thread"})
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
