"""Tests for server bind safety: remote unauthenticated bind refusal."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from seam_runtime.server import (
    _factory_server_settings,
    _is_remote_bind,
    _validate_server_safety,
)


class TestRemoteBindSafety:
    @pytest.mark.parametrize("workers", [0, -1, True])
    def test_non_positive_or_boolean_worker_count_is_rejected(self, workers, monkeypatch):
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        with pytest.raises(RuntimeError, match="positive integer"):
            _validate_server_safety(host="127.0.0.1", workers=workers)

    def test_localhost_bind_allowed_without_token(self, monkeypatch):
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_ALLOW_REMOTE_NO_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        # Should not raise
        _validate_server_safety(host="127.0.0.1", workers=1)

    def test_localhost_bind_allowed_without_token_ipv6(self, monkeypatch):
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_ALLOW_REMOTE_NO_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        _validate_server_safety(host="::1", workers=1)

    def test_remote_bind_rejected_without_token(self, monkeypatch):
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_ALLOW_REMOTE_NO_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        with pytest.raises(RuntimeError, match="without an authentication token"):
            _validate_server_safety(host="0.0.0.0", workers=1)

    def test_remote_bind_allowed_with_override(self, monkeypatch):
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.setenv("SEAM_API_ALLOW_REMOTE_NO_TOKEN", "1")
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        # Should not raise
        _validate_server_safety(host="0.0.0.0", workers=1)

    def test_remote_bind_allowed_with_token(self, monkeypatch):
        monkeypatch.setenv("SEAM_API_TOKEN", "test-token")
        monkeypatch.setenv("SEAM_API_ALLOW_INSECURE_REMOTE", "1")
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        # Should not raise if insecure remote is allowed
        _validate_server_safety(host="0.0.0.0", workers=1)

    def test_is_remote_bind_false_for_localhost(self):
        assert not _is_remote_bind("127.0.0.1")
        assert not _is_remote_bind("localhost")
        assert not _is_remote_bind("::1")

    def test_is_remote_bind_true_for_public(self):
        assert _is_remote_bind("0.0.0.0")
        assert _is_remote_bind("192.168.1.1")


def test_factory_settings_resolve_uvicorn_cli_over_environment():
    host, workers = _factory_server_settings(
        ["seam_runtime.server:create_app_from_env", "--factory", "--host=0.0.0.0", "--workers", "3"],
        {"UVICORN_HOST": "127.0.0.1", "UVICORN_WORKERS": "1"},
    )
    assert (host, workers) == ("0.0.0.0", 3)


def test_run_server_rejects_bad_worker_count_before_optional_imports(monkeypatch):
    import seam_runtime.server as server

    def optional_import_reached():
        raise AssertionError("optional server import should not be reached")

    monkeypatch.setattr(server, "_require_fastapi", optional_import_reached)
    with pytest.raises(RuntimeError, match="positive integer"):
        server.run_server(workers=0)


def test_real_uvicorn_factory_refuses_unsafe_remote_launch(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    for name in (
        "SEAM_API_TOKEN",
        "SEAM_API_ALLOW_REMOTE_NO_TOKEN",
        "SEAM_API_ALLOW_INSECURE_REMOTE",
        "SEAM_SERVER_HOST",
        "SEAM_SERVER_WORKERS",
        "UVICORN_HOST",
        "UVICORN_WORKERS",
        "WEB_CONCURRENCY",
    ):
        env.pop(name, None)
    env["SEAM_SERVER_DB"] = str(tmp_path / "factory.db")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "seam_runtime.server:create_app_from_env",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "0",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "without an authentication token" in (result.stdout + result.stderr)


class TestGeneratedDocsRoutesFollowTheAuthDecision:
    """FastAPI registers /docs, /redoc and /openapi.json without dependencies, so
    they bypass both the bearer guard and the rate limiter. When an operator sets
    SEAM_API_TOKEN they have asked for an authenticated surface; anonymous path
    inventory disclosure (and an unmetered per-request schema rebuild)
    contradicts that."""

    @staticmethod
    def _client(monkeypatch, token):
        from fastapi.testclient import TestClient

        from seam_runtime.server import create_app_from_env

        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        if token is None:
            monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        else:
            monkeypatch.setenv("SEAM_API_TOKEN", token)
        return TestClient(create_app_from_env())

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
    def test_docs_routes_are_absent_when_a_token_is_configured(self, path, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_DB_PATH", str(tmp_path / "docs_gate.db"))
        client = self._client(monkeypatch, "test-token-value")

        assert client.get(path).status_code == 404

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
    def test_docs_routes_remain_for_unauthenticated_loopback_development(
        self, path, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("SEAM_DB_PATH", str(tmp_path / "docs_open.db"))
        client = self._client(monkeypatch, None)

        assert client.get(path).status_code == 200

    def test_openapi_operation_ids_are_unique(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_DB_PATH", str(tmp_path / "openapi_ids.db"))
        client = self._client(monkeypatch, None)

        schema = client.get("/openapi.json").json()
        operation_ids = [
            operation["operationId"]
            for path_item in schema["paths"].values()
            for operation in path_item.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]

        assert len(operation_ids) == len(set(operation_ids))
        expected_health_operations = {
            "/health": {
                "get": ("health_health_get", "Health"),
                "head": ("health_health_head", "Health"),
            },
            "/v1/health": {
                "get": ("public_health_v1_health_get", "Public Health"),
                "head": ("public_health_v1_health_head", "Public Health"),
            },
        }
        for path, expected_operations in expected_health_operations.items():
            path_item = schema["paths"][path]
            assert set(path_item) == set(expected_operations)
            for method, (operation_id, summary) in expected_operations.items():
                operation = path_item[method]
                assert operation["operationId"] == operation_id
                assert operation["summary"] == summary
                assert operation["responses"]["200"]["content"][
                    "application/json"
                ]["schema"]
