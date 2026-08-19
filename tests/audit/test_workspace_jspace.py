from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import seam_runtime.server as server
from seam_runtime.jspace import (
    JLensUnavailable,
    LocalQwenJLensWorker,
    RemoteJLensWorker,
    UnavailableJLensWorker,
    _remote_transport,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, SearchCandidate, SearchResult, Status
from seam_runtime.runtime import SeamRuntime
from seam_runtime.workspace import spread_graph_activation


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
    instance = SeamRuntime(tmp_path / "workspace.db")
    try:
        yield instance
    finally:
        instance.close()


def _parse_sse(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in body.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in frame.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key] = value.lstrip()
        payload = json.loads(fields["data"])
        assert int(fields["id"]) == payload["event_id"]
        assert fields["event"] == payload["event_type"]
        events.append(payload)
    return events


def _chat_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "message": "What should I remember?",
        "model": "test-model",
        "provider": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "use_memory": False,
        "persist_chat": False,
    }
    payload.update(overrides)
    return payload


def test_workspace_storage_is_append_only_ordered_concurrent_and_redacted(runtime: SeamRuntime) -> None:
    run = runtime.store.create_workspace_run(
        run_id="ws:test",
        ns="team.alpha",
        scope="project",
        metadata={
            "message_chars": 7,
            "authorization": "Bearer metadata-secret",
            "access_token": "metadata-access-token",
            "safe": "not-allowlisted",
        },
    )
    assert run["metadata"] == {
        "message_chars": 7,
        "redacted_fields": ["access_token", "authorization", "safe"],
    }

    def append(index: int) -> dict[str, object]:
        return runtime.store.append_workspace_event(
            run_id="ws:test",
            event_type="tool",
            payload={
                "tool": "chat_provider",
                "status": "completed",
                "provider": "local",
                "model": str(index),
                "access_token": f"access-{index}",
                "client_secret": f"client-secret-{index}",
                "description": [1, 2, 3],
                "nested": {
                    "raw_activations": [1, 2, 3],
                    "chain_of_thought": "private reasoning",
                },
            },
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(append, range(18)))

    events = runtime.store.iter_workspace_events(run_id="ws:test", limit=100)
    assert [event["seq"] for event in events] == list(range(1, 19))
    assert [event["event_id"] for event in events] == sorted(event["event_id"] for event in events)
    assert {event["payload"]["model"] for event in events} == {str(index) for index in range(18)}
    assert all("nested" not in event["payload"] for event in events)
    assert all("access_token" not in event["payload"] for event in events)
    assert all("client_secret" not in event["payload"] for event in events)
    assert all(
        event["payload"]["redacted_fields"]
        == ["access_token", "client_secret", "description", "nested"]
        for event in events
    )
    unsafe_concept = runtime.store.append_workspace_event(
        run_id="ws:test",
        event_type="jlens_concept",
        payload={
            "concept": {
                "id": "concept:unsafe",
                "label": "bounded label",
                "description": [[1.0, 2.0, 3.0]],
                "access_token": "nested-access-token",
            },
            "backend": "test",
            "model": "test-model",
            "revision": "fixed",
            "model_artifact_hash": "a" * 64,
            "lens_artifact_hash": "b" * 64,
            "identity_verified": True,
            "raw_activations_persisted": False,
            "client_secret": "top-level-secret",
        },
    )
    assert unsafe_concept["payload"]["concept"] == {
        "id": "concept:unsafe",
        "label": "bounded label",
        "description": "",
    }
    assert unsafe_concept["payload"]["redacted_fields"] == [
        "client_secret",
        "concept.access_token",
        "concept.description",
    ]

    with runtime.store._pool.checkout() as connection:
        stored = " ".join(
            str(row[0])
            for row in connection.execute(
                "select metadata_json from workspace_run union all "
                "select payload_json from workspace_event"
            ).fetchall()
        )
        assert "metadata-secret" not in stored
        assert "metadata-access-token" not in stored
        assert "client-secret-" not in stored
        assert "private reasoning" not in stored
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("update workspace_event set event_type = 'failure' where event_id = 1")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("delete from workspace_run where run_id = 'ws:test'")


