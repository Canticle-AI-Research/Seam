from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import sqlite3
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

try:
    from rich import box
    from rich.console import Console, Group
    from rich.markup import escape
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
    from rich.text import Text
    _RICH_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - user-facing guard
    box = Console = Group = Panel = Prompt = Table = Text = None  # type: ignore[assignment]

    def escape(value):  # type: ignore[misc]
        return value

    _RICH_IMPORT_ERROR = exc

try:
    from textual import on
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, ScrollableContainer, Vertical
    from textual.widgets import Button, Input, Label, Log, RichLog, Static, TabbedContent, TabPane, Tree

    _TEXTUAL_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - optional dashboard path
    on = App = ComposeResult = Horizontal = Vertical = Input = Log = RichLog = Static = None  # type: ignore[assignment]
    TabbedContent = TabPane = Tree = Button = Label = None  # type: ignore[assignment]
    ScrollableContainer = None  # type: ignore[assignment]
    _TEXTUAL_IMPORT_ERROR = exc

from . import config
from .context_views import CONTEXT_VIEWS, build_context_payload
from .installer import default_runtime_db_path
from .lossless import (
    LOSSLESS_CODECS,
    LOSSLESS_TRANSFORMS,
    READABLE_GRANULARITIES,
    TOKENIZER_CHOICES,
    benchmark_text_lossless,
    compress_text_lossless,
    compress_text_readable,
    decompress_text_lossless,
    decompress_text_readable,
    query_readable_compressed,
)
from .mirl import IRBatch
from .models import HashEmbeddingModel
from .runtime import SeamRuntime
from .ui import animations as _ui_animations
from .ui import bars as _ui_bars
from .ui import logo as _ui_logo


def _build_retrieval_orchestrator(
    runtime: SeamRuntime,
    *,
    vector_backend: str,
    vector_path: str,
    vector_collection: str,
) -> Any:
    from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator

    return RetrievalOrchestrator(
        runtime,
        semantic_backend=vector_backend,
        chroma_path=vector_path,
        chroma_collection=vector_collection,
    )


def _write_private_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    if os.name != "nt":
        path.chmod(0o600)


DEFAULT_CHAT_MODELS = [
    # OpenAI defaults for the stock https://api.openai.com/v1 endpoint.
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o4-mini",
    # Strong OpenRouter-compatible coding and agent models.
    "openrouter/pareto-code",
    "qwen/qwen3-coder",
    "qwen/qwen3-coder-next",
    "qwen/qwen3-coder-plus",
    "qwen/qwen3.6-plus",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v3.2",
    "xiaomi/mimo-v2.5-pro",
    "xiaomi/mimo-v2.5",
    "moonshotai/kimi-k2.6",
    "z-ai/glm-5.1",
    "x-ai/grok-4.20",
    "x-ai/grok-4.20-multi-agent",
    "x-ai/grok-4.1-fast",
    "x-ai/grok-code-fast-1",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.7",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3.1-flash-lite-preview",
    "google/gemma-4-31b-it",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-26b-a4b-it:free",
]


# Tokens that look like shell control operators. The dashboard shell executes
# commands with shell=False (see _run_shell_subprocess), so these can never
# chain, redirect, or substitute regardless — but we reject the spaced forms up
# front to give the operator a clear error instead of a confusing literal-arg
# run. The security boundary is shell=False, not this list.
_SHELL_OPERATOR_TOKENS: frozenset[str] = frozenset({
    "&&", "||", ";", "|", "&", "|&",
    ">", ">>", "<", "<<", "<<<", "2>", "2>>", "&>",
    "`", "$(",
})

ALLOWED_SHELL_COMMANDS: frozenset[str] = frozenset({
    "ls", "cat", "grep", "find", "pwd", "date", "whoami", "echo",
    "head", "tail", "wc", "sort", "uniq", "cut", "awk", "sed",
    "git", "diff", "tree", "stat", "file", "which", "env", "printenv",
    "tr", "tee", "less", "more", "basename", "dirname", "realpath",
    "true", "false", "test", "sleep",
})

BLOCKED_SHELL_COMMANDS: frozenset[str] = frozenset({
    "rm", "sudo", "su", "chmod", "chown", "kill", "pkill",
    "dd", "mkfs", "mount", "umount", "shutdown", "reboot", "init",
    "fdisk", "parted", "wipefs", "passwd", "useradd", "userdel",
    "iptables", "nft", "ifconfig", "ip",
})


def _validate_shell_command(command: str) -> list[str]:
    """Parse, validate, and return the argv to run shell-free.

    The returned list is executed directly with ``shell=False`` so no operator
    chaining, redirection, or command substitution is ever interpreted. We also
    reject spaced shell-operator tokens here for a clear up-front error.
    """
    if not command or not command.strip():
        raise PermissionError("Empty shell command")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise PermissionError(f"Cannot parse shell command: {exc}") from exc
    if not argv:
        raise PermissionError("Empty shell command")
    for token in argv:
        if token in _SHELL_OPERATOR_TOKENS:
            raise PermissionError(f"Shell operator {token!r} is not allowed")
    # Reject a path in argv[0] (e.g. /custom/path/git): validating only the
    # basename would let an absolute/relative path whose final component matches
    # an allowed name through, running an arbitrary binary. Require a bare command
    # name resolved against PATH. Slashes in later args (e.g. `ls /tmp`) are fine.
    if "/" in argv[0] or "\\" in argv[0]:
        raise PermissionError(
            f"Command {argv[0]!r} must be a bare command name resolved on PATH, not a path"
        )
    cmd_name = argv[0]
    family_root = cmd_name.split(".", 1)[0]
    if cmd_name in BLOCKED_SHELL_COMMANDS or family_root in BLOCKED_SHELL_COMMANDS:
        raise PermissionError(f"Command {cmd_name!r} is in blocked set")
    if cmd_name not in ALLOWED_SHELL_COMMANDS:
        raise PermissionError(f"Command {cmd_name!r} is not in the allowed set")
    return argv


def _validate_shell_cwd(cwd: Path, project_root: Path | None = None) -> Path:
    resolved = Path(cwd).resolve()
    allowed_roots: list[Path] = [Path("/tmp").resolve()]
    if project_root is not None:
        allowed_roots.append(Path(project_root).resolve())
    for root in allowed_roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise PermissionError(f"Working directory {resolved} is outside allowed roots")


def _get_shell_timeout() -> float:
    raw = os.environ.get("SEAM_SHELL_TIMEOUT_SECONDS")
    if raw is None:
        return 10.0
    try:
        return float(raw)
    except ValueError:
        return 10.0


@dataclass
class DashboardMetrics:
    db_path: str
    db_size: str
    total_records: int
    vector_entries: int
    pack_entries: int
    provenance_entries: int
    symbol_entries: int
    raw_entries: int
    namespaces: int
    scopes: int
    top_kinds: list[tuple[str, int]]
    model_name: str
    execution_mode: str
    vector_adapter_name: str
    pgvector_configured: bool
    vector_store_size: str


@dataclass
class DashboardEvent:
    timestamp: str
    kind: str
    message: str


@dataclass(frozen=True)
class CommandPaletteItem:
    trigger: str
    command: str
    insert_text: str
    description: str


class DashboardParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - exercised through controller
        raise ValueError(message)


class SeamChatClient:
    def __init__(self) -> None:
        # Read effective configuration rather than only the process snapshot.
        # The Textual Settings panel persists edits immediately; consulting
        # `config.effective_value` lets a newly saved key/base/model take
        # effect when the TUI rebuilds this client before its next request,
        # while explicit process environment values retain precedence.
        self.base_url = (
            config.effective_value("SEAM_CHAT_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = config.effective_value("SEAM_CHAT_MODEL") or "gpt-4o-mini"
        self.api_key = (
            config.effective_value("SEAM_CHAT_API_KEY")
            or config.effective_value("OPENAI_API_KEY")
        )
        configured_models = [
            item.strip()
            for item in config.effective_value("SEAM_CHAT_MODELS").split(",")
            if item.strip()
        ]
        self.available_models = configured_models or list(DEFAULT_CHAT_MODELS)
        if self.model not in self.available_models:
            self.available_models.insert(0, self.model)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, messages: list[dict[str, str]], context_prompt: str) -> str:
        if not self.configured:
            return (
                "Chat model is not configured.\n"
                "Set SEAM_CHAT_API_KEY (or OPENAI_API_KEY) and optionally SEAM_CHAT_MODEL / SEAM_CHAT_BASE_URL."
            )
        try:
            import httpx

            payload_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the SEAM dashboard assistant. Keep answers concise, actionable, and grounded in runtime state.\n\n"
                        f"Runtime context:\n{context_prompt}"
                    ),
                },
                *messages[-8:],
            ]
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.2,
                    "messages": payload_messages,
                },
                timeout=45.0,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return "No response choices were returned by the chat model."
            content = choices[0].get("message", {}).get("content", "")
            return str(content).strip() or "(empty model response)"
        except Exception as exc:
            return f"Chat request failed: {exc}"


