"""HTTP contract tests for the opaque public agent-turn lifecycle."""

from __future__ import annotations

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
