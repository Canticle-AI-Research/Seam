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

import json
from pathlib import Path
from typing import Any

from rich.markup import escape as _escape_markup
from textual import events, on, work
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
from ..context_views import build_context_payload
from . import brand, shell
from .commands import (
    SURFACES,
    CommandSpec,
    build_catalog,
    catalog_counts,
    filter_catalog,
)
from .keys import META_DIGIT_KEYS, SeamInput
from .panels import PANEL_CLASSES
from .settings_screen import SettingsPanel

__all__ = ["SeamTUI", "CommandPalette", "run"]

THEME_PATH = Path(__file__).with_name("theme.tcss")

#: Tab id -> label. `TabbedContent.active` is always `f"tab-{id}"`. The `tab`
#: command (below, `_run_tab_command`) matches an operator's argument
#: case-insensitively against both the id and the label here (prefix match
#: is fine) and switches to it directly -- it does NOT delegate to the
#: backend's own `tab` verb, whose argparse choices (`runtime`/`benchmark`)
#: are the previous dashboard's tab names and do not exist on this one.
TABS: tuple[tuple[str, str], ...] = (
    ("memory", "Memory"),
    ("retrieval", "Retrieval"),
    ("benchmarks", "Benchmarks"),
    ("compression", "Compression"),
    ("chat", "Chat"),
    ("live", "Live"),
    ("settings", "Settings"),
)

#: Reference-row surface tag shown in the palette. "rest" reads better than
#: the internal "api" key next to "cli"/"mcp"/"sdk".
_SURFACE_TAGS: dict[str, str] = {"cli": "cli", "mcp": "mcp", "api": "rest", "sdk": "sdk"}

