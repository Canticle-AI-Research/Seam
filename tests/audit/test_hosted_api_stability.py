from __future__ import annotations

from fastapi.testclient import TestClient

from seam_runtime.server import create_app


class _HostedRuntime:
    def __init__(self, *, readiness_error: Exception | None = None) -> None:
        self.readiness_error = readiness_error
        self.checks = 0

    def check_ready(self) -> None:
        self.checks += 1
        if self.readiness_error is not None:
            raise self.readiness_error


def test_hosted_health_checks_storage_once_and_supports_head(monkeypatch) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "10000")
    runtime = _HostedRuntime()
    client = TestClient(create_app(runtime))

    internal = client.get("/health")
    public = client.get("/v1/health")
    public_head = client.head("/v1/health")

    assert internal.status_code == 200
    assert internal.json() == {"status": "ok"}
    assert public.status_code == 200
    assert public.json() == {"status": "ok", "api_version": "v1"}
    assert public_head.status_code == 200
    assert public_head.content == b""
    assert runtime.checks == 1


def test_hosted_health_degrades_without_backend_details(monkeypatch) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "10000")
    runtime = _HostedRuntime(
        readiness_error=ConnectionError("private managed database detail")
    )
    client = TestClient(create_app(runtime))

    internal = client.get("/health")
    public = client.get("/v1/health")

    assert internal.status_code == 503
    assert internal.json() == {"status": "degraded"}
    assert public.status_code == 503
    assert public.json() == {"status": "degraded", "api_version": "v1"}
    assert "private managed database detail" not in internal.text
    assert "private managed database detail" not in public.text


def test_hosted_api_returns_generic_json_for_unexpected_errors(monkeypatch) -> None:
    class _BrokenRuntime(_HostedRuntime):
        def compile_nl(self, *_args: object, **_kwargs: object) -> None:
            raise ZeroDivisionError("private hosted failure")

    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "10000")
    client = TestClient(create_app(_BrokenRuntime()), raise_server_exceptions=False)

    response = client.post("/v1/memories", json={"text": "remember this"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal server error"}
    assert "private hosted failure" not in response.text


def test_hosted_api_rate_limit_includes_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("SEAM_API_RATE_LIMIT", "1")
    monkeypatch.setenv("SEAM_API_TOKEN", "hosted-test-token")
    client = TestClient(create_app(_HostedRuntime()))

    assert client.post("/v1/memories", json={"text": "one"}).status_code == 401
    limited = client.post("/v1/memories", json={"text": "two"})

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
