"""Regression guards for the 2026-06-05 correctness/security audit fixes.

Each test fails against the pre-fix code and passes after. Covers:
  AUD-02/03  graph adapter namespace + scoped-edge isolation
  AUD-04     mode="vector" must not inject the sql leg
  AUD-05     /chat base_url SSRF guard (private/link-local rejected, loopback allowed)
  AUD-06     PNG image-bomb / oversized-dimension guard
  AUD-07     readable decompression raises ValueError (not KeyError) on a corrupt order
  AUD-08     shell validation rejects a path in argv[0]
"""
import json
import struct
import sys
import zlib

import pytest
from fastapi.testclient import TestClient

from seam_runtime.dashboard import _validate_shell_command
from seam_runtime.holographic import (
    MAX_SURFACE_DIMENSION,
    PNG_SIGNATURE,
    _bounded_inflate,
    _png_chunk,
    _read_png,
)
from seam_runtime.lossless import compress_text_readable, decompress_text_readable
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import (
    _chat_opener,
    _validate_provider_base_url,
    create_app_from_env,
)


# --------------------------------------------------------------------------- #
# AUD-08 — shell validation: a path in argv[0] must not pass via its basename
# --------------------------------------------------------------------------- #
class TestShellPathBypass:
    def test_absolute_path_basename_bypass_rejected(self):
        with pytest.raises(PermissionError):
            _validate_shell_command("/custom/path/git status")

    def test_relative_path_basename_bypass_rejected(self):
        with pytest.raises(PermissionError):
            _validate_shell_command("./git status")

    def test_slash_in_later_arg_still_allowed(self):
        assert _validate_shell_command("ls /tmp") == ["ls", "/tmp"]
        assert _validate_shell_command("cat /etc/hosts") == ["cat", "/etc/hosts"]


# --------------------------------------------------------------------------- #
# AUD-07 — readable decompression: corrupt order -> ValueError, not KeyError
# --------------------------------------------------------------------------- #
class TestReadableDecompressCorruptOrder:
    def test_missing_chunk_in_order_raises_valueerror(self):
        artifact = compress_text_readable("The quick brown fox. The quick brown fox jumps.")
        machine_text = artifact.machine_text
        lines = machine_text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("ORDER|"):
                payload = json.loads(line[len("ORDER|"):])
                payload["items"][0]["id"] = "c:nonexistent"
                lines[i] = "ORDER|" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                break
        corrupt = "\n".join(lines)
        with pytest.raises(ValueError):
            decompress_text_readable(corrupt)


# --------------------------------------------------------------------------- #
# AUD-04 — mode="vector" must not inject the sql leg
# --------------------------------------------------------------------------- #
class TestVectorModeNoSqlLeg:
    def test_vector_mode_filtered_query_has_no_sql_leg(self):
        plan = build_plan("kind:CLM", mode="vector")
        names = [leg.name for leg in plan.legs]
        assert "sql" not in names
        assert names == ["vector"]

    def test_hybrid_mode_still_has_sql_leg(self):
        plan = build_plan("kind:CLM ledger", mode="hybrid")
        assert "sql" in [leg.name for leg in plan.legs]

    def test_structured_intent_still_runs_sql_outside_vector_mode(self):
        # A pure-filter query in hybrid mode keeps the sql leg.
        plan = build_plan("kind:CLM", mode="hybrid")
        assert "sql" in [leg.name for leg in plan.legs]


# --------------------------------------------------------------------------- #
# AUD-06 — PNG image bomb / oversized dimensions
# --------------------------------------------------------------------------- #
def _make_png(width: int, height: int, raw: bytes, color_type: int = 6, bit_depth: int = 8) -> bytes:
    png = bytearray(PNG_SIGNATURE)
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)))
    png.extend(_png_chunk(b"IDAT", zlib.compress(raw)))
    png.extend(_png_chunk(b"IEND", b""))
    return bytes(png)


class TestPngBombGuard:
    def test_bounded_inflate_rejects_overrun(self):
        data = zlib.compress(b"x" * 1000)
        with pytest.raises(ValueError):
            _bounded_inflate(data, 10)
        assert _bounded_inflate(data, 1000) == b"x" * 1000

    def test_read_png_rejects_oversized_dimensions(self, tmp_path):
        p = tmp_path / "huge.png"
        p.write_bytes(_make_png(MAX_SURFACE_DIMENSION + 1, 1, b"\x00" * 16))
        with pytest.raises(ValueError):
            _read_png(p)

    def test_read_png_rejects_decompression_bomb(self, tmp_path):
        # Declare tiny dimensions (expected_raw is small) but ship an IDAT that
        # inflates far beyond it — the bounded inflate must reject it.
        p = tmp_path / "bomb.png"
        p.write_bytes(_make_png(2, 2, b"\x00" * (1024 * 1024)))
        with pytest.raises(ValueError):
            _read_png(p)


