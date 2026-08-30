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

# `textual` is an optional extra (`seam[dash]`), and the test-and-benchmark CI
# lane does not install it. A module-level import of anything under
# `seam_runtime.tui` therefore raises at COLLECTION, which pytest treats as an
# error rather than a skip and which aborts the entire run -- not just this
# file. Everything textual-dependent is imported inside the test that needs it,
# behind `textual_required`, so the config and packaging tests below still run
# on an installation without the extra.
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

    def test_file_promoted_value_refreshes_without_becoming_an_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = "SEAM_TEST_PROMOTED_SETTING"
        path = _write_env(tmp_path, f"{name}=first\n")
        monkeypatch.delenv(name, raising=False)

        assert config.apply_persisted_to_environ(path=path) == [name]
        assert os.environ[name] == "first"
        assert config.value_source(name, path) == "file"

        path.write_text(f"{name}=second\n", encoding="utf-8")
        # Consumers that use `effective_value` see a saved value immediately,
        # before the explicit Reload action synchronizes the process mapping.
        assert config.effective_value(name, path) == "second"
        assert config.apply_persisted_to_environ(path=path) == [name]
        assert os.environ[name] == "second"

    def test_real_process_override_is_never_refreshed_from_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        name = "SEAM_TEST_EXPLICIT_SETTING"
        path = _write_env(tmp_path, f"{name}=from_file\n")
        monkeypatch.setenv(name, "from_process")

        assert config.apply_persisted_to_environ(path=path) == []
        path.write_text(f"{name}=changed_file\n", encoding="utf-8")
        assert config.effective_value(name, path) == "from_process"
        assert config.value_source(name, path) == "env"
        assert config.apply_persisted_to_environ(path=path) == []
        assert os.environ[name] == "from_process"


