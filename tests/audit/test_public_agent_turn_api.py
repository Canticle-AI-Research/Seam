"""HTTP contract tests for the opaque public agent-turn lifecycle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from seam_runtime.public_api import PublicPrincipal, StaticPrincipalResolver
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


def _dimensions(**extra: object) -> dict[str, object]:
    return {
        "namespace": "ghost.test",
        "scope": "thread",
        "session_id": "thread-1",
        **extra,
    }


def _begin(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    query: str = "What color does the operator prefer?",
):
    return client.post(
        "/v1/agent/turns/begin",
        json=_dimensions(
            query=query,
            limit=8,
            graph_hops=1,
            agent_id="ghost",
            model="test-model",
            provider="test-provider",
        ),
        headers=headers,
    )


def test_completed_turn_is_recalled_and_has_an_accepted_outcome(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "agent-turn.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            first = _begin(client)
            assert first.status_code == 200
            assert first.json()["memories"] == []
            turn_id = first.json()["turn_id"]

            actions = client.post(
                "/v1/agent/turns/actions",
                json=_dimensions(
                    turn_id=turn_id,
                    attempts=[
                        {
                            "name": "read_file",
                            "request": '{"path":"notes.txt"}',
                            "output": "ultramarine",
                            "ok": True,
                            "exit_code": 0,
                            "duration_ms": 4.5,
                        }
                    ],
                ),
            )
            assert actions.status_code == 200
            assert len(actions.json()["passed_verification_ids"]) == 1

            completed = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=turn_id,
                    user_input="Remember that my preferred color is ultramarine.",
                    assistant_output="I will remember that preference.",
                ),
            )
            assert completed.status_code == 200
            assert completed.json()["accepted"] is True
            assert completed.json()["memory_count"] > 0

            recalled = _begin(client)
            assert recalled.status_code == 200
            assert any(
                "ultramarine" in item["text"].lower()
                for item in recalled.json()["memories"]
            )

        graph = runtime.store.reasoning_graph(turn_id)
        outcomes = [node for node in graph["nodes"] if node["kind"] == "outcome"]
        assert outcomes[-1]["status"] == "accepted"
        verifications = runtime.store.reasoning_verifications(run_id=turn_id)
        assert verifications[0]["result_sha256"]
        assert "ultramarine" not in str(verifications[0])
    finally:
        runtime.close()


def test_failed_turn_is_rejected_and_never_recalled(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "failed-turn.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            started = _begin(client)
            turn_id = started.json()["turn_id"]
            failed = client.post(
                "/v1/agent/turns/fail",
                json=_dimensions(turn_id=turn_id, error_type="RuntimeError"),
            )
            assert failed.status_code == 200
            assert failed.json()["status"] == "rejected"

            recalled = client.post(
                "/v1/memories/recall",
                json=_dimensions(query="RuntimeError", limit=8),
            )
            assert recalled.status_code == 200
            assert recalled.json()["memories"] == []

        graph = runtime.store.reasoning_graph(turn_id)
        outcomes = [node for node in graph["nodes"] if node["kind"] == "outcome"]
        assert outcomes[-1]["status"] == "rejected"
    finally:
        runtime.close()


def test_turn_handles_cannot_cross_principals(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "principal-turn.db", allow_pgvector_env=False)
    app = create_app(
        runtime,
        principal_resolver=StaticPrincipalResolver(
            {"alice-token": PublicPrincipal("alice"), "bob-token": PublicPrincipal("bob")}
        ),
        public_id_key=b"public-agent-turn-test-key-32-bytes",
        process_workers=1,
    )
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    try:
        with TestClient(app) as client:
            turn_id = _begin(client, headers=alice).json()["turn_id"]
            crossed = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=turn_id,
                    user_input="Alice private input",
                    assistant_output="Alice private output",
                ),
                headers=bob,
            )
            assert crossed.status_code == 404

            own = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=turn_id,
                    user_input="Alice private input",
                    assistant_output="Alice private output",
                ),
                headers=alice,
            )
            assert own.status_code == 200
            recalled = _begin(client, headers=alice, query="Alice private input")
            assert recalled.status_code == 200
            assert any(
                "alice private input" in item["text"].lower()
                for item in recalled.json()["memories"]
            )
    finally:
        runtime.close()


def test_turn_handles_cannot_cross_session_partitions(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "session-turn.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            turn_id = _begin(client).json()["turn_id"]
            crossed = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    session_id="thread-2",
                    turn_id=turn_id,
                    user_input="private input",
                    assistant_output="private output",
                ),
            )
            assert crossed.status_code == 404
    finally:
        runtime.close()


def test_completion_and_failure_are_idempotent_terminal_replays(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "terminal-replay.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            completed_turn = _begin(client).json()["turn_id"]
            payload = _dimensions(
                turn_id=completed_turn,
                user_input="Remember cobalt.",
                assistant_output="Remembered.",
            )
            first = client.post("/v1/agent/turns/complete", json=payload)
            replay = client.post("/v1/agent/turns/complete", json=payload)
            assert first.status_code == replay.status_code == 200
            assert first.json()["receipt_id"] == replay.json()["receipt_id"]
            assert replay.json()["memory_count"] == first.json()["memory_count"]
            assert replay.json()["replayed"] is True
            after_terminal = client.post(
                "/v1/agent/turns/actions",
                json=_dimensions(turn_id=completed_turn, attempts=[]),
            )
            assert after_terminal.status_code == 409

            failed_turn = _begin(client).json()["turn_id"]
            failure = _dimensions(turn_id=failed_turn, error_type="CancelledError")
            assert client.post("/v1/agent/turns/fail", json=failure).status_code == 200
            replayed = client.post("/v1/agent/turns/fail", json=failure)
            assert replayed.status_code == 200
            assert replayed.json()["replayed"] is True
            assert replayed.json()["status"] == "rejected"
    finally:
        runtime.close()


def test_tool_verification_limit_applies_across_action_batches(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "action-limit.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            turn_id = _begin(client).json()["turn_id"]
            first = client.post(
                "/v1/agent/turns/actions",
                json=_dimensions(
                    turn_id=turn_id,
                    attempts=[
                        {"name": "read_file", "request": "{}", "ok": True}
                        for _index in range(64)
                    ],
                ),
            )
            assert first.status_code == 200
            overflow = client.post(
                "/v1/agent/turns/actions",
                json=_dimensions(
                    turn_id=turn_id,
                    attempts=[{"name": "read_file", "request": "{}", "ok": True}],
                ),
            )
            assert overflow.status_code == 409
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("decision", "reason_code"),
    [("reject", "transient"), ("review", "unconfirmed_durable")],
)
def test_non_admission_completes_reasoning_without_storing_memory(
    tmp_path, decision: str, reason_code: str
) -> None:
    runtime = SeamRuntime(tmp_path / "rejected-admission.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            turn_id = _begin(client, query="transient weather chatter").json()["turn_id"]
            completed = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=turn_id,
                    user_input="It is raining right now.",
                    assistant_output="Take an umbrella.",
                    memory_admission={
                        "decision": decision,
                        "kind": "none",
                        "reason_code": reason_code,
                    },
                ),
            )
            assert completed.status_code == 200
            assert completed.json()["memory_count"] == 0
            assert completed.json()["memory_admission"] == {
                "decision": decision,
                "kind": "none",
                "reason_code": reason_code,
            }

            replay = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=turn_id,
                    user_input="ignored on replay",
                    assistant_output="ignored on replay",
                ),
            )
            assert replay.status_code == 200
            assert replay.json()["replayed"] is True
            assert replay.json()["memory_admission"] == completed.json()[
                "memory_admission"
            ]
            recalled = client.post(
                "/v1/memories/recall",
                json=_dimensions(query="raining umbrella", limit=8),
            )
            assert recalled.status_code == 200
            assert recalled.json()["memories"] == []

        graph = runtime.store.reasoning_graph(turn_id)
        admission_nodes = [
            node
            for node in graph["nodes"]
            if node["kind"] == "decision"
            and node.get("operation") == "memory_admission"
        ]
        assert len(admission_nodes) == 1
        outcomes = [node for node in graph["nodes"] if node["kind"] == "outcome"]
        assert outcomes[-1]["status"] == "accepted"
        assert any(
            edge["src_node_id"] == admission_nodes[0]["node_id"]
            and edge["dst_node_id"] == outcomes[-1]["node_id"]
            and edge["relation"] == "supports"
            for edge in graph["edges"]
        )
    finally:
        runtime.close()


def test_explicit_admission_stores_memory_and_invalid_combinations_fail(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "explicit-admission.db", allow_pgvector_env=False)
    try:
        with TestClient(create_app(runtime)) as client:
            admitted_turn = _begin(client, query="operator preference").json()["turn_id"]
            admitted = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=admitted_turn,
                    user_input="Remember that I prefer indigo terminals.",
                    assistant_output="I will remember that preference.",
                    memory_admission={
                        "decision": "admit",
                        "kind": "preference",
                        "reason_code": "explicit_remember",
                    },
                ),
            )
            assert admitted.status_code == 200
            assert admitted.json()["memory_count"] > 0

            invalid_turn = _begin(client, query="invalid admission").json()["turn_id"]
            invalid = client.post(
                "/v1/agent/turns/complete",
                json=_dimensions(
                    turn_id=invalid_turn,
                    user_input="Do not store this.",
                    assistant_output="Understood.",
                    memory_admission={
                        "decision": "reject",
                        "kind": "preference",
                        "reason_code": "not_allowed",
                    },
                ),
            )
            assert invalid.status_code == 400
            graph = runtime.store.reasoning_graph(invalid_turn)
            assert not any(node["kind"] == "outcome" for node in graph["nodes"])
    finally:
        runtime.close()


def test_history_begin_does_not_publish_mutation_handles(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "history-turn.db", allow_pgvector_env=False)
    app = create_app(
        runtime,
        principal_resolver=StaticPrincipalResolver(
            {"alice-token": PublicPrincipal("alice")}
        ),
        public_id_key=b"history-agent-turn-test-key-32-bytes",
        process_workers=1,
    )
    headers = {"Authorization": "Bearer alice-token"}
    dimensions = _dimensions(workspace="workspace-1", project="project-1")
    try:
        with TestClient(app) as client:
            stored = client.post(
                "/v1/memories",
                json={"text": "The history marker is amber quartz.", **dimensions},
                headers=headers,
            )
            assert stored.status_code == 200
            current = client.post(
                "/v1/memories/recall",
                json={"query": "amber quartz", **dimensions},
                headers=headers,
            )
            memory_id = current.json()["memories"][0]["id"]
            deleted = client.post(
                "/v1/memories/delete",
                json={
                    "memory_ids": [memory_id],
                    "idempotency_key": "delete-history-agent-marker",
                    **dimensions,
                },
                headers=headers,
            )
            assert deleted.status_code == 200

            historical = client.post(
                "/v1/agent/turns/begin",
                json={
                    "query": "amber quartz",
                    "limit": 8,
                    "graph_hops": 1,
                    "agent_id": "ghost",
                    "view": "history",
                    **dimensions,
                },
                headers=headers,
            )
            assert historical.status_code == 200
            old = next(
                item
                for item in historical.json()["memories"]
                if "amber quartz" in item["text"].lower()
                and item["status"] == "deleted_soft"
            )
            mutation = client.post(
                "/v1/memories/delete",
                json={
                    "memory_ids": [old["id"]],
                    "idempotency_key": "delete-history-only-handle",
                    **dimensions,
                },
                headers=headers,
            )
            assert mutation.status_code == 404
    finally:
        runtime.close()
