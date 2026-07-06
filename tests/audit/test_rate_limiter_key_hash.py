"""Tests for rate limiter key: plaintext token must not be used as dict key."""
from seam_runtime.server import _client_key


class TestRateLimiterKeyHash:
    def test_uses_hash_not_raw_token(self):
        auth = "Bearer secret-token-12345"
        key = _client_key(None, authorization=auth)
        # The raw token must not appear in the key
        assert "secret-token-12345" not in key
        assert "Bearer" not in key
        # Should be a SHA-256 hex digest (64 hex chars)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_different_tokens_produce_different_keys(self):
        key1 = _client_key(None, authorization="Bearer token-a")
        key2 = _client_key(None, authorization="Bearer token-b")
        assert key1 != key2

    def test_same_token_produces_same_key(self):
        key1 = _client_key(None, authorization="Bearer same-token")
        key2 = _client_key(None, authorization="Bearer same-token")
        assert key1 == key2

    def test_no_auth_uses_client_ip(self):
        key = _client_key(None, authorization=None)
        assert key == "local"  # default when no client