# --------------------------------------------------------------------------- #
# AUD-05 — /chat base_url SSRF guard
# --------------------------------------------------------------------------- #
class TestChatBaseUrlSsrf:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEAM_SERVER_DB", str(tmp_path / "ssrf.db"))
        monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    def _client(self):
        return TestClient(create_app_from_env())

    def test_link_local_metadata_address_rejected(self):
        # 169.254.169.254 is an IP literal, not an allowlisted host and not
        # loopback, so the host allowlist rejects it before any outbound call.
        resp = self._client().post("/chat", json={
            "message": "hi", "model": "x", "provider": "OpenAI",
            "base_url": "http://169.254.169.254/latest/meta-data", "api_key": "k",
        })
        assert resp.status_code == 400
        assert "allowlist" in resp.json()["detail"].lower()

    def test_private_range_rejected(self):
        resp = self._client().post("/chat", json={
            "message": "hi", "model": "x", "provider": "OpenAI",
            "base_url": "http://10.0.0.5:8080/v1", "api_key": "k",
        })
        assert resp.status_code == 400

    def test_non_http_scheme_rejected(self):
        resp = self._client().post("/chat", json={
            "message": "hi", "model": "x", "provider": "OpenAI",
            "base_url": "file:///etc/passwd", "api_key": "k",
        })
        assert resp.status_code == 400
        assert "scheme" in resp.json()["detail"].lower()

    def test_loopback_allowed_reaches_provider_call(self):
        # Loopback is allowed by design (Ollama). The SSRF guard must pass it
        # through to the provider call, which fails with 502 (nothing listening),
        # not a 400 validation error.
        resp = self._client().post("/chat", json={
            "message": "hi", "model": "x", "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
        })
        assert resp.status_code == 502

    # --- host allowlist (primary SSRF / DNS-rebinding defense) --------------- #
    @staticmethod
    def _patch_resolve(monkeypatch, ip: str):
        """Force getaddrinfo to return a fixed IP so allowlist logic is the only
        variable under test (no real DNS, deterministic)."""
        import socket as _socket

        def fake(host, port, *a, **k):
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port or 0))]

        monkeypatch.setattr(_socket, "getaddrinfo", fake)

    def test_unlisted_public_host_rejected(self, monkeypatch):
        # A host that resolves to a perfectly public IP is still rejected unless
        # it is an allowlisted provider - this is what closes rebinding: the
        # attacker cannot name a host they control.
        self._patch_resolve(monkeypatch, "93.184.216.34")  # example.com, public
        with pytest.raises(Exception) as exc:
            _validate_provider_base_url("https://evil.example.com/v1")
        assert exc.value.status_code == 400
        assert "allowlist" in str(exc.value.detail).lower()

    def test_builtin_allowlisted_host_passes(self, monkeypatch):
        self._patch_resolve(monkeypatch, "93.184.216.34")
        # api.openai.com is a built-in provider -> no exception.
        _validate_provider_base_url("https://api.openai.com/v1")

    def test_env_allowlist_permits_custom_host(self, monkeypatch):
        self._patch_resolve(monkeypatch, "93.184.216.34")
        monkeypatch.setenv("SEAM_CHAT_ALLOWED_HOSTS", "my.custom.host, other.host")
        _validate_provider_base_url("https://my.custom.host/v1")  # no raise

    def test_allowlisted_host_resolving_internal_still_rejected(self, monkeypatch):
        # Defense-in-depth: even an allowlisted host that resolves into the cloud
        # metadata range is rejected by the IP-range check.
        self._patch_resolve(monkeypatch, "169.254.169.254")
        with pytest.raises(Exception) as exc:
            _validate_provider_base_url("https://api.openai.com/v1")
        assert exc.value.status_code == 400
        assert "disallowed" in str(exc.value.detail).lower()

    # --- outbound opener refuses redirects (validated-host 302 bypass) ------- #
    @pytest.mark.skipif(sys.platform == "win32", reason=(
        "Windows-flaky: this ephemeral http.server + background-thread loopback "
        "socket intermittently hits ConnectionAbortedError (WinError 10053) on "
        "GitHub's windows-latest runner (confirmed twice, HISTORY#360/#361) -- "
        "same flaky-subprocess/socket-timing class as the other win32 skips in "
        "this suite, not a defect in the SSRF redirect-block logic under test."
    ))
    def test_chat_opener_blocks_redirects(self):
        import http.server
        import threading
        import urllib.error
        import urllib.request

        class _Redirect(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib hook name
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.end_headers()

            def log_message(self, *a):  # silence
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"
            req = urllib.request.Request(url, data=b"{}", method="POST")
            with pytest.raises(urllib.error.HTTPError) as exc:
                _chat_opener().open(req, timeout=5)
            assert "redirect blocked" in str(exc.value.reason).lower()
        finally:
            srv.server_close()


# --------------------------------------------------------------------------- #
# AUD-02 / AUD-03 — graph adapter namespace + scoped-edge isolation
# --------------------------------------------------------------------------- #
class TestGraphAdapterIsolation:
    def test_graph_leg_returns_only_in_scope_records(self, tmp_path):
        rt = SeamRuntime(str(tmp_path / "graph.db"))
        rt.persist_ir(rt.compile_nl("Alice manages the alpha payment ledger.", ns="alpha", scope="project"))
        rt.persist_ir(rt.compile_nl("Carol runs the beta payment ledger.", ns="beta", scope="thread"))
        orch = RetrievalOrchestrator(rt)
        plan = orch.plan("payment ledger", scope="project", mode="graph")
        hits = orch.graph_adapter.search(plan, limit=10)
        assert hits  # the in-scope record is found
        for hit in hits:
            assert hit.record.scope == "project"

    def test_graph_leg_respects_namespace_filter(self, tmp_path):
        rt = SeamRuntime(str(tmp_path / "graph_ns.db"))
        rt.persist_ir(rt.compile_nl("Alice manages the alpha payment ledger.", ns="alpha", scope="project"))
        rt.persist_ir(rt.compile_nl("Bob runs the beta payment ledger.", ns="beta", scope="project"))
        orch = RetrievalOrchestrator(rt)
        plan = orch.plan("ns:alpha payment ledger", scope="project", mode="graph")
        hits = orch.graph_adapter.search(plan, limit=10)
        for hit in hits:
            assert hit.record.ns == "alpha"
