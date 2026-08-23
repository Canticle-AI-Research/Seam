"""HTTP regression coverage for principal-aware authentication rate limiting."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from seam_runtime.public_api import PublicPrincipal, StaticPrincipalResolver
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


class _RejectingResolver:
    def __init__(self) -> None:
        self.credentials: list[str] = []

    def resolve_bearer(self, credential: str) -> None:
        self.credentials.append(credential)
        return None


class _RecordingResolver:
    def __init__(self, credentials: dict[str, str]) -> None:
        self.principals = {
            credential: PublicPrincipal(subject)
            for credential, subject in credentials.items()
        }
        self.credentials: list[str] = []

    def resolve_bearer(self, credential: str) -> PublicPrincipal | None:
        self.credentials.append(credential)
        return self.principals.get(credential)


class _FailingResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve_bearer(self, _credential: str) -> None:
        self.calls += 1
        raise RuntimeError("injected resolver failure")


class _BlockingRejectingResolver:
    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def resolve_bearer(self, _credential: str) -> None:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        return None


def test_static_resolver_handles_non_ascii_credentials_without_error() -> None:
    resolver = StaticPrincipalResolver({"ascii-token": "account/alice"})

    assert resolver.resolve_bearer("tökén") is None


def test_successful_principals_release_the_shared_client_reservation(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver(
        {
            "alice-token": "account/alice",
            "bob-token": "account/bob",
        }
    )
    runtime = SeamRuntime(tmp_path / "principal-client-reservation.db")

    try:
        with TestClient(create_app(
            runtime,
            principal_resolver=resolver,
            public_id_key=b"principal-rate-limit-public-id-key",
            process_workers=1,
        )) as client:
            alice = client.post(
                "/v1/memories",
                json={"text": "Alice reservation succeeds."},
                headers={"Authorization": "Bearer alice-token"},
            )
            bob = client.post(
                "/v1/memories",
                json={"text": "Bob reservation also succeeds."},
                headers={"Authorization": "Bearer bob-token"},
            )
    finally:
        runtime.close()

    assert alice.status_code == 200
    assert bob.status_code == 200


def test_subject_limit_blocks_repeated_valid_credential_before_resolver(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver({"valid-token": "account/alice"})
    runtime = SeamRuntime(tmp_path / "valid-resolver-budget.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            responses = [
                client.post(
                    "/v1/memories/recall",
                    json={"query": "resolver budget"},
                    headers={"Authorization": "Bearer valid-token"},
                )
                for _ in range(3)
            ]
    finally:
        runtime.close()

    assert [response.status_code for response in responses] == [200, 429, 429]
    assert resolver.credentials == ["valid-token"]


def test_credential_budget_does_not_evict_live_key_at_capacity(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_MAX_KEYS", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver({"valid-token": "account/alice"})
    runtime = SeamRuntime(tmp_path / "credential-budget-capacity.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            def recall(credential: str):
                return client.post(
                    "/v1/memories/recall",
                    json={"query": "credential capacity"},
                    headers={"Authorization": f"Bearer {credential}"},
                )

            responses = [
                recall("valid-token"),
                recall("rotating-invalid-one"),
                recall("valid-token"),
                recall("rotating-invalid-two"),
                recall("valid-token"),
            ]
    finally:
        runtime.close()

    assert [response.status_code for response in responses] == [
        200,
        429,
        200,
        429,
        429,
    ]
    assert resolver.credentials == ["valid-token", "valid-token"]


def test_malformed_public_bodies_consume_preparse_client_budget(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver({"valid-token": "account/alice"})
    runtime = SeamRuntime(tmp_path / "malformed-preparse-budget.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            first = client.post(
                "/v1/memories",
                content=b"{",
                headers={
                    "Authorization": "Bearer valid-token",
                    "Content-Type": "application/json",
                },
            )
            second = client.post(
                "/v1/memories",
                content=b"{",
                headers={
                    "Authorization": "Bearer valid-token",
                    "Content-Type": "application/json",
                },
            )
    finally:
        runtime.close()

    assert first.status_code == 422
    assert second.status_code == 429
    assert resolver.credentials == []


def test_rotating_invalid_bearer_tokens_share_the_client_rate_limit(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RejectingResolver()
    runtime = SeamRuntime(tmp_path / "principal-auth-rate-limit.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            first = client.post(
                "/v1/memories",
                json={"text": "not accepted"},
                headers={"Authorization": "Bearer invalid-one"},
            )
            second = client.post(
                "/v1/memories",
                json={"text": "still not accepted"},
                headers={"Authorization": "Bearer invalid-two"},
            )
    finally:
        runtime.close()

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert resolver.credentials == ["invalid-one"]


def test_authenticated_aliases_use_one_stable_principal_key(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver(
        {
            "rotating-valid-one": "account/alice",
            "rotating-valid-two": "account/alice",
        }
    )
    runtime = SeamRuntime(tmp_path / "principal-alias-rate-limit.db")

    try:
        app = create_app(
            runtime,
            principal_resolver=resolver,
            public_id_key=b"principal-rate-limit-public-id-key",
            process_workers=1,
        )
        with (
            TestClient(app, client=("192.0.2.10", 50000)) as first_client,
            TestClient(app, client=("192.0.2.11", 50000)) as second_client,
        ):
            first = first_client.post(
                "/v1/memories",
                json={"text": "accepted once"},
                headers={"Authorization": "Bearer rotating-valid-one"},
            )
            second = second_client.post(
                "/v1/memories",
                json={"text": "rate limited"},
                headers={"Authorization": "Bearer rotating-valid-two"},
            )
    finally:
        runtime.close()

    assert first.status_code == 200
    assert second.status_code == 429
    assert resolver.credentials == ["rotating-valid-one", "rotating-valid-two"]


def test_concurrent_invalid_burst_invokes_resolver_only_within_client_bound(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _BlockingRejectingResolver()
    runtime = SeamRuntime(tmp_path / "principal-concurrent-auth-limit.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(
                        client.post,
                        "/v1/memories",
                        json={"text": f"invalid attempt {index}"},
                        headers={"Authorization": f"Bearer invalid-{index}"},
                    )
                    for index in range(8)
                ]
                assert resolver.entered.wait(timeout=5)
                resolver.release.set()
                statuses = sorted(future.result().status_code for future in futures)
    finally:
        resolver.release.set()
        runtime.close()

    assert statuses == [401, *([429] * 7)]
    assert resolver.calls == 1


def test_resolver_failures_are_bounded_before_reinvocation(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _FailingResolver()
    runtime = SeamRuntime(tmp_path / "principal-resolver-failure-limit.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            ),
            raise_server_exceptions=False,
        ) as client:
            first = client.post(
                "/v1/memories",
                json={"text": "resolver fails once"},
                headers={"Authorization": "Bearer failing-token-one"},
            )
            second = client.post(
                "/v1/memories",
                json={"text": "resolver is not called twice"},
                headers={"Authorization": "Bearer failing-token-two"},
            )
    finally:
        runtime.close()

    assert first.status_code == 500
    assert first.json() == {"detail": "Internal server error"}
    assert second.status_code == 429
    assert resolver.calls == 1


def test_legacy_token_preserves_per_credential_rate_limit_keys(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("SEAM_API_TOKEN", "legacy-valid")
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    runtime = SeamRuntime(tmp_path / "legacy-auth-rate-limit.db")

    try:
        with TestClient(create_app(runtime)) as client:
            first_invalid = client.post(
                "/v1/memories",
                json={"text": "not accepted"},
                headers={"Authorization": "Bearer invalid-one"},
            )
            authenticated = client.post(
                "/v1/memories",
                json={"text": "accepted"},
                headers={"Authorization": "Bearer legacy-valid"},
            )
            second_invalid = client.post(
                "/v1/memories",
                json={"text": "still not accepted"},
                headers={"Authorization": "Bearer invalid-two"},
            )
    finally:
        runtime.close()

    assert first_invalid.status_code == 401
    assert authenticated.status_code == 200
    assert second_invalid.status_code == 401


def test_health_remains_unauthenticated_and_rate_limited_by_client(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver({"valid-token": "account/alice"})
    runtime = SeamRuntime(tmp_path / "health-rate-limit.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            first = client.get(
                "/v1/health",
                headers={"Authorization": "Bearer ignored-one"},
            )
            second = client.get(
                "/v1/health",
                headers={"Authorization": "Bearer ignored-two"},
            )
    finally:
        runtime.close()

    assert first.status_code == 200
    assert second.status_code == 429
    assert resolver.credentials == []


def test_hidden_private_routes_are_rate_limited_before_router_matching(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_PRINCIPAL", raising=False)
    resolver = _RecordingResolver({"valid-token": "account/alice"})
    runtime = SeamRuntime(tmp_path / "hidden-route-rate-limit.db")

    try:
        with TestClient(
            create_app(
                runtime,
                principal_resolver=resolver,
                public_id_key=b"principal-rate-limit-public-id-key",
                process_workers=1,
            )
        ) as client:
            first = client.post(
                "/stats",
                headers={"Authorization": "Bearer valid-token"},
            )
            second = client.get(
                "/stats/",
                headers={"Authorization": "Bearer valid-token"},
                follow_redirects=False,
            )
    finally:
        runtime.close()

    assert first.status_code == 404
    assert first.json() == {"detail": "Not found"}
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert resolver.credentials == []