#: The three modes an operator can latch `#command-input` into (S2b). Typing
#: `!` or `?` latches immediately, so subsequent keystrokes run in that mode;
#: a whole prefixed line inserted atomically (for example, by paste) remains a
#: one-shot override. `/` opens the palette and seeds it with following text.
_MODE_PLACEHOLDERS: dict[str, str] = {
    "seam": "Run a command, or press / for the menu",
    "shell": "run a shell command in {cwd}",
    # Shown instead of the row above when `shell.shell_enabled()` is False,
    # so the input itself -- not just a message that scrolls away -- keeps
    # telling the operator why `!` does nothing (Part 5 of the shell gate).
    # Still carries `{cwd}` (formatted the same way as the row above) so the
    # session's working directory stays visible even while shell mode is
    # disabled.
    "shell-disabled": (
        f"shell disabled -- set {shell.ALLOW_SHELL_ENV}=1 in the Settings "
        "tab (cwd: {cwd})"
    ),
    "chat": "message the model",
}
_MODE_COLORS: dict[str, str] = {
    "seam": brand.PINK, "shell": brand.ORANGE, "chat": brand.CYAN,
}
#: Palette option ids -> (label, summary) for the "Modes" group (Part 5).
_MODE_MENU_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mode:shell", "!shell", "Latch shell mode -- bare text runs a shell command"),
    ("mode:chat", "?chat", "Latch chat mode -- bare text messages the model"),
    ("mode:seam", "/seam", "Return to seam mode -- bare text runs dashboard commands"),
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
                yield SeamInput(
                    value=self.initial,
                    placeholder="type to filter…",
                    id="palette-input",
                )
                yield OptionList(id="palette-list")

    def on_mount(self) -> None:
        # `initial` is text the operator had already typed into
        # `#command-input` before the palette opened (`action_open_palette`
        # in the App below): apply it as a live filter, not just cosmetic
        # text sitting in `#palette-input` (S2b defect #1 -- previously
        # `initial` filled the input's *display* value in `compose()` above
        # but nothing ever re-rendered the option list against it, so a
        # fast `/stats` opened on an unfiltered, unrelated first entry).
        if self.initial:
            self._render_options(filter_catalog(self.catalog, self.initial))
        else:
            self._render_options(self.catalog)
        self.query_one("#palette-input", Input).focus()

    def _render_options(self, specs: tuple[CommandSpec, ...]) -> None:
        """Render two sections: Run (executable dash verbs), then Reference
        (cli/mcp/api/sdk documentation). Both group by shared task rather
        than by surface, so a Reference row for the same task across
        surfaces sits together; each Reference row carries a dim surface tag
        so the CLI form, the REST route, and the MCP tool are still
        distinguishable at a glance.
        """
        option_list = self.query_one("#palette-list", OptionList)
        option_list.clear_options()
        self._visible = specs

        run_specs = [s for s in specs if s.executable]
        reference_specs = [s for s in specs if not s.executable]

        def add_section(label: str, count: int) -> None:
            option_list.add_option(Option(
                f"[b {brand.MAGENTA}]── {label}[/] [{brand.TEXT_DIM}]{count}[/]",
                disabled=True,
            ))

        def add_rows(section_specs: list[CommandSpec], *, tagged: bool) -> None:
            group = None
            for spec in section_specs:
                if spec.group and spec.group != group:
                    group = spec.group
                    option_list.add_option(Option(
                        f"   [{brand.LAVENDER}]{group}[/]", disabled=True))

                alias = f" ({', '.join(spec.aliases)})" if spec.aliases else ""
                summary = spec.summary or ""
                colour = brand.PINK if spec.executable else brand.CYAN
                tag = ""
                if tagged:
                    surface_tag = _SURFACE_TAGS.get(spec.surface, spec.surface)
                    tag = f"[{brand.TEXT_DIM}]{surface_tag}[/]  "
                row = f"   {tag}[{colour}]{spec.prefix}{spec.name}[/][{brand.TEXT_DIM}]{alias}[/]"
                if summary:
                    row += f"  [{brand.TEXT_MUTED}]— {summary}[/]"
                option_list.add_option(Option(row, id=f"{spec.surface}:{spec.name}"))

        # The three input-mode sigils (Part 1 of S2b) live in the Run
        # section next to the dash verbs -- they are just as executable,
        # just not backend commands -- and stay listed even when a search
        # filters every dash verb out, so they are always discoverable.
        add_section("Run", len(run_specs) + len(_MODE_MENU_ROWS))
        add_rows(run_specs, tagged=False)
        self._add_modes_group(option_list)
        if reference_specs:
            add_section("Reference", len(reference_specs))
            add_rows(reference_specs, tagged=True)

        if specs:
            # Land on the first real entry, not a section header.
            for index in range(option_list.option_count):
                if not option_list.get_option_at_index(index).disabled:
                    option_list.highlighted = index
                    break

    def _add_modes_group(self, option_list: OptionList) -> None:
        """The Run section's "Modes" group: `!shell`, `?chat`, `/seam`.

        Selecting one dismisses the palette with a `mode:<name>` id that
        `SeamTUI._palette_result` special-cases -- these are not
        `CommandSpec`s (they are not backend commands the catalog derives
        from), so they are rendered here directly instead of being folded
        into `commands.py`'s `build_catalog`, which would also perturb its
        pinned executable-row count.
        """
        option_list.add_option(Option(f"   [{brand.LAVENDER}]Modes[/]", disabled=True))
        for option_id, label, summary in _MODE_MENU_ROWS:
            row = f"   [{brand.PINK}]{label}[/]  [{brand.TEXT_MUTED}]— {summary}[/]"
            option_list.add_option(Option(row, id=option_id))

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


