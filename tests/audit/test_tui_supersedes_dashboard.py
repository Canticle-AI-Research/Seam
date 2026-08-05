"""The Canticle TUI supersedes the old Textual dashboard UI.

Two classes of regression are covered, both found by launching the real
binary in a real terminal after headless `run_test()` mounts had passed:

* the persisted settings file is a shell env file operators hand-edit, so
  `export FOO=bar` must yield `FOO`, not a variable named `export FOO`; and
* nothing read out of that file may reach a Textual widget id unsanitised,
  because `BadIdentifier` is raised at construction and takes down the whole
  app at mount rather than degrading one row.

The third block pins the supersession itself: every interactive entry point
must reach the new TUI, while the non-interactive snapshot and script modes
stay on the Rich backend.
"""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

import pytest

from seam_runtime import config
from seam_runtime.tui.settings_screen import SettingRow, _slug

textual_required = pytest.mark.skipif(
    find_spec("textual") is None, reason="textual is not installed"
)


def _write_env(tmp_path: Path, body: str) -> Path:
    target = tmp_path / "seam.env"
    target.write_text(body, encoding="utf-8")
    return target


class TestPersistedEnvParsing:
    """`load_persisted` reads shell-style env files."""

    def test_export_prefix_is_stripped(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "export DEEPSEEK_API_KEY=abc123\n")
        assert config.load_persisted(path) == {"DEEPSEEK_API_KEY": "abc123"}

    def test_bare_assignment_still_parses(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "SEAM_DB_PATH=/tmp/x.db\n")
        assert config.load_persisted(path) == {"SEAM_DB_PATH": "/tmp/x.db"}

    def test_export_and_bare_forms_coexist(self, tmp_path: Path) -> None:
        path = _write_env(
            tmp_path,
            "# a comment\nexport A_KEY=1\nB_KEY=2\n\nexport C_KEY='quoted'\n",
        )
        assert config.load_persisted(path) == {
            "A_KEY": "1",
            "B_KEY": "2",
            "C_KEY": "quoted",
        }

    def test_export_alone_is_not_a_key(self, tmp_path: Path) -> None:
        """`export=1` is a real assignment to a var named `export`, not a prefix."""
        path = _write_env(tmp_path, "export=1\n")
        assert config.load_persisted(path) == {"export": "1"}

    def test_exported_key_reaches_the_environment(self, tmp_path: Path) -> None:
        """The bug this fixes: the key parsed, but under an unusable name."""
        path = _write_env(tmp_path, "export DEEPSEEK_API_KEY=abc123\n")
        env: dict[str, str] = {}
        applied = config.apply_persisted_to_environ(env, path)
        assert applied == ["DEEPSEEK_API_KEY"]
        assert env["DEEPSEEK_API_KEY"] == "abc123"


class TestUnusableNamesAreRejected:
    """A hand-edited file cannot inject names the OS would not accept."""

    def test_is_env_name(self) -> None:
        assert config.is_env_name("SEAM_DB_PATH")
        assert config.is_env_name("_private")
        assert not config.is_env_name("export DEEPSEEK_API_KEY")
        assert not config.is_env_name("has-a-hyphen")
        assert not config.is_env_name("9leading_digit")
        assert not config.is_env_name("")

    def test_unusable_name_is_not_applied_to_environ(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "not a name=value\n")
        env: dict[str, str] = {}
        assert config.apply_persisted_to_environ(env, path) == []
        assert env == {}

    def test_unusable_name_synthesizes_no_row(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "not a name=value\nGOOD_KEY=value\n")
        names = [s.name for s in config.custom_settings(path)]
        assert names == ["GOOD_KEY"]

    def test_process_env_still_wins(self, tmp_path: Path) -> None:
        path = _write_env(tmp_path, "export A_KEY=from_file\n")
        env = {"A_KEY": "from_process"}
        assert config.apply_persisted_to_environ(env, path) == []
        assert env["A_KEY"] == "from_process"


class TestWidgetIdsAreAlwaysLegal:
    """Textual raises `BadIdentifier` at construction, so this is a crash guard."""

    LEGAL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

    def _id_for(self, name: str) -> str:
        setting = config.Setting(name=name, group="Custom Keys", kind="str")
        return SettingRow(setting)._widget_id

    def test_ordinary_name(self) -> None:
        assert self._id_for("SEAM_DB_PATH") == "set-seam-db-path"

    @pytest.mark.parametrize(
        "name",
        [
            "export DEEPSEEK_API_KEY",
            "has space",
            "has.dot",
            "has/slash",
            "has:colon",
            "has$dollar",
            "unicodeé",
        ],
    )
    def test_hostile_name_yields_a_legal_id(self, name: str) -> None:
        widget_id = self._id_for(name)
        assert widget_id.startswith("set-")
        assert set(widget_id) <= self.LEGAL, widget_id

    def test_group_slug_is_legal(self) -> None:
        for group in ("Provider Keys", "Retrieval & Ranking", "Custom Keys"):
            assert set(_slug(group)) <= self.LEGAL, group

    @textual_required
    def test_registry_rows_all_construct(self) -> None:
        """Every shipped setting builds a row without raising."""
        for setting in config.SETTINGS:
            widget_id = SettingRow(setting)._widget_id
            assert set(widget_id) <= self.LEGAL, setting.name


