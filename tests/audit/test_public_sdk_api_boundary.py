from __future__ import annotations

import json
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from seam_runtime import public_api
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app

_INTERNAL_RESPONSE_KEYS = {
    "attrs",
    "evidence",
    "kind",
    "pack",
    "prov",
    "reasons",
    "record",
    "records",
    "stored_ids",
    "store_path",
}
_INTERNAL_ID = re.compile(r"\b(?:raw|clm|ent|evt|prov|span|sta|pack):")


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "10000")
    return TestClient(create_app(SeamRuntime(tmp_path / "public-sdk.db")))


def _assert_public_payload(payload: object) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    assert not _INTERNAL_ID.search(serialized)

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert not (_INTERNAL_RESPONSE_KEYS & value.keys())
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)


def test_public_sdk_memory_round_trip_is_opaque(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "api_version": "v1"}

    remembered = client.post(
        "/v1/memories",
        json={
            "text": "The operator prefers concise evidence-backed answers.",
            "namespace": "agent.demo",
            "scope": "thread",
            "session_id": "session-1",
            "agent_id": "demo-agent",
        },
    )
    assert remembered.status_code == 200
    receipt = remembered.json()
    assert receipt["accepted"] is True
    assert receipt["receipt_id"].startswith("rcpt_")
    assert receipt["memory_count"] == 1
    _assert_public_payload(receipt)

    recalled = client.post(
        "/v1/memories/recall",
        json={
            "query": "How should answers be written?",
            "namespace": "agent.demo",
            "scope": "thread",
            "session_id": "session-1",
            "limit": 5,
        },
    )
    assert recalled.status_code == 200
    payload = recalled.json()
    assert payload["memories"]
    assert payload["memories"][0]["id"].startswith("mem_")
    assert "concise evidence-backed answers" in payload["memories"][0]["text"]
    _assert_public_payload(payload)

    context = client.post(
        "/v1/context",
        json={
            "query": "answer style",
            "namespace": "agent.demo",
            "scope": "thread",
            "session_id": "session-1",
            "limit": 5,
            "max_chars": 200,
        },
    )
    assert context.status_code == 200
    payload = context.json()
    assert payload["context"].startswith("- ")
    assert len(payload["context"]) <= 200
    _assert_public_payload(payload)


def test_public_sdk_namespaces_are_isolated(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    assert client.post(
        "/v1/memories",
        json={
            "text": "Agent alpha remembers the cobalt launch code name.",
            "namespace": "agent.alpha",
            "scope": "thread",
            "session_id": "alpha-session",
        },
    ).status_code == 200

    other = client.post(
        "/v1/memories/recall",
        json={
            "query": "cobalt launch",
            "namespace": "agent.beta",
            "scope": "thread",
            "session_id": "alpha-session",
        },
    )
    assert other.status_code == 200
    assert other.json()["memories"] == []


def test_public_sdk_rejects_invalid_dimensions_and_bounds(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    invalid_namespace = client.post(
        "/v1/memories",
        json={"text": "remember this", "namespace": "../private"},
    )
    assert invalid_namespace.status_code == 400

    invalid_limit = client.post(
        "/v1/memories/recall",
        json={"query": "remember", "limit": 51},
    )
    assert invalid_limit.status_code == 400

    invalid_context = client.post(
        "/v1/context",
        json={"query": "remember", "max_chars": 0},
    )
    assert invalid_context.status_code == 400


def test_public_sdk_respects_bearer_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SEAM_API_TOKEN", "unit-test-token")
    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "10000")
    client = TestClient(create_app(SeamRuntime(tmp_path / "public-sdk-auth.db")))

    unauthorized = client.post("/v1/memories", json={"text": "remember this"})
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/v1/memories",
        json={"text": "remember this"},
        headers={"Authorization": "Bearer unit-test-token"},
    )
    assert authorized.status_code == 200


def test_public_context_budget_includes_line_separators(monkeypatch) -> None:
    class _Runtime:
        def search_ir(self, **_kwargs):
            return SimpleNamespace(candidates=[])

    monkeypatch.setattr(
        public_api,
        "_public_memories",
        lambda _candidates, *, limit: [
            {"text": "alpha"},
            {"text": "beta"},
        ][:limit],
    )
    payload = public_api.context(
        _Runtime(),
        {"query": "letters", "limit": 2, "max_chars": 10},
    )
    assert payload["context"].startswith("- alpha")
    assert len(payload["context"]) <= 10
