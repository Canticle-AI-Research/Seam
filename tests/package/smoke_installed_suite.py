"""Exercise a built Suite in isolation: python -I /path/to/this/file.py.

Install only the wheel or sdist in a fresh environment first. No source checkout,
test extra, database, provider, or optional backend may supply missing pieces.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import os
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
        for module in ("textual", "httpx", "fastapi", "uvicorn", "python_multipart"):
            with self.subTest(module=module):
                try:
                    importlib.import_module(module)
                except ModuleNotFoundError as error:
                    if module != "python_multipart" or error.name != module:
                        raise
                    importlib.import_module("multipart")

    def test_console_entrypoints(self):
        scripts = Path(sysconfig.get_path("scripts"))
        for name in ("seam", "seam-tui", "seam-dash", "seam-server", "seam-mcp", "seam-benchmark"):
            with self.subTest(command=name):
                executable = scripts / (name + (".exe" if os.name == "nt" else ""))
                result = subprocess.run([str(executable), "--help"], cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout.lower())

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


if __name__ == "__main__":
    unittest.main()
