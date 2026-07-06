"""Tests for graceful shutdown: signal handling, request draining, resource cleanup."""
import threading
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from seam_runtime.server import (
    ShutdownState,
    _cleanup_runtime,
    _shutdown_timeout_from_env,
    create_app,
)


class TestShutdownState:
    def test_initial_state(self):
        state = ShutdownState()
        assert state.shutting_down is False
        assert state.in_flight == 0

    def test_begin_request_increments_counter(self):
        state = ShutdownState()
        assert state.begin_request() is True
        assert state.in_flight == 1
        assert state.begin_request() is True
        assert state.in_flight == 2

    def test_end_request_decrements_counter(self):
        state = ShutdownState()
        state.begin_request()
        state.begin_request()
        state.end_request()
        assert state.in_flight == 1
        state.end_request()
        assert state.in_flight == 0

    def test_end_request_does_not_go_negative(self):
        state = ShutdownState()
        state.end_request()
        assert state.in_flight == 0

    def test_trigger_shutdown(self):
        state = ShutdownState()
        state.trigger_shutdown()
        assert state.shutting_down is True

    def test_begin_request_rejected_during_shutdown(self):
        state = ShutdownState()
        state.trigger_shutdown()
        assert state.begin_request() is False
        assert state.in_flight == 0

    def test_snapshot(self):
        state = ShutdownState()
        state.begin_request()
        state.begin_request()
        shutting_down, in_flight = state.snapshot()
        assert shutting_down is False
        assert in_flight == 2

    def test_snapshot_during_shutdown(self):
        state = ShutdownState()
        state.begin_request()
        state.trigger_shutdown()
        shutting_down, in_flight = state.snapshot()
        assert shutting_down is True
        assert in_flight == 1

    def test_wait_drain_immediate(self):
        state = ShutdownState()
        assert state.wait_drain(1.0) is True

    def test_wait_drain_with_requests(self):
        state = ShutdownState()
        state.begin_request()
        state.begin_request()

        def release_after_delay():
            time.sleep(0.1)
            state.end_request()
            state.end_request()

        thread = threading.Thread(target=release_after_delay)
        thread.start()
        assert state.wait_drain(2.0) is True
        thread.join()

    def test_wait_drain_timeout(self):
        state = ShutdownState()
        state.begin_request()
        assert state.wait_drain(0.1) is False


class TestShutdownTimeout:
    def test_default_timeout(self, monkeypatch):
        monkeypatch.delenv("SEAM_SHUTDOWN_TIMEOUT", raising=False)
        assert _shutdown_timeout_from_env() == 30.0

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "10")
        assert _shutdown_timeout_from_env() == 10.0

    def test_invalid_timeout_uses_default(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "invalid")
        assert _shutdown_timeout_from_env() == 30.0

    def test_minimum_timeout(self, monkeypatch):
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "0.5")
        assert _shutdown_timeout_from_env() == 1.0


class TestShutdownMiddleware:
    @pytest.fixture
    def setup_app(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_shutdown.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        app = create_app(shutdown_state=state)
        return app, state

    def test_normal_request_passes(self, setup_app):
        app, state = setup_app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_request_rejected_during_shutdown(self, setup_app):
        app, state = setup_app
        state.trigger_shutdown()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "shutting_down"}

    def test_in_flight_tracking(self, setup_app):
        app, state = setup_app
        client = TestClient(app)
        assert state.in_flight == 0
        response = client.get("/health")
        assert response.status_code == 200
        assert state.in_flight == 0

    def test_multiple_requests_tracked(self, setup_app):
        app, state = setup_app
        client = TestClient(app)
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200
        assert state.in_flight == 0


class TestHealthEndpoint:
    @pytest.fixture
    def setup_app(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_health.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        app = create_app(shutdown_state=state)
        return app, state

    def test_health_ok_when_running(self, setup_app):
        app, state = setup_app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_503_when_shutting_down(self, setup_app):
        app, state = setup_app
        state.trigger_shutdown()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "shutting_down"}


class TestResourceCleanup:
    def test_cleanup_closes_store(self):
        runtime = Mock()
        runtime.store = Mock()
        runtime.vector_adapter = None

        _cleanup_runtime(runtime)

        runtime.store.close.assert_called_once()

    def test_cleanup_closes_vector_adapter(self):
        runtime = Mock()
        runtime.store = Mock()
        runtime.vector_adapter = Mock()
        runtime.vector_adapter.close = Mock()

        _cleanup_runtime(runtime)

        runtime.store.close.assert_called_once()
        runtime.vector_adapter.close.assert_called_once()

    def test_cleanup_handles_missing_close(self):
        runtime = Mock()
        runtime.store = Mock()
        runtime.vector_adapter = Mock(spec=[])

        _cleanup_runtime(runtime)

        runtime.store.close.assert_called_once()

    def test_cleanup_handles_store_error(self, caplog):
        runtime = Mock()
        runtime.store = Mock()
        runtime.store.close.side_effect = Exception("close failed")
        runtime.vector_adapter = None

        _cleanup_runtime(runtime)

        assert "Error closing store" in caplog.text

    def test_cleanup_handles_vector_error(self, caplog):
        runtime = Mock()
        runtime.store = Mock()
        runtime.vector_adapter = Mock()
        runtime.vector_adapter.close = Mock(side_effect=Exception("close failed"))

        _cleanup_runtime(runtime)

        assert "Error closing vector adapter" in caplog.text


class TestSignalHandling:
    def test_sigterm_triggers_shutdown(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_sigterm.db"))
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "1")
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        app = create_app(shutdown_state=state)
        client = TestClient(app)

        assert state.shutting_down is False
        state.trigger_shutdown()
        assert state.shutting_down is True

        response = client.get("/health")
        assert response.status_code == 503

    def test_in_flight_requests_complete_before_shutdown(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_drain.db"))
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "2")
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        assert state.begin_request() is True
        assert state.in_flight == 1

        def complete_request():
            time.sleep(0.1)
            state.end_request()

        thread = threading.Thread(target=complete_request)
        thread.start()

        drained = state.wait_drain(2.0)
        assert drained is True
        assert state.in_flight == 0
        thread.join()

    def test_new_requests_rejected_during_drain(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_reject.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        state.begin_request()
        state.trigger_shutdown()

        assert state.begin_request() is False
        assert state.in_flight == 1

        state.end_request()
        assert state.in_flight == 0


class TestIntegration:
    def test_full_shutdown_flow(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_flow.db"))
        monkeypatch.setenv("SEAM_SHUTDOWN_TIMEOUT", "2")
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

        state = ShutdownState()
        app = create_app(shutdown_state=state)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200

        state.begin_request()
        assert state.in_flight == 1

        state.trigger_shutdown()

        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "shutting_down"

        state.end_request()
        assert state.in_flight == 0

        drained = state.wait_drain(1.0)
        assert drained is True