def test_workspace_replay_capabilities_and_auth(runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime.store.create_workspace_run(run_id="ws:one", ns="team.alpha", scope="project")
    first = runtime.store.append_workspace_event(run_id="ws:one", event_type="run", payload={"status": "started"})
    second = runtime.store.append_workspace_event(
        run_id="ws:one", event_type="completion", payload={"status": "completed"}
    )
    monkeypatch.setenv("SEAM_API_TOKEN", "workspace-token")
    client = TestClient(server.create_app(runtime, jlens_worker=UnavailableJLensWorker("disabled for test")))

    assert client.get("/workspace/capabilities").status_code == 401
    headers = {"Authorization": "Bearer workspace-token"}
    capabilities = client.get("/workspace/capabilities", headers=headers).json()
    assert capabilities["schema"] == "seam-workspace-capabilities/v1"
    assert capabilities["append_only_replay"] is True
    assert capabilities["raw_chain_of_thought_persisted"] is False
    assert capabilities["raw_activations_persisted"] is False
    assert capabilities["jlens"]["available"] is False
    assert {"run", "completion", "failure", "jlens_concept"} <= set(capabilities["event_types"])

    replay = client.get(
        "/workspace/events",
        params={"run_id": "ws:one", "after": first["event_id"]},
        headers=headers,
    ).json()
    assert [event["event_id"] for event in replay["events"]] == [second["event_id"]]
    assert replay["next_after"] == second["event_id"]
    runs = client.get(
        "/workspace/runs", params={"namespace": "team.alpha", "scope": "project"}, headers=headers
    ).json()["runs"]
    assert runs[0]["run_id"] == "ws:one"
    assert runs[0]["status"] == "completed"
    detail = client.get("/workspace/runs/ws:one", headers=headers).json()
    assert [event["seq"] for event in detail["events"]] == [1, 2]


def test_chat_stream_sse_contract_replay_and_terminal_completion(
    runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "_call_chat_provider", lambda **kwargs: "streamed answer")
    client = TestClient(server.create_app(runtime))

    response = client.post("/chat/stream", json=_chat_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    run_id = response.headers["x-seam-workspace-run"]
    events = _parse_sse(response.text)
    assert all(event["run_id"] == run_id for event in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "run"
    assert events[-1]["event_type"] == "completion"
    assert sum(event["event_type"] in {"completion", "failure"} for event in events) == 1
    assert "".join(
        str(event["payload"]["text"])
        for event in events
        if event["event_type"] == "answer_delta"
    ) == "streamed answer"
    replay = client.get(f"/workspace/runs/{run_id}").json()
    assert replay["events"] == events
    assert replay["run"]["status"] == "completed"


def test_chat_stream_provider_failure_is_terminal_and_sanitized(
    runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_provider(**kwargs: object) -> str:
        raise RuntimeError("provider-secret-must-not-enter-events")

    monkeypatch.setattr(server, "_call_chat_provider", fail_provider)
    response = TestClient(server.create_app(runtime)).post("/chat/stream", json=_chat_payload())
    events = _parse_sse(response.text)
    assert events[-1]["event_type"] == "failure"
    assert events[-1]["payload"]["error_type"] == "RuntimeError"
    assert "provider-secret-must-not-enter-events" not in response.text


def test_answer_context_gate_filters_unverified_and_refuted_records_on_both_chat_surfaces(
    runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe = MIRLRecord(
        id="raw:safe",
        kind=RecordKind.RAW,
        ns="team.alpha",
        scope="project",
        attrs={"content": "SAFE EVIDENCE: deployment is Friday", "source_ref": "human://ops"},
    )
    unverified = MIRLRecord(
        id="clm:unverified",
        kind=RecordKind.CLM,
        ns="team.alpha",
        scope="project",
        attrs={
            "subject": "ent:deployment",
            "predicate": "is",
            "object": "UNVERIFIED MONDAY",
        },
    )
    refuted = MIRLRecord(
        id="clm:refuted",
        kind=RecordKind.CLM,
        ns="team.alpha",
        scope="project",
        status=Status.CONTRADICTED,
        attrs={"subject": "ent:deployment", "predicate": "is", "object": "REFUTED TUESDAY"},
    )
    deployment = MIRLRecord(
        id="ent:deployment",
        kind=RecordKind.ENT,
        ns="team.alpha",
        scope="project",
        attrs={"label": "Deployment", "entity_type": "concept"},
    )
    runtime.persist_ir(IRBatch([safe, deployment, unverified, refuted]))
    candidates = [
        SearchCandidate(record=safe, score=0.9),
        SearchCandidate(record=unverified, score=0.8),
        SearchCandidate(record=refuted, score=0.7),
    ]
    monkeypatch.setattr(
        runtime,
        "search_ir",
        lambda **kwargs: SearchResult(query=str(kwargs["query"]), candidates=candidates),
    )
    prompts: list[str] = []

    def provider(**kwargs: object) -> str:
        messages = kwargs["messages"]
        prompts.append(next(message["content"] for message in messages if message["role"] == "system"))
        return "answer"

    monkeypatch.setattr(server, "_call_chat_provider", provider)
    client = TestClient(server.create_app(runtime))
    payload = _chat_payload(
        use_memory=True,
        ns="team.alpha",
        scope="project",
    )

    regular = client.post("/chat", json=payload)
    streamed = client.post("/chat/stream", json=payload)

    assert regular.status_code == 200
    assert regular.json()["memory_used"] == 1
    assert streamed.status_code == 200
    assert len(prompts) == 2
    for prompt in prompts:
        assert "SAFE EVIDENCE" in prompt
        assert "UNVERIFIED MONDAY" not in prompt
        assert "REFUTED TUESDAY" not in prompt
    events = _parse_sse(streamed.text)
    retrieval = next(event for event in events if event["event_type"] == "retrieval")
    assert retrieval["payload"]["asserted_context_ids"] == ["raw:safe"]
    assert [candidate["record_id"] for candidate in retrieval["payload"]["candidates"]] == [
        "raw:safe",
        "clm:unverified",
        "clm:refuted",
    ]
    graph_event = next(event for event in events if event["event_type"] == "graph_activation")
    assert graph_event["payload"]["seed_ids"] == ["raw:safe", "clm:unverified", "clm:refuted"]


def test_chat_defaults_fail_closed_to_local_chat_thread_and_excludes_other_tenant(
    runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = runtime.compile_nl(
        "TENANT B SECRET FACT should never enter the default chat.",
        source_ref="human://tenant-b",
        ns="tenant.b",
        scope="thread",
    )
    runtime.persist_ir(other)
    captured: dict[str, str] = {}

    def provider(**kwargs: object) -> str:
        messages = kwargs["messages"]
        captured["system"] = next(
            str(message["content"]) for message in messages if message["role"] == "system"
        )
        return "default-boundary-answer"

    monkeypatch.setattr(server, "_call_chat_provider", provider)
    response = TestClient(server.create_app(runtime)).post(
        "/chat",
        json=_chat_payload(
            message="What is the tenant B secret fact?",
            use_memory=True,
            persist_chat=True,
        ),
    )

    assert response.status_code == 200
    assert "TENANT B SECRET FACT" not in captured["system"]
    assert response.json()["memory_used"] == 0
    with runtime.store._pool.checkout() as connection:
        chat_rows = connection.execute(
            "select payload_json from ir_records where ns = 'local.chat' and scope = 'thread'"
        ).fetchall()
        assistant_episode = connection.execute(
            "select metadata_json from knowledge_episodes "
            "where ns = 'local.chat' and scope = 'thread' and source_ref like 'chat://%/assistant'"
        ).fetchone()
    payloads = [json.loads(row[0]) for row in chat_rows]
    assistant_raw = next(
        payload
        for payload in payloads
        if payload["kind"] == "RAW" and payload["attrs"]["source_ref"].endswith("/assistant")
    )
    assert assistant_raw["attrs"]["source_type"] == "model_output"
    assert assistant_raw["attrs"]["model_output"] is True
    assert assistant_episode is not None
    assert json.loads(assistant_episode[0])["source_type"] == "model_output"
    assert json.loads(assistant_episode[0])["model_output"] is True

    assert TestClient(server.create_app(runtime)).post(
        "/chat", json=_chat_payload(ns="", persist_chat=False)
    ).status_code == 400


def test_local_jlens_uses_verified_mocked_artifacts_without_download_and_normalizes_output(
    tmp_path: Path,
) -> None:
    loader_calls: list[dict[str, object]] = []

    def loader(**kwargs: object) -> tuple[object, object]:
        loader_calls.append(dict(kwargs))
        return object(), object()

    def analyzer(**kwargs: object) -> dict[str, object]:
        return {
            "concepts": [
                {
                    "id": "concept:memory",
                    "label": "memory retrieval",
                    "score": 1.7,
                    "raw_activations": [9, 8, 7],
                    "description": ["nested", "activation", "array"],
                }
            ]
        }

    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(json.dumps({"model": "local/qwen", "revision": "abc123"}), encoding="utf-8")
    lens = tmp_path / "lens.bin"
    lens.write_bytes(b"verified-lens-artifact")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    lens_hash = hashlib.sha256(lens.read_bytes()).hexdigest()

    worker = LocalQwenJLensWorker(
        model="local/qwen",
        revision="abc123",
        model_artifact_hash=manifest_hash,
        lens_artifact_hash=lens_hash,
        model_manifest_path=manifest,
        lens_artifact_path=lens,
        analyzer=analyzer,
        model_loader=loader,
    )
    assert worker.capability()["available"] is True
    result = worker.analyze(messages=[{"role": "user", "content": "hello"}], answer="world")
    assert loader_calls == [
        {"model": "local/qwen", "revision": "abc123", "local_files_only": True}
    ]
    assert result.concepts == ({"id": "concept:memory", "label": "memory retrieval", "score": 1.0},)
    assert result.model_artifact_hash == manifest_hash
    assert result.lens_artifact_hash == lens_hash
    assert result.identity_verified is True

    manifest.write_text(json.dumps({"model": "other/model", "revision": "abc123"}), encoding="utf-8")
    assert worker.capability()["available"] is False
    assert worker.capability()["genuine_jacobian_lens"] is False


def test_remote_jlens_mock_transport_is_authenticated_without_token_leak() -> None:
    calls: list[tuple[str, str, dict[str, object], int]] = []

    def transport(endpoint: str, token: str, body: dict[str, object], timeout: int) -> dict[str, object]:
        calls.append((endpoint, token, body, timeout))
        return {
            "model": "remote/qwen",
            "revision": "fixed",
            "model_artifact_hash": "a" * 64,
            "lens_artifact_hash": "b" * 64,
            "concepts": [
                {
                    "label": "decision",
                    "score": 0.5,
                    "description": [[1.0, 2.0]],
                    "access_token": "must-not-survive",
                    "client_secret": "must-not-survive",
                }
            ],
        }

    worker = RemoteJLensWorker(
        endpoint="http://127.0.0.1:9444/analyze",
        token="remote-secret-token",
        model="remote/qwen",
        revision="fixed",
        model_artifact_hash="a" * 64,
        lens_artifact_hash="b" * 64,
        transport=transport,
        timeout=70,
    )
    capability = worker.capability()
    assert capability["genuine_jacobian_lens"] is False
    assert capability["identity_verified"] is False
    result = worker.analyze(messages=[{"role": "user", "content": "hello"}], answer="world")

    assert capability["authenticated"] is True
    assert "remote-secret-token" not in json.dumps(capability)
    assert "remote-secret-token" not in json.dumps(result.to_dict())
    assert calls[0][1] == "remote-secret-token"
    assert calls[0][2]["return_raw_activations"] is False
    assert calls[0][3] == 30
    assert result.identity_verified is True
    assert worker.capability()["genuine_jacobian_lens"] is True
    assert result.concepts == ({"id": "concept:0", "label": "decision", "score": 0.5},)

    def mismatched(endpoint: str, token: str, body: dict[str, object], timeout: int) -> dict[str, object]:
        del endpoint, token, body, timeout
        return {
            "model": "remote/qwen",
            "revision": "wrong",
            "model_artifact_hash": "a" * 64,
            "lens_artifact_hash": "b" * 64,
            "concepts": [],
        }

    mismatched_worker = RemoteJLensWorker(
        endpoint="http://127.0.0.1:9444/analyze",
        token="token",
        model="remote/qwen",
        revision="fixed",
        model_artifact_hash="a" * 64,
        lens_artifact_hash="b" * 64,
        transport=mismatched,
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        mismatched_worker.analyze(messages=[], answer="")


def test_remote_jlens_public_endpoint_requires_operator_allowlist_and_exact_dns_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "seam_runtime.jspace.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("8.8.8.8", port or 443))],
    )
    base = {
        "endpoint": "https://jlens.example.test/analyze",
        "token": "token",
        "model": "remote/qwen",
        "revision": "fixed",
        "model_artifact_hash": "a" * 64,
        "lens_artifact_hash": "b" * 64,
    }
    assert RemoteJLensWorker(**base).capability()["available"] is False
    allowlisted = RemoteJLensWorker(
        **base,
        allowed_hosts=frozenset({"jlens.example.test"}),
    )
    assert allowlisted.capability()["available"] is False
    assert "pinned" in str(allowlisted.capability()["reason"])
    pinned = RemoteJLensWorker(
        **base,
        allowed_hosts=frozenset({"jlens.example.test"}),
        pinned_ips=frozenset({"8.8.8.8"}),
    )
    assert pinned.capability()["available"] is True
    assert pinned.capability()["identity_verified"] is False
    assert pinned.capability()["genuine_jacobian_lens"] is False


def test_remote_transport_caps_timeout_and_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def read(self, limit: int) -> bytes:
            return b"x" * limit

    class Opener:
        def open(self, request, timeout: int):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()

    monkeypatch.setattr("seam_runtime.jspace.urllib.request.build_opener", lambda *handlers: Opener())
    with pytest.raises(ValueError, match="byte limit"):
        _remote_transport(
            "http://127.0.0.1:9444/analyze",
            "token",
            {"schema": "seam-jlens-request/v1"},
            500,
            max_response_bytes=64,
        )
    assert captured == {"url": "http://127.0.0.1:9444/analyze", "timeout": 30}


def test_jlens_unavailable_fallback_fails_closed_without_loading_a_model() -> None:
    worker = UnavailableJLensWorker("no configured worker")
    assert worker.capability()["mode"] == "structured_workspace_only"
    with pytest.raises(JLensUnavailable, match="no configured worker"):
        worker.analyze(messages=[], answer="")

    incomplete_local = LocalQwenJLensWorker(model_loader=lambda **kwargs: (object(), object()))
    assert incomplete_local.capability()["available"] is False
    with pytest.raises(JLensUnavailable, match="analyzer"):
        incomplete_local.analyze(messages=[], answer="")


def test_spreading_activation_is_bounded_deterministic_and_provenance_preserving() -> None:
    graph = {
        "edges": [
            {"id": "edge:ab", "source": "a", "target": "b", "confidence": 0.5},
            {"id": "edge:bc", "source": "b", "target": "c", "confidence": 1.0},
            {"id": "edge:ad", "source": "a", "target": "d", "confidence": 0.5},
        ]
    }
    activated = spread_graph_activation(graph, ["a"], max_hops=2, decay=0.72, limit=10)
    assert activated == [
        {"node_id": "a", "activation": 1.0, "hop": 0, "from_node_id": None, "via_edge_id": None},
        {"node_id": "b", "activation": 0.36, "hop": 1, "from_node_id": "a", "via_edge_id": "edge:ab"},
        {"node_id": "d", "activation": 0.36, "hop": 1, "from_node_id": "a", "via_edge_id": "edge:ad"},
        {"node_id": "c", "activation": 0.2592, "hop": 2, "from_node_id": "b", "via_edge_id": "edge:bc"},
    ]
    assert spread_graph_activation(graph, ["a"], limit=2) == activated[:2]
    assert spread_graph_activation(
        {
            "edges": [
                {
                    "id": "edge:zero",
                    "source": "a",
                    "target": "blocked",
                    "confidence": 0.0,
                }
            ]
        },
        ["a"],
    ) == [
        {
            "node_id": "a",
            "activation": 1.0,
            "hop": 0,
            "from_node_id": None,
            "via_edge_id": None,
        }
    ]
    with pytest.raises(ValueError, match="decay"):
        spread_graph_activation(graph, ["a"], decay=0.0)
