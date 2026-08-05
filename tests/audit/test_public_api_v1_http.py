"""HTTP-level coverage for the public `/v1` API surface.

Closes finding 9 of `docs/audits/2026-08-01-full-repo-audit.md`: before this
file the entire `/v1` surface had zero HTTP-level tests. The only `/v1/`
string in the test tree was a mock provider's `/v1/chat/completions` URL in
`test_audit_2026_06_05.py`, which does not exercise a SEAM route.

These are **characterization** tests: they pin down what `/v1` does today so
that S6 (principal tenancy and opaque deletion) changes observable behaviour
deliberately rather than incidentally. The tenancy tests at the bottom record
the *current* boundary — isolation is driven by the request body, not by the
caller's identity — and are written so S6 must consciously flip them.

Free paths only: no provider is contacted, no paid benchmark runs. Retrieval
assertions avoid ranking-sensitive claims because the default hash embedder is
not reliable for paraphrase; presence/absence within a namespace is a hard SQL
filter and is deterministic.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from seam_runtime.public_api import (
    MAX_CONTEXT_CHARS,
    MAX_MEMORY_TEXT_CHARS,
    MAX_QUERY_CHARS,
    MAX_RECALL_LIMIT,
    PUBLIC_API_VERSION,
)
from seam_runtime.server import create_app_from_env


@pytest.fixture(autouse=True)
def _isolated_server_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_public_api_v1.db"))
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)


@pytest.fixture
def client():
    return TestClient(create_app_from_env())


def _remember(client, text, **kwargs):
    return client.post("/v1/memories", json={"text": text, **kwargs})


def _recall(client, query, **kwargs):
    return client.post("/v1/memories/recall", json={"query": query, **kwargs})


def _context(client, query, **kwargs):
    return client.post("/v1/context", json={"query": query, **kwargs})


class TestPublicHealth:
    def test_get_reports_api_version(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "api_version": PUBLIC_API_VERSION}

    def test_head_is_routed(self, client):
        assert client.head("/v1/health").status_code == 200

    def test_health_needs_no_bearer_token(self, monkeypatch):
        monkeypatch.setenv("SEAM_API_TOKEN", "secret-token")
        resp = TestClient(create_app_from_env()).get("/v1/health")
        assert resp.status_code == 200


class TestPublicRemember:
    def test_returns_receipt_and_echoes_dimensions(self, client):
        resp = _remember(
            client,
            "Alice prefers oat milk in her coffee.",
            namespace="team-alpha",
            scope="thread",
            session_id="sess-1",
            agent_id="agent.one",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] is True
        assert body["api_version"] == PUBLIC_API_VERSION
        assert body["receipt_id"].startswith("rcpt_")
        assert body["memory_count"] == 1
        assert body["namespace"] == "team-alpha"
        assert body["scope"] == "thread"
        assert body["session_id"] == "sess-1"

    def test_receipt_ids_are_unique_per_call(self, client):
        first = _remember(client, "Bob rides a blue bicycle.").json()["receipt_id"]
        second = _remember(client, "Bob rides a blue bicycle.").json()["receipt_id"]
        assert first != second

    def test_defaults_namespace_and_scope(self, client):
        body = _remember(client, "Carol works in Lisbon.").json()
        assert body["namespace"] == "default"
        assert body["scope"] == "thread"
        assert body["session_id"] is None

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"text": ""},
            {"text": "   "},
            {"text": None},
            {"text": 42},
            {"text": ["a", "list"]},
        ],
        ids=["missing", "empty", "whitespace", "null", "int", "list"],
    )
    def test_rejects_bad_text(self, client, payload):
        assert client.post("/v1/memories", json=payload).status_code == 400

    def test_rejects_oversize_text(self, client):
        resp = _remember(client, "x" * (MAX_MEMORY_TEXT_CHARS + 1))
        assert resp.status_code == 400
        assert str(MAX_MEMORY_TEXT_CHARS) in resp.json()["detail"]

    def test_accepts_text_at_the_limit(self, client):
        assert _remember(client, "y" * MAX_MEMORY_TEXT_CHARS).status_code == 200

    @pytest.mark.parametrize(
        "namespace",
        ["", "   ", "-leading-hyphen", ".leading-dot", "has space", "has/slash", "n" * 129],
        ids=["empty", "whitespace", "hyphen", "dot", "space", "slash", "toolong"],
    )
    def test_rejects_bad_namespace(self, client, namespace):
        resp = _remember(client, "some text", namespace=namespace)
        assert resp.status_code == 400

    @pytest.mark.parametrize("scope", ["", "galaxy", "Thread", 7])
    def test_rejects_bad_scope(self, client, scope):
        assert _remember(client, "some text", scope=scope).status_code == 400

    @pytest.mark.parametrize("agent_id", ["has space", "a" * 129, 12, "has/slash"])
    def test_rejects_bad_agent_id(self, client, agent_id):
        assert _remember(client, "some text", agent_id=agent_id).status_code == 400

    def test_blank_agent_id_is_treated_as_absent(self, client):
        assert _remember(client, "some text", agent_id="   ").status_code == 200

    def test_error_body_is_a_detail_string(self, client):
        detail = client.post("/v1/memories", json={}).json()["detail"]
        assert isinstance(detail, str) and detail


class TestPublicRecall:
    def test_round_trips_a_stored_memory(self, client):
        _remember(client, "The deployment key rotates every ninety days.")
        resp = _recall(client, "deployment key rotates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["api_version"] == PUBLIC_API_VERSION
        assert body["query"] == "deployment key rotates"
        assert body["namespace"] == "default"
        assert body["scope"] == "thread"
        assert body["session_id"] is None
        assert isinstance(body["memories"], list)
        assert body["memories"], "a stored memory must be recallable in its namespace"

    def test_memory_ids_are_opaque_and_stable(self, client):
        _remember(client, "The archive lives in cold storage.")
        first = _recall(client, "archive cold storage").json()["memories"]
        second = _recall(client, "archive cold storage").json()["memories"]
        assert first, "expected at least one memory"
        for memory in first:
            assert memory["id"].startswith("mem_")
            # Opaque: never a raw canonical record id.
            assert "::" not in memory["id"]
            assert set(memory) == {"id", "text", "score", "created_at"}
        assert [m["id"] for m in first] == [m["id"] for m in second]

    def test_empty_store_returns_no_memories_not_an_error(self, client):
        resp = _recall(client, "nothing was ever written here")
        assert resp.status_code == 200
        assert resp.json()["memories"] == []

    def test_respects_the_limit(self, client):
        for index in range(6):
            _remember(client, f"Runbook step {index}: restart the ingest worker.")
        memories = _recall(client, "runbook restart ingest worker", limit=2).json()["memories"]
        assert len(memories) <= 2

    @pytest.mark.parametrize(
        "payload",
        [{}, {"query": ""}, {"query": "  "}, {"query": None}, {"query": 5}],
        ids=["missing", "empty", "whitespace", "null", "int"],
    )
    def test_rejects_bad_query(self, client, payload):
        assert client.post("/v1/memories/recall", json=payload).status_code == 400

    def test_rejects_oversize_query(self, client):
        assert _recall(client, "q" * (MAX_QUERY_CHARS + 1)).status_code == 400

    @pytest.mark.parametrize(
        "limit",
        [0, -1, MAX_RECALL_LIMIT + 1, "five", None, True],
        ids=["zero", "negative", "over-max", "string", "null", "bool"],
    )
    def test_rejects_bad_limit(self, client, limit):
        assert _recall(client, "anything", limit=limit).status_code == 400

    @pytest.mark.parametrize("limit", [1, MAX_RECALL_LIMIT])
    def test_accepts_limit_bounds(self, client, limit):
        assert _recall(client, "anything", limit=limit).status_code == 200


class TestPublicContext:
    def test_returns_a_context_block_and_its_memories(self, client):
        _remember(client, "Incident 42 was caused by a stale DNS record.")
        resp = _context(client, "incident stale DNS record")
        assert resp.status_code == 200
        body = resp.json()
        assert body["api_version"] == PUBLIC_API_VERSION
        assert isinstance(body["context"], str)
        assert body["memories"], "expected the stored memory to be retrievable"
        # Every rendered line comes from a returned memory.
        for line in filter(None, body["context"].split("\n")):
            assert line.startswith("- ")

    def test_context_never_exceeds_max_chars(self, client):
        for index in range(8):
            _remember(client, f"Fact {index}: the pipeline retries three times before paging.")
        body = _context(client, "pipeline retries before paging", limit=8, max_chars=120).json()
        assert len(body["context"]) <= 120

    def test_empty_store_returns_empty_context(self, client):
        body = _context(client, "no such thing").json()
        assert body["context"] == ""
        assert body["memories"] == []

    @pytest.mark.parametrize(
        "max_chars",
        [0, -1, MAX_CONTEXT_CHARS + 1, "lots", None, True],
        ids=["zero", "negative", "over-max", "string", "null", "bool"],
    )
    def test_rejects_bad_max_chars(self, client, max_chars):
        assert _context(client, "anything", max_chars=max_chars).status_code == 400

    def test_rejects_bad_query(self, client):
        assert client.post("/v1/context", json={}).status_code == 400


class TestPublicApiAuthBoundary:
    """The bearer guard is the only thing standing in front of `/v1` today."""

    ROUTES = [
        ("/v1/memories", {"text": "guarded"}),
        ("/v1/memories/recall", {"query": "guarded"}),
        ("/v1/context", {"query": "guarded"}),
    ]

    @pytest.mark.parametrize("route,payload", ROUTES)
    def test_rejects_missing_token_when_configured(self, monkeypatch, route, payload):
        monkeypatch.setenv("SEAM_API_TOKEN", "secret-token")
        resp = TestClient(create_app_from_env()).post(route, json=payload)
        assert resp.status_code == 401

    @pytest.mark.parametrize("route,payload", ROUTES)
    def test_rejects_wrong_token(self, monkeypatch, route, payload):
        monkeypatch.setenv("SEAM_API_TOKEN", "secret-token")
        resp = TestClient(create_app_from_env()).post(
            route, json=payload, headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize("route,payload", ROUTES)
    def test_accepts_correct_token(self, monkeypatch, route, payload):
        monkeypatch.setenv("SEAM_API_TOKEN", "secret-token")
        resp = TestClient(create_app_from_env()).post(
            route, json=payload, headers={"Authorization": "Bearer secret-token"}
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("route,payload", ROUTES)
    def test_open_when_no_token_is_configured(self, client, route, payload):
        assert client.post(route, json=payload).status_code == 200


class TestPublicApiTenancyBoundary:
    """Characterization of the *current* `/v1` isolation model.

    Isolation today is derived entirely from the request body (`namespace`,
    `session_id`), never from the caller. S6 must decide whether tenancy
    terminates in a proxy ahead of `/v1` or in-process; when it does, the last
    test in this class is the one that has to change.
    """

    def test_namespace_partitions_recall(self, client):
        _remember(client, "The alpha vault code is marigold.", namespace="tenant-a")
        assert _recall(client, "alpha vault code marigold", namespace="tenant-a").json()["memories"]
        assert _recall(client, "alpha vault code marigold", namespace="tenant-b").json()["memories"] == []

    def test_namespace_partitions_context(self, client):
        _remember(client, "The beta rollout is paused until Friday.", namespace="tenant-a")
        other = _context(client, "beta rollout paused Friday", namespace="tenant-b").json()
        assert other["context"] == ""
        assert other["memories"] == []

    def test_session_id_partitions_within_a_namespace(self, client):
        _remember(client, "Session scoped note about the lighthouse.", session_id="sess-a")
        same = _recall(client, "session scoped note lighthouse", session_id="sess-a").json()
        other = _recall(client, "session scoped note lighthouse", session_id="sess-b").json()
        sessionless = _recall(client, "session scoped note lighthouse").json()
        assert same["memories"]
        assert other["memories"] == []
        assert sessionless["memories"] == []

    def test_one_token_reads_and_writes_every_namespace(self, monkeypatch):
        """Records the S6 gap rather than asserting it is acceptable.

        A single bearer token is the whole authorization model: the same
        credential writes `tenant-a` and reads it back through a request that
        merely names that namespace. There is no caller identity to check it
        against. When S6 binds a principal to the request, this test must be
        rewritten to assert cross-tenant reads are refused.
        """
        monkeypatch.setenv("SEAM_API_TOKEN", "shared-token")
        client = TestClient(create_app_from_env())
        headers = {"Authorization": "Bearer shared-token"}

        write = client.post(
            "/v1/memories",
            json={"text": "Tenant A private revenue is nine million.", "namespace": "tenant-a"},
            headers=headers,
        )
        assert write.status_code == 200

        read = client.post(
            "/v1/memories/recall",
            json={"query": "tenant private revenue nine million", "namespace": "tenant-a"},
            headers=headers,
        )
        assert read.status_code == 200
        assert read.json()["memories"], (
            "the same token that wrote tenant-a can read it back by naming it; "
            "S6 must replace this with a principal-bound check"
        )
