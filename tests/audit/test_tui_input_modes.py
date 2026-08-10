"""S2b: `!`/`?`/`/` mode dispatch, the palette keystroke-race fix, keyboard
tab navigation, `tab <name>`, and chat with monkeypatched network calls.

See `docs/roadmap/TUI_OPERATOR_SURFACE.md` S2b for the spec. `textual` is an
optional extra; every test that mounts a real widget is guarded the same way
as `test_tui_supersedes_dashboard.py` so a module-level import never aborts
the whole suite on an installation without the `dash` extra.
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

textual_required = pytest.mark.skipif(
    find_spec("textual") is None, reason="textual is not installed"
)


def _backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from seam_runtime.dashboard import DashboardApp
    from seam_runtime.runtime import SeamRuntime

    # Match `test_tui_supersedes_dashboard.py`: an operator's own pgvector
    # DSN must never leak into what these tests observe.
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    return DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))


def _backend_with_a_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    backend = _backend(tmp_path, monkeypatch)
    should_exit = backend.execute("compile a note about the memory workspace redesign")
    assert should_exit is False
    assert backend.result_title != "Command Error", backend.result_body
    return backend


@textual_required
class TestModeDispatch:
    """Typed sigils latch immediately; atomically inserted prefixed lines run
    once regardless of the latched mode; Escape returns to seam."""

    def test_bare_bang_latches_shell_mode(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                await pilot.press("!")
                await pilot.pause()
                assert app.mode == "shell"
                assert field.value == ""
                assert field.has_class("-mode-shell")
                assert not field.has_class("-mode-chat")
                assert str(app.shell_session.cwd) in field.placeholder

        asyncio.run(_check())

    def test_bare_question_mark_latches_chat_mode_and_switches_tab(
        self, tmp_path, monkeypatch
    ) -> None:
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                await pilot.press("?")
                await pilot.pause()
                assert app.mode == "chat"
                assert field.value == ""
                assert field.has_class("-mode-chat")
                assert field.placeholder == "message the model"
                assert app.query_one(TabbedContent).active == "tab-chat"

        asyncio.run(_check())

    def test_typed_bang_latches_before_following_shell_text(
        self, tmp_path, monkeypatch
    ) -> None:
        """Immediate activation means a normally typed prefix becomes mode input."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))
        calls: list[str] = []
        monkeypatch.setattr(app, "_run_shell", calls.append)

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._set_mode("chat")
                app.query_one("#command-input", Input).focus()
                await pilot.press("!", "p", "w", "d", "enter")
                await pilot.pause()

                assert app.mode == "shell"
                assert calls == ["pwd"]

        asyncio.run(_check())

    def test_typed_question_latches_before_following_chat_text(
        self, tmp_path, monkeypatch
    ) -> None:
        """The chat sigil follows the same immediate keyboard contract."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))
        calls: list[str] = []
        monkeypatch.setattr(app, "_run_chat", calls.append)

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._set_mode("shell")
                app.query_one("#command-input", Input).focus()
                await pilot.press("?", "h", "e", "l", "l", "o", "enter")
                await pilot.pause()

                assert app.mode == "chat"
                assert calls == ["hello"]

        asyncio.run(_check())

    @pytest.mark.parametrize(("sigil", "expected_mode"), [("!", "shell"), ("?", "chat")])
    def test_mode_sigils_work_when_the_memory_table_has_focus(
        self, tmp_path, monkeypatch, sigil, expected_mode
    ) -> None:
        import asyncio

        from textual.widgets import DataTable, Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                table = app.query_one("#memory-table", DataTable)
                table.focus()
                await pilot.press(sigil)
                await pilot.pause()

                assert app.mode == expected_mode
                assert app.focused is app.query_one("#command-input", Input)

        asyncio.run(_check())

    def test_question_mark_remains_text_inside_the_provenance_input(
        self, tmp_path, monkeypatch
    ) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#prov-query", Input)
                field.focus()
                await pilot.press("?")
                await pilot.pause()

                assert field.value == "?"
                assert app.mode == "seam"

        asyncio.run(_check())

    def test_escape_in_command_input_returns_to_seam_mode(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                await pilot.press("!", "enter")
                await pilot.pause()
                assert app.mode == "shell"

                await pilot.press("escape")
                await pilot.pause()
                assert app.mode == "seam"
                assert not field.has_class("-mode-shell")
                assert not field.has_class("-mode-chat")
                assert field.placeholder == "Run a command, or press / for the menu"

        asyncio.run(_check())

    def test_pasted_prefixed_shell_command_runs_once_while_latched_in_chat(
        self, tmp_path, monkeypatch
    ) -> None:
        """An atomically inserted `!pwd` overrides chat for one command."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                # Latch chat mode through the real bare-`?` path (not by
                # calling `_set_mode` directly) so it also switches the
                # visible tab to Chat, matching what an operator would
                # actually see before typing `!pwd`.
                field = app.query_one("#command-input", Input)
                field.focus()
                await pilot.press("?", "enter")
                await pilot.pause()
                assert app.mode == "chat"

                field.value = "!pwd"
                await pilot.press("enter")
                for _ in range(50):
                    if "exit_code" in _log_text(app, "chat"):
                        break
                    await pilot.pause(0.05)
                # The shell ran (rendered into the active tab's log, which is
                # Chat since that is what was active)...
                assert "exit_code: 0" in _log_text(app, "chat")
                # ...and it did not disturb the latched mode.
                assert app.mode == "chat"

        asyncio.run(_check())

    def test_palette_command_runs_once_while_latched_in_shell(
        self, tmp_path, monkeypatch
    ) -> None:
        """Typing `/index` (a dash verb with no positional arguments) and
        selecting it from the palette must run the dashboard `index`
        command even though the app is latched in shell mode. `/` always
        opens the palette on its own (unchanged pre-existing behaviour --
        see `TestPaletteSeeding` for that mechanism in isolation); this
        test is about what happens *after* the operator picks the filtered
        match -- it must dispatch through `_run_command`, not fall through
        to the still-latched shell mode.
        """
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._set_mode("shell")
                field = app.query_one("#command-input", Input)
                field.focus()
                tab_id = app._active_tab_id()
                before = _log_text(app, tab_id)

                await pilot.press("/", "i", "n", "d", "e", "x")
                await pilot.pause()
                # The palette intercepted the leading "/" and is now open,
                # filtered down to "index".
                assert field.value == ""
                await pilot.press("enter")
                await pilot.pause()

                for _ in range(50):
                    if _log_text(app, tab_id) != before:
                        break
                    await pilot.pause(0.05)
                after = _log_text(app, tab_id)
                assert after != before, "the index command never rendered anything new"
                assert "Index" in after
                # Stayed latched in shell mode; the "/"-selected command was
                # a one-shot dashboard command, not a mode change.
                assert app.mode == "shell"

        asyncio.run(_check())

    def test_unprefixed_text_runs_in_the_latched_shell_mode(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._set_mode("shell")
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "pwd"
                await pilot.press("enter")
                tab_id = app._active_tab_id()
                for _ in range(50):
                    if "exit_code" in _log_text(app, tab_id):
                        break
                    await pilot.pause(0.05)
                assert "exit_code: 0" in _log_text(app, tab_id)

        asyncio.run(_check())

    def test_unprefixed_text_runs_dashboard_commands_in_seam_mode(
        self, tmp_path, monkeypatch
    ) -> None:
        """Unchanged baseline behaviour: with nothing latched, plain text is
        a dashboard command, exactly like before this slice."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.mode == "seam"
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "stats"
                await pilot.press("enter")
                tab_id = app._active_tab_id()
                for _ in range(50):
                    if "Dashboard" in _log_text(app, tab_id) or "Stats" in _log_text(app, tab_id):
                        break
                    await pilot.pause(0.05)
                # Whatever the exact title text, it must not have been
                # treated as a shell or chat message.
                assert "exit_code" not in _log_text(app, tab_id)

        asyncio.run(_check())


def _log_text(app, tab_id: str) -> str:
    from textual.widgets import RichLog

    if tab_id == "settings":
        tab_id = "memory"
    log = app.query_one(f"#log-{tab_id}", RichLog)
    return "\n".join(strip.text for strip in log.lines)


@textual_required
class TestPaletteSeeding:
    """S2b defect #1: leftover text in `#command-input` seeds the palette's
    filter instead of being discarded."""

    def test_action_open_palette_reads_leftover_text_and_clears_the_field(
        self, tmp_path, monkeypatch
    ) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import CommandPalette, SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.value = "/stats"
                app.action_open_palette()
                await pilot.pause()
                assert field.value == ""
                top = app.screen_stack[-1]
                assert isinstance(top, CommandPalette)
                assert top.initial == "stats"

        asyncio.run(_check())

    def test_on_mount_applies_initial_as_a_live_filter(self, tmp_path, monkeypatch) -> None:
        """The other half of the fix: `CommandPalette.on_mount` must not
        just show `initial` in the input box -- it must actually filter the
        option list against it (the previous bug: `on_mount` rendered the
        full unfiltered catalog no matter what `initial` said)."""
        import asyncio

        from textual.app import App
        from textual.widgets import OptionList

        from seam_runtime.tui.app import CommandPalette
        from seam_runtime.tui.commands import build_catalog

        backend = _backend(tmp_path, monkeypatch)
        catalog = build_catalog(backend.command_parser)

        class _Harness(App[None]):
            async def on_mount(self) -> None:
                await self.push_screen(CommandPalette(catalog, initial="stats"))

        async def _check() -> None:
            app = _Harness()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                option_list = app.screen.query_one("#palette-list", OptionList)
                rows = [
                    str(option_list.get_option_at_index(i)._prompt)
                    for i in range(option_list.option_count)
                ]
                # Every non-disabled, non-Modes-group row must actually
                # match "stats" -- an unfiltered catalog would include many
                # rows (compile, search, retrieve, ...) that do not.
                assert any("stats" in row for row in rows)
                assert not any("compile" in row for row in rows)

        asyncio.run(_check())

    def test_empty_leftover_opens_unfiltered_as_before(self, tmp_path, monkeypatch) -> None:
        """A genuinely bare `/` must still open the full, unfiltered menu --
        the fix must not narrow the existing "bare sigil opens the menu"
        behaviour."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import CommandPalette, SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.value = "/"
                app.action_open_palette()
                await pilot.pause()
                top = app.screen_stack[-1]
                assert isinstance(top, CommandPalette)
                assert top.initial == ""

        asyncio.run(_check())


@textual_required
class TestTabNavigation:
    def test_alt_n_jumps_directly(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import TabbedContent

        from seam_runtime.tui.app import TABS, SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.press("alt+3")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == f"tab-{TABS[2][0]}"

        asyncio.run(_check())

    def test_ctrl_right_cycles_forward_even_with_command_input_focused(
        self, tmp_path, monkeypatch
    ) -> None:
        """The reason this needs `priority=True`: plain `Input` already
        binds ctrl+right to word-wise cursor movement, and `#command-input`
        holds focus almost always."""
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import TABS, SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app.query_one("#command-input", Input).focus()
                await pilot.pause()
                assert app.query_one(TabbedContent).active == "tab-memory"
                await pilot.press("ctrl+right")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == f"tab-{TABS[1][0]}"

        asyncio.run(_check())

    def test_ctrl_left_cycles_backward_and_wraps(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import TabbedContent

        from seam_runtime.tui.app import TABS, SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                # Starts on the first tab; cycling backward must wrap to
                # the last one, not raise or stick.
                await pilot.press("ctrl+left")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == f"tab-{TABS[-1][0]}"

        asyncio.run(_check())

    def test_tab_command_switches_by_case_insensitive_prefix(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "tab BENCH"
                await pilot.press("enter")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == "tab-benchmarks"

        asyncio.run(_check())

    def test_tab_command_by_label_prefix(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "tab Live"
                await pilot.press("enter")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == "tab-live"

        asyncio.run(_check())

    def test_unknown_tab_name_errors_and_changes_nothing(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                before = app.query_one(TabbedContent).active
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "tab nonexistent"
                await pilot.press("enter")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == before
                assert "no tab matches" in _log_text(app, app._active_tab_id())

        asyncio.run(_check())

    def test_bare_tab_command_shows_usage_and_changes_nothing(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input, TabbedContent

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                before = app.query_one(TabbedContent).active
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "tab"
                await pilot.press("enter")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == before
                assert "usage: tab" in _log_text(app, app._active_tab_id())

        asyncio.run(_check())


@textual_required
class TestChatNeverCallsTheNetwork:
    """`SeamChatClient.complete` is monkeypatched in every test below -- no
    test in this class may reach `httpx`/a real provider."""

    @pytest.fixture(autouse=True)
    def _isolated_chat_settings(self, tmp_path, monkeypatch) -> None:
        from seam_runtime import config

        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "settings.env")

    def test_not_configured_message_renders_without_a_key(self, tmp_path, monkeypatch) -> None:
        """With no API key set, `SeamChatClient.complete` (unmodified, real
        implementation) already returns an explanatory string rather than
        making a request -- this is the "verify with the key unset" path
        from the task brief, still not a network call."""
        import asyncio

        from textual.widgets import Input

        from seam_runtime.tui.app import SeamTUI

        monkeypatch.delenv("SEAM_CHAT_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert not app.chat_client.configured
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "?hello there"
                await pilot.press("enter")
                for _ in range(50):
                    if "not configured" in _log_text(app, "chat"):
                        break
                    await pilot.pause(0.05)
                assert "not configured" in _log_text(app, "chat")

        asyncio.run(_check())

    def test_chat_reloads_settings_saved_after_app_construction(
        self, tmp_path, monkeypatch
    ) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime import config
        from seam_runtime.dashboard import SeamChatClient
        from seam_runtime.tui.app import SeamTUI

        monkeypatch.delenv("SEAM_CHAT_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        app = SeamTUI(_backend(tmp_path, monkeypatch))
        assert not app.chat_client.configured

        observed: list[tuple[bool, str, str]] = []

        def fake_complete(self, messages, context_prompt):  # noqa: ANN001 - test double
            observed.append((self.configured, self.base_url, self.model))
            return "settings refresh worked"

        monkeypatch.setattr(SeamChatClient, "complete", fake_complete)
        config.save_persisted(
            {
                "SEAM_CHAT_API_KEY": "test-only-key",
                "SEAM_CHAT_BASE_URL": "https://chat.example.test/v1",
                "SEAM_CHAT_MODEL": "test-model",
            }
        )

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "?hello after save"
                await pilot.press("enter")
                for _ in range(50):
                    if observed:
                        break
                    await pilot.pause(0.05)

                assert observed == [
                    (True, "https://chat.example.test/v1", "test-model")
                ]
                assert "settings refresh worked" in _log_text(app, "chat")

        asyncio.run(_check())

    def test_injected_memory_ids_reach_the_log(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.dashboard import SeamChatClient
        from seam_runtime.tui.app import SeamTUI

        backend = _backend_with_a_record(tmp_path, monkeypatch)
        query = "memory workspace redesign"
        expected = backend.orchestrator.rag(
            query, budget=5, pack_budget=384, lens="rag", mode="context"
        ).to_dict()
        expected_ids = expected["candidate_ids"]
        assert expected_ids, "need at least one candidate for this assertion to mean anything"

        calls: list[tuple[list[dict[str, str]], str]] = []

        def fake_complete(self, messages, context_prompt):  # noqa: ANN001 - test double
            calls.append((list(messages), context_prompt))
            return "canned reply, no network involved"

        monkeypatch.setattr(SeamChatClient, "complete", fake_complete)

        app = SeamTUI(backend)

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = f"?{query}"
                await pilot.press("enter")
                for _ in range(50):
                    if calls:
                        break
                    await pilot.pause(0.05)
                await pilot.pause(0.2)

                assert calls, "SeamChatClient.complete was never called"
                text = _log_text(app, "chat")
                assert "canned reply, no network involved" in text
                for memory_id in expected_ids:
                    assert memory_id in text, (memory_id, text)

        asyncio.run(_check())

    def test_chat_history_is_kept_on_the_app(self, tmp_path, monkeypatch) -> None:
        import asyncio

        from textual.widgets import Input

        from seam_runtime.dashboard import SeamChatClient
        from seam_runtime.tui.app import SeamTUI

        monkeypatch.setattr(SeamChatClient, "complete", lambda self, messages, context: "ack")

        app = SeamTUI(_backend(tmp_path, monkeypatch))

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                field = app.query_one("#command-input", Input)
                field.focus()
                field.value = "?hi"
                await pilot.press("enter")
                for _ in range(50):
                    if len(app.chat_history) >= 2:
                        break
                    await pilot.pause(0.05)
                assert app.chat_history[0] == {"role": "user", "content": "hi"}
                assert app.chat_history[1] == {"role": "assistant", "content": "ack"}

        asyncio.run(_check())

    def test_chat_serializes_requests_and_snapshots_worker_state(
        self, tmp_path, monkeypatch
    ) -> None:
        import asyncio

        from seam_runtime.tui.app import SeamTUI

        app = SeamTUI(_backend(tmp_path, monkeypatch))
        calls: list[tuple[str, object, list[dict[str, str]]]] = []
        monkeypatch.setattr(
            app,
            "_execute_chat",
            lambda message, client, history: calls.append((message, client, history)),
        )

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._run_chat("first")
                assert app._chat_busy
                assert len(calls) == 1
                assert calls[0][0] == "first"
                assert calls[0][1] is app.chat_client
                assert calls[0][2] == [{"role": "user", "content": "first"}]
                assert calls[0][2] is not app.chat_history

                app._run_chat("second")
                await pilot.pause()
                assert len(calls) == 1
                assert app.chat_history == [{"role": "user", "content": "first"}]
                assert "already running" in _log_text(app, "chat")

                app._render_chat_reply("first reply", [])
                assert not app._chat_busy
                assert app.chat_history[-1] == {
                    "role": "assistant",
                    "content": "first reply",
                }

        asyncio.run(_check())
