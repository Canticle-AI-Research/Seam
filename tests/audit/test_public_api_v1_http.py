"""HTTP-level coverage for the public `/v1` API surface.

Closes finding 9 of `docs/audits/2026-08-01-full-repo-audit.md`: before this
file the entire `/v1` surface had zero HTTP-level tests. The only `/v1/`
string in the test tree was a mock provider's `/v1/chat/completions` URL in
`test_audit_2026_06_05.py`, which does not exercise a SEAM route.

These tests pin both supported modes: byte-compatible trusted/self-host behavior
without a principal, plus S6's optional in-process principal boundary and opaque
deletion contract.

Free paths only: no provider is contacted, no paid benchmark runs. Retrieval
assertions avoid ranking-sensitive claims because the default hash embedder is
not reliable for paraphrase; presence/absence within a namespace is a hard SQL
filter and is deterministic.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from seam_runtime.public_api import (
    MAX_CONTEXT_CHARS,
    MAX_MEMORY_TEXT_CHARS,
    MAX_QUERY_CHARS,
    MAX_RECALL_LIMIT,
    PUBLIC_API_VERSION,
    PublicPrincipal,
    StaticPrincipalResolver,
    remember,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app, create_app_from_env


@pytest.fixture(autouse=True)
def _isolated_server_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_public_api_v1.db"))
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    monkeypatch.delenv("SEAM_API_PUBLIC_ID_KEY", raising=False)
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

    def test_principal_routes_honor_asgi_root_path(self, tmp_path):
        runtime = SeamRuntime(tmp_path / "root-path.db", allow_pgvector_env=False)
        app = create_app(
            runtime,
            principal_resolver=StaticPrincipalResolver(
                {"root-token": "account/root-path"}
            ),
            public_id_key=b"principal-root-path-public-key-32",
            process_workers=1,
        )
        try:
            with TestClient(
                app,
                root_path="/seam",
                base_url="http://testserver/seam",
            ) as client:
                health = client.get("/v1/health")
                remember_response = client.post(
                    "/v1/memories",
                    json={"text": "Root path memory."},
                    headers={"Authorization": "Bearer root-token"},
                )
        finally:
            runtime.close()

        assert health.status_code == 200
        assert remember_response.status_code == 200


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

    @pytest.mark.parametrize("authenticated", [False, True])
    def test_principal_delete_route_is_absent_from_legacy_modes(
        self, monkeypatch, authenticated
    ):
        headers = {}
        if authenticated:
            monkeypatch.setenv("SEAM_API_TOKEN", "shared-token")
            headers = {"Authorization": "Bearer shared-token"}
        client = TestClient(create_app_from_env())

        assert client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": ["mem_" + "0" * 24],
                "idempotency_key": "not-a-principal-delete",
            },
            headers=headers,
        ).status_code == 405
        schema = client.get("/openapi.json", headers=headers)
        if authenticated:
            assert schema.status_code == 404
        else:
            assert "/v1/memories/delete" not in schema.json()["paths"]


class TestPublicApiTenancyBoundary:
    """Characterization of the legacy no-principal `/v1` isolation model.

    Isolation remains request-dimension based when no principal resolver is
    configured. This is the byte-compatible trusted/self-host path, not a
    hosted multi-tenant claim.
    """

    def test_namespace_partitions_recall(self, client):
        _remember(client, "The alpha vault code is marigold.", namespace="tenant-a")
        assert _recall(client, "alpha vault code marigold", namespace="tenant-a").json()["memories"]
        assert _recall(client, "alpha vault code marigold", namespace="tenant-b").json()["memories"] == []

    def test_same_text_keeps_legacy_cross_namespace_persistence_behavior(
        self, client
    ):
        text = "The legacy namespace collision marker is copper rain."
        query = "legacy namespace collision marker copper rain"

        assert _remember(client, text, namespace="tenant-a").status_code == 200
        assert _remember(client, text, namespace="tenant-b").status_code == 200

        assert _recall(client, query, namespace="tenant-a").json()["memories"] == []
        assert _recall(client, query, namespace="tenant-b").json()["memories"]

    def test_legacy_recall_does_not_register_principal_handle_rows(
        self, client, tmp_path
    ):
        _remember(client, "The compatibility marker is ember glass.")
        assert _recall(client, "compatibility marker ember glass").json()["memories"]

        with sqlite3.connect(tmp_path / "test_public_api_v1.db") as connection:
            assert connection.execute(
                "select count(*) from public_memory_handle"
            ).fetchone() == (0,)

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
        """The legacy single-token path deliberately remains principal-free.

        A single bearer token is the whole authorization model: the same
        credential writes `tenant-a` and reads it back through a request that
        merely names that namespace. There is no caller identity to check it
        against. Hosted callers must configure principal mode instead.
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
            "this legacy mode must not be described as hosted tenancy"
        )