if (
    App is not None
    and Static is not None
    and Input is not None
    and Log is not None
    and RichLog is not None
    and Button is not None
    and Label is not None
    and ScrollableContainer is not None
):
    class _TextualPanel(Log):
        can_focus = True
        BINDINGS = [
            ("up", "scroll_up", "Up"),
            ("down", "scroll_down", "Down"),
            ("left", "scroll_left", "Left"),
            ("right", "scroll_right", "Right"),
            ("pageup", "page_up", "Page Up"),
            ("pagedown", "page_down", "Page Down"),
            ("home", "scroll_home", "Top"),
            ("end", "scroll_end", "Bottom"),
            ("k", "scroll_up", "Up"),
            ("j", "scroll_down", "Down"),
            ("escape", "focus_input", "Back to input"),
        ]

        def __init__(self, title: str, panel_id: str, *, auto_scroll_mode: bool = False) -> None:
            super().__init__(highlight=False, max_lines=2000, auto_scroll=False, id=panel_id)
            self._title = title
            self._panel_lines: list[str] = []
            self._auto_scroll_mode = auto_scroll_mode

        def on_mount(self) -> None:  # pragma: no cover - textual runtime behavior
            self.border_title = self._title
            self.border_subtitle = "Tab/S+Tab · Esc→input"
            self._refresh_content()

        def set_title(self, title: str) -> None:
            self._title = title
            self.border_title = title

        def set_lines(self, lines: list[str]) -> None:
            self._panel_lines = lines[-2000:]
            self.clear()
            if self._panel_lines:
                self.write_lines(self._panel_lines)
            else:
                self.write_line("(empty)")
            if self._auto_scroll_mode:
                self.scroll_end(animate=False, force=True, immediate=True, x_axis=False, y_axis=True)

        def _refresh_content(self) -> None:
            self.clear()
            if self._panel_lines:
                self.write_lines(self._panel_lines)
            else:
                self.write_line("(empty)")
            if self._auto_scroll_mode:
                self.scroll_end(animate=False, force=True, immediate=True, x_axis=False, y_axis=True)

        def on_mouse_down(self, event: Any) -> None:  # pragma: no cover - textual runtime behavior
            self.focus()

        def action_page_up(self) -> None:
            self.scroll_page_up(animate=False, force=True)

        def action_page_down(self) -> None:
            self.scroll_page_down(animate=False, force=True)

        def action_focus_input(self) -> None:  # pragma: no cover - textual runtime behavior
            self.app.query_one("#command-input", Input).focus()


    class _TextualMarkupPanel(RichLog):
        """Markup-rendering scrollable panel for dashboard-authored lines."""

        can_focus = True
        BINDINGS = _TextualPanel.BINDINGS

        def __init__(self, title: str, panel_id: str, *, auto_scroll_mode: bool = False) -> None:
            super().__init__(highlight=False, markup=True, max_lines=2000, auto_scroll=False, id=panel_id)
            self._title = title
            self._panel_lines: list[str] = []
            self._auto_scroll_mode = auto_scroll_mode

        def on_mount(self) -> None:  # pragma: no cover - textual runtime behavior
            self.border_title = self._title
            self.border_subtitle = "Tab/S+Tab · Esc→input"
            self._refresh_content()

        def set_title(self, title: str) -> None:
            self._title = title
            self.border_title = title

        def set_lines(self, lines: list[str]) -> None:
            self._panel_lines = lines[-2000:]
            self._refresh_content()

        def _refresh_content(self) -> None:
            self.clear()
            if self._panel_lines:
                for line in self._panel_lines:
                    self.write(line)
            else:
                self.write("(empty)")
            if self._auto_scroll_mode:
                self.scroll_end(animate=False, force=True, immediate=True, x_axis=False, y_axis=True)

        def on_mouse_down(self, event: Any) -> None:  # pragma: no cover - textual runtime behavior
            self.focus()

        def action_page_up(self) -> None:
            self.scroll_page_up(animate=False, force=True)

        def action_page_down(self) -> None:
            self.scroll_page_down(animate=False, force=True)

        def action_focus_input(self) -> None:  # pragma: no cover - textual runtime behavior
            self.app.query_one("#command-input", Input).focus()


    class ExplorerTree(Tree):
        """Interactive explorer sidebar showing ns → scope → kind hierarchy."""

        BINDINGS = [
            ("r", "refresh_tree", "Refresh"),
            ("escape", "focus_input", "Back to input"),
        ]

        def __init__(self, store_path: str) -> None:
            super().__init__("seam://", id="explorer-tree")
            self._store_path = store_path

        def on_mount(self) -> None:  # pragma: no cover - textual runtime behavior
            self.border_title = "Explorer"
            self.border_subtitle = "r=refresh  Enter=open"
            self.root.expand()
            self._populate()

        def _populate(self) -> None:
            self.clear()
            self.root.expand()
            try:
                with sqlite3.connect(self._store_path) as conn:
                    ns_rows = conn.execute(
                        "SELECT ns, COUNT(*) FROM ir_records GROUP BY ns ORDER BY ns"
                    ).fetchall()
                    if not ns_rows:
                        self.root.add_leaf("(no records yet)")
                        return
                    for ns, ns_count in ns_rows:
                        ns_node = self.root.add(
                            f"\U0001f4c2 {ns}  [{ns_count}]",
                            data={"type": "ns", "ns": ns},
                        )
                        scope_rows = conn.execute(
                            "SELECT scope, COUNT(*) FROM ir_records WHERE ns=? GROUP BY scope ORDER BY scope",
                            (ns,),
                        ).fetchall()
                        for scope, scope_count in scope_rows:
                            scope_node = ns_node.add(
                                f"\U0001f4c4 {scope}  [{scope_count}]",
                                data={"type": "scope", "ns": ns, "scope": scope},
                            )
                            kind_rows = conn.execute(
                                "SELECT kind, COUNT(*) FROM ir_records WHERE ns=? AND scope=? GROUP BY kind ORDER BY COUNT(*) DESC",
                                (ns, scope),
                            ).fetchall()
                            for kind, count in kind_rows:
                                scope_node.add_leaf(
                                    f"  {kind:<6} {count}",
                                    data={"type": "kind", "ns": ns, "scope": scope, "kind": kind},
                                )
            except Exception as exc:
                self.root.add_leaf(f"(error: {exc})")

        def action_refresh_tree(self) -> None:  # pragma: no cover - textual runtime behavior
            self._populate()

        def action_focus_input(self) -> None:  # pragma: no cover - textual runtime behavior
            self.app.query_one("#command-input", Input).focus()


    class TextualDashboardApp(App[None]):
        """Deprecated: superseded by `seam_runtime.tui` in HISTORY#537.

        No entry point reaches this class any more -- `seam dashboard`,
        `seam-dash`, and `seam-tui` all route through `run_dashboard`, which
        launches `seam_runtime.tui.app.SeamTUI` against the `DashboardApp`
        backend below. It is kept, not deleted, because its 28 test usages in
        `test_seam_all/test_seam.py` are the only coverage of several
        dashboard behaviours; deleting the class without porting them would
        trade a working UI for a coverage hole. Remove it once the new TUI has
        real operating time and those tests have been ported or retired.

        Do not add features here. `seam_runtime/tui/` is the live UI.
        """

        CSS = """
        Screen {
            layout: vertical;
            layers: base overlay;
        }

        /* ── Header band ─────────────────────────────────────────── */
        #logo-header {
            height: 6;
            border: round #4f8cfb;
            padding: 0 1;
            color: #8df6ff;
            background: #050b1e;
            text-style: bold;
        }
        #metrics {
            height: 3;
            border: round $primary;
            padding: 0 1;
        }

        /* ── IDE body: explorer | tabs | chat+results ────────────── */
        #ide-layout {
            height: 1fr;
        }

        /* Explorer sidebar */
        #explorer-tree {
            width: 30;
            border: round #4f8cfb;
            background: #050b1e;
        }
        #explorer-tree:focus {
            border: heavy #7efbff;
        }

        /* Centre: TabbedContent fills remaining width */
        #main-tabs {
            width: 1fr;
            height: 1fr;
        }
        TabPane {
            padding: 0;
            height: 1fr;
        }

        /* Tab content panels fill their pane */
        #memory-panel, #retrieval-panel, #benchmark-panel,
        #mirl-panel, #prov-panel, #chat-panel {
            width: 1fr;
            height: 1fr;
            border: round $primary;
            padding: 0 1;
            overflow-y: auto;
            overflow-x: auto;
        }

        /* Live tab: runtime, command history, and results side-by-side */
        #live-row {
            height: 1fr;
        }
        #runtime-log-panel, #command-history-panel, #result-panel {
            width: 1fr;
            height: 1fr;
            border: round $primary;
            padding: 0 1;
            overflow-y: auto;
            overflow-x: auto;
        }

        /* Right column: always-visible overview */
        #right-col {
            width: 34;
        }
        #overview-panel {
            width: 1fr;
            height: 1fr;
            border: round $primary;
            padding: 0 1;
            overflow-y: auto;
            overflow-x: auto;
        }

        /* Focused: highlight any panel */
        #memory-panel:focus, #retrieval-panel:focus, #benchmark-panel:focus,
        #overview-panel:focus, #mirl-panel:focus, #prov-panel:focus,
        #runtime-log-panel:focus, #command-history-panel:focus,
        #chat-panel:focus, #result-panel:focus, #explorer-tree:focus {
            border: heavy #7efbff;
        }
        .zoomed {
            layer: overlay;
            width: 100%;
            height: 100%;
            dock: top;
            border: heavy #7efbff;
            background: #050b1e;
        }

        /* ── Command palette overlay ──────────────────────────────── */
        #command-palette {
            height: 12;
            border: round #7efbff;
            padding: 0 1;
            margin: 0 1;
            color: #d8f7ff;
            background: #050b1e;
            display: none;
        }

        /* ── Settings tab ─────────────────────────────────────────── */
        #settings-scroll {
            width: 1fr;
            height: 1fr;
        }
        #settings-panel {
            height: auto;
            padding: 1 2;
        }
        .settings-section {
            color: #7fe0ff;
            text-style: bold;
            margin-top: 1;
        }
        .settings-label {
            color: #5fc8ff;
            margin-top: 1;
        }
        .settings-input {
            border: round #4f8cfb;
            background: #08132a;
            margin-bottom: 0;
        }
        .settings-input:focus {
            border: round #7fe0ff;
        }
        .settings-btn {
            background: #1a2540;
            border: round #4f8cfb;
            color: #7fe0ff;
            margin-top: 1;
            width: auto;
        }
        .settings-btn:hover {
            background: #274063;
            border: round #7fe0ff;
        }
        .settings-btn-danger {
            border: round #9b6cff;
            color: #d391ff;
        }
        .settings-row {
            height: auto;
        }
        .settings-fill {
            width: 1fr;
        }
        .settings-use {
            width: 7;
            min-width: 7;
            margin-left: 1;
        }

        /* ── Status bar above input ──────────────────────────────── */
        #status-bar {
            dock: bottom;
            height: 1;
            background: #1a2a4a;
            color: #8df6ff;
            padding: 0 1;
        }

        /* ── Input bar docked to bottom ──────────────────────────── */
        #command-input {
            dock: bottom;
            border: round $primary;
        }
        """

        BINDINGS = [
            ("ctrl+c", "quit", "Quit"),
            ("ctrl+d", "quit", "Quit"),
            ("ctrl+b", "toggle_sidebar", "Toggle Explorer"),
            ("ctrl+m", "toggle_zoom", "Zoom focused panel"),
            ("[", "sidebar_shrink", "Shrink Explorer"),
            ("]", "sidebar_grow", "Grow Explorer"),
            ("{", "rightcol_shrink", "Shrink Overview"),
            ("}", "rightcol_grow", "Grow Overview"),
        ]

        def __init__(
            self,
            runtime: SeamRuntime,
            vector_backend: str = "seam",
            vector_path: str = ".seam_chroma",
            vector_collection: str = "seam_hybrid",
        ) -> None:
            super().__init__()
            self.controller = DashboardApp(
                runtime,
                vector_backend=vector_backend,
                vector_path=vector_path,
                vector_collection=vector_collection,
                no_clear=True,
            )
            self.memory_lines: list[str] = []
            self.retrieval_lines: list[str] = []
            self.benchmark_lines: list[str] = []
            self.result_lines: list[str] = []
            self.side_lines: list[str] = []
            self.chat_lines: list[str] = []
            self.chat_history: list[dict[str, str]] = []
            self.command_history_lines: list[str] = []
            self.mirl_lines: list[str] = []
            self.chat_client = SeamChatClient()
            self.transcript_dir = Path(os.environ.get("SEAM_CHAT_TRANSCRIPT_DIR", ".seam/chat_transcripts"))
            self.input_mode = "hybrid"
            self.shell_cwd = Path.cwd()
            self.command_names = {
                "help",
                "quit",
                "exit",
                "tab",
                "compile",
                "compile-nl",
                "compile-dsl",
                "dsl",
                "search",
                "plan",
                "retrieve",
                "context",
                "index",
                "trace",
                "benchmark",
                "compress-doc",
                "lossless-compress",
                "readable-compress",
                "compress-readable",
                "readable-query",
                "query-compressed",
                "readable-rebuild",
                "decompress-doc",
                "lossless-decompress",
                "decompress-last",
                "stats",
                "reload",
                "refresh",
            }
            self._palette_items = self._build_command_palette_items()
            self._palette_matches: list[CommandPaletteItem] = []
            self._palette_index = 0
            self._palette_trigger = ""
            self._palette_query = ""
            self._animation_phase = 0
            self._anim_until = 0.0
            self._anim_label = "idle"
            self._anim_preview = ""
            self._token_source_total = 0
            self._token_machine_total = 0
            self._token_events: deque[tuple[float, int]] = deque(maxlen=32)
            # New ui/ animation engine — drives the MIRL panel with a
            # streaming IR view + RAW→IR→PACK pipeline visual on
            # compile/compress/benchmark triggers.
            self._anim_engine = _ui_animations.AnimationEngine(height=6)
            self._mirl_animation_running = False
            self._sidebar_width = 30
            self._rightcol_width = 34
            self._overview_phase = 0
            self._pgvector_status = "unknown"
            self._pgvector_status_detail = "Press Settings > Status"
            self._pgvector_status_checked = "never"

        def compose(self) -> ComposeResult:
            # ── Header: logo + slim metrics bar (always visible) ──────
            yield Static("", id="logo-header")
            yield Static("", id="metrics")
            # ── IDE body ──────────────────────────────────────────────
            with Horizontal(id="ide-layout"):
                # Left: interactive explorer sidebar
                yield ExplorerTree(self.controller.runtime.store.path)
                # Centre: tabbed workspace
                with TabbedContent(id="main-tabs"):
                    with TabPane("Memory", id="tab-memory"):
                        yield _TextualPanel("Memory Records", "memory-panel")
                    with TabPane("Retrieval", id="tab-retrieval"):
                        yield _TextualPanel("Search / Retrieval", "retrieval-panel")
                    with TabPane("Benchmarks", id="tab-benchmarks"):
                        yield _TextualPanel("Benchmark", "benchmark-panel")
                    with TabPane("Compression", id="tab-compression"):
                        yield _TextualMarkupPanel("MIRL Compression", "mirl-panel")
                    with TabPane("Chat", id="tab-chat"):
                        yield _TextualPanel("Chat", "chat-panel", auto_scroll_mode=True)
                    with TabPane("Live", id="tab-live"):
                        with Horizontal(id="live-row"):
                            yield _TextualMarkupPanel("Runtime Log", "runtime-log-panel", auto_scroll_mode=True)
                            yield _TextualPanel("Command History", "command-history-panel", auto_scroll_mode=True)
                            yield _TextualPanel("Results", "result-panel", auto_scroll_mode=True)
                    with TabPane("Provenance", id="tab-prov"):
                        yield _TextualPanel("Provenance Graph", "prov-panel")
                    with TabPane("Settings", id="tab-settings"):
                        with ScrollableContainer(id="settings-scroll"):
                            with Vertical(id="settings-panel"):
                                yield Static("Provider Keys", classes="settings-section")
                                yield Label("OpenAI  (OPENAI_API_KEY)", classes="settings-label")
                                with Horizontal(classes="settings-row"):
                                    yield Input(value=os.environ.get("OPENAI_API_KEY", ""), placeholder="sk-...", password=True, id="cfg-key-openai", classes="settings-input settings-fill")
                                    yield Button("Use", id="btn-use-openai", classes="settings-btn settings-use")
                                yield Label("OpenRouter  (OPENROUTER_API_KEY)", classes="settings-label")
                                with Horizontal(classes="settings-row"):
                                    yield Input(value=os.environ.get("OPENROUTER_API_KEY", ""), placeholder="sk-or-...", password=True, id="cfg-key-openrouter", classes="settings-input settings-fill")
                                    yield Button("Use", id="btn-use-openrouter", classes="settings-btn settings-use")
                                yield Label("Anthropic  (ANTHROPIC_API_KEY)", classes="settings-label")
                                with Horizontal(classes="settings-row"):
                                    yield Input(value=os.environ.get("ANTHROPIC_API_KEY", ""), placeholder="sk-ant-...", password=True, id="cfg-key-anthropic", classes="settings-input settings-fill")
                                    yield Button("Use", id="btn-use-anthropic", classes="settings-btn settings-use")
                                yield Label("Gemini  (GEMINI_API_KEY)", classes="settings-label")
                                with Horizontal(classes="settings-row"):
                                    yield Input(value=os.environ.get("GEMINI_API_KEY", ""), placeholder="AIza...", password=True, id="cfg-key-gemini", classes="settings-input settings-fill")
                                    yield Button("Use", id="btn-use-gemini", classes="settings-btn settings-use")
                                yield Button("Apply Provider Keys", id="btn-apply-provider-keys", classes="settings-btn")
                                yield Static("── Chat / AI ──────────────────────────────", classes="settings-section")
                                yield Label("Chat API Key  (SEAM_CHAT_API_KEY / OPENAI_API_KEY)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_CHAT_API_KEY", ""), placeholder="sk-…  or  or-…", password=True, id="cfg-api-key", classes="settings-input")
                                yield Label("Base URL  (SEAM_CHAT_BASE_URL)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_CHAT_BASE_URL", "https://api.openai.com/v1"), placeholder="https://api.openai.com/v1", id="cfg-base-url", classes="settings-input")
                                yield Label("Model  (SEAM_CHAT_MODEL)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_CHAT_MODEL", "gpt-4o-mini"), placeholder="gpt-4o-mini", id="cfg-model", classes="settings-input")
                                yield Label("Model List  (SEAM_CHAT_MODELS, comma-separated)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_CHAT_MODELS", ""), placeholder="gpt-4o-mini,qwen/qwen3-coder,deepseek/deepseek-v3.2", id="cfg-chat-models", classes="settings-input")
                                yield Label("Transcript Dir  (SEAM_CHAT_TRANSCRIPT_DIR)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_CHAT_TRANSCRIPT_DIR", ""), placeholder=".seam/chat_transcripts", id="cfg-transcript-dir", classes="settings-input")
                                yield Button("Apply API Settings", id="btn-apply-api", classes="settings-btn")
                                yield Static("Embedding", classes="settings-section")
                                yield Label("Provider  (SEAM_EMBEDDING_PROVIDER)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_EMBEDDING_PROVIDER", "hash"), placeholder="hash or openai", id="cfg-embed-provider", classes="settings-input")
                                yield Label("Model  (SEAM_EMBEDDING_MODEL)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_EMBEDDING_MODEL", "text-embedding-3-small"), placeholder="text-embedding-3-small", id="cfg-embed-model", classes="settings-input")
                                yield Label("API key env var  (SEAM_EMBEDDING_API_KEY_ENV)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_EMBEDDING_API_KEY_ENV", "OPENAI_API_KEY"), placeholder="OPENAI_API_KEY", id="cfg-embed-key-env", classes="settings-input")
                                yield Label("Dimensions  (SEAM_EMBEDDING_DIMENSIONS)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_EMBEDDING_DIMENSIONS", ""), placeholder="leave blank for model default", id="cfg-embed-dims", classes="settings-input")
                                yield Button("Apply Embedding Settings", id="btn-apply-embed", classes="settings-btn")
                                yield Static("Holographic Surface", classes="settings-section")
                                yield Label("Default PNG mode  (SEAM_SURFACE_MODE)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_SURFACE_MODE", "rgb24"), placeholder="rgb24, bw1, rgba32, or rgba64", id="cfg-surface-mode", classes="settings-input")
                                yield Button("Apply Surface Settings", id="btn-apply-surface", classes="settings-btn")
                                yield Static("── Database ────────────────────────────────", classes="settings-section")
                                yield Label("DB Path  (SEAM_DB_PATH)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_DB_PATH", ""), placeholder="(default: ~/.seam/seam.db)", id="cfg-db-path", classes="settings-input")
                                yield Static("── pgvector ────────────────────────────────", classes="settings-section")
                                yield Label("pgvector DSN  (SEAM_PGVECTOR_DSN)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_PGVECTOR_DSN", ""), placeholder="Set SEAM_PGVECTOR_DSN in local env", password=True, id="cfg-pgvector-dsn", classes="settings-input")
                                yield Button("Apply DB / pgvector Settings", id="btn-apply-db", classes="settings-btn")
                                yield Static("pgvector / Docker", classes="settings-section")
                                yield Label("Compose env file  (SEAM_LOCAL_ENV)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_LOCAL_ENV", ""), placeholder="optional path to ignored local .env", id="cfg-compose-env", classes="settings-input")
                                with Horizontal(classes="settings-row"):
                                    yield Button("Start pgvector", id="btn-pg-start", classes="settings-btn")
                                    yield Button("Stop pgvector", id="btn-pg-stop", classes="settings-btn settings-btn-danger")
                                    yield Button("Status", id="btn-pg-status", classes="settings-btn")
                                yield Static("REST API", classes="settings-section")
                                yield Label("Bearer token  (SEAM_API_TOKEN)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_API_TOKEN", ""), placeholder="optional local token", password=True, id="cfg-api-token", classes="settings-input")
                                yield Label("Rate limit/min  (SEAM_API_RATE_LIMIT_PER_MINUTE)", classes="settings-label")
                                yield Input(value=os.environ.get("SEAM_API_RATE_LIMIT_PER_MINUTE", ""), placeholder="60", id="cfg-rate-limit-min", classes="settings-input")
                                yield Button("Apply REST Settings", id="btn-apply-rest", classes="settings-btn")
                                yield Static("── Config Files ────────────────────────────", classes="settings-section")
                                yield Button("Open .env in explorer", id="btn-open-env", classes="settings-btn")
                                yield Button("Open seam config dir", id="btn-open-config-dir", classes="settings-btn")
                                yield Button("Save local env", id="btn-save-env", classes="settings-btn")
                                yield Button("Reload env from disk", id="btn-reload-env", classes="settings-btn settings-btn-danger")
                # Right: overview stays visible while the operator works in tabs.
                with Vertical(id="right-col"):
                    yield _TextualMarkupPanel("Overview", "overview-panel")
            # ── Overlay: command palette + input bar ──────────────────
            yield Static("", id="command-palette")
            yield Static("", id="status-bar")
            yield Input(placeholder="", id="command-input")

        def on_mount(self) -> None:  # pragma: no cover - textual runtime behavior
            self._refresh_logo()
            self._refresh_metrics()
            self._refresh_input_placeholder()
            self._sync_side_panel()
            self._refresh_overview()
            self.query_one("#benchmark-panel", _TextualPanel).set_lines(["Run `benchmark <file>` to populate benchmark results."])
            self.query_one("#retrieval-panel", _TextualPanel).set_lines(["Run search/retrieve/context/plan to populate this panel."])
            self.query_one("#memory-panel", _TextualPanel).set_lines(["Run compile, stats, or trace to populate this panel."])
            self.query_one("#chat-panel", _TextualPanel).set_lines(
                [
                    "Harness ready — SEAM IDE dashboard.",
                    "",
                    "  /compile <text>    compile NL into MIRL records",
                    "  /search  <query>   lexical + vector search",
                    "  /retrieve <query>  ranked retrieval",
                    "  /benchmark <file>  lossless compression benchmark",
                    "  /stats             refresh runtime metrics",
                    "  /help              full command reference",
                    "",
                    "Prefixes:  /command   !shell-cmd   ?mode-switch   ??chat",
                    "Type / to open the command palette.",
                ]
            )
            self.query_one("#command-history-panel", _TextualPanel).set_lines(["No commands yet."])
            self.query_one("#mirl-panel", _TextualMarkupPanel).set_lines(
                [
                    "SEAM-LX/1 Compression Engine",
                    "",
                    "Idle — run compile/compress/benchmark to trigger the",
                    "live RAW → IR → PACK → LX/1 animation.",
                ]
            )
            self.query_one("#prov-panel", _TextualPanel).set_lines(
                [
                    "Provenance Graph  [placeholder]",
                    "",
                    "Coming soon: interactive DAG of memory records, their",
                    "evidence spans, and pack/retrieval lineage.",
                    "",
                    "Use  trace <record-id>  to inspect a single record now.",
                ]
            )
            self._push_result("Welcome", self.controller.result_body)
            self.set_interval(0.25, self._tick_mirl_animation)
            self.set_interval(1.0, self._tick_metrics)

        @on(Input.Submitted, "#command-input")
        def _on_command_submitted(self, event: Input.Submitted) -> None:  # pragma: no cover - textual runtime behavior
            command = event.value.strip()
            if self._palette_matches and command in {"/", "!", "?"}:
                self._accept_palette_selection(event.input, submit=False)
                return
            event.input.value = ""
            self._hide_command_palette()
            if not command:
                return
            self.process_command(command)

        @on(Input.Changed, "#command-input")
        def _on_command_input_changed(self, event: Input.Changed) -> None:  # pragma: no cover - textual runtime behavior
            self._update_command_palette(event.value)

        def on_key(self, event: Any) -> None:  # pragma: no cover - textual runtime behavior
            if self.focused is not self.query_one("#command-input", Input):
                return
            if not self._palette_matches:
                return
            if event.key == "escape":
                self._hide_command_palette()
                event.prevent_default()
                event.stop()
                return
            if event.key in {"down", "ctrl+n"}:
                self._move_palette_selection(1)
                event.prevent_default()
                event.stop()
                return
            if event.key in {"up", "ctrl+p"}:
                self._move_palette_selection(-1)
                event.prevent_default()
                event.stop()
                return
            if event.key == "tab":
                input_widget = self.query_one("#command-input", Input)
                self._accept_palette_selection(input_widget, submit=False)
                event.prevent_default()
                event.stop()
                return
            if event.key == "enter":
                input_widget = self.query_one("#command-input", Input)
                self._accept_palette_selection(input_widget, submit=True)
                event.prevent_default()
                event.stop()

        def _build_command_palette_items(self) -> list[CommandPaletteItem]:
            return [
                CommandPaletteItem("/", "compile", "/compile ", "compile natural language into MIRL"),
                CommandPaletteItem("/", "compile-dsl", "/compile-dsl ", "compile a SEAM DSL file"),
                CommandPaletteItem("/", "retrieve", "/retrieve ", "rank memory results for a query"),
                CommandPaletteItem("/", "context", "/context ", "build generation context from memory"),
                CommandPaletteItem("/", "search", "/search ", "combined lexical/vector search"),
                CommandPaletteItem("/", "plan", "/plan ", "show retrieval plan before execution"),
                CommandPaletteItem("/", "index", "/index ", "sync persisted records into vector indexes"),
                CommandPaletteItem("/", "trace", "/trace ", "trace one MIRL record id"),
                CommandPaletteItem("/", "stats", "/stats", "refresh runtime metrics"),
                CommandPaletteItem("/", "reload", "/reload", "reload dashboard panels and charts"),
                CommandPaletteItem("/", "refresh", "/refresh", "alias for dashboard reload"),
                CommandPaletteItem("/", "benchmark", "/benchmark ", "run lossless/retrieval benchmark"),
                CommandPaletteItem("/", "compress-doc", "/compress-doc ", "compress a source document"),
                CommandPaletteItem("/", "readable-compress", "/readable-compress ", "build readable SEAM-RC/1 language"),
                CommandPaletteItem("/", "readable-query", "/readable-query ", "query SEAM-RC/1 without rebuilding source"),
                CommandPaletteItem("/", "readable-rebuild", "/readable-rebuild ", "verify and rebuild SEAM-RC/1 text"),
                CommandPaletteItem("/", "decompress-doc", "/decompress-doc ", "decompress a source artifact"),
                CommandPaletteItem("/", "decompress-last", "/decompress-last", "decompress last compressed artifact"),
                CommandPaletteItem("/", "tab runtime", "/tab runtime", "switch to runtime view"),
                CommandPaletteItem("/", "tab benchmark", "/tab benchmark", "switch to benchmark view"),
                CommandPaletteItem("/", "help", "/help", "show dashboard command help"),
                CommandPaletteItem("/", "agent", "/agent", "switch input to agent/chat mode"),
                CommandPaletteItem("/", "shell", "/shell", "switch input to shell mode"),
                CommandPaletteItem("/", "seam", "/seam", "switch input to SEAM command mode"),
                CommandPaletteItem("/", "cmd", "/cmd", "alias for SEAM command mode"),
                CommandPaletteItem("/", "hybrid", "/hybrid", "switch input to hybrid mode"),
                CommandPaletteItem("/", "model", "/model ", "show or switch chat model"),
                CommandPaletteItem("/", "models", "/models", "list available chat models"),
                CommandPaletteItem("/", "status", "/status", "show harness mode and runtime state"),
                CommandPaletteItem("/", "clear", "/clear", "clear chat history"),
                CommandPaletteItem("/", "savechat", "/savechat ", "export chat transcript"),
                CommandPaletteItem("/", "quit", "/quit", "close the dashboard"),
                CommandPaletteItem("!", "compile", "!compile ", "force a SEAM compile command"),
                CommandPaletteItem("!", "retrieve", "!retrieve ", "force a SEAM retrieval command"),
                CommandPaletteItem("!", "context", "!context ", "force a SEAM context command"),
                CommandPaletteItem("!", "stats", "!stats", "force dashboard stats command"),
                CommandPaletteItem("!", "reload", "!reload", "force dashboard reload"),
                CommandPaletteItem("!", "refresh", "!refresh", "force dashboard reload"),
                CommandPaletteItem("!", "pwd", "!pwd", "print shell working directory"),
                CommandPaletteItem("!", "cd", "!cd ", "change shell working directory"),
                CommandPaletteItem("!", "dir", "!dir", "list files in PowerShell"),
                CommandPaletteItem("!", "git status", "!git status --short", "show concise git status"),
                CommandPaletteItem("!", "docker ps", "!docker ps", "show running Docker containers"),
                CommandPaletteItem("!", "python", "!python ", "run Python from the current shell"),
                CommandPaletteItem("?", "agent", "?agent", "plain text chats with the model"),
                CommandPaletteItem("?", "shell", "?shell", "plain text runs shell commands"),
                CommandPaletteItem("?", "seam", "?seam", "plain text runs dashboard commands"),
                CommandPaletteItem("?", "hybrid", "?hybrid", "known commands execute, other text chats"),
                CommandPaletteItem("?", "model", "?model ", "show or switch chat model"),
                CommandPaletteItem("?", "models", "?models", "list available chat models"),
                CommandPaletteItem("?", "status", "?status", "show harness mode and runtime state"),
                CommandPaletteItem("?", "clear", "?clear", "clear chat history"),
                CommandPaletteItem("?", "savechat", "?savechat ", "export chat transcript"),
                CommandPaletteItem("?", "??", "??", "force a chat message from any mode"),
                CommandPaletteItem("?", "help", "?help", "show shortcut help"),
            ]

        def _update_command_palette(self, value: str) -> None:
            raw = value.strip()
            if not raw or raw[0] not in {"/", "!", "?"}:
                self._hide_command_palette()
                return
            trigger = raw[0]
            query = raw[1:].strip().lower()
            if trigger in {"/", "!", "?"} and " " in raw[1:].lstrip():
                self._hide_command_palette()
                return

            matches = [
                item
                for item in self._palette_items
                if item.trigger == trigger
                and (
                    not query
                    or query in item.command.lower()
                    or query in item.description.lower()
                    or query in item.insert_text.lower()
                )
            ]
            if query:
                matches.sort(key=lambda item: self._palette_match_rank(item, query))
            self._palette_trigger = trigger
            self._palette_query = query
            max_matches = 32 if trigger == "/" and not query else 8
            self._palette_matches = matches[:max_matches]
            self._palette_index = min(self._palette_index, max(0, len(self._palette_matches) - 1))
            self._render_command_palette()

        @staticmethod
        def _palette_match_rank(item: CommandPaletteItem, query: str) -> tuple[int, int, str]:
            command = item.command.lower()
            insert_text = item.insert_text.lower().lstrip("/!?")
            description = item.description.lower()
            if command == query:
                bucket = 0
            elif command.startswith(query):
                bucket = 1
            elif insert_text.startswith(query):
                bucket = 2
            elif query in command:
                bucket = 3
            elif query in insert_text:
                bucket = 4
            elif query in description:
                bucket = 5
            else:
                bucket = 6
            return (bucket, len(command), command)

        def _render_command_palette(self) -> None:
            palette = self.query_one("#command-palette", Static)
            if not self._palette_matches:
                palette.update("")
                palette.styles.display = "none"
                return
            palette.styles.display = "block"
            title = {
                "/": "SEAM commands",
                "!": "force command / shell",
                "?": "mode shortcuts",
            }.get(self._palette_trigger, "commands")
            rows = [f"[bold cyan]{escape(title)}[/]  [dim]Up/Down move · Tab/Enter select · Esc close[/]"]
            if self._palette_trigger == "/" and not self._palette_query:
                rows.extend(self._render_slash_command_grid())
                palette.update("\n".join(rows))
                return
            for idx, item in enumerate(self._palette_matches):
                selected = idx == self._palette_index
                marker = ">" if selected else " "
                row = f"{marker} {escape(item.trigger + item.command):<22} {escape(item.description)}"
                if selected:
                    row = f"[reverse]{row}[/reverse]"
                rows.append(row)
            palette.update("\n".join(rows))

        def _render_slash_command_grid(self) -> list[str]:
            commands = [item.trigger + item.command for item in self._palette_matches]
            columns = 3
            rows: list[str] = []
            for start in range(0, len(commands), columns):
                cells = []
                for offset, command in enumerate(commands[start:start + columns]):
                    idx = start + offset
                    marker = ">" if idx == self._palette_index else " "
                    cell = f"{marker} {escape(command):<18}"
                    if idx == self._palette_index:
                        cell = f"[reverse]{cell}[/reverse]"
                    cells.append(cell)
                rows.append("  ".join(cells))
            return rows

        def _hide_command_palette(self) -> None:
            self._palette_matches = []
            self._palette_index = 0
            self._palette_trigger = ""
            self._palette_query = ""
            try:
                palette = self.query_one("#command-palette", Static)
                palette.update("")
                palette.styles.display = "none"
            except Exception:
                return

        def _move_palette_selection(self, delta: int) -> None:
            if not self._palette_matches:
                return
            self._palette_index = (self._palette_index + delta) % len(self._palette_matches)
            self._render_command_palette()

        def _accept_palette_selection(self, input_widget: Input, submit: bool = False) -> None:
            if not self._palette_matches:
                return
            item = self._palette_matches[self._palette_index]
            input_widget.value = item.insert_text
            input_widget.cursor_position = len(input_widget.value)
            self._hide_command_palette()
            if submit and not input_widget.value.endswith(" "):
                command = input_widget.value.strip()
                input_widget.value = ""
                self.process_command(command)

        def process_command(self, command: str) -> None:
            raw = command.strip()
            if not raw:
                return
            if raw.startswith("??"):
                self._handle_chat_message(raw[2:].strip())
                return
            if raw.startswith("?") or raw.startswith("/"):
                self._handle_shortcut(raw)
                return
            if raw.startswith("!"):
                candidate = raw[1:].strip()
                token = candidate.split()[0].lower() if candidate else ""
                if token in self.command_names:
                    self._execute_dashboard_command(candidate)
                else:
                    self._execute_shell_command(candidate)
                return

            token = raw.split()[0].lower()
            if self.input_mode == "agent":
                self._handle_chat_message(raw)
                return
            if self.input_mode == "shell":
                self._execute_shell_command(raw)
                return
            if self.input_mode == "seam":
                self._execute_dashboard_command(raw)
                return
            if token in self.command_names:
                self._execute_dashboard_command(raw)
                return
            self._handle_chat_message(raw)

        def _execute_dashboard_command(self, command: str) -> None:
            started_at = time.perf_counter()
            self._record_command("run", command)
            should_exit = self.controller.execute(command)
            elapsed = max(0.0, time.perf_counter() - started_at)
            title = self.controller.result_title
            body = self.controller.result_body
            self._route_command_output(command, title, body)
            if command.split()[0].lower() in {"reload", "refresh"}:
                self._reload_dashboard_surface()
            self._push_result(title, body)
            self._sync_side_panel()
            self._refresh_metrics()
            self._refresh_tab_bar()
            phase = "ok" if self.controller.last_command_ok else "err"
            self._record_command(phase, f"{command} -> {title} ({self._format_elapsed(elapsed)})")
            self._capture_token_metrics_from_command(command)
            if should_exit:
                self.exit()

        @on(Tree.NodeSelected, "#explorer-tree")
        def _on_explorer_node_selected(self, event: Tree.NodeSelected) -> None:  # pragma: no cover - textual runtime behavior
            data = event.node.data
            if not data:
                return
            ns = data.get("ns")
            scope = data.get("scope")
            kind = data.get("kind")
            try:
                batch = self.controller.runtime.store.load_ir(
                    ns=ns,
                    scope=scope if scope else None,
                )
                if kind:
                    records = [r for r in batch.records if r.kind.value == kind]
                else:
                    records = batch.records
                if not records:
                    lines = [f"No records for {ns}/{scope or '*'}/{kind or '*'}"]
                else:
                    lines = []
                    for rec in records[:200]:
                        lines.append(f"[{rec.kind.value}] {rec.id}")
                        if hasattr(rec, 'body') and rec.body:
                            preview = str(rec.body)[:120].replace('\n', ' ')
                            lines.append(f"  {preview}")
                        lines.append("")
                self.query_one("#memory-panel", _TextualPanel).set_lines(lines)
                tabs = self.query_one("#main-tabs", TabbedContent)
                tabs.active = "tab-memory"
                self._update_status(f"Explorer: {ns}/{scope or '*'}")
            except Exception as exc:
                self._update_status(f"Explorer error: {exc}")

        def _handle_shortcut(self, raw: str) -> None:
            prefix = raw[:1]
            content = raw[1:].strip()
            parts = content.split(maxsplit=1)
            shortcut = parts[0].lower() if parts else ""
            argument = parts[1].strip() if len(parts) > 1 else ""
            argument = argument.strip("\"'")
            if prefix == "/" and shortcut in self.command_names:
                command = shortcut if not argument else f"{shortcut} {argument}"
                self._execute_dashboard_command(command)
                return
            if prefix == "/" and shortcut in {"cmd", "command", "c"}:
                shortcut = "seam"
            elif prefix == "/" and shortcut in {"hybrid", "h"}:
                shortcut = "hybrid"
            elif prefix == "/" and shortcut in {"agent", "chat", "a"}:
                shortcut = "agent"
            elif prefix == "/" and shortcut in {"shell", "bash", "sh"}:
                shortcut = "shell"
            elif prefix == "/" and shortcut in {"clear", "cls"}:
                shortcut = "clear"
            elif prefix == "/" and shortcut in {"help", "?"}:
                shortcut = "help"
            elif prefix == "/" and shortcut in {"savechat", "save-chat", "export-chat", "exportchat"}:
                shortcut = "savechat"
            elif prefix == "/" and shortcut in {"model", "m", "models", "status"}:
                pass

            if shortcut in {"agent", "chat", "a"}:
                self.input_mode = "agent"
                self._refresh_input_placeholder()
                self._push_result("Input Mode", "Switched to agent mode. Plain text chats. Use !<shell> for shell work.")
                self._record_command("mode", "agent")
                self._append_chat_activity("harness", "mode -> agent")
                self._refresh_tab_bar()
                self._refresh_logo()
                return
            if shortcut in {"shell", "bash", "sh"}:
                self.input_mode = "shell"
                self._refresh_input_placeholder()
                self._push_result("Input Mode", f"Switched to shell mode. Plain text runs shell commands from {self.shell_cwd}. Use ??<message> to chat.")
                self._record_command("mode", "shell")
                self._append_chat_activity("harness", f"mode -> shell ({self.shell_cwd})")
                self._refresh_tab_bar()
                self._refresh_logo()
                return
            if shortcut in {"seam", "cmd", "command", "c"}:
                self.input_mode = "seam"
                self._refresh_input_placeholder()
                self._push_result("Input Mode", "Switched to SEAM mode. Plain text runs dashboard commands. Use ??<message> to chat.")
                self._record_command("mode", "seam")
                self._append_chat_activity("harness", "mode -> seam")
                self._refresh_tab_bar()
                self._refresh_logo()
                return
            if shortcut in {"hybrid", "h"}:
                self.input_mode = "hybrid"
                self._refresh_input_placeholder()
                self._push_result("Input Mode", "Switched to hybrid mode. Known SEAM commands run directly, other text chats, and !<shell> runs shell.")
                self._record_command("mode", "hybrid")
                self._append_chat_activity("harness", "mode -> hybrid")
                self._refresh_tab_bar()
                self._refresh_logo()
                return
            if shortcut in {"clear", "cls"}:
                self.chat_lines.clear()
                self.chat_history.clear()
                self.query_one("#chat-panel", _TextualPanel).set_lines(["Chat cleared."])
                self._push_result("Chat", "Chat history cleared.")
                self._record_command("chat", "clear")
                return
            if shortcut == "model":
                if not argument:
                    current = self.chat_client.model
                    available = "\n".join(f"- {name}" for name in self.chat_client.available_models)
                    self._push_result("Chat Model", f"Current model: {current}\nAvailable models:\n{available}")
                    self._record_command("state", f"model -> {current}")
                    return
                self.chat_client.model = argument
                if argument not in self.chat_client.available_models:
                    self.chat_client.available_models.insert(0, argument)
                self._push_result("Chat Model", f"Switched chat model to {argument}")
                self._record_command("state", f"model -> {argument}")
                self._append_chat_activity("harness", f"model -> {argument}")
                self._refresh_logo()
                return
            if shortcut == "models":
                current = self.chat_client.model
                rows = [f"{name} (current)" if name == current else name for name in self.chat_client.available_models]
                self._push_result("Available Models", "\n".join(rows))
                self._record_command("state", "models")
                return
            if shortcut == "status":
                self._push_result(
                    "Harness Status",
                    (
                        f"Input mode: {self.input_mode}\n"
                        f"Chat model: {self.chat_client.model}\n"
                        f"Shell cwd: {self.shell_cwd}\n"
                        f"Active tab: {self.controller.active_tab}"
                    ),
                )
                self._record_command("state", "status")
                return
            if shortcut in {"help", ""}:
                self._push_result(
                    "Shortcuts",
                    (
                        "?agent   -> plain text chats\n"
                        "?shell   -> plain text shell commands\n"
                        "?seam    -> plain text SEAM dashboard commands\n"
                        "?hybrid  -> known SEAM commands run, other text chats\n"
                        "?model [name] -> show or switch chat model\n"
                        "?models  -> list available chat models\n"
                        "?status  -> show current harness state\n"
                        "?clear   -> clear chat history\n"
                        "?savechat [path] -> export chat transcript (.jsonl)\n"
                        "!<shell> -> run a shell command immediately\n"
                        "??<text> -> force a chat message from shell/SEAM modes\n"
                        "Legacy /model /cmd /hybrid /savechat aliases still work."
                    ),
                )
                self._record_command("help", "shortcuts")
                return
            if shortcut in {"savechat", "save-chat", "export-chat", "exportchat"}:
                destination = Path(argument).expanduser() if argument else self._default_chat_export_path()
                target, count = self._save_chat_transcript(destination)
                self._push_result("Chat Transcript", f"Exported {count} messages to {target}")
                self._record_command("state", f"chat transcript -> {target}")
                return
            self._push_result("Shortcut Error", f"Unknown shortcut: {raw}. Use ?help.")
            self._record_command("error", f"shortcut {raw}")

        def _execute_shell_command(self, command: str) -> None:
            shell_command = command.strip()
            if not shell_command:
                self._push_result("Shell", "Enter a shell command after '!'.")
                self._record_command("error", "empty shell input")
                return
            self._record_command("shell", shell_command)
            started_at = time.perf_counter()
            try:
                token, _, remainder = shell_command.partition(" ")
                token = token.lower()
                if token in {"cd", "chdir"}:
                    destination = remainder.strip() or str(Path.home())
                    next_cwd = Path(destination).expanduser()
                    if not next_cwd.is_absolute():
                        next_cwd = self.shell_cwd / next_cwd
                    next_cwd = next_cwd.resolve()
                    if not next_cwd.exists() or not next_cwd.is_dir():
                        raise FileNotFoundError(f"No such directory: {next_cwd}")
                    self.shell_cwd = next_cwd
                    body = f"cwd -> {self.shell_cwd}"
                    returncode = 0
                elif token in {"pwd", "cwd"} and not remainder.strip():
                    body = str(self.shell_cwd)
                    returncode = 0
                else:
                    completed = self._run_shell_subprocess(shell_command)
                    returncode = completed.returncode
                    stdout = completed.stdout.strip()
                    stderr = completed.stderr.strip()
                    sections = [f"cwd: {self.shell_cwd}", f"exit_code: {returncode}"]
                    if stdout:
                        sections.extend(["", "stdout:", stdout])
                    if stderr:
                        sections.extend(["", "stderr:", stderr])
                    if not stdout and not stderr:
                        sections.extend(["", "(no output)"])
                    body = "\n".join(sections)
                elapsed = max(0.0, time.perf_counter() - started_at)
                self._push_result("Shell", body)
                if returncode == 0:
                    self._record_command("ok", f"{shell_command} -> shell ({self._format_elapsed(elapsed)})")
                else:
                    self._record_command("err", f"{shell_command} -> shell exit {returncode} ({self._format_elapsed(elapsed)})")
                self.controller._log("shell", f"{shell_command} -> exit {returncode}")
                self._sync_side_panel()
                self._refresh_logo()
                preview = body.splitlines()[0] if body else "(no output)"
                self._append_chat_activity("shell", f"!{shell_command}", preview)
            except Exception as exc:
                self._push_result("Shell", str(exc))
                self._record_command("err", f"{shell_command} -> {type(exc).__name__}")
                self.controller._log("shell", f"{shell_command} -> {type(exc).__name__}")
                self._sync_side_panel()
                self._append_chat_activity("shell", f"!{shell_command}", str(exc))

        def _run_shell_subprocess(self, command: str) -> subprocess.CompletedProcess[str]:
            if os.environ.get("SEAM_DASHBOARD_ALLOW_SHELL") != "1":
                raise PermissionError(
                    "Shell execution is disabled by default; set SEAM_DASHBOARD_ALLOW_SHELL=1 to enable subprocess commands."
                )

            argv = _validate_shell_command(command)

            project_root = Path(__file__).parent.parent.resolve()
            cwd = _validate_shell_cwd(Path(self.shell_cwd), project_root=project_root)

            timeout_seconds = _get_shell_timeout()

            # Execute shell-free: no shell is spawned, so the validated argv is
            # passed verbatim and operator chaining / redirection / command
            # substitution is structurally impossible. This is the security
            # boundary for the off-by-default dashboard shell.
            #
            # Do NOT log the command text: an operator command can embed a secret
            # (e.g. an auth header / token passed as an arg), and the logging sink
            # would record it in clear text. Log only the non-sensitive argv token
            # count so the security-boundary event stays observable; the full
            # command remains in the operator-facing audit trail (_record_command /
            # controller._log), which is not a clear-text logging sink.
            LOGGER.debug("Executing shell command (shell-free): %d-token argv", len(argv))
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )

        def _route_command_output(self, command: str, title: str, body: str) -> None:
            token = command.split()[0].lower()
            try:
                tabs = self.query_one("#main-tabs", TabbedContent)
            except Exception:
                tabs = None

            if token in {"compile", "compile-nl", "compile-dsl", "dsl", "stats", "reload", "refresh", "trace", "index"}:
                self.memory_lines.extend([f"{title}: {command}", body, ""])
                self.query_one("#memory-panel", _TextualPanel).set_lines(self.memory_lines)
                if tabs:
                    tabs.active = "tab-memory"
                if token in {"compile", "compile-nl", "compile-dsl", "dsl"}:
                    self._trigger_mirl_animation("compile", body)
                return
            if token in {"search", "retrieve", "context", "plan"}:
                self.retrieval_lines.extend([f"{title}: {command}", body, ""])
                self.query_one("#retrieval-panel", _TextualPanel).set_lines(self.retrieval_lines)
                if tabs:
                    tabs.active = "tab-retrieval"
                return
            if token in {
                "benchmark",
                "compress-doc",
                "lossless-compress",
                "readable-compress",
                "compress-readable",
                "readable-query",
                "query-compressed",
                "readable-rebuild",
                "decompress-doc",
                "lossless-decompress",
                "decompress-last",
            }:
                self.benchmark_lines.extend([f"{title}: {command}", body, ""])
                self.query_one("#benchmark-panel", _TextualPanel).set_lines(self.benchmark_lines)
                if tabs:
                    tabs.active = "tab-benchmarks"
                if token in {"benchmark", "compress-doc", "lossless-compress", "readable-compress", "compress-readable"}:
                    self._trigger_mirl_animation(token, body)
            if token == "tab":
                self._record_command("state", f"active tab => {self.controller.active_tab}")
                if tabs:
                    _tab_map = {"benchmark": "tab-benchmarks", "runtime": "tab-memory"}
                    tabs.active = _tab_map.get(self.controller.active_tab, "tab-memory")

        def _push_result(self, title: str, body: str) -> None:
            self.result_lines.extend([f"{title}", body, ""])
            self.query_one("#result-panel", _TextualPanel).set_lines(self.result_lines)

        _PROVIDER_PRESETS: dict[str, tuple[str, str]] = {
            "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
            "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
            "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1"),
            "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
        }

        def _set_env_fields(self, fields: dict[str, str]) -> list[str]:
            changed: list[str] = []
            for key, value in fields.items():
                clean_value = value.strip()
                if clean_value:
                    os.environ[key] = clean_value
                    changed.append(key)
            return changed

        def _repo_root(self) -> Path:
            return Path(__file__).resolve().parents[1]

        def _path_inside_repo(self, path: Path) -> bool:
            try:
                path.resolve().relative_to(self._repo_root())
                return True
            except ValueError:
                return False

        def _configured_local_env_path(self) -> Path | None:
            raw_path = os.environ.get("SEAM_LOCAL_ENV", "").strip()
            return Path(raw_path).expanduser() if raw_path else None

        def _local_env_candidates(self, *, include_repo_fallback: bool = False) -> list[Path]:
            candidates: list[Path] = []
            configured = self._configured_local_env_path()
            if configured is not None:
                candidates.append(configured)
            candidates.append(Path.home() / "Documents" / "SEAM" / "local" / ".env")
            if include_repo_fallback:
                candidates.append(Path(".env"))
            return candidates

        def _local_env_path(self) -> Path:
            configured = self.query_one("#cfg-compose-env", Input).value.strip()
            if configured:
                return Path(configured).expanduser()
            existing = next(
                (path for path in self._local_env_candidates() if path.exists()),
                None,
            )
            return existing or Path.home() / "Documents" / "SEAM" / "local" / ".env"

        def _activate_provider(self, provider: str) -> None:  # pragma: no cover
            env_var, base_url = self._PROVIDER_PRESETS[provider]
            key = self.query_one(f"#cfg-key-{provider}", Input).value.strip()
            if not key:
                self._push_result("Settings", f"No {provider} key entered.")
                return
            os.environ[env_var] = key
            os.environ["SEAM_CHAT_API_KEY"] = key
            os.environ["SEAM_CHAT_BASE_URL"] = base_url
            self.chat_client.api_key = key
            self.chat_client.base_url = base_url
            self.query_one("#cfg-api-key", Input).value = key
            self.query_one("#cfg-base-url", Input).value = base_url
            self._push_result("Settings", f"Activated {provider}: {env_var}, SEAM_CHAT_API_KEY, SEAM_CHAT_BASE_URL.")
            self._refresh_logo()

        @on(Button.Pressed, "#btn-use-openai")
        def _on_btn_use_openai(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._activate_provider("openai")

        @on(Button.Pressed, "#btn-use-openrouter")
        def _on_btn_use_openrouter(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._activate_provider("openrouter")

        @on(Button.Pressed, "#btn-use-anthropic")
        def _on_btn_use_anthropic(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._activate_provider("anthropic")

        @on(Button.Pressed, "#btn-use-gemini")
        def _on_btn_use_gemini(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._activate_provider("gemini")

        @on(Button.Pressed, "#btn-apply-provider-keys")
        def _on_btn_apply_provider_keys(self, _: Button.Pressed) -> None:  # pragma: no cover
            changed = self._set_env_fields(
                {
                    env_var: self.query_one(f"#cfg-key-{provider}", Input).value
                    for provider, (env_var, _) in self._PROVIDER_PRESETS.items()
                }
            )
            msg = f"Stored for this session: {', '.join(changed)}" if changed else "No provider keys entered."
            self._push_result("Settings", msg)

        @on(Button.Pressed, "#btn-apply-api")
        def _on_btn_apply_api(self, event: Button.Pressed) -> None:  # pragma: no cover
            api_key = self.query_one("#cfg-api-key", Input).value.strip()
            base_url = self.query_one("#cfg-base-url", Input).value.strip()
            model = self.query_one("#cfg-model", Input).value.strip()
            models = self.query_one("#cfg-chat-models", Input).value.strip()
            transcript_dir = self.query_one("#cfg-transcript-dir", Input).value.strip()
            changed: list[str] = []
            if api_key:
                os.environ["SEAM_CHAT_API_KEY"] = api_key
                self.chat_client.api_key = api_key
                changed.append("SEAM_CHAT_API_KEY")
            if base_url:
                os.environ["SEAM_CHAT_BASE_URL"] = base_url
                self.chat_client.base_url = base_url.rstrip("/")
                changed.append("SEAM_CHAT_BASE_URL")
            if model:
                os.environ["SEAM_CHAT_MODEL"] = model
                self.chat_client.model = model
                changed.append("SEAM_CHAT_MODEL")
            if models:
                os.environ["SEAM_CHAT_MODELS"] = models
                self.chat_client.available_models = [item.strip() for item in models.split(",") if item.strip()]
                changed.append("SEAM_CHAT_MODELS")
            if transcript_dir:
                os.environ["SEAM_CHAT_TRANSCRIPT_DIR"] = transcript_dir
                self.transcript_dir = Path(transcript_dir)
                changed.append("SEAM_CHAT_TRANSCRIPT_DIR")
            msg = f"Applied: {', '.join(changed)}" if changed else "Nothing to apply — all fields empty."
            self._push_result("Settings", msg)
            self._append_chat_activity("harness", f"settings -> {msg}")
            self._refresh_logo()

        @on(Button.Pressed, "#btn-apply-embed")
        def _on_btn_apply_embed(self, _: Button.Pressed) -> None:  # pragma: no cover
            changed = self._set_env_fields(
                {
                    "SEAM_EMBEDDING_PROVIDER": self.query_one("#cfg-embed-provider", Input).value,
                    "SEAM_EMBEDDING_MODEL": self.query_one("#cfg-embed-model", Input).value,
                    "SEAM_EMBEDDING_API_KEY_ENV": self.query_one("#cfg-embed-key-env", Input).value,
                    "SEAM_EMBEDDING_DIMENSIONS": self.query_one("#cfg-embed-dims", Input).value,
                }
            )
            msg = f"Applied embedding settings: {', '.join(changed)}. Restart required for model reload." if changed else "Nothing changed."
            self._push_result("Settings", msg)

        @on(Button.Pressed, "#btn-apply-surface")
        def _on_btn_apply_surface(self, _: Button.Pressed) -> None:  # pragma: no cover
            mode = self.query_one("#cfg-surface-mode", Input).value.strip().lower()
            if mode and mode not in {"bw1", "rgb", "rgb24", "rgba32", "rgba64"}:
                self._push_result("Settings", "Surface mode must be bw1, rgb24, rgba32, or rgba64.")
                return
            changed = self._set_env_fields({"SEAM_SURFACE_MODE": mode})
            msg = f"Applied Holographic Surface settings: {', '.join(changed)}" if changed else "Nothing changed."
            self._push_result("Settings", msg)

        @on(Button.Pressed, "#btn-apply-db")
        def _on_btn_apply_db(self, event: Button.Pressed) -> None:  # pragma: no cover
            db_path = self.query_one("#cfg-db-path", Input).value.strip()
            dsn = self.query_one("#cfg-pgvector-dsn", Input).value.strip()
            changed: list[str] = []
            if db_path:
                os.environ["SEAM_DB_PATH"] = db_path
                changed.append("SEAM_DB_PATH")
            if dsn:
                os.environ["SEAM_PGVECTOR_DSN"] = dsn
                changed.append("SEAM_PGVECTOR_DSN")
            msg = (
                f"Updated for this session: {', '.join(changed)}. Restart required for new runtime connections."
                if changed else
                "DB and pgvector fields empty — nothing changed."
            )
            self._push_result("Settings", msg)

        def _pg_compose_cmd(self, *args: str) -> list[str]:
            env_path = self._local_env_path()
            cmd = ["docker", "compose"]
            if env_path.exists():
                cmd.extend(["--env-file", str(env_path)])
            return cmd + list(args)

        def _run_docker_compose(self, *args: str, label: str) -> None:  # pragma: no cover
            cmd = self._pg_compose_cmd(*args)
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except FileNotFoundError:
                output = "docker not found. Install/start Docker Desktop first."
                self._push_result(label, output)
                self._record_pgvector_status(label, output, returncode=-1)
                return
            except subprocess.TimeoutExpired:
                output = "docker compose timed out after 30 seconds."
                self._push_result(label, output)
                self._record_pgvector_status(label, output, returncode=-1)
                return
            output = (result.stdout + result.stderr).strip()
            status = f"exit={result.returncode}"
            self._push_result(label, output or status)
            self._record_pgvector_status(label, output or status, returncode=result.returncode)

        @on(Button.Pressed, "#btn-pg-start")
        def _on_btn_pg_start(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._run_docker_compose("up", "-d", "pgvector", label="pgvector start")

        @on(Button.Pressed, "#btn-pg-stop")
        def _on_btn_pg_stop(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._run_docker_compose("stop", "pgvector", label="pgvector stop")

        @on(Button.Pressed, "#btn-pg-status")
        def _on_btn_pg_status(self, _: Button.Pressed) -> None:  # pragma: no cover
            self._run_docker_compose("ps", "pgvector", label="pgvector status")

        @on(Button.Pressed, "#btn-apply-rest")
        def _on_btn_apply_rest(self, _: Button.Pressed) -> None:  # pragma: no cover
            changed = self._set_env_fields(
                {
                    "SEAM_API_TOKEN": self.query_one("#cfg-api-token", Input).value,
                    "SEAM_API_RATE_LIMIT_PER_MINUTE": self.query_one("#cfg-rate-limit-min", Input).value,
                }
            )
            msg = f"Applied REST settings: {', '.join(changed)}. Restart seam serve to apply." if changed else "Nothing changed."
            self._push_result("Settings", msg)

        @on(Button.Pressed, "#btn-open-env")
        def _on_btn_open_env(self, event: Button.Pressed) -> None:  # pragma: no cover
            env_candidates = self._local_env_candidates(include_repo_fallback=True)
            found = next((path for path in env_candidates if str(path) and path.exists()), None)
            if found is None:
                self._push_result("Settings", f"No .env found. Checked: {[str(p) for p in env_candidates]}")
            else:
                self._push_result("Settings", f".env found: {found}\nSize: {found.stat().st_size} bytes")

        @on(Button.Pressed, "#btn-open-config-dir")
        def _on_btn_open_config_dir(self, event: Button.Pressed) -> None:  # pragma: no cover
            config_dir = Path.home() / "Documents" / "SEAM"
            if config_dir.exists():
                self._push_result("Settings", f"Config dir found: {config_dir}")
                self._update_status(f"Config dir: {config_dir}")
            else:
                self._push_result("Settings", f"Config dir not found: {config_dir}")

        @on(Button.Pressed, "#btn-save-env")
        def _on_btn_save_env(self, _: Button.Pressed) -> None:  # pragma: no cover
            env_path = self._local_env_path()
            if self._path_inside_repo(env_path):
                self._push_result("Settings", f"Refusing to write secrets inside repo: {env_path}")
                return
            values = {
                "OPENAI_API_KEY": self.query_one("#cfg-key-openai", Input).value,
                "OPENROUTER_API_KEY": self.query_one("#cfg-key-openrouter", Input).value,
                "ANTHROPIC_API_KEY": self.query_one("#cfg-key-anthropic", Input).value,
                "GEMINI_API_KEY": self.query_one("#cfg-key-gemini", Input).value,
                "SEAM_CHAT_API_KEY": self.query_one("#cfg-api-key", Input).value,
                "SEAM_CHAT_BASE_URL": self.query_one("#cfg-base-url", Input).value,
                "SEAM_CHAT_MODEL": self.query_one("#cfg-model", Input).value,
                "SEAM_CHAT_MODELS": self.query_one("#cfg-chat-models", Input).value,
                "SEAM_CHAT_TRANSCRIPT_DIR": self.query_one("#cfg-transcript-dir", Input).value,
                "SEAM_EMBEDDING_PROVIDER": self.query_one("#cfg-embed-provider", Input).value,
                "SEAM_EMBEDDING_MODEL": self.query_one("#cfg-embed-model", Input).value,
                "SEAM_EMBEDDING_API_KEY_ENV": self.query_one("#cfg-embed-key-env", Input).value,
                "SEAM_EMBEDDING_DIMENSIONS": self.query_one("#cfg-embed-dims", Input).value,
                "SEAM_SURFACE_MODE": self.query_one("#cfg-surface-mode", Input).value,
                "SEAM_DB_PATH": self.query_one("#cfg-db-path", Input).value,
                "SEAM_PGVECTOR_DSN": self.query_one("#cfg-pgvector-dsn", Input).value,
                "SEAM_LOCAL_ENV": self.query_one("#cfg-compose-env", Input).value,
                "SEAM_API_TOKEN": self.query_one("#cfg-api-token", Input).value,
                "SEAM_API_RATE_LIMIT_PER_MINUTE": self.query_one("#cfg-rate-limit-min", Input).value,
            }
            lines = ["# SEAM local environment written by dashboard\n"]
            saved_keys: list[str] = []
            for key, value in values.items():
                clean_value = value.strip()
                if clean_value:
                    lines.append(f"{key}={clean_value}\n")
                    saved_keys.append(key)
            if not saved_keys:
                self._push_result("Settings", "No non-empty settings to save.")
                return
            try:
                _write_private_text_file(env_path, "".join(lines))
                self._push_result("Settings", f"Saved {len(saved_keys)} keys to local env: {env_path}")
            except Exception as exc:
                self._push_result("Settings", f"Failed to save local env: {exc}")

        @on(Button.Pressed, "#btn-reload-env")
        def _on_btn_reload_env(self, event: Button.Pressed) -> None:  # pragma: no cover
            env_path = next(
                (path for path in self._local_env_candidates(include_repo_fallback=True) if path.exists()),
                None,
            )
            if env_path is None:
                self._push_result("Settings", "No .env file found to reload.")
                return
            loaded: list[str] = []
            try:
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key.startswith("SEAM_") or key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}:
                        os.environ[key] = value.strip().strip('"').strip("'")
                        loaded.append(key)
                self.chat_client = SeamChatClient()
                self._refresh_logo()
                self._push_result("Settings", f"Reloaded {len(loaded)} vars from {env_path}: {', '.join(loaded[:8])}")
            except Exception as exc:
                self._push_result("Settings", f"Failed to reload .env: {exc}")

        def _reload_dashboard_surface(self) -> None:
            self._hide_command_palette()
            self._refresh_logo()
            self._refresh_input_placeholder()
            self._refresh_metrics()
            self._refresh_overview()
            self._sync_side_panel()
            self._refresh_tab_bar()
            self.query_one("#memory-panel", _TextualPanel).set_lines(
                self.memory_lines or ["Dashboard reloaded. Memory panel is ready for compile, stats, or trace."]
            )
            self.query_one("#retrieval-panel", _TextualPanel).set_lines(
                self.retrieval_lines or ["Dashboard reloaded. Retrieval panel is ready for search, retrieve, context, or plan."]
            )
            self.query_one("#benchmark-panel", _TextualPanel).set_lines(
                self.benchmark_lines or ["Dashboard reloaded. Benchmark panel is ready for benchmark or compression commands."]
            )
            if self.mirl_lines:
                self.query_one("#mirl-panel", _TextualMarkupPanel).set_lines(self.mirl_lines)
            elif not self._mirl_animation_running:
                self.query_one("#mirl-panel", _TextualMarkupPanel).set_lines(self._anim_engine.tick_and_render())

        def _sync_side_panel(self) -> None:
            # Benchmark search-log goes into #benchmark-panel via _route_command_output.
            # This panel always shows the live runtime event stream.
            panel = self.query_one("#runtime-log-panel", _TextualMarkupPanel)
            _kind_color: dict[str, str] = {
                "store": "#7efdb9",
                "index": "#d391ff",
                "query": "#7fe0ff",
                "pack": "#7efdb9",
                "agent": "#f4d676",
                "trace": "#9b6cff",
                "reload": "#7fe0ff",
                "shell": "#f4d676",
                "system": "#9fd4ff",
            }
            lines = [
                f"[dim]{event.timestamp}[/]  "
                f"[bold {_kind_color.get(event.kind, '#7fe0ff')}]{event.kind.upper():<8}[/]  "
                f"{event.message}"
                for event in list(self.controller.events)
            ]
            panel.set_title("[#7fe0ff]Runtime Log[/]")
            self.side_lines = lines
            panel.set_lines(lines)

        def _refresh_metrics(self) -> None:
            metrics = self.controller._collect_metrics()
            db_bytes = Path(metrics.db_path).stat().st_size if Path(metrics.db_path).exists() else 0
            db_ratio = min(1.0, db_bytes / float(1024 * 1024 * 1024))
            source_tokens = self._token_source_total
            machine_tokens = self._token_machine_total
            compressed = max(source_tokens - machine_tokens, 0)
            savings_ratio = 0.0 if source_tokens == 0 else compressed / float(source_tokens)
            token_rate = self._estimate_token_rate()
            summary = (
                f"[{metrics.db_size}] {metrics.db_path}  "
                f"records={metrics.total_records}  vectors={metrics.vector_entries}  "
                f"packs={metrics.pack_entries}  mode={self.input_mode}\n"
                f"tok/s={token_rate:.0f}  compressed={compressed} (src={source_tokens} → mch={machine_tokens})  "
                f"DB:{self._bar(db_ratio, 14)}  lx1:{self._bar(savings_ratio, 14)}"
            )
            self.query_one("#metrics", Static).update(summary)

        def _refresh_tab_bar(self) -> None:
            # Sync TabbedContent active state from the controller's coarse tab flag.
            # Fine-grained switching happens in _route_command_output; this handles
            # the legacy `tab runtime` / `tab benchmark` dashboard commands.
            try:
                tabs = self.query_one("#main-tabs", TabbedContent)
                if self.controller.active_tab == "benchmark" and tabs.active not in {"tab-benchmarks"}:
                    tabs.active = "tab-benchmarks"
                elif self.controller.active_tab == "runtime" and tabs.active == "tab-benchmarks":
                    tabs.active = "tab-memory"
            except Exception:
                return

        def _refresh_input_placeholder(self) -> None:
            widget = self.query_one("#command-input", Input)
            if self.input_mode == "agent":
                widget.placeholder = "Agent mode: type to chat | !<shell> | ?help"
            elif self.input_mode == "shell":
                widget.placeholder = "Shell mode: type shell commands | ??<message> to chat | ?help"
            elif self.input_mode == "seam":
                widget.placeholder = "SEAM mode: type dashboard commands | ??<message> | !<shell> | ?help"
            else:
                widget.placeholder = "Hybrid mode: known SEAM commands auto-run, otherwise chat | !<shell> | ?help"

        def _refresh_logo(self) -> None:
            fields = _ui_logo.HeaderFields(
                version="v0.1.0",
                tagline="MIRL Interpreter & Persistence Engine",
                launch_dir=str(Path.cwd()),
                shell_cwd=str(self.shell_cwd),
                model=self.chat_client.model,
                chat_status="configured" if self.chat_client.configured else "offline",
                mode=self.input_mode,
                glow=True,
            )
            self.query_one("#logo-header", Static).update(_ui_logo.header_markup(fields))

        def _handle_chat_message(self, message: str) -> None:
            if not message:
                self._push_result("Chat", "Enter a message after ?? or switch to ?agent mode and type normally.")
                self._record_command("error", "empty chat input")
                return
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.chat_history.append({"role": "user", "content": message})
            context_prompt = self._build_chat_context_prompt(message)
            assistant = self.chat_client.complete(self.chat_history, context_prompt)
            self.chat_history.append({"role": "assistant", "content": assistant})
            self.chat_lines.extend(
                [
                    f"{timestamp} user: {message}",
                    f"{timestamp} seam: {assistant}",
                    "",
                ]
            )
            self.query_one("#chat-panel", _TextualPanel).set_lines(self.chat_lines)
            self._push_result("Chat", assistant)
            self._record_command("chat", message)

        def _append_chat_activity(self, speaker: str, message: str, detail: str | None = None) -> None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.chat_lines.append(f"{timestamp} {speaker}: {message}")
            if detail:
                self.chat_lines.append(f"{timestamp} {speaker}: {detail}")
            self.chat_lines.append("")
            self.query_one("#chat-panel", _TextualPanel).set_lines(self.chat_lines)

        def _build_chat_context_prompt(self, message: str) -> str:
            try:
                rag = self.controller.orchestrator.rag(message, budget=5, pack_budget=384, lens="rag", mode="context").to_dict()
                prompt_view = build_context_payload(rag, view="prompt")
                if isinstance(prompt_view, dict):
                    return json.dumps(prompt_view, indent=2)[:4000]
                return str(prompt_view)[:4000]
            except Exception as exc:
                return f"(context retrieval failed: {exc})"

        def _record_command(self, phase: str, text: str) -> None:
            badge = {
                "run": "[RUN]",
                "ok": "[OK]",
                "err": "[ERR]",
                "mode": "[MODE]",
                "chat": "[CHAT]",
                "shell": "[SHELL]",
                "help": "[HELP]",
                "state": "[STATE]",
                "error": "[ERR]",
            }.get(phase, f"[{phase.upper()}]")
            self.command_history_lines.append(f"{datetime.now().strftime('%H:%M:%S')} {badge} {text}")
            self.query_one("#command-history-panel", _TextualPanel).set_lines(self.command_history_lines)

        def _trigger_mirl_animation(self, label: str, body: str) -> None:
            # Keep legacy attributes around in case any callsite still
            # reads them; the live render now goes through ``_anim_engine``.
            self._anim_label = label
            self._anim_until = time.monotonic() + 4.0
            compact = body.replace("\n", " ").replace("\r", " ")
            self._anim_preview = compact[:120]
            # Heuristic token estimates — body is the just-emitted MIRL
            # text, source isn't tracked here yet so use length/4 as a
            # crude proxy for source tokens and ~1/3 of that for machine
            # tokens (typical SEAM compression ratio in current bench).
            source_tokens = max(1, len(body) // 4)
            machine_tokens = max(1, source_tokens // 3)
            kind = "compile" if label.lower().startswith("compile") else (
                "compress" if "compress" in label.lower() else "compile"
            )
            self._anim_engine.trigger_compress(label, source_tokens, machine_tokens, kind)
            self._mirl_animation_running = True

        def _tick_mirl_animation(self) -> None:
            if not self.is_mounted:
                return
            if not self._mirl_animation_running:
                return
            self._animation_phase = (self._animation_phase + 1) % 8
            try:
                panel = self.query_one("#mirl-panel", _TextualMarkupPanel)
            except Exception:  # pragma: no cover - timer can fire during teardown
                return
            lines = self._anim_engine.tick_and_render()
            panel.set_lines(lines)
            if not self._anim_engine.active:
                self._mirl_animation_running = False

        def _tick_metrics(self) -> None:
            if not self.is_mounted:
                return
            try:
                self._overview_phase = (self._overview_phase + 1) % 24
                self._refresh_metrics()
                self._refresh_overview()
                self._update_status()
            except Exception:  # pragma: no cover - timer can fire during teardown
                return

        def _record_pgvector_status(self, label: str, output: str, *, returncode: int) -> None:
            lower = output.lower()
            if returncode != 0:
                state = "error"
            elif any(marker in lower for marker in ("running", "healthy", " up ")):
                state = "active"
            elif any(marker in lower for marker in ("exited", "created", "not running", "no containers", "not found")):
                state = "inactive"
            elif output.strip() in {"", "exit=0"}:
                state = "inactive"
            else:
                state = "unknown"
            detail_lines = [line.strip() for line in output.splitlines() if line.strip()]
            detail = detail_lines[-1] if detail_lines else f"{label}: exit={returncode}"
            self._pgvector_status = state
            self._pgvector_status_detail = detail[:120]
            self._pgvector_status_checked = datetime.now().strftime("%H:%M:%S")
            self._refresh_overview()

        def _status_bar(self, state: str, *, width: int = 14) -> str:
            if state in {"active", "ok", "set"}:
                return _ui_bars.solid(1.0, width=width, style=_ui_bars.OK_STYLE, show_pct=False)
            if state in {"inactive", "missing", "unset", "warn"}:
                return _ui_bars.solid(1.0, width=width, style=_ui_bars.WARN_STYLE, show_pct=False)
            if state == "error":
                return _ui_bars.error(1.0, width=width, note="error")
            return _ui_bars.indeterminate(self._overview_phase, width=width, style=_ui_bars.RUN_STYLE)

        def _overview_status_line(self, label: str, state: str, detail: str) -> str:
            state_label = {
                "active": "[green]active[/]",
                "ok": "[green]ok[/]",
                "set": "[green]set[/]",
                "inactive": "[yellow]inactive[/]",
                "missing": "[yellow]missing[/]",
                "unset": "[yellow]unset[/]",
                "warn": "[yellow]warn[/]",
                "error": "[red]error[/]",
                "unknown": "[cyan]unknown[/]",
            }.get(state, f"[cyan]{escape(state)}[/]")
            return f"  {label:<13} {self._status_bar(state)} {state_label}  {escape(detail)}"

        def _path_state(self, path: Path, *, directory: bool = False) -> str:
            try:
                if directory:
                    return "set" if path.exists() and path.is_dir() else "missing"
                return "set" if path.exists() else "missing"
            except OSError:
                return "error"

        def _settings_value(self, selector: str, env_key: str = "") -> str:
            try:
                value = self.query_one(selector, Input).value.strip()
            except Exception:
                value = ""
            if value:
                return value
            return os.environ.get(env_key, "").strip() if env_key else ""

        def _refresh_overview(self) -> None:
            try:
                metrics = self.controller._collect_metrics()
                source_tokens = self._token_source_total
                machine_tokens = self._token_machine_total
                compressed = max(source_tokens - machine_tokens, 0)
                savings_ratio = 0.0 if source_tokens == 0 else compressed / float(source_tokens)
                total = max(metrics.total_records, 1)
                db_path = Path(metrics.db_path)
                db_state = "ok" if db_path.exists() else "missing"
                local_env_path = self._local_env_path()
                transcript_dir = Path(
                    self._settings_value("#cfg-transcript-dir", "SEAM_CHAT_TRANSCRIPT_DIR") or ".seam/chat_transcripts"
                )
                config_dir = Path.home() / "Documents" / "SEAM"
                pgvector_env_state = "set" if self._settings_value("#cfg-pgvector-dsn", "SEAM_PGVECTOR_DSN") else "unset"
                chat_state = "set" if (
                    self._settings_value("#cfg-api-key", "SEAM_CHAT_API_KEY")
                    or os.environ.get("OPENAI_API_KEY", "").strip()
                    or os.environ.get("OPENROUTER_API_KEY", "").strip()
                ) else "unset"
                rest_state = "set" if self._settings_value("#cfg-api-token", "SEAM_API_TOKEN") else "unset"
                lines = [
                    "--- Live Health Bars -----------------------------",
                    self._overview_status_line("Database", db_state, f"{metrics.db_size} at {metrics.db_path}"),
                    self._overview_status_line(
                        "pgvector",
                        self._pgvector_status,
                        f"{self._pgvector_status_detail}  checked={self._pgvector_status_checked}",
                    ),
                    self._overview_status_line("pg DSN", pgvector_env_state, "SEAM_PGVECTOR_DSN configured" if pgvector_env_state == "set" else "SEAM_PGVECTOR_DSN not set"),
                    self._overview_status_line("Chat/API", chat_state, f"{self.chat_client.model} via {self.chat_client.base_url}"),
                    self._overview_status_line("REST token", rest_state, "SEAM_API_TOKEN set" if rest_state == "set" else "local unauthenticated mode"),
                    f"  {'Runtime pulse':<13} {_ui_bars.indeterminate(self._overview_phase, width=14, style=_ui_bars.RUN_STYLE)} [cyan]live[/]",
                    "",
                    "--- Settings Paths --------------------------------",
                    self._overview_status_line("DB path", db_state, metrics.db_path),
                    self._overview_status_line("Local env", self._path_state(local_env_path), str(local_env_path)),
                    self._overview_status_line("Transcript", self._path_state(transcript_dir, directory=True), str(transcript_dir)),
                    self._overview_status_line("Config dir", self._path_state(config_dir, directory=True), str(config_dir)),
                    self._overview_status_line("Compose env", self._path_state(local_env_path), str(local_env_path)),
                    "",
                    "--- Settings Values -------------------------------",
                    f"  Embedding     {escape(self._settings_value('#cfg-embed-provider', 'SEAM_EMBEDDING_PROVIDER') or 'hash')} / {escape(self._settings_value('#cfg-embed-model', 'SEAM_EMBEDDING_MODEL') or metrics.model_name)}",
                    f"  Surface mode  {escape(self._settings_value('#cfg-surface-mode', 'SEAM_SURFACE_MODE') or 'rgb24')}",
                    f"  Rate limit    {escape(self._settings_value('#cfg-rate-limit-min', 'SEAM_API_RATE_LIMIT_PER_MINUTE') or 'off')}",
                    self._overview_status_line("OpenAI key", "set" if self._settings_value("#cfg-key-openai", "OPENAI_API_KEY") else "unset", "OPENAI_API_KEY"),
                    self._overview_status_line("OpenRouter", "set" if self._settings_value("#cfg-key-openrouter", "OPENROUTER_API_KEY") else "unset", "OPENROUTER_API_KEY"),
                    self._overview_status_line("Anthropic", "set" if self._settings_value("#cfg-key-anthropic", "ANTHROPIC_API_KEY") else "unset", "ANTHROPIC_API_KEY"),
                    self._overview_status_line("Gemini", "set" if self._settings_value("#cfg-key-gemini", "GEMINI_API_KEY") else "unset", "GEMINI_API_KEY"),
                    "",
                    "--- Record Counts ---------------------------------",
                    f"  Total         {metrics.total_records}",
                    f"  Vectors       {metrics.vector_entries}",
                    f"  Packs         {metrics.pack_entries}",
                    f"  Provenance    {metrics.provenance_entries}",
                    f"  Symbols       {metrics.symbol_entries}",
                    f"  Raw docs      {metrics.raw_entries}",
                    f"  Namespaces    {metrics.namespaces}    Scopes  {metrics.scopes}",
                    f"  Adapter       {metrics.vector_adapter_name}   store={metrics.vector_store_size}",
                    "",
                    "--- Top Record Kinds ------------------------------",
                ]
                for kind, count in metrics.top_kinds:
                    bar = _ui_bars.solid(count / total, width=20, show_pct=False)
                    lines.append(f"  {kind:<12} {count:>5}  {bar}")
                if not metrics.top_kinds:
                    lines.append("  (no records yet)")
                lines += [
                    "",
                    "--- Token Budget ----------------------------------",
                    f"  Source tokens   {source_tokens}",
                    f"  Machine tokens  {machine_tokens}",
                    f"  Savings         {self._bar(savings_ratio, 20)}",
                    "",
                    "--- Quick Commands --------------------------------",
                    "  /compile <text>     compile NL into MIRL",
                    "  /search  <query>    lexical + vector search",
                    "  /benchmark <file>   lossless compression benchmark",
                    "  /stats              refresh all metrics",
                ]
                panel = self.query_one("#overview-panel", _TextualMarkupPanel)
                previous_y = float(panel.scroll_y)
                previous_max = float(panel.max_scroll_y)
                preserve_y = previous_y if previous_y < max(previous_max - 1.0, 0.0) else None
                panel.set_lines(lines)
                if preserve_y is not None:
                    panel.scroll_to(y=preserve_y, animate=False, force=True, immediate=True)
                return
                lines = [
                    "─── SEAM Runtime Overview ─────────────────────────────────",
                    f"  Database   {metrics.db_path}",
                    f"  Size       {metrics.db_size}   execution={metrics.execution_mode}",
                    f"  Model      {metrics.model_name}",
                    f"  Adapter    {metrics.vector_adapter_name}   pgvector={'configured' if metrics.pgvector_configured else 'not set'}",
                    "",
                    "─── Record Counts ─────────────────────────────────────────",
                    f"  Total       {metrics.total_records}",
                    f"  Vectors     {metrics.vector_entries}",
                    f"  Packs       {metrics.pack_entries}",
                    f"  Provenance  {metrics.provenance_entries}",
                    f"  Symbols     {metrics.symbol_entries}",
                    f"  Raw docs    {metrics.raw_entries}",
                    f"  Namespaces  {metrics.namespaces}    Scopes  {metrics.scopes}",
                    "",
                    "─── Top Record Kinds ──────────────────────────────────────",
                ]
                for kind, count in metrics.top_kinds:
                    bar = _ui_bars.solid(count / total, width=20, show_pct=False)
                    lines.append(f"  {kind:<12} {count:>5}  {bar}")
                if not metrics.top_kinds:
                    lines.append("  (no records yet)")
                lines += [
                    "",
                    "─── Token Budget ──────────────────────────────────────────",
                    f"  Source tokens   {source_tokens}",
                    f"  Machine tokens  {machine_tokens}",
                    f"  Savings         {self._bar(savings_ratio, 20)}",
                    "",
                    "─── Quick Commands ────────────────────────────────────────",
                    "  /compile <text>     compile NL into MIRL",
                    "  /search  <query>    lexical + vector search",
                    "  /benchmark <file>   lossless compression benchmark",
                    "  /stats              refresh all metrics",
                ]
                self.query_one("#overview-panel", _TextualMarkupPanel).set_lines(lines)
            except Exception:
                return

        def _capture_token_metrics_from_command(self, command: str) -> None:
            token = command.split()[0].lower()
            source_tokens: int | None = None
            machine_tokens: int | None = None
            if token == "benchmark" and self.controller.last_benchmark_payload:
                artifact = self.controller.last_benchmark_payload.get("artifact", {})
                source_tokens = int(artifact.get("source_tokens", 0) or 0)
                machine_tokens = int(artifact.get("machine_tokens", 0) or 0)
            elif token in {"compress-doc", "lossless-compress", "readable-compress", "compress-readable"}:
                try:
                    payload = json.loads(self.controller.result_body)
                    source_tokens = int(payload.get("source_tokens", payload.get("original_tokens", 0)) or 0)
                    machine_tokens = int(payload.get("machine_tokens", 0) or 0)
                except Exception:
                    pass
            if source_tokens is not None and machine_tokens is not None and source_tokens > 0:
                self._token_source_total += source_tokens
                self._token_machine_total += machine_tokens
                self._token_events.append((time.monotonic(), source_tokens))

        def _estimate_token_rate(self) -> float:
            if len(self._token_events) < 2:
                return 0.0
            first_t, _ = self._token_events[0]
            last_t, _ = self._token_events[-1]
            elapsed = max(1e-6, last_t - first_t)
            total = sum(tokens for _, tokens in self._token_events)
            return total / elapsed

        @staticmethod
        def _bar(ratio: float, width: int = 24) -> str:
            # Thin shim over ui.bars.solid — old callers expect a single
            # string, the new bar emits Rich markup which Static renders
            # natively. If you need a different bar kind (segmented,
            # indeterminate, error), call ui.bars directly at the use
            # site rather than overloading this helper.
            return _ui_bars.solid(ratio, width=width)

        @staticmethod
        def _format_elapsed(seconds: float) -> str:
            if seconds < 1.0:
                return f"{int(round(seconds * 1000))}ms"
            return f"{seconds:.2f}s"

        def _default_chat_export_path(self) -> Path:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            return self.transcript_dir / f"chat-{stamp}.jsonl"

        def _save_chat_transcript(self, destination: Path) -> tuple[Path, int]:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8") as handle:
                for idx, message in enumerate(self.chat_history, start=1):
                    row = {
                        "index": idx,
                        "role": str(message.get("role", "")),
                        "content": str(message.get("content", "")),
                    }
                    handle.write(json.dumps(row, sort_keys=True))
                    handle.write("\n")
            return destination.resolve(), len(self.chat_history)

        def _update_status(self, message: str = "") -> None:  # pragma: no cover - textual runtime behavior
            try:
                metrics = self.controller._collect_metrics()
                mode_str = f"mode:{self.input_mode}"
                rec_str = f"records:{metrics.total_records}"
                right = f"{mode_str}  {rec_str}  {metrics.db_path}"
                text = f" {message}{'  ' if message else ''}{right}"
                self.query_one("#status-bar", Static).update(text)
            except Exception:
                return

        def action_toggle_sidebar(self) -> None:  # pragma: no cover - textual runtime behavior
            try:
                tree = self.query_one("#explorer-tree", ExplorerTree)
                tree.display = not tree.display
            except Exception:
                return

        def action_toggle_zoom(self) -> None:  # pragma: no cover - textual runtime behavior
            target = self.focused
            if target is None:
                return
            zoomable_ids = {
                "explorer-tree",
                "overview-panel",
                "memory-panel",
                "retrieval-panel",
                "benchmark-panel",
                "mirl-panel",
                "runtime-log-panel",
                "command-history-panel",
                "prov-panel",
                "chat-panel",
                "result-panel",
            }
            target_id = getattr(target, "id", None)
            if target_id not in zoomable_ids:
                return
            if "zoomed" in target.classes:
                target.remove_class("zoomed")
                self._update_status("Zoom cleared")
                return
            for widget in self.query(".zoomed"):
                widget.remove_class("zoomed")
            target.add_class("zoomed")
            self._update_status(f"Zoomed: {target_id}")

        def action_sidebar_grow(self) -> None:  # pragma: no cover - textual runtime behavior
            try:
                tree = self.query_one("#explorer-tree", ExplorerTree)
                self._sidebar_width = min(self._sidebar_width + 4, 60)
                tree.styles.width = self._sidebar_width
            except Exception:
                return

        def action_sidebar_shrink(self) -> None:  # pragma: no cover - textual runtime behavior
            try:
                tree = self.query_one("#explorer-tree", ExplorerTree)
                self._sidebar_width = max(self._sidebar_width - 4, 14)
                tree.styles.width = self._sidebar_width
            except Exception:
                return

        def action_rightcol_grow(self) -> None:  # pragma: no cover - textual runtime behavior
            try:
                col = self.query_one("#right-col", Vertical)
                self._rightcol_width = min(self._rightcol_width + 4, 80)
                col.styles.width = self._rightcol_width
            except Exception:
                return

        def action_rightcol_shrink(self) -> None:  # pragma: no cover - textual runtime behavior
            try:
                col = self.query_one("#right-col", Vertical)
                self._rightcol_width = max(self._rightcol_width - 4, 20)
                col.styles.width = self._rightcol_width
            except Exception:
                return

else:
    class TextualDashboardApp:  # pragma: no cover - exercised when textual is missing
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ensure_textual()


class DashboardApp:
    def __init__(
        self,
        runtime: SeamRuntime,
        vector_backend: str = "seam",
        vector_path: str = ".seam_chroma",
        vector_collection: str = "seam_hybrid",
        console: Console | None = None,
        no_clear: bool = False,
    ) -> None:
        _ensure_rich()
        self.runtime = runtime
        self.console = console or Console(legacy_windows=False)
        self.vector_backend = vector_backend
        self.vector_path = vector_path
        self.vector_collection = vector_collection
        self.no_clear = no_clear
        self.orchestrator = _build_retrieval_orchestrator(
            runtime,
            vector_backend=vector_backend,
            vector_path=vector_path,
            vector_collection=vector_collection,
        )
        self.events: deque[DashboardEvent] = deque(maxlen=2000)
        self.active_tab = "runtime"
        self.last_benchmark_payload: dict[str, Any] | None = None
        self.last_machine_text: str | None = None
        self.last_command = "help"
        self.last_command_ok = True
        self.result_title = "Welcome"
        self.result_body = (
            "SEAM dashboard is live.\n\n"
            "Try commands like:\n"
            "  compile We need durable memory for AI systems\n"
            "  retrieve translator natural language\n"
            "  context translator natural language\n"
            "  stats\n"
            "  help\n"
            "  quit"
        )
        self.command_parser = self._build_command_parser()
        self._log("system", f"Dashboard attached to {self.runtime.store.path}")

    def _build_command_parser(self) -> DashboardParser:
        parser = DashboardParser(add_help=False, prog="seam-dashboard")
        subparsers = parser.add_subparsers(dest="command")

        help_parser = subparsers.add_parser("help", add_help=False)
        help_parser.add_argument("topic", nargs="?")

        quit_parser = subparsers.add_parser("quit", add_help=False, aliases=["exit"])
        quit_parser.add_argument("rest", nargs="*")

        tab_parser = subparsers.add_parser("tab", add_help=False)
        tab_parser.add_argument("view", choices=["runtime", "benchmark"])

        compile_parser = subparsers.add_parser("compile", add_help=False, aliases=["compile-nl"])
        compile_parser.add_argument("text", nargs="+")
        compile_parser.add_argument("--scope", default="thread")
        compile_parser.add_argument("--ns", default="local.default")
        compile_parser.add_argument("--source-ref", default="dashboard://interactive")
        compile_parser.add_argument("--no-index", action="store_true")

        dsl_parser = subparsers.add_parser("compile-dsl", add_help=False, aliases=["dsl"])
        dsl_parser.add_argument("file")
        dsl_parser.add_argument("--scope", default="project")
        dsl_parser.add_argument("--ns", default="local.default")
        dsl_parser.add_argument("--no-index", action="store_true")

        for name in ("search", "plan", "retrieve", "context"):
            command_parser = subparsers.add_parser(name, add_help=False)
            command_parser.add_argument("query", nargs="+")
            command_parser.add_argument("--scope")
            command_parser.add_argument("--budget", type=int, default=5)
            if name == "context":
                command_parser.add_argument("--pack-budget", type=int, default=512)
                command_parser.add_argument("--lens", default="rag")
                command_parser.add_argument("--mode", choices=["context", "narrative", "exact"], default="context")
                command_parser.add_argument("--view", choices=CONTEXT_VIEWS, default="pack")
            else:
                command_parser.add_argument("--trace", action="store_true")

        index_parser = subparsers.add_parser("index", add_help=False)
        index_parser.add_argument("--scope")
        index_parser.add_argument("--namespace")
        index_parser.add_argument("--record-ids", default="")

        trace_parser = subparsers.add_parser("trace", add_help=False)
        trace_parser.add_argument("obj_id")

        benchmark_parser = subparsers.add_parser("benchmark", add_help=False)
        benchmark_parser.add_argument("source")
        benchmark_parser.add_argument("--codec", choices=["auto", *LOSSLESS_CODECS], default="auto")
        benchmark_parser.add_argument("--transform", choices=["auto", *LOSSLESS_TRANSFORMS], default="auto")
        benchmark_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
        benchmark_parser.add_argument("--min-savings", type=float, default=0.30)
        benchmark_parser.add_argument("--show-machine", action="store_true")

        compress_parser = subparsers.add_parser("compress-doc", add_help=False, aliases=["lossless-compress"])
        compress_parser.add_argument("source")
        compress_parser.add_argument("--codec", choices=["auto", *LOSSLESS_CODECS], default="auto")
        compress_parser.add_argument("--transform", choices=["auto", *LOSSLESS_TRANSFORMS], default="auto")
        compress_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")

        readable_compress_parser = subparsers.add_parser("readable-compress", add_help=False, aliases=["compress-readable"])
        readable_compress_parser.add_argument("source")
        readable_compress_parser.add_argument("--source-ref")
        readable_compress_parser.add_argument("--granularity", choices=READABLE_GRANULARITIES, default="auto")
        readable_compress_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")

        readable_query_parser = subparsers.add_parser("readable-query", add_help=False, aliases=["query-compressed"])
        readable_query_parser.add_argument("source")
        readable_query_parser.add_argument("query", nargs="+")
        readable_query_parser.add_argument("--limit", type=int, default=5)

        readable_rebuild_parser = subparsers.add_parser("readable-rebuild", add_help=False)
        readable_rebuild_parser.add_argument("source")

        decompress_parser = subparsers.add_parser("decompress-doc", add_help=False, aliases=["lossless-decompress"])
        decompress_parser.add_argument("source")

        subparsers.add_parser("decompress-last", add_help=False)

        stats_parser = subparsers.add_parser("stats", add_help=False)
        stats_parser.add_argument("rest", nargs="*")

        reload_parser = subparsers.add_parser("reload", add_help=False, aliases=["refresh"])
        reload_parser.add_argument("rest", nargs="*")
        return parser

    def run_script(self, commands: list[str], render_each: bool = False) -> None:
        for command in commands:
            should_exit = self.execute(command)
            if render_each:
                self.render()
            if should_exit:
                break
        if not render_each:
            self.render()

    def run_interactive(self) -> None:  # pragma: no cover - interactive shell path
        while True:
            self.render()
            raw_command = Prompt.ask("[bold cyan]seam[/bold cyan]")
            should_exit = self.execute(raw_command)
            if should_exit:
                self.render()
                return

    def execute(self, raw_command: str) -> bool:
        command = raw_command.strip()
        if not command:
            self.result_title = "No Command"
            self.result_body = "Enter a command or type `help`."
            self.last_command_ok = False
            return False

        self.last_command = command
        try:
            args = self.command_parser.parse_args(self._split_command(command))
        except ValueError as exc:
            self._fail("Command Error", str(exc))
            return False

        if args.command in {"quit", "exit"}:
            self.result_title = "Dashboard Exit"
            self.result_body = "SEAM dashboard closed cleanly."
            self._log("system", "Dashboard shutdown requested.")
            self.last_command_ok = True
            return True
        if args.command == "help":
            self.result_title = "Dashboard Help"
            self.result_body = self._help_text()
            self._log("help", "Displayed interactive command help.")
            self.last_command_ok = True
            return False
        if args.command == "tab":
            self.active_tab = args.view
            self.result_title = "Dashboard Tab"
            self.result_body = f"Switched to the {args.view} tab."
            self._log("system", f"Switched dashboard tab to {args.view}.")
            self.last_command_ok = True
            return False

        try:
            if args.command in {"compile", "compile-nl"}:
                batch = self.runtime.compile_nl(
                    " ".join(args.text),
                    source_ref=args.source_ref,
                    ns=args.ns,
                    scope=args.scope,
                )
                report = self.runtime.persist_ir(batch).to_dict()
                index_report = None
                if not args.no_index:
                    index_report = self.orchestrator.sync_persistent_indexes(record_ids=[record.id for record in batch.records])
                payload = {"persist": report, "index": index_report, "records": batch.to_json()}
                self._succeed("Compile", payload, f"Compiled and stored {len(batch.records)} MIRL records.")
                return False

            if args.command in {"compile-dsl", "dsl"}:
                batch = self.runtime.compile_dsl(Path(args.file).read_text(encoding="utf-8"), ns=args.ns, scope=args.scope)
                report = self.runtime.persist_ir(batch).to_dict()
                index_report = None
                if not args.no_index:
                    index_report = self.orchestrator.sync_persistent_indexes(record_ids=[record.id for record in batch.records])
                payload = {"persist": report, "index": index_report, "records": batch.to_json()}
                self._succeed("Compile DSL", payload, f"Compiled DSL file {args.file}.")
                return False

            if args.command == "search":
                result = self.runtime.search_ir(" ".join(args.query), scope=args.scope, budget=args.budget).to_dict()
                self._succeed("Search", result, f"Ran lexical/vector search with budget {args.budget}.")
                return False

            if args.command == "plan":
                result = self.orchestrator.plan(" ".join(args.query), scope=args.scope, budget=args.budget).to_dict()
                self._succeed("Plan", result, "Built retrieval plan.")
                return False

            if args.command == "retrieve":
                result = self.orchestrator.search(
                    " ".join(args.query),
                    scope=args.scope,
                    budget=args.budget,
                    include_trace=args.trace,
                ).to_dict()
                self._succeed("Retrieve", result, "Ran ranked retrieval across active legs.")
                return False

            if args.command == "context":
                result = build_context_payload(
                    self.orchestrator.rag(
                        " ".join(args.query),
                        scope=args.scope,
                        budget=args.budget,
                        pack_budget=args.pack_budget,
                        lens=args.lens,
                        mode=args.mode,
                    ).to_dict(),
                    view=args.view,
                )
                self._succeed("Context", result, "Built generation context from retrieved records.")
                return False

            if args.command == "index":
                result = self.orchestrator.sync_persistent_indexes(
                    record_ids=self._split_ids(args.record_ids),
                    scope=args.scope,
                    namespace=args.namespace,
                )
                self._succeed("Index", result, "Synced persisted records into the active vector backend.")
                return False

            if args.command == "trace":
                result = self.runtime.trace(args.obj_id).to_dict()
                self._succeed("Trace", result, f"Traced provenance for {args.obj_id}.")
                return False

            if args.command == "benchmark":
                benchmark_result = benchmark_text_lossless(
                    self._read_text_source(args.source),
                    codec=args.codec,
                    transform=args.transform,
                    min_token_savings=args.min_savings,
                    tokenizer=args.tokenizer,
                )
                result = benchmark_result.to_dict(include_machine_text=args.show_machine)
                self.last_benchmark_payload = result
                self.last_machine_text = benchmark_result.artifact.machine_text
                self.active_tab = "benchmark"
                self._succeed("Benchmark", result, "Ran iterative lossless benchmark search.")
                return False

            if args.command in {"compress-doc", "lossless-compress"}:
                artifact = compress_text_lossless(
                    self._read_text_source(args.source),
                    codec=args.codec,
                    transform=args.transform,
                    tokenizer=args.tokenizer,
                ).to_dict(include_machine_text=True)
                self.last_machine_text = str(artifact.get("machine_text", ""))
                self.active_tab = "benchmark"
                self._succeed("Compress Doc", artifact, "Built lossless machine text.")
                return False

            if args.command in {"readable-compress", "compress-readable"}:
                artifact = compress_text_readable(
                    self._read_text_source(args.source),
                    source_ref=args.source_ref or str(args.source),
                    granularity=args.granularity,
                    tokenizer=args.tokenizer,
                ).to_dict(include_machine_text=True)
                self.last_machine_text = str(artifact.get("machine_text", ""))
                self.active_tab = "benchmark"
                self._succeed("Readable Compress", artifact, "Built directly readable SEAM-RC/1 machine language.")
                return False

            if args.command in {"readable-query", "query-compressed"}:
                result = query_readable_compressed(
                    self._read_text_source(args.source),
                    " ".join(args.query),
                    limit=args.limit,
                ).to_dict()
                self.active_tab = "benchmark"
                self._succeed("Readable Query", result, "Queried SEAM-RC/1 without rebuilding source text.")
                return False

            if args.command == "readable-rebuild":
                text = decompress_text_readable(self._read_text_source(args.source))
                self.active_tab = "benchmark"
                self._succeed("Readable Rebuild", text, "Verified and rebuilt exact text from SEAM-RC/1.")
                return False

            if args.command in {"decompress-doc", "lossless-decompress"}:
                text = decompress_text_lossless(self._read_text_source(args.source))
                self.active_tab = "benchmark"
                self._succeed("Decompress Doc", text, "Restored source document from machine text.")
                return False

            if args.command == "decompress-last":
                if not self.last_machine_text:
                    raise ValueError("No in-memory machine text is available yet. Run benchmark or compress-doc first.")
                text = decompress_text_lossless(self.last_machine_text)
                self.active_tab = "benchmark"
                self._succeed("Decompress Last", text, "Restored the latest machine text from the benchmark tab.")
                return False

            if args.command == "stats":
                metrics = self._collect_metrics()
                payload = {
                    "db_path": metrics.db_path,
                    "db_size": metrics.db_size,
                    "total_records": metrics.total_records,
                    "vector_entries": metrics.vector_entries,
                    "pack_entries": metrics.pack_entries,
                    "provenance_entries": metrics.provenance_entries,
                    "symbol_entries": metrics.symbol_entries,
                    "raw_entries": metrics.raw_entries,
                    "namespaces": metrics.namespaces,
                    "scopes": metrics.scopes,
                    "top_kinds": metrics.top_kinds,
                    "model_name": metrics.model_name,
                    "execution_mode": metrics.execution_mode,
                    "vector_adapter": metrics.vector_adapter_name,
                    "pgvector_configured": metrics.pgvector_configured,
                    "vector_store_size": metrics.vector_store_size,
                }
                self._succeed("Stats", payload, "Refreshed runtime metrics.")
                return False

            if args.command in {"reload", "refresh"}:
                self.orchestrator = _build_retrieval_orchestrator(
                    self.runtime,
                    vector_backend=self.vector_backend,
                    vector_path=self.vector_path,
                    vector_collection=self.vector_collection,
                )
                metrics = self._collect_metrics()
                payload = {
                    "status": "reloaded",
                    "db_path": metrics.db_path,
                    "db_size": metrics.db_size,
                    "total_records": metrics.total_records,
                    "vector_entries": metrics.vector_entries,
                    "pack_entries": metrics.pack_entries,
                    "provenance_entries": metrics.provenance_entries,
                    "symbol_entries": metrics.symbol_entries,
                    "raw_entries": metrics.raw_entries,
                    "namespaces": metrics.namespaces,
                    "scopes": metrics.scopes,
                    "top_kinds": metrics.top_kinds,
                    "model_name": metrics.model_name,
                    "execution_mode": metrics.execution_mode,
                    "vector_adapter": metrics.vector_adapter_name,
                    "pgvector_configured": metrics.pgvector_configured,
                    "vector_store_size": metrics.vector_store_size,
                    "active_tab": self.active_tab,
                    "refreshed_at": datetime.now().isoformat(timespec="seconds"),
                }
                self._succeed("Reload", payload, "Reloaded dashboard runtime state, metrics, and derived charts.")
                return False
        except Exception as exc:  # pragma: no cover - error handling path is exercised through scripted smoke
            self._fail(type(exc).__name__, str(exc))
            return False

        self._fail("Command Error", f"Unknown command: {args.command}")
        return False

    def render(self) -> None:
        metrics = self._collect_metrics()
        if not self.no_clear:
            self.console.clear()
        self.console.print(self._build_dashboard(metrics))

    def _build_dashboard(self, metrics: DashboardMetrics):
        return Group(
            self._build_header(metrics),
            self._build_runtime_panels(metrics),
            self._build_activity_panels(metrics),
        )

    def _build_header(self, metrics: DashboardMetrics) -> Panel:
        title = Text("SEAM Console", style="bold cyan")
        db_line = Text(f"db={metrics.db_path}  records={metrics.total_records}", style="dim white")
        tabs = Text()
        tabs.append(" Runtime ", style="bold black on bright_white" if self.active_tab == "runtime" else "white on grey23")
        tabs.append("  ")
        tabs.append(" Benchmark ", style="bold black on bright_white" if self.active_tab == "benchmark" else "white on grey23")
        return Panel(Group(title, db_line, tabs), border_style="bright_blue", box=box.ROUNDED)

    def _build_runtime_panels(self, metrics: DashboardMetrics):
        pgvector_status = "[green]configured[/green]" if metrics.pgvector_configured else "[dim]not set[/dim]"
        runtime_table = Table.grid(expand=True, padding=(0, 1))
        runtime_table.add_column(no_wrap=True)
        runtime_table.add_column(ratio=1)
        runtime_table.add_row("Execution Mode", metrics.execution_mode)
        runtime_table.add_row("Embedding Model", metrics.model_name)
        runtime_table.add_row("Vector Adapter", metrics.vector_adapter_name)
        runtime_table.add_row("PgVector DSN", pgvector_status)

        storage_table = Table.grid(expand=True, padding=(0, 1))
        storage_table.add_column(ratio=1)
        storage_table.add_column(justify="right")
        storage_table.add_row("DB Size", metrics.db_size)
        storage_table.add_row("Vector Store Size", metrics.vector_store_size)
        storage_table.add_row("Records", str(metrics.total_records))
        storage_table.add_row("Vectors", str(metrics.vector_entries))
        storage_table.add_row("Packs", str(metrics.pack_entries))
        storage_table.add_row("Provenance", str(metrics.provenance_entries))
        storage_table.add_row("Symbols", str(metrics.symbol_entries))
        storage_table.add_row("Raw Docs", str(metrics.raw_entries))
        storage_table.add_row("Namespaces / Scopes", f"{metrics.namespaces} / {metrics.scopes}")

        kinds_table = Table.grid(expand=True, padding=(0, 1))
        kinds_table.add_column(ratio=1)
        kinds_table.add_column(justify="right")
        for kind, count in metrics.top_kinds:
            kinds_table.add_row(kind, str(count))
        if not metrics.top_kinds:
            kinds_table.add_row("No persisted records", "0")

        panels = Table.grid(expand=True)
        panels.add_column(ratio=1)
        panels.add_column(ratio=1)
        panels.add_column(ratio=1)
        third_panel = (
            Panel(self._build_benchmark_summary_table(), title="[cyan]Benchmark[/cyan]", border_style="bright_blue", box=box.ROUNDED)
            if self.active_tab == "benchmark"
            else Panel(kinds_table, title="[cyan]Top Kinds[/cyan]", border_style="bright_blue", box=box.ROUNDED)
        )
        panels.add_row(
            Panel(runtime_table, title="[cyan]Runtime[/cyan]", border_style="bright_blue", box=box.ROUNDED),
            Panel(storage_table, title="[cyan]Storage[/cyan]", border_style="bright_blue", box=box.ROUNDED),
            third_panel,
        )
        return panels

    def _build_activity_panels(self, metrics: DashboardMetrics):
        body = Table.grid(expand=True)
        body.add_column(ratio=3)
        body.add_column(ratio=2)
        side_group = (
            Group(
                Panel(self._build_benchmark_log_table(), title="[cyan]Benchmark Log[/cyan]", border_style="bright_blue", box=box.ROUNDED),
                Panel(self._build_command_help(), title="[cyan]Commands[/cyan]", border_style="bright_blue", box=box.ROUNDED),
            )
            if self.active_tab == "benchmark"
            else Group(
                Panel(self._build_log_table(), title="[cyan]Runtime Log[/cyan]", border_style="bright_blue", box=box.ROUNDED),
                Panel(self._build_command_help(), title="[cyan]Commands[/cyan]", border_style="bright_blue", box=box.ROUNDED),
            )
        )
        body.add_row(
            Panel(self._build_result_body(), title=f"[cyan]{escape(self.result_title)}[/cyan]", border_style="bright_blue", box=box.ROUNDED),
            side_group,
        )
        footer = Panel(
            Text(f"Last command: {self.last_command}", style="green"),
            border_style="blue",
            box=box.ROUNDED,
        )
        return Group(body, footer)

    def _build_result_body(self):
        lines = self.result_body.splitlines() or ["(no output)"]
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        for line in lines[:28]:
            table.add_row(Text(line))
        if len(lines) > 28:
            table.add_row(Text(f"... {len(lines) - 28} more lines", style="dim"))
        return table

    def _build_log_table(self):
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=8, style="dim")
        table.add_column(width=10)
        table.add_column(ratio=1)
        for event in list(self.events)[-8:]:
            style = {
                "system": "cyan",
                "compile": "green",
                "search": "cyan",
                "retrieve": "magenta",
                "context": "green",
                "index": "yellow",
                "trace": "blue",
                "help": "white",
                "error": "red",
            }.get(event.kind, "white")
            table.add_row(event.timestamp, f"[{style}]{event.kind}[/{style}]", event.message)
        return table

    def _build_command_help(self):
        help_lines = [
            ("tab", "runtime|benchmark"),
            ("compile", "<text>"),
            ("compile-dsl", "<file>"),
            ("search", "<query> [--budget N]"),
            ("plan", "<query>"),
            ("retrieve", "<query> [--budget N] [--trace]"),
            ("context", "<query> [--view pack|prompt|evidence|summary]"),
            ("benchmark", "<file> [--min-savings N] [--tokenizer auto|...]"),
            ("compress-doc", "<file>"),
            ("readable-compress", "<file>"),
            ("readable-query", "<file> <query>"),
            ("readable-rebuild", "<file>"),
            ("decompress-doc / decompress-last", ""),
            ("index", "[--scope S] [--namespace NS]"),
            ("trace", "<record-id>"),
            ("stats", ""),
            ("reload / refresh", ""),
            ("help / quit", ""),
        ]
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(style="cyan", no_wrap=True)
        table.add_column(style="dim white")
        for cmd, args in help_lines:
            table.add_row(cmd, args)
        return table

    def _succeed(self, title: str, payload: object, log_message: str) -> None:
        self.result_title = title
        self.result_body = self._format_payload(payload)
        self.last_command_ok = True
        self._log(title.lower(), log_message)

    def _fail(self, title: str, message: str) -> None:
        self.result_title = title
        self.result_body = message
        self.last_command_ok = False
        self._log("error", message)

    def _log(self, kind: str, message: str) -> None:
        self.events.append(DashboardEvent(timestamp=datetime.now().strftime("%H:%M:%S"), kind=kind, message=message))

    def _format_payload(self, payload: object) -> str:
        if isinstance(payload, IRBatch):
            return payload.to_text()
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict) and "artifact" in payload and "roundtrip_match" in payload:
            from .lossless import render_lossless_benchmark_pretty

            return render_lossless_benchmark_pretty(payload)
        return json.dumps(payload, indent=2, sort_keys=True)

    def _build_benchmark_summary_table(self):
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(justify="right")
        payload = self.last_benchmark_payload
        if not payload:
            table.add_row("State", "No benchmark yet")
            table.add_row("Run", "benchmark <file>")
            return table
        artifact = payload.get("artifact", {})
        table.add_row("Status", "PASS" if payload.get("passed") else "FAIL")
        table.add_row("Roundtrip", "PASS" if payload.get("roundtrip_match") else "FAIL")
        table.add_row("Transform", str(artifact.get("transform")))
        table.add_row("Codec", str(artifact.get("codec")))
        table.add_row("Tokenizer", str(artifact.get("token_estimator")))
        table.add_row("Savings", f"{float(artifact.get('token_savings_ratio', 0.0)):.1%}")
        table.add_row("Gain", f"{float(artifact.get('intelligence_per_token_gain', 0.0)):.2f}x")
        table.add_row("Flags", str(len(payload.get("flags", []))))
        return table

    def _build_benchmark_log_table(self):
        table = Table.grid(expand=True)
        table.add_column(width=6, style="dim")
        table.add_column(width=14)
        table.add_column(ratio=1)
        payload = self.last_benchmark_payload or {}
        attempts = payload.get("search_log", [])
        if not attempts:
            table.add_row("-", "benchmark", "Run a benchmark to populate the search log.")
            return table
        for attempt in attempts[-8:]:
            flags = f" flags={','.join(attempt.get('flags', []))}" if attempt.get("flags") else ""
            detail = (
                f"{attempt.get('transform')}/{attempt.get('codec')} "
                f"savings={float(attempt.get('token_savings_ratio', 0.0)):.1%} "
                f"tokens={attempt.get('machine_tokens')}{flags}"
            )
            table.add_row(str(attempt.get("iteration")), str(attempt.get("status")), detail)
        return table

    def _collect_metrics(self) -> DashboardMetrics:
        db_path = Path(self.runtime.store.path)
        model = self.runtime.embedding_model
        if isinstance(model, HashEmbeddingModel):
            execution_mode = "local"
        elif getattr(model, "name", "").startswith("st:"):
            execution_mode = "local (neural)"
        else:
            execution_mode = "cloud"
        db_size = self._format_bytes(db_path.stat().st_size if db_path.exists() else 0)
        vector_store_size = self._format_bytes(self._directory_size(Path(self.vector_path))) if self.vector_backend == "chroma" else "embedded"
        vector_adapter_name = getattr(self.runtime.vector_adapter, "name", "unknown")
        pgvector_configured = bool(os.environ.get("SEAM_PGVECTOR_DSN"))

        total_records = 0
        vector_entries = 0
        pack_entries = 0
        provenance_entries = 0
        symbol_entries = 0
        raw_entries = 0
        namespaces = 0
        scopes = 0
        top_kinds: list[tuple[str, int]] = []

        with sqlite3.connect(self.runtime.store.path) as connection:
            cursor = connection.cursor()
            total_records = cursor.execute("select count(*) from ir_records").fetchone()[0]
            vector_entries = cursor.execute("select count(*) from vector_index").fetchone()[0]
            pack_entries = cursor.execute("select count(*) from pack_store").fetchone()[0]
            provenance_entries = cursor.execute("select count(*) from prov_log").fetchone()[0]
            symbol_entries = cursor.execute("select count(*) from symbol_table").fetchone()[0]
            raw_entries = cursor.execute("select count(*) from raw_docs").fetchone()[0]
            namespaces = cursor.execute("select count(distinct ns) from ir_records").fetchone()[0]
            scopes = cursor.execute("select count(distinct scope) from ir_records").fetchone()[0]
            top_kinds = cursor.execute(
                "select kind, count(*) as n from ir_records group by kind order by n desc, kind asc limit 5"
            ).fetchall()
        return DashboardMetrics(
            db_path=str(db_path),
            db_size=db_size,
            total_records=total_records,
            vector_entries=vector_entries,
            pack_entries=pack_entries,
            provenance_entries=provenance_entries,
            symbol_entries=symbol_entries,
            raw_entries=raw_entries,
            namespaces=namespaces,
            scopes=scopes,
            top_kinds=[(str(kind), int(count)) for kind, count in top_kinds],
            model_name=self.runtime.embedding_model.name,
            execution_mode=execution_mode,
            vector_adapter_name=vector_adapter_name,
            pgvector_configured=pgvector_configured,
            vector_store_size=vector_store_size,
        )

    def _help_text(self) -> str:
        return (
            "SEAM dashboard commands\n\n"
            "tab runtime|benchmark\n"
            "compile <text>\n"
            "compile-dsl <file>\n"
            "search <query> [--budget N]\n"
            "plan <query> [--budget N]\n"
            "retrieve <query> [--budget N] [--trace]\n"
            "context <query> [--budget N] [--pack-budget N] [--view pack|prompt|evidence|summary|records]\n"
            "benchmark <file> [--min-savings N] [--tokenizer auto|char4_approx|cl100k_base|o200k_base]\n"
            "compress-doc <file> [--tokenizer auto|char4_approx|cl100k_base|o200k_base]\n"
            "readable-compress <file> [--granularity auto|line|paragraph|chunk]\n"
            "readable-query <file> <query> [--limit N]\n"
            "readable-rebuild <file>\n"
            "decompress-doc <file>\n"
            "decompress-last\n"
            "index [--scope S] [--namespace NS]\n"
            "trace <record-id>\n"
            "stats\n"
            "reload\n"
            "quit"
        )

    @staticmethod
    def _split_ids(text: str) -> list[str] | None:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return parts or None

    @staticmethod
    def _split_command(command: str) -> list[str]:
        parts = shlex.split(command, posix=os.name != "nt")
        if os.name == "nt":
            return [
                part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'} else part
                for part in parts
            ]
        return parts

    @staticmethod
    def _read_text_source(source: str) -> str:
        if source == "-":
            return sys.stdin.read()
        return Path(source).read_bytes().decode("utf-8")

    @staticmethod
    def _directory_size(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        unit = units[0]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                break
            size /= 1024
        return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"


def run_dashboard(
    runtime: SeamRuntime,
    vector_backend: str = "seam",
    vector_path: str = ".seam_chroma",
    vector_collection: str = "seam_hybrid",
    snapshot: bool = False,
    commands: list[str] | None = None,
    no_clear: bool = False,
    console: Console | None = None,
) -> None:
    _ensure_rich()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    app = DashboardApp(
        runtime,
        vector_backend=vector_backend,
        vector_path=vector_path,
        vector_collection=vector_collection,
        console=console,
        no_clear=no_clear,
    )
    if commands:
        app.run_script(commands)
        return
    if snapshot:
        app.render()
        return
    if _TEXTUAL_IMPORT_ERROR is None:
        # `seam dashboard`, `seam-dash`, and `seam-tui` all land here, so
        # repointing this one branch supersedes the old UI on every entry
        # point at once. `app` (DashboardApp) stays the backend: it already
        # holds the vector-backend selection above, which is why the TUI is
        # handed the built backend rather than constructing its own.
        # Imported lazily -- seam_runtime.tui imports textual at module level,
        # and dashboard.py must stay importable without it.
        from .tui.app import run as run_tui

        config.apply_persisted_to_environ()
        run_tui(app)
        return
    app.run_interactive()


def _ensure_rich() -> None:
    if _RICH_IMPORT_ERROR is not None:  # pragma: no cover - environment-dependent path
        raise SystemExit(
            "The dashboard requires 'rich'. Install dependencies with:\n"
            "  .\\.venv\\Scripts\\python -m pip install -r requirements.txt"
        ) from _RICH_IMPORT_ERROR


def _ensure_textual() -> None:
    if _TEXTUAL_IMPORT_ERROR is not None:  # pragma: no cover - environment-dependent path
        raise SystemExit(
            "The interactive dashboard requires 'textual'. Install optional dependencies with:\n"
            "  pip install seam-runtime[dash]"
        ) from _TEXTUAL_IMPORT_ERROR


def main(argv: list[str] | None = None) -> None:
    # Applied before the parser is built, not just before the runtime: the
    # --db default is `default_runtime_db_path()`, which reads SEAM_DB_PATH at
    # add_argument time, so a persisted value applied any later is ignored.
    config.apply_persisted_to_environ()
    parser = argparse.ArgumentParser(description="Launch the SEAM interactive dashboard")
    parser.add_argument("--db", default=default_runtime_db_path(), help="SQLite database path")
    parser.add_argument("--snapshot", action="store_true", help="Render one Rich dashboard frame and exit")
    parser.add_argument("--run", dest="dashboard_commands", action="append", default=[], help="Run a dashboard command non-interactively")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal in Rich snapshot/script mode")
    parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
    parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
    parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")
    args = parser.parse_args(argv)

    if not args.snapshot and not args.dashboard_commands:
        _ensure_textual()

    runtime = SeamRuntime(args.db)
    run_dashboard(
        runtime,
        vector_backend=args.vector_backend,
        vector_path=args.vector_path,
        vector_collection=args.vector_collection,
        snapshot=args.snapshot,
        commands=args.dashboard_commands,
        no_clear=args.no_clear,
    )