#: `alt+1`..`alt+N`, capped at 9 (there is no "alt+10" key) -- derived from
#: `len(TABS)` rather than hardcoded, because TABS has already changed size
#: once (S1 removed the standalone Provenance tab) and will again (S9 folds
#: Benchmarks/Compression into Engine).
#:
#: Each tab gets both spellings: the real `alt+N` keycode, and what an
#: "Alt sends Escape" terminal actually delivers instead (see `keys.py`).
#: The fallback half dispatches to a *separate* action name so `check_action`
#: can switch it off on its own via `SEAM_TUI_META_DIGITS`, without also
#: disabling real `alt+N`. Both halves are `priority=True` because
#: `#command-input` holds focus almost always.
_JUMP_TAB_BINDINGS: tuple[Binding, ...] = tuple(
    binding
    for i in range(1, min(len(TABS), 9) + 1)
    for binding in (
        Binding(f"alt+{i}", f"jump_tab({i - 1})", f"Tab {i}", show=False, priority=True),
        Binding(
            META_DIGIT_KEYS[i - 1],
            f"jump_tab_meta({i - 1})",
            f"Tab {i}",
            show=False,
            priority=True,
        ),
    )
)


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
        # From tables, trees, buttons, and tabs these printable sigils move
        # focus to the global command bar and latch their mode immediately.
        # `check_action` below disables the bindings while any Input owns
        # focus, so punctuation remains ordinary editable text in settings,
        # search, provenance, and the command bar itself.
        Binding(
            "exclamation_mark",
            "focus_mode('shell')",
            "Shell mode",
            show=False,
            priority=True,
        ),
        Binding(
            "question_mark",
            "focus_mode('chat')",
            "Chat mode",
            show=False,
            priority=True,
        ),
        # Escape is not marked priority: CommandPalette (a ModalScreen) is
        # excluded from the non-priority binding chain while it is open
        # (Textual truncates at the first modal ancestor), so this never
        # competes with the palette's own escape-to-close binding.
        Binding("escape", "seam_mode", "Seam mode", show=False),
        # `priority=True` on the next two: plain `Input` already binds
        # ctrl+left/ctrl+right to word-wise cursor movement (textual's
        # `_input.py`), and `#command-input` holds focus almost always, so a
        # non-priority binding here would never be reached. Priority
        # bindings are checked before the focused widget gets the key at
        # all (`App._check_bindings(priority=True)` in `on_event`).
        Binding("ctrl+right", "next_tab", "Next tab", show=False, priority=True),
        Binding("ctrl+left", "previous_tab", "Previous tab", show=False, priority=True),
        *_JUMP_TAB_BINDINGS,
    ]

    def __init__(self, backend: Any) -> None:
        super().__init__()
        self.backend = backend
        self.catalog = build_catalog(backend.command_parser)
        #: The three S2b input modes; see the module-level `_MODE_PLACEHOLDERS`
        #: table and `_set_mode` below.
        self.mode: str = "seam"
        self.shell_session = shell.ShellSession()
        #: `SeamChatClient` (`dashboard.py:256`) is module-level and already
        #: covers "not configured" and request-failure explanations. The TUI
        #: rebuilds this small client before a chat interaction so Settings
        #: saved after launch take effect; it does not implement a second
        #: client. Imported lazily so importing this
        #: module never requires `httpx`, which `SeamChatClient.complete`
        #: only imports when it actually has a key to use.
        from ..dashboard import SeamChatClient

        self.chat_client = SeamChatClient()
        self.chat_history: list[dict[str, str]] = []
        self._chat_busy = False
        self._chat_intro_shown = False
        motion = config.effective_value("SEAM_TUI_MOTION").strip().lower()
        self._startup_motion = motion if motion in {"full", "reduced", "off"} else "full"
        #: Whether `_META_DIGIT_KEYS` still jump tabs; see the binding table.
        #: Read once at construction so the Settings tab's own value, not the
        #: process environment alone, decides. Anything other than an explicit
        #: `off` keeps the fallback, because the failure it repairs is silent
        #: and the failure it can cause is visible.
        meta_digits = config.effective_value("SEAM_TUI_META_DIGITS").strip().lower()
        self.meta_digits_jump = meta_digits != "off"
        self._startup_active = False
        self._startup_frame = 0
        self._startup_timer: Any = None
        self._cursor_timer: Any = None

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="brand-bar"):
            with Horizontal(id="brand-lockup"):
                yield Static(brand.terminal_prompt(), id="brand-symbol")
                yield Static(brand.product_wordmark(), id="brand-product")
            yield Static(str(self.backend.runtime.store.path), id="brand-context")
            yield Static("seam", id="brand-mode")
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

        yield SeamInput(placeholder=_MODE_PLACEHOLDERS["seam"], id="command-input")
        yield Static(
            "[b]/[/b] commands   [b]![/b] shell   [b]?[/b] chat   [b]^S[/b] settings   "
            "[b]y[/b] copy id   [b]^L[/b] clear   [b]^C[/b] quit",
            id="help-rail",
        )
        if self._startup_motion != "off":
            with Horizontal(id="startup-splash"):
                yield Static(brand.terminal_prompt(), id="startup-symbol")
                yield Static(
                    brand.product_wordmark(brand.STARTUP_WORD_FRAMES[0]),
                    id="startup-word",
                )

    def _blink(self) -> None:
        """Toggle the brand caret, giving the rail a live terminal feel."""
        if self._startup_motion != "full":
            return
        self._cursor_on = not self._cursor_on
        try:
            self.query_one("#brand-symbol", Static).update(
                brand.terminal_prompt(self._cursor_on)
            )
        except Exception:
            pass

    def _start_startup_animation(self) -> None:
        """Show the product lockup once, then collapse it into the header."""
        if self._startup_motion == "off" or not self.query("#startup-splash"):
            return
        self._startup_active = True
        self._startup_frame = 0
        if self._startup_motion == "reduced":
            self.query_one("#startup-word", Static).update(
                brand.product_wordmark(brand.STARTUP_WORD_FRAMES[-1])
            )
            self.set_timer(brand.STARTUP_HOLD_SECONDS, self._finish_startup_animation)
            return
        self._startup_timer = self.set_interval(
            brand.STARTUP_FRAME_SECONDS,
            self._advance_startup_animation,
        )

    def _advance_startup_animation(self) -> None:
        """Advance one `S -> SE -> SEA -> SEAM` frame."""
        # A key press may dismiss the splash while a timer tick is already
        # queued. The callback can still arrive once after `Timer.stop()`;
        # treat it as a no-op instead of querying the now-pruned layer.
        if not self._startup_active:
            return
        words = self.query("#startup-word")
        if not words:
            # The app may be tearing down while a timer tick is queued.
            self._startup_active = False
            if self._startup_timer is not None:
                self._startup_timer.stop()
                self._startup_timer = None
            return
        self._startup_frame += 1
        if self._startup_frame < len(brand.STARTUP_WORD_FRAMES):
            word = brand.STARTUP_WORD_FRAMES[self._startup_frame]
            words.first().update(brand.product_wordmark(word))
            if self._startup_frame < len(brand.STARTUP_WORD_FRAMES) - 1:
                return
            # The final frame's own display time is exactly the hold contract;
            # do not leave the interval alive for one extra frame tick.
        if self._startup_timer is not None:
            self._startup_timer.stop()
            self._startup_timer = None
        self.set_timer(brand.STARTUP_HOLD_SECONDS, self._finish_startup_animation)

    def _finish_startup_animation(self) -> None:
        """Dismiss the launch layer; safe to call early from a key press."""
        if not self._startup_active:
            return
        self._startup_active = False
        if self._startup_timer is not None:
            self._startup_timer.stop()
            self._startup_timer = None
        splash = self.query("#startup-splash")
        if splash:
            splash.first().display = False

    def on_key(self, event: events.Key) -> None:
        """Any operator input skips the remaining launch motion."""
        if self._startup_active:
            self._finish_startup_animation()

    def on_mount(self) -> None:
        self._cursor_on = True
        if self._startup_motion == "full":
            self._cursor_timer = self.set_interval(
                brand.CURSOR_TOGGLE_SECONDS,
                self._blink,
            )
        self._start_startup_animation()
        self._write(
            "memory",
            f"[b {brand.PINK}]SEAM ready[/]  [{brand.TEXT_DIM}]"
            f"{len(self.catalog)} commands · press / for the menu · "
            f"{len(config.SETTINGS)} settings in the Settings tab[/]",
        )
        # The Memory tab is now a page (table + provenance trace + this log,
        # panels.py's `MemoryPanel`), and neither the copy-id key nor the
        # trace-on-select behaviour is otherwise visible without reading the
        # source, so say it once, dim, right under the splash.
        self._write(
            "memory",
            f"[{brand.TEXT_DIM}]tip: select a record (enter or click) to "
            f"trace it below · paste an id in the field · [b]Copy ID[/b] or "
            f"[b]y[/b] copies explicitly[/]",
        )
        self.query_one("#command-input", Input).focus()
        self._set_mode("seam")

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

    def _set_mode(self, mode: str) -> None:
        """Latch `#command-input` into `mode` and update all three places
        the mode must be visible (Part 1 of S2b): the brand-bar indicator,
        the input's placeholder, and its border colour.

        Called both for a genuine latch (bare `!`/`?`/Escape) and, harmlessly
        idempotently, to refresh the placeholder after a `cd` changes the
        shell session's `cwd` while shell mode is still latched.

        Shell mode additionally checks `shell.shell_enabled()` on every call
        (never cached), because an operator who latches into a disabled mode
        and sees nothing but the ordinary placeholder has no way to tell
        "this does nothing" from "nothing has happened yet" -- an invisible
        gate is worse than no gate. When disabled, all three surfaces say so
        and name `shell.ALLOW_SHELL_ENV`.
        """
        self.mode = mode
        field = self.query_one("#command-input", Input)
        field.remove_class("-mode-shell", "-mode-shell-disabled", "-mode-chat")
        shell_disabled = mode == "shell" and not shell.shell_enabled()
        if mode == "shell":
            # `-mode-shell` stays on regardless of the gate -- this is still
            # shell mode, just a disabled instance of it -- and
            # `-mode-shell-disabled` layers the red border on top (it is
            # declared after `-mode-shell` in theme.tcss, so it wins).
            field.add_class("-mode-shell")
            if shell_disabled:
                field.add_class("-mode-shell-disabled")
                field.placeholder = _MODE_PLACEHOLDERS["shell-disabled"].format(
                    cwd=self.shell_session.cwd
                )
            else:
                field.placeholder = _MODE_PLACEHOLDERS["shell"].format(cwd=self.shell_session.cwd)
        elif mode == "chat":
            field.add_class("-mode-chat")
            field.placeholder = _MODE_PLACEHOLDERS["chat"]
        else:
            field.placeholder = _MODE_PLACEHOLDERS["seam"]
        colour = brand.RED if shell_disabled else _MODE_COLORS.get(mode, brand.TEXT_MUTED)
        label = f"shell (disabled: {shell.ALLOW_SHELL_ENV})" if shell_disabled else mode
        self.query_one("#brand-mode", Static).update(f"[{colour}]{label}[/]")

    def _show_chat_tab(self) -> None:
        """Entering chat mode -- latched or one-shot -- always switches the
        visible tab, so a reply is never written somewhere the operator is
        not looking (Part 3 of S2b)."""
        self.query_one(TabbedContent).active = "tab-chat"

    # -- actions -----------------------------------------------------------

    def action_seam_mode(self) -> None:
        """Escape returns to seam mode and the global command bar."""
        self._set_mode("seam")
        self.query_one("#command-input", Input).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keep global mode sigils out of every editable text field.

        Printable-character bindings are needed so `!` and `?` still work
        after a table or tree has focus. They must not steal those same
        characters from Inputs (including Settings fields and `#prov-query`),
        or from the command palette's modal input.
        """
        if action == "focus_mode":
            if isinstance(self.screen, CommandPalette):
                return False
            return not isinstance(self.focused, Input)
        if action == "jump_tab_meta":
            return self.meta_digits_jump
        return super().check_action(action, parameters)

    def action_focus_mode(self, mode: str) -> None:
        """Focus the command bar and latch shell/chat from non-text widgets."""
        field = self.query_one("#command-input", Input)
        field.focus()
        field.value = ""
        if mode == "shell":
            self._latch_shell_mode()
        elif mode == "chat":
            self._enter_chat_mode()

    def action_open_palette(self) -> None:
        # Whatever the operator had already typed into `#command-input`
        # (possibly with a leading `/` still attached, possibly not, per
        # how this is reached -- see `_on_input_prefix` below) becomes the
        # palette's seed filter rather than being silently discarded
        # (S2b defect #1).
        field = self.query_one("#command-input", Input)
        leftover = field.value[1:] if field.value.startswith("/") else field.value
        field.value = ""
        self.push_screen(CommandPalette(self.catalog, initial=leftover), self._palette_result)

    def _palette_result(self, selection: str | None) -> None:
        if not selection:
            return
        if selection.startswith("mode:"):
            self._apply_mode_selection(selection.removeprefix("mode:"))
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

    def _apply_mode_selection(self, mode: str) -> None:
        """Handle a `mode:<name>` id from the palette's "Modes" group."""
        if mode not in ("seam", "shell", "chat"):
            return
        if mode == "shell":
            self._latch_shell_mode()
        elif mode == "chat":
            self._enter_chat_mode()
        else:
            self._set_mode(mode)
        self.query_one("#command-input", Input).focus()

    def _latch_shell_mode(self) -> None:
        """Latch into shell mode and, if disabled, say so once immediately.

        The placeholder and `#brand-mode` (both set inside `_set_mode`) stay
        visible for as long as the mode is latched, but an operator who just
        typed a bare `!` is looking at the input, not necessarily reading
        its placeholder text -- printing the one-line instruction into the
        active tab's log is what makes the refusal impossible to miss the
        first time, from either latch path (bare `!` or the palette's
        "Modes" group).
        """
        self._set_mode("shell")
        if not shell.shell_enabled():
            self._write(self._active_tab_id(), f"[{brand.TEXT_DIM}]{shell.DISABLED_MESSAGE}[/]")

    def _refresh_chat_client(self) -> None:
        """Re-read effective Settings before the next chat interaction."""
        from ..dashboard import SeamChatClient

        self.chat_client = SeamChatClient()

    def _enter_chat_mode(self) -> None:
        """Latch chat, show its transcript, and surface configuration state."""
        self._refresh_chat_client()
        self._set_mode("chat")
        self._show_chat_tab()
        if self._chat_intro_shown:
            return
        self._chat_intro_shown = True
        if self.chat_client.configured:
            self._write(
                "chat",
                f"[{brand.MINT}]chat ready[/]  "
                f"[{brand.TEXT_DIM}]{self.chat_client.model} · "
                f"{self.chat_client.base_url}[/]",
            )
        else:
            self._write(
                "chat",
                f"[{brand.TEXT_MUTED}]Chat is not configured. Set "
                f"SEAM_CHAT_API_KEY, SEAM_CHAT_BASE_URL, and SEAM_CHAT_MODEL "
                f"in Settings, then send a message.[/]",
            )

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
        if spec.full_signature:
            # SDK rows: the row itself shows a trimmed call form
            # (`commands.py`'s `_trimmed_call_form`); the reference card is
            # where the untrimmed signature -- types and return annotation
            # included -- actually belongs (Part 5 of S2b). Escaped: a type
            # annotation like `dict[str, object]` is indistinguishable from
            # Rich markup syntax to a `RichLog(markup=True)`, and would
            # otherwise render as "dict" with the rest silently swallowed
            # as a bogus style tag.
            signature_text = _escape_markup(f"{spec.prefix}{spec.full_signature}")
            lines.append(f"[{brand.CYAN}]signature[/]  {signature_text}")
        elif spec.positionals or spec.options:
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

    def action_jump_tab(self, index: int) -> None:
        """`alt+1`..`alt+N`: jump directly to the Nth tab."""
        if 0 <= index < len(TABS):
            self.query_one(TabbedContent).active = f"tab-{TABS[index][0]}"

    def action_jump_tab_meta(self, index: int) -> None:
        """The same jump, reached by `alt+N`'s "Alt sends Escape" spelling.

        Deliberately does nothing of its own: the point of `_META_DIGIT_KEYS`
        is that the two spellings are one shortcut. It exists only to give
        `check_action` a name it can disable independently.
        """
        self.action_jump_tab(index)

    def action_next_tab(self) -> None:
        self._cycle_tab(1)

    def action_previous_tab(self) -> None:
        self._cycle_tab(-1)

    def _cycle_tab(self, delta: int) -> None:
        tabs = self.query_one(TabbedContent)
        ids = [f"tab-{tab_id}" for tab_id, _ in TABS]
        try:
            index = ids.index(tabs.active)
        except ValueError:
            index = 0
        tabs.active = ids[(index + delta) % len(ids)]

    @on(Input.Changed, "#command-input")
    def _on_input_prefix(self, event: Input.Changed) -> None:
        """React to a fresh mode sigil without waiting for Enter.

        Exact `!` and `?` values latch and clear the command field, so the very
        next typed character is ordinary text in that mode. A whole line
        inserted atomically, such as a pasted `!pwd` or `?hello`, is left
        intact for `_on_command` to dispatch once. `/` retains its existing
        prefix/filter behavior below.

        Checks the *live* `event.input.value`, not `event.value` (the value
        this particular `Changed` message was posted with). At full typing
        speed, several keystrokes typed right after the leading `/` land in
        the widget before this handler's first `Changed` message is even
        dequeued -- `event.value` is a stale snapshot ("/"), while
        `event.input.value` already holds "/stats". Reading the live value
        and handing whatever follows the `/` to `action_open_palette` as its
        seed filter is what stops those characters from being silently
        discarded (S2b defect #1). Once `action_open_palette` clears the
        field, later-queued `Changed` messages from the same burst see a
        value that no longer starts with `/`, so this only fires once.
        """
        live_value = event.input.value
        if live_value == "!":
            event.input.value = ""
            self._latch_shell_mode()
            return
        if live_value == "?":
            event.input.value = ""
            self._enter_chat_mode()
            return
        if live_value.startswith("/"):
            self.action_open_palette()

    @on(Input.Submitted, "#command-input")
    def _on_command(self, event: Input.Submitted) -> None:
        """Dispatch on Enter: an atomically inserted `!`/`?`-prefixed line
        runs once regardless of the latched mode; typed sigils normally latch
        earlier in `_on_input_prefix`. `/` opens or dispatches through the
        command palette. Unprefixed text runs in the currently latched mode.
        """
        raw = event.value.strip()
        if not raw:
            return
        event.input.value = ""

        if raw.startswith("!"):
            rest = raw[1:].strip()
            if rest:
                self._run_shell(rest)
            else:
                self._latch_shell_mode()
            return
        if raw.startswith("?"):
            rest = raw[1:].strip()
            if rest:
                self._run_chat(rest)
            else:
                self._enter_chat_mode()
            return
        if raw.startswith("/"):
            # Normally already intercepted by `_on_input_prefix` above while the
            # `/` was still being typed; kept as a direct fallback (e.g. a
            # single-shot paste of a whole "/name arg" line).
            rest = raw[1:].strip()
            if rest:
                self._run_command(rest)
            else:
                self.action_open_palette()
            return

        if self.mode == "shell":
            self._run_shell(raw)
        elif self.mode == "chat":
            self._run_chat(raw)
        else:
            self._run_command(raw)

    def _run_command(self, command: str) -> None:
        verb, _, rest = command.partition(" ")
        if verb.lower() == "tab":
            self._run_tab_command(rest.strip())
            return

        tab_id = self._active_tab_id()
        echo = f"\n[b {brand.PINK}]{brand.PROMPT}[/] [b {brand.MAGENTA}]{verb}[/]"
        if rest:
            echo += f" [{brand.TEXT_MUTED}]{rest}[/]"
        self._write(tab_id, echo)
        self._set_status(f"[{brand.YELLOW}]working…[/]")
        self._execute(command, tab_id)

    def _run_tab_command(self, argument: str) -> None:
        """`tab <name>`, handled here rather than delegated to the backend.

        `DashboardApp`'s own `tab` verb (`dashboard.py:2421`) only accepts
        `runtime`/`benchmark` -- the previous dashboard's tab names -- so
        forwarding to `backend.execute("tab ...")` could never move this
        UI's tabs. Matching is case-insensitive and a prefix match against
        either the tab id or its label is enough (`mem` reaches Memory).
        """
        source_tab = self._active_tab_id()
        echo = f"\n[b {brand.PINK}]{brand.PROMPT}[/] [b {brand.MAGENTA}]tab[/]"
        if argument:
            echo += f" [{brand.TEXT_MUTED}]{argument}[/]"
        self._write(source_tab, echo)

        valid = ", ".join(f"{tab_id} ({label})" for tab_id, label in TABS)
        if not argument:
            self._write(source_tab, f"[{brand.RED}]usage: tab <name>[/]  [{brand.TEXT_DIM}]{valid}[/]")
            self._set_status(f"[{brand.RED}]error[/]")
            return

        needle = argument.lower()
        match = next(
            (tab_id for tab_id, label in TABS
             if tab_id.lower().startswith(needle) or label.lower().startswith(needle)),
            None,
        )
        if match is None:
            self._write(
                source_tab,
                f"[{brand.RED}]no tab matches {argument!r}[/]  [{brand.TEXT_DIM}]{valid}[/]",
            )
            self._set_status(f"[{brand.RED}]error[/]")
            return

        self.query_one(TabbedContent).active = f"tab-{match}"
        self._write(match, f"[{brand.MINT}]switched to {match}[/]")
        self._set_status(f"[{brand.MINT}]ready[/]")

    # -- shell mode (`!`) ---------------------------------------------------

    def _run_shell(self, command: str) -> None:
        command = command.strip()
        tab_id = self._active_tab_id()
        if tab_id == "settings":
            # Settings has no output log. Keep the result visible instead of
            # silently redirecting it to a tab the operator cannot see.
            tab_id = "memory"
            self.query_one(TabbedContent).active = "tab-memory"
        if not command:
            self._write(tab_id, f"[{brand.TEXT_DIM}]enter a shell command after ![/]")
            return
        echo = f"\n[b {brand.ORANGE}]!{brand.PROMPT}[/] [{brand.TEXT_MUTED}]{command}[/]"
        self._write(tab_id, echo)
        self._set_status(f"[{brand.YELLOW}]working…[/]")
        self._execute_shell(command, tab_id)

    @work(thread=True, exclusive=False)
    def _execute_shell(self, command: str, tab_id: str) -> None:
        """`ShellSession.run` never raises (`shell.py`); this is still a
        worker thread because `subprocess.run` blocks for real time, same as
        every other backend call (S2b contract #2)."""
        result = self.shell_session.run(command)
        self.call_from_thread(self._render_shell_result, tab_id, result)

    def _render_shell_result(self, tab_id: str, result: Any) -> None:
        lines = [f"cwd: {result.cwd}", f"exit_code: {result.returncode}"]
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if stdout:
            lines.extend(["", "stdout:", stdout])
        if stderr:
            lines.extend(["", "stderr:", stderr])
        if not stdout and not stderr:
            lines.extend(["", "(no output)"])
        self._write(tab_id, "\n".join(lines))
        if result.returncode == 0:
            self._set_status(f"[{brand.MINT}]ready[/]")
        else:
            self._set_status(f"[{brand.RED}]shell exit {result.returncode}[/]")
        if self.mode == "shell":
            # `cd` may have moved the session's `cwd`; refresh the
            # placeholder so it keeps telling the truth.
            self._set_mode("shell")

    # -- chat mode (`?`) -----------------------------------------------------

    def _run_chat(self, message: str) -> None:
        message = message.strip()
        if not message:
            self._write("chat", f"[{brand.TEXT_DIM}]enter a message after ?[/]")
            return
        if self._chat_busy:
            self._show_chat_tab()
            self._write(
                "chat",
                f"[{brand.YELLOW}]A chat request is already running; "
                f"wait for its reply before sending the next message.[/]",
            )
            return
        # Settings may have been saved after app construction. Rebuild the
        # small, state-free client before every request so the next message
        # sees the effective key/base/model without a restart.
        self._refresh_chat_client()
        self._show_chat_tab()
        self._write("chat", f"\n[b {brand.CYAN}]?{brand.PROMPT}[/] [{brand.TEXT_MUTED}]{message}[/]")
        self._set_status(f"[{brand.YELLOW}]working…[/]")
        self.chat_history.append({"role": "user", "content": message})
        self._chat_busy = True
        # A later Settings interaction may replace `self.chat_client`; pass
        # this request its own client and history snapshot so worker-thread
        # state cannot change underneath it.
        client = self.chat_client
        history = [dict(item) for item in self.chat_history]
        self._execute_chat(message, client, history)

    @work(thread=True, exclusive=False)
    def _execute_chat(
        self,
        message: str,
        client: Any,
        history: list[dict[str, str]],
    ) -> None:
        """Network call on a worker thread (S2b contract #2 / Part 3).

        `SeamChatClient.complete` (`dashboard.py:256`) already returns an
        explanatory string, never raises, when it is not configured -- see
        its `configured` guard -- so there is no try/except needed around
        it here for that path specifically.
        """
        context_prompt, memory_ids = self._build_chat_context_prompt(message)
        reply = client.complete(history, context_prompt)
        self.call_from_thread(self._render_chat_reply, reply, memory_ids)

    def _build_chat_context_prompt(self, message: str) -> tuple[str, list[str]]:
        """Build the context prompt the way the old UI did
        (`dashboard.py:1964`), and also return the candidate ids the `rag`
        call injected -- the reply renders those alongside the model's
        answer (Part 3 of S2b): that list is the whole reason chat earns a
        place in a memory runtime instead of being a worse terminal for a
        chat available elsewhere.
        """
        try:
            rag = self.backend.orchestrator.rag(
                message, budget=5, pack_budget=384, lens="rag", mode="context"
            ).to_dict()
            prompt_view = build_context_payload(rag, view="prompt")
            if isinstance(prompt_view, dict):
                context_prompt = json.dumps(prompt_view, indent=2)[:4000]
            else:
                context_prompt = str(prompt_view)[:4000]
            memory_ids = [str(item) for item in (rag.get("candidate_ids") or [])]
            return context_prompt, memory_ids
        except Exception as exc:
            return f"(context retrieval failed: {exc})", []

    def _render_chat_reply(self, reply: str, memory_ids: list[str]) -> None:
        self.chat_history.append({"role": "assistant", "content": reply})
        self._chat_busy = False
        self._write("chat", reply)
        if memory_ids:
            self._write("chat", f"[{brand.TEXT_DIM}]memory: {', '.join(memory_ids)}[/]")
        else:
            self._write("chat", f"[{brand.TEXT_DIM}]memory: (none injected)[/]")
        self._set_status(f"[{brand.MINT}]ready[/]")

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