@textual_required
class TestWidgetIdsAreAlwaysLegal:
    """Textual raises `BadIdentifier` at construction, so this is a crash guard."""

    LEGAL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

    def _id_for(self, name: str) -> str:
        from seam_runtime.tui.settings_screen import SettingRow

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
        from seam_runtime.tui.settings_screen import _slug

        for group in ("Provider Keys", "Retrieval & Ranking", "Custom Keys"):
            assert set(_slug(group)) <= self.LEGAL, group

    def test_registry_rows_all_construct(self) -> None:
        """Every shipped setting builds a row without raising."""
        from seam_runtime.tui.settings_screen import SettingRow

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

    @textual_required
    def test_snapshot_mode_does_not_launch_the_tui(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from seam_runtime import dashboard
        from seam_runtime.tui import app as tui_app

        launched: list[object] = []
        monkeypatch.setattr(tui_app, "run", lambda backend: launched.append(backend))

        dashboard.run_dashboard(self._backend(tmp_path), snapshot=True)

        assert launched == []

    @textual_required
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


@textual_required
class TestCanticleBrandLaunch:
    """The reusable product lockup types once, then yields to the workspace."""

    def _backend(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime

        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        return DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))

    def test_full_motion_types_the_exact_seam_frames(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import Static

        from seam_runtime.tui import brand
        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setenv("SEAM_TUI_MOTION", "full")
        monkeypatch.setattr(brand, "STARTUP_FRAME_SECONDS", 60.0)
        monkeypatch.setattr(brand, "STARTUP_HOLD_SECONDS", 60.0)
        app = SeamTUI(self._backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(120, 38)) as pilot:
                await pilot.pause()
                assert brand.STARTUP_WORD_FRAMES == ("S", "SE", "SEA", "SEAM")
                assert app._startup_active
                assert app._cursor_timer is not None
                assert app._cursor_timer._interval == brand.CURSOR_TOGGLE_SECONDS
                if app._startup_timer is not None:
                    app._startup_timer.stop()
                    app._startup_timer = None
                hold_delays: list[float] = []
                monkeypatch.setattr(
                    app,
                    "set_timer",
                    lambda delay, callback: hold_delays.append(delay),
                )

                word = app.query_one("#startup-word", Static)
                assert word.content == brand.product_wordmark(brand.STARTUP_WORD_FRAMES[0])
                for expected in brand.STARTUP_WORD_FRAMES[1:]:
                    app._advance_startup_animation()
                    assert word.content == brand.product_wordmark(expected)
                assert hold_delays == [brand.STARTUP_HOLD_SECONDS]

                app._finish_startup_animation()
                assert not app.query_one("#startup-splash").display

        asyncio.run(_check())

    def test_motion_off_mounts_no_launch_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setenv("SEAM_TUI_MOTION", "off")
        app = SeamTUI(self._backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(120, 38)) as pilot:
                await pilot.pause()
                assert not app.query("#startup-splash")
                assert not app._startup_active
                assert app._cursor_timer is None
                assert app._cursor_on
                app._blink()
                assert app._cursor_on

        asyncio.run(_check())

    def test_reduced_motion_shows_only_the_static_final_lockup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import Static

        from seam_runtime.tui import brand
        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setenv("SEAM_TUI_MOTION", "reduced")
        monkeypatch.setattr(brand, "STARTUP_HOLD_SECONDS", 60.0)
        app = SeamTUI(self._backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(120, 38)) as pilot:
                await pilot.pause()
                assert "SEAM" in str(app.query_one("#startup-word", Static).content)
                assert app._startup_timer is None
                assert app._cursor_timer is None
                assert app._cursor_on
                app._blink()
                assert app._cursor_on

        asyncio.run(_check())


@textual_required
class TestMemoryPageIsNowAWorkspace:
    """The Memory tab became a page -- records table on top, provenance
    trace directly beneath it, one shared log -- instead of a tab with a
    sibling Provenance tab. This is the operator's ask verbatim: "the memory
    tab should act like a table so I can copy IDs and paste them ... put
    provenance below memory, making it easier to search." See panels.py's
    `MemoryPanel`/`MemoryRecordsPanel`/`ProvPanel` and app.py's `TABS`.
    """

    def test_no_prov_tab_or_panel_class(self) -> None:
        from seam_runtime.tui.app import SECTIONS
        from seam_runtime.tui.panels import PANEL_CLASSES

        assert "prov" not in {section.id for section in SECTIONS}
        assert "prov" not in PANEL_CLASSES

    def _backend_with_a_record(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A real backend over a temp store holding one compiled record.

        `SeamRuntime.__init__` (runtime.py) reads `SEAM_PGVECTOR_DSN`
        straight out of the process environment and, if set, tries to reach
        that Postgres for vector indexing -- an operator's own DSN pointed
        at a database this test knows nothing about must never leak into
        whether `compile` here succeeds, so it is cleared for the sqlite-
        backed adapter every time.
        """
        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime

        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        runtime = SeamRuntime(str(tmp_path / "seam.db"))
        backend = DashboardApp(runtime)
        should_exit = backend.execute("compile a note about the memory workspace redesign")
        assert should_exit is False
        assert backend.result_title != "Command Error", backend.result_body
        return backend

    def test_mounted_app_has_exactly_one_of_each_shared_widget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                # The page's shared log moved to app level (`#app-log`);
                # the memory page itself is now the records/detail workspace.
                assert len(app.query("#app-log")) == 1
                assert len(app.query("#prov-query")) == 1
                assert len(app.query("#prov-tree")) == 1
                assert len(app.query("#memory-copy-id")) == 1
                assert not app.query("#log-prov")
                assert not app.query("#log-memory")

                # And specifically inside the memory page, not floating
                # somewhere else in the DOM.
                panel = app.query_one("#panel-memory")
                assert panel.query_one("#prov-query") is not None
                assert panel.query_one("#prov-tree") is not None

        asyncio.run(_check())

    def test_row_selection_traces_without_changing_clipboard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import DataTable, Input

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.panels import MemoryRecordsPanel

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                # `refresh_records` runs on a `@work(thread=True)` worker
                # (panels.py), so the row may not exist yet on the first
                # pause -- poll rather than assume one pause is enough.
                for _ in range(50):
                    if records._row_ids:
                        break
                    await pilot.pause(0.05)
                assert records._row_ids, "load worker never populated a row"
                expected_id = records._row_ids[0]

                table = app.query_one("#memory-table", DataTable)
                app.copy_to_clipboard("keep-this-clipboard-value")
                table.focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause(0.2)

                # Selection drives the trace but is no longer an implicit
                # clipboard mutation.
                assert app.clipboard == "keep-this-clipboard-value"
                assert app.query_one("#prov-query", Input).value == expected_id

        asyncio.run(_check())

    def test_copy_id_button_copies_the_full_visible_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import Button, DataTable, Input

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.panels import MemoryRecordsPanel

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                for _ in range(50):
                    if records._row_ids:
                        break
                    await pilot.pause(0.05)
                assert records._row_ids
                expected_id = records._row_ids[0]

                table = app.query_one("#memory-table", DataTable)
                table.focus()
                await pilot.press("enter")
                await pilot.pause(0.2)
                assert app.query_one("#prov-query", Input).value == expected_id
                assert app.clipboard == ""

                button = app.query_one("#memory-copy-id", Button)
                button.focus()
                await pilot.press("enter")
                await pilot.pause(0.2)
                assert app.clipboard == expected_id

        asyncio.run(_check())

    def test_yank_copies_id_without_changing_prov_query(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import DataTable, Input

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.panels import MemoryRecordsPanel

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                for _ in range(50):
                    if records._row_ids:
                        break
                    await pilot.pause(0.05)
                assert records._row_ids
                expected_id = records._row_ids[0]

                table = app.query_one("#memory-table", DataTable)
                query = app.query_one("#prov-query", Input)
                before_query = query.value
                table.focus()
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause(0.2)

                assert app.clipboard == expected_id
                # `y` only yanks -- it must not change whichever trace the
                # designed detail pane already follows.
                assert query.value == before_query

        asyncio.run(_check())

    def test_empty_store_guard_no_ops_without_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import Button, DataTable

        from seam_runtime.dashboard import DashboardApp
        from seam_runtime.runtime import SeamRuntime
        from seam_runtime.tui.app import SeamTUI

        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        runtime = SeamRuntime(str(tmp_path / "seam.db"))
        app = SeamTUI(DashboardApp(runtime))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                table = app.query_one("#memory-table", DataTable)
                app.copy_to_clipboard("sentinel")
                table.focus()
                await pilot.pause()

                # The empty store renders one status row ("no MIRL records
                # yet ..."); `_row_ids` stays `[]` for it, so both the `y`
                # and row-selection paths must no-op rather than raise or
                # copy the status text as if it were an id.
                await pilot.press("y")
                await pilot.pause(0.2)
                assert app.clipboard == "sentinel"

                await pilot.press("enter")
                await pilot.pause(0.2)
                assert app.clipboard == "sentinel"

                button = app.query_one("#memory-copy-id", Button)
                button.focus()
                await pilot.press("enter")
                await pilot.pause(0.2)
                assert app.clipboard == "sentinel"

        asyncio.run(_check())

    def test_memory_panel_reload_reloads_both_children(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.memory_page import MemoryPage
        from seam_runtime.tui.panels import MemoryRecordsPanel, ProvPanel

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                prov = app.query_one("#memory-prov", ProvPanel)

                records_calls: list[None] = []
                prov_calls: list[None] = []
                monkeypatch.setattr(records, "reload", lambda: records_calls.append(None))
                monkeypatch.setattr(prov, "reload", lambda: prov_calls.append(None))

                app.query_one("#panel-memory", MemoryPage).reload()

                assert records_calls == [None]
                assert prov_calls == [None]

        asyncio.run(_check())

    def test_first_visible_record_populates_detail_without_enter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The painted cursor and detail pane must describe the same row."""
        import asyncio

        from textual.widgets import DataTable

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.memory_page import MemoryPage
        from seam_runtime.tui.panels import MemoryRecordsPanel

        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                detail = app.query_one("#panel-memory", MemoryPage)
                attrs = app.query_one("#detail-attrs", DataTable)
                for _ in range(50):
                    if records._row_ids and detail._selected_id and attrs.row_count:
                        break
                    await pilot.pause(0.05)

                assert records._row_ids
                assert detail._selected_id == records._row_ids[0]
                assert attrs.row_count > 0

        asyncio.run(_check())

    def test_memory_search_filters_live_and_keeps_detail_in_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.memory_page import MemoryPage
        from seam_runtime.tui.panels import MemoryRecordsPanel

        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                records = app.query_one("#memory-records", MemoryRecordsPanel)
                for _ in range(50):
                    if len(records._row_ids) > 1:
                        break
                    await pilot.pause(0.05)
                assert len(records._row_ids) > 1
                expected_id = records._row_ids[-1]

                app.query_one("#memory-search", Input).value = expected_id
                await pilot.pause()

                assert records._row_ids == [expected_id]
                assert app.query_one("#panel-memory", MemoryPage)._selected_id == expected_id

        asyncio.run(_check())

    def test_graph_view_uses_the_real_knowledge_graph_and_constellation_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The design's Graph view is a node canvas, never an edge table."""
        import asyncio

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.graph_canvas import ConstellationGraph

        backend = self._backend_with_a_record(tmp_path, monkeypatch)
        calls: list[dict[str, object]] = []
        payload = {
            "nodes": [
                {"id": "ent:seam", "label": "SEAM", "kind": "ent", "degree": 2},
                {"id": "clm:sqlite", "label": "SQLite is canonical", "kind": "clm", "degree": 1},
                {"id": "ent:sqlite", "label": "SQLite", "kind": "ent", "degree": 1},
            ],
            "edges": [
                {"source": "clm:sqlite", "target": "ent:seam", "predicate": "about"},
                {"source": "ent:seam", "target": "ent:sqlite", "predicate": "uses"},
            ],
            "stats": {"nodes": 3, "edges": 2},
        }

        def _knowledge_graph(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return payload

        monkeypatch.setattr(backend.runtime, "knowledge_graph", _knowledge_graph)
        monkeypatch.setattr(
            backend.runtime,
            "trace",
            lambda _record_id: (_ for _ in ()).throw(
                AssertionError("Graph view must not collapse to the selected trace")
            ),
        )
        monkeypatch.setenv("SEAM_TUI_MOTION", "off")
        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.click("#view-graph-btn")
                graph = app.query_one("#constellation-graph", ConstellationGraph)
                for _ in range(50):
                    if graph.node_count == 3:
                        break
                    await pilot.pause(0.05)

                assert calls == [{"limit": 300, "hops": 2}]
                assert graph.node_count == 3
                assert graph.edge_count == 2
                assert not app.query("#graph-edges")

                await pilot.click("#layout-constellation")
                await pilot.pause()
                assert graph.graph_layout == "constellation"
                assert graph.zoom == 1.0
                assert "SEAM" in graph.rendered_plain_text

        asyncio.run(_check())

    def test_memory_divider_drag_resizes_both_panes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The five-pixel design divider is an interaction, not decoration."""
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setenv("SEAM_TUI_MOTION", "off")
        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                await pilot.pause()
                left = app.query_one("#memory-list-pane")
                right = app.query_one("#memory-detail-pane")
                divider = app.query_one("#memory-divider")
                before_left = left.region.width
                before_right = right.region.width
                target_x = divider.region.x + 12
                target_y = divider.region.y + 2

                await pilot.mouse_down(divider, offset=(0, 2))
                await pilot.hover(offset=(target_x, target_y))
                await pilot.mouse_up(offset=(target_x, target_y))
                await pilot.pause()

                assert left.region.width >= before_left + 10
                assert right.region.width <= before_right - 10
                assert divider.region.x == left.region.right

        asyncio.run(_check())

    def test_settings_section_divider_is_also_resizable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setenv("SEAM_TUI_MOTION", "off")
        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                app._activate_section("settings")
                await pilot.pause()
                left = app.query_one("#settings-list-pane")
                divider = app.query_one("#settings-divider")
                before = left.region.width
                target = (divider.region.x + 8, divider.region.y + 2)

                await pilot.mouse_down(divider, offset=(0, 2))
                await pilot.hover(offset=target)
                await pilot.mouse_up(offset=target)
                await pilot.pause()

                assert left.region.width >= before + 6

        asyncio.run(_check())

    def test_overlays_are_exclusive_and_escape_closes_the_open_surface(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.overlays import (
            ChatDrawer,
            ConnectionsPopover,
            MemoriesDrawer,
        )

        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                app._on_topbar_chat()
                await pilot.pause()
                assert app.query_one(ChatDrawer).open
                assert not app.query_one(MemoriesDrawer).open

                app._on_topbar_memories()
                await pilot.pause()
                assert not app.query_one(ChatDrawer).open
                assert app.query_one(MemoriesDrawer).open
                assert not app.query_one(ConnectionsPopover).open

                app.action_seam_mode()
                assert not app.query_one(MemoriesDrawer).open

        asyncio.run(_check())

    def test_new_chat_resets_history_and_activity_log_is_collapsible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import RichLog

        from seam_runtime.tui.app import SeamTUI
        from seam_runtime.tui.overlays import ChatDrawer

        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 60)) as pilot:
                log = app.query_one("#app-log", RichLog)
                assert not log.has_class("-open")

                app._write("memory", "operator-visible result")
                assert log.has_class("-open")
                app._on_topbar_log()
                assert not log.has_class("-open")

                drawer = app.query_one(ChatDrawer)
                drawer.set_open(True)
                app.chat_history[:] = [
                    {"role": "user", "content": "old question"},
                    {"role": "assistant", "content": "old answer"},
                ]
                assert app.start_new_chat()
                await pilot.pause()
                assert app.chat_history == []
                assert "new local conversation" in "\n".join(
                    strip.text for strip in drawer.query_one("#chat-log", RichLog).lines
                )

        asyncio.run(_check())

    def test_compact_terminal_collapses_rail_without_hiding_memory_detail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(self._backend_with_a_record(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                assert app.screen.has_class("-compact")
                assert app.query_one("#memory-detail-pane").region.width > 0

        asyncio.run(_check())


def test_persisted_file_is_never_the_repo_env() -> None:
    """Settings must never be written into the repo's own .env."""
    path = config.config_path()
    assert path.name == "seam.env"
    assert "/.config/seam/" in str(path) or os.environ.get("SEAM_CONFIG_HOME")
    assert Path.cwd() not in path.parents
