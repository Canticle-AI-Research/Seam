"""The SEAM TUI application shell.

Structure mirrors the split that already existed but was never enforced:
`DashboardApp` stays the backend (parser, command implementations, runtime
access) and this module is only presentation. Every command the backend
accepts is therefore reachable here by construction, and the `/` palette is
derived from the backend's own parser rather than a parallel list.

Blocking work runs on a worker thread. The previous dashboard called straight
into retrieval, chat, and subprocesses from the event loop, which froze the UI
for the duration of every operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Input,
    OptionList,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from .. import config
from . import brand
from .commands import (
    SURFACES,
    CommandSpec,
    build_catalog,
    catalog_counts,
    filter_catalog,
)
from .panels import PANEL_CLASSES
from .settings_screen import SettingsPanel

__all__ = ["SeamTUI", "CommandPalette", "run"]

THEME_PATH = Path(__file__).with_name("theme.tcss")

#: Tab id -> label. Preserved from the previous dashboard so muscle memory and
#: the `tab` command keep working.
TABS: tuple[tuple[str, str], ...] = (
    ("memory", "Memory"),
    ("retrieval", "Retrieval"),
    ("benchmarks", "Benchmarks"),
    ("compression", "Compression"),
    ("chat", "Chat"),
    ("live", "Live"),
    ("settings", "Settings"),
)


class CommandPalette(ModalScreen[str]):
    """The `/` menu: every backend command, filterable, Charm-styled."""

    BINDINGS = [
        Binding("escape", "dismiss_palette", "Close", show=False),
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
    ]

    def __init__(self, catalog: tuple[CommandSpec, ...], initial: str = "") -> None:
        super().__init__()
        self.catalog = catalog
        self.initial = initial
        self._visible: tuple[CommandSpec, ...] = catalog

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-wrap"):
            with Vertical(id="palette"):
                counts = catalog_counts(self.catalog)
                breakdown = "  ".join(
                    f"[{brand.CYAN}]{counts[key]}[/][{brand.TEXT_DIM}] "
                    f"{SURFACES[key][0].split('·')[0].strip().lower()}[/]"
                    for key in SURFACES if counts.get(key)
                )
                yield Static(
                    f"[b {brand.MAGENTA}]{len(self.catalog)} commands[/]   {breakdown}",
                    id="palette-prompt",
                )
                yield Input(
                    value=self.initial,
                    placeholder="type to filter…",
                    id="palette-input",
                )
                yield OptionList(id="palette-list")

    def on_mount(self) -> None:
        self._render_options(self.catalog)
        self.query_one("#palette-input", Input).focus()

    def _render_options(self, specs: tuple[CommandSpec, ...]) -> None:
        option_list = self.query_one("#palette-list", OptionList)
        option_list.clear_options()
        self._visible = specs

        surface = None
        group = None
        for spec in specs:
            if spec.surface != surface:
                surface = spec.surface
                group = None
                label, executable = SURFACES.get(surface, (surface, False))
                count = sum(1 for s in specs if s.surface == surface)
                tag = "" if executable else "  ·  reference"
                option_list.add_option(Option(
                    f"[b {brand.MAGENTA}]── {label}[/] "
                    f"[{brand.TEXT_DIM}]{count}{tag}[/]",
                    disabled=True,
                ))
            if spec.group and spec.group != group:
                group = spec.group
                option_list.add_option(Option(
                    f"   [{brand.LAVENDER}]{group}[/]", disabled=True))

            alias = f" ({', '.join(spec.aliases)})" if spec.aliases else ""
            summary = spec.summary or ""
            colour = brand.PINK if spec.executable else brand.CYAN
            row = f"   [{colour}]{spec.prefix}{spec.name}[/][{brand.TEXT_DIM}]{alias}[/]"
            if summary:
                row += f"  [{brand.TEXT_MUTED}]— {summary}[/]"
            option_list.add_option(Option(row, id=f"{spec.surface}:{spec.name}"))

        if specs:
            # Land on the first real entry, not a section header.
            for index in range(option_list.option_count):
                if not option_list.get_option_at_index(index).disabled:
                    option_list.highlighted = index
                    break

    @on(Input.Changed, "#palette-input")
    def _on_filter(self, event: Input.Changed) -> None:
        self._render_options(filter_catalog(self.catalog, event.value))

    @on(Input.Submitted, "#palette-input")
    def _on_submit(self) -> None:
        option_list = self.query_one("#palette-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.id:
            self.dismiss(option.id)

    @on(OptionList.OptionSelected, "#palette-list")
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_dismiss_palette(self) -> None:
        self.dismiss("")

    def action_cursor_down(self) -> None:
        self.query_one("#palette-list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#palette-list", OptionList).action_cursor_up()


class SeamTUI(App[None]):
    """SEAM operator dashboard."""

    CSS_PATH = THEME_PATH
    TITLE = "SEAM"

    BINDINGS = [
        Binding("slash", "open_palette", "Commands"),
        Binding("ctrl+p", "open_palette", "Commands", show=False),
        Binding("ctrl+s", "show_settings", "Settings"),
        Binding("ctrl+l", "clear_output", "Clear"),
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    def __init__(self, backend: Any) -> None:
        super().__init__()
        self.backend = backend
        self.catalog = build_catalog(backend.command_parser)

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="brand-bar"):
            yield Static(brand.brand_mark(), id="brand-mark")
            yield Static(str(self.backend.runtime.store.path), id="brand-context")
            yield Static("ready", id="brand-status")

        with TabbedContent(id="tabs"):
            for tab_id, label in TABS:
                with TabPane(label, id=f"tab-{tab_id}"):
                    if tab_id == "settings":
                        yield SettingsPanel()
                    else:
                        # Each panel owns its own `#log-{tab_id}` RichLog, so
                        # `_write()` and `action_clear_output()` below keep
                        # working unchanged -- only the container around that
                        # log changed, from a bare RichLog to a RichLog plus
                        # a DataTable/Tree/Input showing structured state.
                        yield PANEL_CLASSES[tab_id](id=f"panel-{tab_id}")

        yield Input(placeholder="Run a command, or press / for the menu", id="command-input")
        yield Static(
            "[b]/[/b] commands   [b]^S[/b] settings   [b]y[/b] copy id   "
            "[b]^L[/b] clear   [b]^C[/b] quit",
            id="help-rail",
        )

    def _blink(self) -> None:
        """Toggle the brand caret, giving the rail a live terminal feel."""
        self._cursor_on = not self._cursor_on
        try:
            self.query_one("#brand-mark", Static).update(
                brand.brand_mark(self._cursor_on)
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        self._cursor_on = True
        self.set_interval(0.55, self._blink)
        self._write(
            "memory",
            brand.splash(
                f"{len(self.catalog)} commands · press / for the menu · "
                f"{len(config.SETTINGS)} settings in the Settings tab"
            ),
        )
        # The Memory tab is now a page (table + provenance trace + this log,
        # panels.py's `MemoryPanel`), and neither the copy-id key nor the
        # trace-on-select behaviour is otherwise visible without reading the
        # source, so say it once, dim, right under the splash.
        self._write(
            "memory",
            f"[{brand.TEXT_DIM}]tip: select a record (enter or click) to "
            f"trace it below · [b]y[/b] copies its id[/]",
        )
        self.query_one("#command-input", Input).focus()

    # -- helpers -----------------------------------------------------------

    def _active_tab_id(self) -> str:
        active = self.query_one(TabbedContent).active or "tab-memory"
        return active.removeprefix("tab-")

    def _write(self, tab_id: str, text: str) -> None:
        """Write to a tab's log, falling back to Memory for the settings tab."""
        if tab_id == "settings":
            tab_id = "memory"
        try:
            self.query_one(f"#log-{tab_id}", RichLog).write(text)
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        self.query_one("#brand-status", Static).update(text)

    # -- actions -----------------------------------------------------------

    def action_open_palette(self) -> None:
        self.push_screen(CommandPalette(self.catalog), self._palette_result)

    def _palette_result(self, selection: str | None) -> None:
        if not selection:
            return
        surface, _, name = selection.partition(":")
        spec = next(
            (c for c in self.catalog if c.surface == surface and c.name == name),
            None,
        )
        if spec is None:
            return

        # Only dashboard verbs are ours to run. CLI/MCP/REST/SDK entries are
        # documentation: showing their usage is honest, whereas silently
        # shelling out would run code the operator did not ask for.
        if not spec.executable:
            self._show_reference(spec)
            return

        field = self.query_one("#command-input", Input)
        if spec.positionals:
            field.value = f"{spec.name} "
            field.focus()
            field.cursor_position = len(field.value)
        else:
            self._run_command(spec.name)

    def _show_reference(self, spec: CommandSpec) -> None:
        """Print a reference card for a command the TUI does not execute."""
        label = SURFACES.get(spec.surface, (spec.surface, False))[0]
        lines = [
            "",
            f"[b {brand.MAGENTA}]{spec.prefix}{spec.name}[/]",
            f"[{brand.TEXT_DIM}]{label}[/]",
        ]
        if spec.summary:
            lines.append(f"[{brand.TEXT_MUTED}]{spec.summary}[/]")
        if spec.positionals or spec.options:
            lines.append(f"[{brand.CYAN}]usage[/]  {spec.usage}")
        for flag, values in spec.choices.items():
            lines.append(f"[{brand.LAVENDER}]{flag}[/]  {', '.join(values)}")
        self._write(self._active_tab_id(), "\n".join(lines))

    def action_show_settings(self) -> None:
        self.query_one(TabbedContent).active = "tab-settings"

    def action_clear_output(self) -> None:
        tab_id = self._active_tab_id()
        if tab_id == "settings":
            return
        try:
            self.query_one(f"#log-{tab_id}", RichLog).clear()
        except Exception:
            pass

    @on(Input.Changed, "#command-input")
    def _on_slash(self, event: Input.Changed) -> None:
        """Open the palette when `/` starts a fresh command.

        The `slash` binding alone is not enough: focus normally rests in the
        command input, which consumes printable keys, so pressing `/` would
        just type a character. Opening on a leading slash matches how every
        other `/`-menu behaves.
        """
        if event.value == "/":
            event.input.value = ""
            self.action_open_palette()

    @on(Input.Submitted, "#command-input")
    def _on_command(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if not command:
            return
        event.input.value = ""
        if command.startswith("/"):
            command = command[1:]
        self._run_command(command)

    def _run_command(self, command: str) -> None:
        tab_id = self._active_tab_id()
        verb, _, rest = command.partition(" ")
        echo = f"\n[b {brand.PINK}]{brand.PROMPT}[/] [b {brand.MAGENTA}]{verb}[/]"
        if rest:
            echo += f" [{brand.TEXT_MUTED}]{rest}[/]"
        self._write(tab_id, echo)
        self._set_status(f"[{brand.YELLOW}]working…[/]")
        self._execute(command, tab_id)

    @work(thread=True, exclusive=False)
    def _execute(self, command: str, tab_id: str) -> None:
        """Run a backend command off the event loop.

        The backend is synchronous and can block for seconds (retrieval, chat,
        subprocesses); running it inline is what made the old dashboard freeze.
        """
        try:
            should_exit = self.backend.execute(command)
            title = getattr(self.backend, "result_title", "")
            body = getattr(self.backend, "result_body", "")
        except Exception as exc:  # surface, never swallow
            self.call_from_thread(
                self._write, tab_id,
                f"[b {brand.RED}]error[/]  [{brand.TEXT_MAIN}]{exc}[/]",
            )
            self.call_from_thread(self._set_status, f"[{brand.RED}]error[/]")
            return

        self.call_from_thread(self._render_result, tab_id, title, body)
        if should_exit:
            self.call_from_thread(self.exit)

    def _render_result(self, tab_id: str, title: str, body: str) -> None:
        if title:
            self._write(tab_id, f"[b {brand.MAGENTA}]{title}[/]")
        if body:
            self._write(tab_id, brand.colorize(body))
        self._set_status(f"[{brand.MINT}]ready[/]")
        self._refresh_panel(tab_id)

    def _refresh_panel(self, tab_id: str) -> None:
        """Reload the active tab's structured view after a command runs.

        The text above comes straight from the backend's `result_body`; the
        DataTable/Tree panels read runtime state independently (panels.py),
        so a completed command does not update them unless something asks.
        Calling `reload()` is safe even when nothing changed for that panel
        (e.g. running `stats` on the Retrieval tab) -- panels with a pending
        query/id just re-run it, panels with none are a no-op.
        """
        if tab_id == "settings":
            return
        try:
            panel = self.query_one(f"#panel-{tab_id}")
        except Exception:
            return
        reload = getattr(panel, "reload", None)
        if callable(reload):
            reload()


def run(backend: Any) -> None:
    """Launch the TUI against an existing `DashboardApp` backend."""
    SeamTUI(backend).run()


def main(argv: list[str] | None = None) -> None:
    """Console entry point for `seam-tui`.

    Persisted settings are applied *before* the runtime is constructed, because
    knobs like `SEAM_DB_PATH` and the embedding provider are read during
    construction and would otherwise be ignored until the next launch.
    """
    import argparse

    config.apply_persisted_to_environ()

    from ..dashboard import DashboardApp
    from ..installer import default_runtime_db_path
    from ..runtime import SeamRuntime

    parser = argparse.ArgumentParser(prog="seam-tui", description="SEAM terminal dashboard")
    parser.add_argument("--db", default=None, help="database path (default: SEAM_DB_PATH)")
    args = parser.parse_args(argv)

    db_path = args.db or default_runtime_db_path()
    run(DashboardApp(SeamRuntime(db_path)))


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
