"""Tests for server bind safety: remote unauthenticated bind refusal."""
import pytest

from seam_runtime.server import _is_remote_bind, _validate_server_safety


class TestRemoteBindSafety:
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
