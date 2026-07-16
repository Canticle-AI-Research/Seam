"""Tests for REST API budget parameter clamping."""
import pytest
from fastapi.testclient import TestClient

from seam_runtime.server import create_app_from_env


class TestBudgetBounds:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_budget.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

    def test_search_budget_too_low_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_budget_low.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        app = create_app_from_env()
        client = TestClient(app)
        resp = client.get("/search?query=test&budget=0")
        assert resp.status_code == 422

    def test_search_budget_too_high_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_budget_high.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        app = create_app_from_env()
        client = TestClient(app)
        resp = client.get("/search?query=test&budget=999")
        assert resp.status_code == 422

    def test_search_budget_max_boundary_accepted(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_budget_max.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        app = create_app_from_env()
        client = TestClient(app)
        resp = client.get("/search?query=test&budget=200")
        assert resp.status_code == 200

    def test_context_budget_zero_clamped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_ctx_budget.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        app = create_app_from_env()
        client = TestClient(app)
        resp = client.post("/context", json={"query": "test", "budget": 0})
        # Should clamp to 1 and return 200 (not crash)
        assert resp.status_code == 200

    def test_context_pack_budget_huge_clamped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "test_ctx_pack.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)
        app = create_app_from_env()
        client = TestClient(app)
        resp = client.post("/context", json={"query": "test", "pack_budget": 99999999})
        # Should clamp and return 200
        assert resp.status_code == 200