@pytest.fixture
def principal_api(tmp_path):
    db_path = tmp_path / "principal-api.db"
    runtime = SeamRuntime(db_path)
    resolver = StaticPrincipalResolver(
        {
            "token-a": "account/alice",
            "token-b": "account/bob",
        }
    )
    app = create_app(
        runtime,
        principal_resolver=resolver,
        public_id_key=b"principal-public-id-key-for-tests",
        process_workers=1,
    )
    with TestClient(app) as client:
        yield client, runtime, db_path
    runtime.close()


def _principal_headers(name):
    return {"Authorization": f"Bearer token-{name}"}


def _post_as(client, principal, path, payload):
    return client.post(path, json=payload, headers=_principal_headers(principal))


class TestPublicApiPrincipalTenancy:
    def test_environment_adapter_binds_shared_token_to_one_principal(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "env-principal.db"))
        monkeypatch.setenv("SEAM_API_TOKEN", "environment-token")
        monkeypatch.setenv("SEAM_API_PRINCIPAL", "account/environment")
        monkeypatch.setenv(
            "SEAM_API_PUBLIC_ID_KEY",
            "environment-public-id-key-32-bytes",
        )
        client = TestClient(create_app_from_env())
        assert client.post(
            "/v1/memories",
            json={"text": "Environment principal memory."},
            headers={"Authorization": "Bearer environment-token"},
        ).status_code == 200
        assert client.post(
            "/v1/memories/recall",
            json={"query": "environment principal memory"},
            headers={"Authorization": "Bearer wrong"},
        ).status_code == 401
        assert client.get(
            "/stats",
            headers={"Authorization": "Bearer environment-token"},
        ).status_code == 404

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/stats"),
            ("GET", "/stats/"),
            ("GET", "/workspace/events"),
        ],
    )
    def test_private_route_shapes_are_hidden_before_router_matching(
        self, principal_api, method, path
    ):
        client, _runtime, _db_path = principal_api

        response = client.request(
            method,
            path,
            headers=_principal_headers("a"),
            follow_redirects=False,
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}
        assert "allow" not in response.headers
        assert "location" not in response.headers

    def test_principal_memory_cors_preflight_reaches_cors_middleware(
        self, principal_api
    ):
        client, _runtime, _db_path = principal_api

        response = client.options(
            "/v1/memories",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == (
            "http://localhost:5173"
        )

    def test_same_request_dimensions_and_content_remain_principal_isolated(
        self, principal_api
    ):
        client, runtime, db_path = principal_api
        payload = {
            "text": "The shared launch phrase is silver orchard.",
            "namespace": "workspace",
            "session_id": "session-replay",
        }
        assert _post_as(client, "a", "/v1/memories", payload).status_code == 200
        assert _post_as(client, "b", "/v1/memories", payload).status_code == 200

        query = {
            "query": "shared launch phrase silver orchard",
            "namespace": "workspace",
            "session_id": "session-replay",
        }
        alice = _post_as(client, "a", "/v1/memories/recall", query).json()
        bob = _post_as(client, "b", "/v1/memories/recall", query).json()
        assert alice["memories"] and bob["memories"]
        assert alice["memories"][0]["id"] != bob["memories"][0]["id"]

        namespaces = runtime.store.list_namespaces()
        assert len(namespaces) == 2
        assert all(namespace.startswith("principal:") for namespace in namespaces)
        assert all(".sdk.boundary-" in namespace for namespace in namespaces)
        assert namespaces[0] != namespaces[1]
        with sqlite3.connect(db_path) as connection:
            raw_ids = [
                str(row[0])
                for row in connection.execute(
                    "select id from ir_records where kind = 'RAW' order by id"
                )
            ]
        assert len(raw_ids) == 2
        assert all(len(record_id) == len("raw:") + 64 for record_id in raw_ids)
        assert all(
            set(record_id.removeprefix("raw:")) <= set("0123456789abcdef")
            for record_id in raw_ids
        )

    def test_same_text_remains_isolated_across_scopes(self, principal_api):
        client, _runtime, _db_path = principal_api
        text = "The cross-scope marker is indigo lattice."
        base = {"text": text, "namespace": "workspace"}
        assert _post_as(
            client, "a", "/v1/memories", {**base, "scope": "thread"}
        ).status_code == 200
        assert _post_as(
            client, "a", "/v1/memories", {**base, "scope": "project"}
        ).status_code == 200

        query = {"query": "cross-scope marker indigo lattice", "namespace": "workspace"}
        thread = _post_as(
            client, "a", "/v1/memories/recall", {**query, "scope": "thread"}
        ).json()["memories"]
        project = _post_as(
            client, "a", "/v1/memories/recall", {**query, "scope": "project"}
        ).json()["memories"]

        assert thread and project
        assert thread[0]["id"] != project[0]["id"]

    def test_namespace_text_cannot_alias_a_session_boundary(self, principal_api):
        client, runtime, _db_path = principal_api
        session_id = "crafted-session"
        session_digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
        session_dimensions = {
            "namespace": "alpha",
            "session_id": session_id,
        }
        crafted_dimensions = {
            "namespace": f"alpha.session-{session_digest}",
        }
        assert _post_as(
            client,
            "a",
            "/v1/memories",
            {"text": "The session-only marker is saffron delta.", **session_dimensions},
        ).status_code == 200
        assert _post_as(
            client,
            "a",
            "/v1/memories",
            {"text": "The crafted-namespace marker is cobalt harbor.", **crafted_dimensions},
        ).status_code == 200

        assert len(runtime.store.list_namespaces()) == 2
        session_memories = _post_as(
            client,
            "a",
            "/v1/memories/recall",
            {"query": "marker", **session_dimensions},
        ).json()["memories"]
        crafted_memories = _post_as(
            client,
            "a",
            "/v1/memories/recall",
            {"query": "marker", **crafted_dimensions},
        ).json()["memories"]
        assert [memory["text"] for memory in session_memories] == [
            "The session-only marker is saffron delta."
        ]
        assert [memory["text"] for memory in crafted_memories] == [
            "The crafted-namespace marker is cobalt harbor."
        ]

    def test_namespace_and_session_replay_cannot_cross_principals(self, principal_api):
        client, _runtime, _db_path = principal_api
        dimensions = {"namespace": "private", "session_id": "same-session"}
        assert _post_as(
            client,
            "a",
            "/v1/memories",
            {"text": "Alice private revenue is nine million.", **dimensions},
        ).status_code == 200

        query = {"query": "private revenue nine million", **dimensions}
        assert _post_as(
            client, "a", "/v1/memories/recall", query
        ).json()["memories"]
        bob_recall = _post_as(
            client, "b", "/v1/memories/recall", query
        ).json()
        bob_context = _post_as(client, "b", "/v1/context", query).json()
        assert bob_recall["memories"] == []
        assert bob_context["memories"] == []
        assert bob_context["context"] == ""

    def test_every_principal_data_call_binds_a_concrete_internal_namespace(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        seen: list[str | None] = []
        original_compile = runtime.compile_nl
        original_search = runtime.search_ir
        original_plan_delete = runtime.plan_scoped_delete

        def capture_compile(*args, **kwargs):
            seen.append(kwargs.get("ns"))
            return original_compile(*args, **kwargs)

        def capture_search(*args, **kwargs):
            seen.append(kwargs.get("ns"))
            return original_search(*args, **kwargs)

        def capture_delete(*args, **kwargs):
            seen.append(kwargs.get("namespace"))
            return original_plan_delete(*args, **kwargs)

        monkeypatch.setattr(runtime, "compile_nl", capture_compile)
        monkeypatch.setattr(runtime, "search_ir", capture_search)
        monkeypatch.setattr(runtime, "plan_scoped_delete", capture_delete)
        headers = _principal_headers("a")
        client.post(
            "/v1/memories",
            json={"text": "Namespace capture marker."},
            headers=headers,
        )
        recall = client.post(
            "/v1/memories/recall",
            json={"query": "namespace capture marker"},
            headers=headers,
        ).json()
        client.post(
            "/v1/context",
            json={"query": "namespace capture marker"},
            headers=headers,
        )
        client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [recall["memories"][0]["id"]],
                "idempotency_key": "capture-delete",
            },
            headers=headers,
        )
        assert len(seen) == 4
        assert all(value and value.startswith("principal:") for value in seen)

    def test_foreign_delete_is_indistinguishable_and_owned_delete_is_idempotent(
        self, principal_api
    ):
        client, _runtime, db_path = principal_api
        dimensions = {"namespace": "private", "session_id": "delete-session"}
        assert _post_as(
            client,
            "a",
            "/v1/memories",
            {"text": "The recovery phrase is cedar comet.", **dimensions},
        ).status_code == 200
        query = {"query": "recovery phrase cedar comet", **dimensions}
        memory_id = _post_as(
            client, "a", "/v1/memories/recall", query
        ).json()["memories"][0]["id"]

        foreign = _post_as(
            client,
            "b",
            "/v1/memories/delete",
            {
                "memory_ids": [memory_id],
                "idempotency_key": "bob-foreign-attempt",
                **dimensions,
            },
        )
        unknown = _post_as(
            client,
            "b",
            "/v1/memories/delete",
            {
                "memory_ids": ["mem_" + "0" * 24],
                "idempotency_key": "bob-unknown-attempt",
                **dimensions,
            },
        )
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json() == unknown.json() == {"detail": "Memory not found"}
        assert _post_as(
            client, "a", "/v1/memories/recall", query
        ).json()["memories"]

        deletion_payload = {
            "memory_ids": [memory_id],
            "idempotency_key": "alice-delete-1",
            **dimensions,
        }
        first = _post_as(
            client, "a", "/v1/memories/delete", deletion_payload
        )
        repeated = _post_as(
            client, "a", "/v1/memories/delete", deletion_payload
        )
        stale_with_new_key = _post_as(
            client,
            "a",
            "/v1/memories/delete",
            {**deletion_payload, "idempotency_key": "alice-delete-2"},
        )
        assert first.status_code == repeated.status_code == 200
        assert first.json() == repeated.json()
        assert stale_with_new_key.status_code == 404
        assert stale_with_new_key.json() == {"detail": "Memory not found"}
        assert first.json()["deletion_id"].startswith("del_")
        assert first.json()["status"] == "deleted"
        assert _post_as(
            client, "a", "/v1/memories/recall", query
        ).json()["memories"] == []
        assert _post_as(client, "a", "/v1/context", query).json()["context"] == ""

        with sqlite3.connect(db_path) as connection:
            operation = connection.execute(
                "select operation_id, tenant_id, ns from lifecycle_operation"
            ).fetchone()
            assert operation is not None
            states = [
                row[0]
                for row in connection.execute(
                    "select state from lifecycle_event where operation_id = ? "
                    "order by event_seq",
                    (operation[0],),
                )
            ]
            assert states == ["planned", "applying", "cleanup_pending", "applied"]
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(
                    "update lifecycle_operation set ns = ? where operation_id = ?",
                    ("tampered", operation[0]),
                )

    def test_delete_uses_registered_handle_index_without_loading_namespace(
        self, principal_api, monkeypatch
    ):
        client, runtime, db_path = principal_api
        headers = _principal_headers("a")
        client.post(
            "/v1/memories",
            json={"text": "The indexed deletion marker is copper moon."},
            headers=headers,
        )
        memory_id = client.post(
            "/v1/memories/recall",
            json={"query": "indexed deletion marker copper moon"},
            headers=headers,
        ).json()["memories"][0]["id"]
        with sqlite3.connect(db_path) as connection:
            registered = connection.execute(
                "select handle_id, record_id from public_memory_handle "
                "where handle_id = ?",
                (memory_id,),
            ).fetchone()
            assert registered is not None

        def forbid_namespace_load(*_args, **_kwargs):
            raise AssertionError("delete must use the indexed handle projection")

        monkeypatch.setattr(runtime.store, "load_ir", forbid_namespace_load)
        response = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [memory_id],
                "idempotency_key": "indexed-delete",
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

    def test_reingest_mints_a_new_handle_generation_and_binds_idempotency(
        self, principal_api
    ):
        client, _runtime, db_path = principal_api
        headers = _principal_headers("a")
        text = "The durable principal handle phrase is coral summit."
        query = {"query": "durable principal handle phrase coral summit"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        original_handle = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]

        original_delete = {
            "memory_ids": [original_handle],
            "idempotency_key": "principal-generation-delete",
        }
        first = client.post(
            "/v1/memories/delete", json=original_delete, headers=headers
        )
        assert first.status_code == 200
        assert first.json()["status"] == "deleted"
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"] == []

        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        recalled = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"]
        assert len(recalled) == 1
        replacement_handle = recalled[0]["id"]
        assert replacement_handle != original_handle

        stale = client.post(
            "/v1/memories/delete",
            json=original_delete,
            headers=headers,
        )
        conflict = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [replacement_handle],
                "idempotency_key": "principal-generation-delete",
            },
            headers=headers,
        )
        deleted = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [replacement_handle],
                "idempotency_key": "replacement-generation-delete",
            },
            headers=headers,
        )

        assert stale.status_code == 404
        assert stale.json() == {"detail": "Memory not found"}
        assert conflict.status_code == 409
        assert conflict.json() == {
            "detail": "idempotency_key already names a different deletion"
        }
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"] == []

        with sqlite3.connect(db_path) as connection:
            payloads = [
                json.loads(row[0])
                for row in connection.execute(
                    "select payload_json from ir_records"
                ).fetchall()
            ]
        assert all(
            isinstance(payload["ext"].get("public_memory_generation"), str)
            for payload in payloads
        )

    def test_applied_delete_retry_rechecks_generation_inside_apply(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The apply retry race marker is violet harbor."
        query = {"query": "apply retry race marker violet harbor"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        memory_id = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]
        payload = {
            "memory_ids": [memory_id],
            "idempotency_key": "apply-retry-generation-race",
        }
        assert client.post(
            "/v1/memories/delete", json=payload, headers=headers
        ).status_code == 200

        original_apply = runtime.apply_scoped_delete
        injected = False

        def reingest_before_applied_fast_path(*args, **kwargs):
            nonlocal injected
            if not injected:
                injected = True
                remember(
                    runtime,
                    {"text": text},
                    principal=PublicPrincipal("account/alice"),
                )
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(
            runtime,
            "apply_scoped_delete",
            reingest_before_applied_fast_path,
        )
        stale_retry = client.post(
            "/v1/memories/delete", json=payload, headers=headers
        )

        assert stale_retry.status_code == 404
        assert stale_retry.json() == {"detail": "Memory not found"}
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"]

    def test_concurrent_first_plan_rechecks_returned_operation_generation(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The concurrent planning marker is silver delta."
        query = {"query": "concurrent planning marker silver delta"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        memory_id = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]
        original_plan = runtime.plan_scoped_delete
        original_apply = runtime.apply_scoped_delete
        injected = False

        def win_plan_apply_and_reingest(*args, **kwargs):
            nonlocal injected
            operation = original_plan(*args, **kwargs)
            if not injected:
                injected = True
                original_apply(
                    tenant_id=str(operation["tenant_id"]),
                    operation_id=str(operation["operation_id"]),
                    actor="principal-api",
                )
                remember(
                    runtime,
                    {"text": text},
                    principal=PublicPrincipal("account/alice"),
                )
            return operation

        monkeypatch.setattr(
            runtime,
            "plan_scoped_delete",
            win_plan_apply_and_reingest,
        )
        response = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [memory_id],
                "idempotency_key": "concurrent-first-plan",
            },
            headers=headers,
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Memory not found"}
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"]

    def test_stale_resolved_handle_cannot_delete_replacement_generation(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The stale resolution marker is indigo summit."
        query = {"query": "stale resolution marker indigo summit"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        stale_handle = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]
        original_plan = runtime.plan_scoped_delete
        replaced = False

        def replace_before_stale_plan(*args, **kwargs):
            nonlocal replaced
            if not replaced:
                competing_kwargs = {
                    **kwargs,
                    "idempotency_key": "competing-generation-delete",
                    "idempotency_context": "competing-generation-delete",
                }
                competing = original_plan(*args, **competing_kwargs)
                runtime.apply_scoped_delete(
                    tenant_id=str(competing["tenant_id"]),
                    operation_id=str(competing["operation_id"]),
                    actor=str(competing["created_by"]),
                )
                remember(
                    runtime,
                    {"text": text},
                    principal=PublicPrincipal("account/alice"),
                )
                replaced = True
            return original_plan(*args, **kwargs)

        monkeypatch.setattr(runtime, "plan_scoped_delete", replace_before_stale_plan)
        stale_delete = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [stale_handle],
                "idempotency_key": "stale-generation-delete",
            },
            headers=headers,
        )

        assert stale_delete.status_code == 404
        assert stale_delete.json() == {"detail": "Memory not found"}
        replacement = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"]
        assert len(replacement) == 1
        assert replacement[0]["id"] != stale_handle

    def test_stale_recall_snapshot_cannot_register_replacement_handle(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The stale registration marker is umber harbor."
        query = {"query": "stale registration marker umber harbor"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        original_register = runtime.register_public_memory_handles
        original_plan = runtime.plan_scoped_delete
        replaced = False

        def replace_before_registration(**kwargs):
            nonlocal replaced
            if not replaced:
                record_generations = {
                    record_id: generation
                    for record_id, generation in kwargs["handles"].values()
                }
                competing = original_plan(
                    tenant_id=kwargs["tenant_id"],
                    namespace=kwargs["namespace"],
                    scope=kwargs["scope"],
                    record_ids=list(record_generations),
                    idempotency_key="competing-registration-delete",
                    actor="principal-test",
                    idempotency_context="competing-registration-delete",
                    record_generations=record_generations,
                )
                runtime.apply_scoped_delete(
                    tenant_id=kwargs["tenant_id"],
                    operation_id=str(competing["operation_id"]),
                    actor="principal-test",
                )
                remember(
                    runtime,
                    {"text": text},
                    principal=PublicPrincipal("account/alice"),
                )
                replaced = True
            return original_register(**kwargs)

        monkeypatch.setattr(
            runtime,
            "register_public_memory_handles",
            replace_before_registration,
        )
        stale = client.post(
            "/v1/memories/recall", json=query, headers=headers
        )

        assert stale.status_code == 409
        assert stale.json() == {"detail": "memory changed during recall; retry"}
        monkeypatch.setattr(
            runtime,
            "register_public_memory_handles",
            original_register,
        )
        retry = client.post(
            "/v1/memories/recall", json=query, headers=headers
        )
        assert retry.status_code == 200
        assert len(retry.json()["memories"]) == 1

    def test_deleted_recall_snapshot_cannot_publish_a_handle(
        self, principal_api, monkeypatch
    ):
        client, runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The deleted registration marker is jade harbor."
        query = {"query": "deleted registration marker jade harbor"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        original_register = runtime.register_public_memory_handles
        deleted = False

        def delete_before_registration(**kwargs):
            nonlocal deleted
            if not deleted:
                generations = {
                    record_id: generation
                    for record_id, generation in kwargs["handles"].values()
                }
                operation = runtime.plan_scoped_delete(
                    tenant_id=kwargs["tenant_id"],
                    namespace=kwargs["namespace"],
                    scope=kwargs["scope"],
                    record_ids=list(generations),
                    idempotency_key="delete-before-registration",
                    actor="principal-test",
                    record_generations=generations,
                )
                runtime.apply_scoped_delete(
                    tenant_id=kwargs["tenant_id"],
                    operation_id=str(operation["operation_id"]),
                    actor="principal-test",
                )
                deleted = True
            return original_register(**kwargs)

        monkeypatch.setattr(
            runtime,
            "register_public_memory_handles",
            delete_before_registration,
        )

        stale = client.post("/v1/memories/recall", json=query, headers=headers)

        assert stale.status_code == 409
        assert stale.json() == {"detail": "memory changed during recall; retry"}

    def test_handle_registration_joins_the_runtime_projection_lock(
        self, principal_api
    ):
        client, runtime, db_path = principal_api
        headers = _principal_headers("a")
        assert client.post(
            "/v1/memories",
            json={"text": "The projection lock marker is copper fir."},
            headers=headers,
        ).status_code == 200
        memory_id = client.post(
            "/v1/memories/recall",
            json={"query": "projection lock marker copper fir"},
            headers=headers,
        ).json()["memories"][0]["id"]
        with sqlite3.connect(db_path) as connection:
            tenant_id, namespace, scope, record_id, generation = connection.execute(
                "select tenant_id, ns, scope, record_id, generation "
                "from public_memory_handle where handle_id = ?",
                (memory_id,),
            ).fetchone()

        lock_held = threading.Event()
        release_lock = threading.Event()
        registration_done = threading.Event()

        def hold_projection_lock():
            with runtime._persist_projection_lock:
                lock_held.set()
                assert release_lock.wait(timeout=5)

        def register_handle():
            runtime.register_public_memory_handles(
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                handles={memory_id: (record_id, generation)},
            )
            registration_done.set()

        holder = threading.Thread(target=hold_projection_lock)
        registrar = threading.Thread(target=register_handle)
        holder.start()
        assert lock_held.wait(timeout=5)
        registrar.start()
        assert not registration_done.wait(timeout=0.1)
        release_lock.set()
        holder.join(timeout=5)
        registrar.join(timeout=5)

        assert registration_done.is_set()
        assert not holder.is_alive()
        assert not registrar.is_alive()

    def test_one_delete_key_cannot_name_different_handle_sets(self, principal_api):
        client, _runtime, _db_path = principal_api
        headers = _principal_headers("a")
        for text in (
            "The first conflict marker is copper dawn.",
            "The second conflict marker is silver dusk.",
        ):
            assert client.post(
                "/v1/memories", json={"text": text}, headers=headers
            ).status_code == 200

        first_handle = client.post(
            "/v1/memories/recall",
            json={"query": "first conflict marker copper dawn"},
            headers=headers,
        ).json()["memories"][0]["id"]
        second_handle = client.post(
            "/v1/memories/recall",
            json={"query": "second conflict marker silver dusk"},
            headers=headers,
        ).json()["memories"][0]["id"]

        first = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [first_handle],
                "idempotency_key": "conflicting-handle-set",
            },
            headers=headers,
        )
        conflict = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [second_handle],
                "idempotency_key": "conflicting-handle-set",
            },
            headers=headers,
        )

        assert first.status_code == 200
        assert conflict.status_code == 409
        assert conflict.json() == {
            "detail": "idempotency_key already names a different deletion"
        }

    def test_delete_rejects_duplicate_handles_without_deleting(self, principal_api):
        client, _runtime, _db_path = principal_api
        headers = _principal_headers("a")
        text = "The duplicate handle marker is amber ridge."
        query = {"query": "duplicate handle marker amber ridge"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        memory_id = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]

        duplicate = client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [memory_id, memory_id],
                "idempotency_key": "duplicate-handle-delete",
            },
            headers=headers,
        )

        assert duplicate.status_code == 400
        assert duplicate.json() == {
            "detail": "memory_ids must contain unique ids"
        }
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"]

    def test_refused_boundary_race_is_content_free_and_replayable(
        self, principal_api, monkeypatch
    ):
        client, runtime, db_path = principal_api
        headers = _principal_headers("a")
        client.post(
            "/v1/memories",
            json={"text": "The boundary race marker is silver tide."},
            headers=headers,
        )
        memory_id = client.post(
            "/v1/memories/recall",
            json={"query": "boundary race marker silver tide"},
            headers=headers,
        ).json()["memories"][0]["id"]
        original_plan = runtime.plan_scoped_delete
        moved = False

        def plan_then_move(*args, **kwargs):
            nonlocal moved
            operation = original_plan(*args, **kwargs)
            if not moved:
                with sqlite3.connect(db_path) as connection:
                    connection.execute(
                        "update ir_records set ns = ? where id in ("
                        "select record_id from public_memory_handle where handle_id = ?)",
                        ("principal:foreign.sdk.race", memory_id),
                    )
                moved = True
            return operation

        monkeypatch.setattr(runtime, "plan_scoped_delete", plan_then_move)
        payload = {
            "memory_ids": [memory_id],
            "idempotency_key": "boundary-race-delete",
        }
        first = client.post(
            "/v1/memories/delete", json=payload, headers=headers
        )
        repeated = client.post(
            "/v1/memories/delete", json=payload, headers=headers
        )

        assert first.status_code == repeated.status_code == 404
        assert first.json() == repeated.json() == {"detail": "Memory not found"}

    def test_public_responses_do_not_leak_internal_boundaries(self, principal_api):
        client, _runtime, _db_path = principal_api
        headers = _principal_headers("a")
        write = client.post(
            "/v1/memories",
            json={"text": "The redacted note is amber river."},
            headers=headers,
        )
        recall = client.post(
            "/v1/memories/recall",
            json={"query": "redacted note amber river"},
            headers=headers,
        )
        memory_id = recall.json()["memories"][0]["id"]
        deleted = client.post(
            "/v1/memories/delete",
            json={"memory_ids": [memory_id], "idempotency_key": "redact-delete"},
            headers=headers,
        )
        rendered = json.dumps([write.json(), recall.json(), deleted.json()])
        for forbidden in (
            "principal:",
            ".sdk.",
            "tenant_id",
            "raw:",
            "clm:",
            "life:",
            "payload_json",
            "retrieval_policy",
            "graph",
        ):
            assert forbidden not in rendered

    def test_derived_cleanup_failure_is_opaque_and_recoverable(
        self, principal_api, monkeypatch
    ):
        client, runtime, db_path = principal_api
        headers = _principal_headers("a")
        client.post(
            "/v1/memories",
            json={"text": "The cleanup marker is violet harbor."},
            headers=headers,
        )
        query = {"query": "cleanup marker violet harbor"}
        memory_id = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]
        original_cleanup = runtime._delete_derived_records

        def fail_cleanup(_record_ids):
            raise RuntimeError("injected derived cleanup failure")

        monkeypatch.setattr(runtime, "_delete_derived_records", fail_cleanup)
        payload = {
            "memory_ids": [memory_id],
            "idempotency_key": "recoverable-delete",
        }
        pending = client.post(
            "/v1/memories/delete", json=payload, headers=headers
        )
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"
        assert "RuntimeError" not in json.dumps(pending.json())
        assert client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"] == []
        blocked_reingest = client.post(
            "/v1/memories",
            json={"text": "The cleanup marker is violet harbor."},
            headers=headers,
        )
        assert blocked_reingest.status_code == 409
        assert blocked_reingest.json() == {
            "detail": "memory deletion is still pending"
        }

        with sqlite3.connect(db_path) as connection:
            tenant_id = connection.execute(
                "select tenant_id from lifecycle_operation"
            ).fetchone()[0]
        assert runtime.store.recoverable_lifecycle_operations(
            tenant_id=tenant_id
        )[0]["state"] == "cleanup_pending"

        monkeypatch.setattr(runtime, "_delete_derived_records", original_cleanup)
        recovered = client.post(
            "/v1/memories/delete", json=payload, headers=headers
        )
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "deleted"
        assert recovered.json()["deletion_id"] == pending.json()["deletion_id"]
        assert runtime.store.recoverable_lifecycle_operations(
            tenant_id=tenant_id
        ) == []
        assert client.post(
            "/v1/memories",
            json={"text": "The cleanup marker is violet harbor."},
            headers=headers,
        ).status_code == 200

    def test_pending_delete_blocks_recreation_after_canonical_row_removal(
        self, principal_api, monkeypatch
    ):
        client, runtime, db_path = principal_api
        headers = _principal_headers("a")
        text = "The removed cleanup marker is cobalt harbor."
        query = {"query": "removed cleanup marker cobalt harbor"}
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200
        memory_id = client.post(
            "/v1/memories/recall", json=query, headers=headers
        ).json()["memories"][0]["id"]
        original_cleanup = runtime._delete_derived_records

        def fail_cleanup(_record_ids):
            raise RuntimeError("injected derived cleanup failure")

        monkeypatch.setattr(runtime, "_delete_derived_records", fail_cleanup)
        assert client.post(
            "/v1/memories/delete",
            json={
                "memory_ids": [memory_id],
                "idempotency_key": "removed-cleanup-delete",
            },
            headers=headers,
        ).json()["status"] == "pending"
        with sqlite3.connect(db_path) as connection:
            operation_id, tenant_id, payload_json = connection.execute(
                "select operation_id, tenant_id, payload_json "
                "from lifecycle_operation"
            ).fetchone()
        target_id = json.loads(payload_json)["record_ids"][0]
        runtime.store.delete_ir([target_id])

        blocked = client.post(
            "/v1/memories", json={"text": text}, headers=headers
        )
        assert blocked.status_code == 409
        assert blocked.json() == {"detail": "memory deletion is still pending"}

        monkeypatch.setattr(runtime, "_delete_derived_records", original_cleanup)
        assert runtime.apply_scoped_delete(
            tenant_id=tenant_id,
            operation_id=operation_id,
            actor="principal-test-recovery",
        )["state"] == "applied"
        assert client.post(
            "/v1/memories", json={"text": text}, headers=headers
        ).status_code == 200

    @pytest.mark.parametrize("path", ["/stats", "/persist", "/chat", "/openapi.json"])
    def test_principal_mode_disables_legacy_and_schema_routes(self, principal_api, path):
        client, _runtime, _db_path = principal_api
        payload = {"records": []} if path == "/persist" else {}
        if path == "/openapi.json" or path == "/stats":
            response = client.get(path, headers=_principal_headers("a"))
        else:
            response = client.post(path, json=payload, headers=_principal_headers("a"))
        assert response.status_code == 404

    @pytest.mark.parametrize("path", ["/", "/dashboard.html", "/seam-api.js"])
    def test_principal_mode_does_not_mount_the_private_webui(
        self, principal_api, path
    ):
        client, _runtime, _db_path = principal_api

        anonymous = client.get(path)
        authenticated = client.get(path, headers=_principal_headers("a"))

        assert anonymous.status_code == authenticated.status_code == 404

    def test_principal_mode_requires_stable_public_id_key(self, tmp_path):
        runtime = SeamRuntime(tmp_path / "missing-key.db")
        try:
            with pytest.raises(RuntimeError, match="public ID key"):
                create_app(
                    runtime,
                    principal_resolver=StaticPrincipalResolver(
                        {"token-a": "account/alice"}
                    ),
                    process_workers=1,
                )
        finally:
            runtime.close()

    def test_handle_and_deletion_receipt_survive_public_id_key_rotation(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
        monkeypatch.delenv("SEAM_API_PUBLIC_ID_KEY", raising=False)
        path = tmp_path / "rotated-public-id-key.db"
        resolver = StaticPrincipalResolver({"token-a": "account/alice"})
        original = SeamRuntime(path)
        try:
            with TestClient(
                create_app(
                    original,
                    principal_resolver=resolver,
                    public_id_key=b"original-public-id-key-32-bytes-long",
                    process_workers=1,
                )
            ) as client:
                assert client.post(
                    "/v1/memories",
                    json={"text": "The rotated handle marker is amber coast."},
                    headers=_principal_headers("a"),
                ).status_code == 200
                handle = client.post(
                    "/v1/memories/recall",
                    json={"query": "rotated handle marker amber coast"},
                    headers=_principal_headers("a"),
                ).json()["memories"][0]["id"]
                deletion_payload = {
                    "memory_ids": [handle],
                    "idempotency_key": "rotated-key-delete",
                }
                original_delete = client.post(
                    "/v1/memories/delete",
                    json=deletion_payload,
                    headers=_principal_headers("a"),
                )
                assert original_delete.status_code == 200
                original_deletion_id = original_delete.json()["deletion_id"]
        finally:
            original.close()

        reopened = SeamRuntime(path)
        try:
            with TestClient(
                create_app(
                    reopened,
                    principal_resolver=resolver,
                    public_id_key=b"replacement-public-id-key-32-bytes-long",
                    process_workers=1,
                )
            ) as client:
                response = client.post(
                    "/v1/memories/delete",
                    json=deletion_payload,
                    headers=_principal_headers("a"),
                )
                assert response.status_code == 200
                assert response.json()["status"] == "deleted"
                assert response.json()["deletion_id"] == original_deletion_id
        finally:
            reopened.close()