@textual_required
class TestTuiMountsAgainstAHandEditedFile:
    """The exact launch that crashed: real config file, real mount."""

    def test_mounts_with_export_lines_and_junk_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.tui.app import SeamTUI

        env_path = _write_env(
            tmp_path,
            "# operator's shell env file\n"
            "export DEEPSEEK_API_KEY=abc123\n"
            "export SEAM_BENCH_RECORD_DIR=/tmp/records\n"
            "not a legal name=whatever\n",
        )
        monkeypatch.setattr(config, "config_path", lambda: env_path)

        runtime = SeamRuntime(str(tmp_path / "seam.db"))
        app = SeamTUI(DashboardApp(runtime))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                # The settings panel is what raised BadIdentifier at mount.
                assert app.query_one("#panel-memory") is not None
                assert app.query_one("#command-input") is not None
                # The legal exported key is settable; the junk name is absent.
                assert app.query_one("#set-deepseek-api-key") is not None
                assert not app.query("#set-not-a-legal-name")

        asyncio.run(_check())


class TestSupersession:
    """`run_dashboard` reaches the new TUI, and only for interactive launches."""

    def _backend(self, tmp_path: Path):
        from seam_runtime.runtime import SeamRuntime

        return SeamRuntime(str(tmp_path / "seam.db"))

    @textual_required
    def test_interactive_launch_runs_the_new_tui(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from seam_runtime import dashboard
        from seam_runtime.tui import app as tui_app

        launched: list[object] = []
        monkeypatch.setattr(tui_app, "run", lambda backend: launched.append(backend))

        dashboard.run_dashboard(self._backend(tmp_path))

        assert len(launched) == 1
        # The backend is handed over, not reconstructed, so the vector-backend
        # selection made in run_dashboard survives into the UI.
        assert isinstance(launched[0], dashboard.DashboardApp)

    def test_snapshot_mode_does_not_launch_the_tui(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from seam_runtime import dashboard
        from seam_runtime.tui import app as tui_app

        launched: list[object] = []
        monkeypatch.setattr(tui_app, "run", lambda backend: launched.append(backend))

        dashboard.run_dashboard(self._backend(tmp_path), snapshot=True)

        assert launched == []

    def test_script_mode_does_not_launch_the_tui(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from seam_runtime import dashboard
        from seam_runtime.tui import app as tui_app

        launched: list[object] = []
        monkeypatch.setattr(tui_app, "run", lambda backend: launched.append(backend))

        dashboard.run_dashboard(self._backend(tmp_path), commands=["stats"])

        assert launched == []

    def test_seam_tui_console_script_is_registered(self) -> None:
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        assert 'seam-tui = "seam_runtime.tui.app:main"' in text

    def test_theme_is_shipped_as_package_data(self) -> None:
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        assert "tui/*.tcss" in text
        manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
        assert "recursive-include seam_runtime/tui *.tcss" in manifest

    def test_textual_pin_covers_the_installed_api(self) -> None:
        """The new TUI uses Textual 8 APIs; the old pin allowed 0.50."""
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        assert 'dash = ["textual>=8.0,<9.0"' in text
        assert "textual>=0.50" not in text


class TestBackendContractHoldsForTheNewUi:
    """The new UI is presentation-only; these are the attributes it relies on."""

    def test_dashboard_app_exposes_what_the_tui_uses(self, tmp_path: Path) -> None:
        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime

        backend = DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))
        assert callable(backend.execute)
        assert backend.command_parser is not None
        assert isinstance(backend.result_title, str)
        assert isinstance(backend.result_body, str)
        assert backend.runtime.store.path is not None

    def test_catalog_is_derived_from_the_backend_parser(self, tmp_path: Path) -> None:
        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.tui.commands import build_catalog

        backend = DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))
        catalog = build_catalog(backend.command_parser)
        assert catalog, "catalog must not be empty"
        executable = {c.name for c in catalog if c.executable}
        # Derived, not a parallel hand-maintained list: every executable entry
        # must be a verb the backend parser actually accepts.
        for action in backend.command_parser._subparsers._group_actions:
            assert executable <= set(action.choices)
            break


def test_persisted_file_is_never_the_repo_env() -> None:
    """Settings must never be written into the repo's own .env."""
    path = config.config_path()
    assert path.name == "seam.env"
    assert "/.config/seam/" in str(path) or os.environ.get("SEAM_CONFIG_HOME")
    assert Path.cwd() not in path.parents
