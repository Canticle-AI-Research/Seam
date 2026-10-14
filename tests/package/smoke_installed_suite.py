"""Exercise a built Suite in isolation: python -I /path/to/this/file.py.

Install only the wheel or sdist in a fresh environment first. No source checkout,
test extra, database, provider, or optional backend may supply missing pieces.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import json
import os
import secrets
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class InstalledSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        environment.update({"XDG_CONFIG_HOME": str(self.root), "SEAM_DB_PATH": str(self.root / "cli.db")})
        self.env = patch.dict(os.environ, environment, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_dependencies_and_package_origin(self):
        import seam_runtime

        self.assertTrue(Path(seam_runtime.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()))
        self.assertEqual(importlib.metadata.distribution("seam-suite").metadata["Name"], "seam-suite")
        self.assertIsNone(importlib.util.find_spec("chromadb"), "Chroma must remain explicit opt-in")
        for module in ("textual", "httpx", "fastapi", "uvicorn", "python_multipart"):
            with self.subTest(module=module):
                try:
                    importlib.import_module(module)
                except ModuleNotFoundError as error:
                    if module != "python_multipart" or error.name != module:
                        raise
                    importlib.import_module("multipart")

    def test_installed_doctor_reports_complete_default_dependencies(self):
        from seam_runtime.doctor import build_doctor_report

        report = build_doctor_report()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["required_dependencies"], [
            "rich", "tiktoken", "textual", "httpx", "fastapi", "uvicorn", "python_multipart"
        ])
        self.assertEqual(report["missing_required_dependencies"], [])

    def test_console_entrypoints(self):
        scripts = Path(sysconfig.get_path("scripts"))
        for name in ("seam", "seam-tui", "seam-dash", "seam-server", "seam-mcp", "seam-benchmark"):
            with self.subTest(command=name):
                executable = scripts / (name + (".exe" if os.name == "nt" else ""))
                result = subprocess.run([str(executable), "--help"], cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout.lower())

    def executable(self, name):
        return str(Path(sysconfig.get_path("scripts")) / (name + (".exe" if os.name == "nt" else "")))

    def cli_json(self, *arguments):
        result = subprocess.run([self.executable("seam"), *arguments], cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_cli_ingest_retrieve_and_restart_preserve_evidence(self):
        source = self.root / "memory.txt"
        source.write_text("The suite smoke beacon is ambercinder. Ambercinder is stored locally.", encoding="utf-8")
        ingested = self.cli_json("ingest", str(source), "--persist", "--format", "json")
        self.assertTrue(ingested["stored_ids"])
        self.assertEqual(ingested["document"]["source_ref"], str(source))
        found = self.cli_json("retrieve", "ambercinder", "--mode", "mix", "--format", "json")
        self.assertTrue(found["candidates"])
        first_ids = {row["record"]["id"] for row in found["candidates"]}
        self.assertTrue(first_ids.intersection(ingested["stored_ids"]))
        self.assertTrue(any(row["record"]["prov"] for row in found["candidates"]))
        # Every call starts a fresh process; this second retrieval also verifies restart persistence.
        restarted = self.cli_json("retrieve", "ambercinder", "--mode", "mix", "--format", "json")
        self.assertEqual(first_ids, {row["record"]["id"] for row in restarted["candidates"]})

    def protocol(self, requests):
        result = subprocess.run([self.executable("seam-mcp"), "--db", str(self.root / "mcp.db")],
                                input="".join(json.dumps(row) + "\n" for row in requests), cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        for response in responses:
            self.assertEqual(response["jsonrpc"], "2.0")
            self.assertNotIn("error", response)
        return {row["id"]: row["result"] for row in responses}

    def test_mcp_initialization_ingest_search_and_restart(self):
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "installed-suite-smoke", "version": "1"},
        }}
        listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        ingest = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "seam_ingest", "arguments": {
                "text": "The MCP smoke beacon is ambercinder.", "source_ref": "smoke://mcp"
            }
        }}
        search = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "seam_memory_search", "arguments": {"query": "ambercinder"}
        }}
        results = self.protocol([
            initialize, {"jsonrpc": "2.0", "method": "notifications/initialized"}, listing, ingest, search,
        ])
        self.assertEqual(results[1]["protocolVersion"], "2025-06-18")
        self.assertEqual(results[1]["serverInfo"]["version"], importlib.metadata.version("seam-suite"))
        names = {tool["name"] for tool in results[2]["tools"]}
        self.assertTrue({"seam_ingest", "seam_memory_search"}.issubset(names))
        for request_id in (3, 4):
            self.assertFalse(results[request_id]["isError"])
        self.assertTrue(results[3]["structuredContent"]["stored_ids"])
        found = results[4]["structuredContent"]
        self.assertTrue(found["results"])
        stored_ids = set(results[3]["structuredContent"]["stored_ids"])
        found_ids = {row["id"] for row in found["results"]}
        self.assertTrue(found_ids.issubset(stored_ids))
        self.assertTrue(any(row["refs"] for row in found["results"]))
        self.assertTrue(any("ambercinder" in row["summary"].lower() for row in found["results"]))
        restarted = self.protocol([initialize, search])
        self.assertFalse(restarted[4]["isError"])
        self.assertEqual(found_ids, {row["id"] for row in restarted[4]["structuredContent"]["results"]})

    def test_tui_mounts_from_installed_assets(self):
        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.tui.app import SeamTUI

        runtime = SeamRuntime(str(self.root / "tui.db"), allow_pgvector_env=False)
        self.addCleanup(runtime.close)
        app = SeamTUI(DashboardApp(runtime))

        async def check():
            async with app.run_test(size=(140, 48)) as pilot:
                await pilot.pause()
                self.assertIsNotNone(app.query_one("#command-input"))
                self.assertIsNotNone(app.query_one("#panel-memory"))

        asyncio.run(check())

    def test_server_serves_packaged_dashboard_and_public_health(self):
        from fastapi.testclient import TestClient

        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.server import create_app

        runtime = SeamRuntime(str(self.root / "http.db"), allow_pgvector_env=False)
        self.addCleanup(runtime.close)
        with TestClient(create_app(runtime)) as client:
            response = client.get("/v1/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            for path in ("/", "/seam-api.js", "/favicon.svg"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content)

    def test_http_write_recall_and_token_denied(self):
        from fastapi.testclient import TestClient

        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.server import create_app

        runtime = SeamRuntime(str(self.root / "authenticated-http.db"), allow_pgvector_env=False)
        self.addCleanup(runtime.close)
        # Ephemeral local test credential: never print it or use a real account/provider key.
        with patch.dict(os.environ, {"SEAM_API_TOKEN": secrets.token_hex(16)}):
            headers = {"Authorization": "Bearer " + os.environ["SEAM_API_TOKEN"]}
            with TestClient(create_app(runtime)) as client:
                self.assertEqual(client.get("/v1/health").status_code, 200)
                for denied_headers in ({}, {"Authorization": "Bearer invalid-local-smoke"}):
                    for path, payload in (
                        ("/v1/memories", {"text": "Unauthorized smoke input."}),
                        ("/v1/memories/recall", {"query": "ambercinder"}),
                    ):
                        with self.subTest(path=path, authenticated=False):
                            self.assertEqual(client.post(path, json=payload, headers=denied_headers).status_code, 401)
                written = client.post("/v1/memories", json={
                    "text": "The HTTP smoke beacon is ambercinder."
                }, headers=headers)
                self.assertEqual(written.status_code, 200)
                self.assertTrue(written.json()["accepted"])
                self.assertGreater(written.json()["memory_count"], 0)
                recalled = client.post("/v1/memories/recall", json={"query": "ambercinder"}, headers=headers)
                self.assertEqual(recalled.status_code, 200)
                memories = recalled.json()["memories"]
                self.assertTrue(memories)
                self.assertTrue(any("ambercinder" in row["text"].lower() for row in memories))


if __name__ == "__main__":
    unittest.main()
