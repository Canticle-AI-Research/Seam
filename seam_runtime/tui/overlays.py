"""The overlay drawers and the connections popover.

The mockup demotes two things from navigation sections to overlays: Chat
becomes a right-hand drawer reachable from the topbar, and the full record
list becomes a "Memories" drawer with a filter box. Both stay honest:

* The chat drawer renders the real `SeamChatClient` transcript including
  the memory ids injected into each reply. The mockup's file attachments
  and thread selector are omitted — the backend keeps one in-memory
  conversation and has no attachment path — so "+ New" clears both the
  transcript and the app-owned conversation history rather than pretending
  to switch threads.
* The memories drawer lists real records (the same
  `list_namespaces -> list_scopes -> list_record_summaries` walk the
  records table uses) and real recent workspace events under a truthful
  "recent activity" label. The mockup's "forming now" stream was
  simulated; workspace events are what the store actually records.
* The connections popover runs `doctor.build_doctor_report()` on a worker
  thread on demand and renders exactly the checks it returns.
"""

from __future__ import annotations

from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, ListItem, ListView, RichLog, Static

from . import brand
from .keys import SeamInput
from .panels import _event_summary, _preview_attrs

__all__ = ["ChatDrawer", "MemoriesDrawer", "ConnectionsPopover"]


class ChatDrawer(Vertical):
    """Right-hand chat overlay: transcript, model line, draft, send."""

    DEFAULT_CSS = """
    ChatDrawer {
        dock: right;
        width: 46;
        background: #1f2028;
        border-left: solid #3b3d57;
        display: none;
    }
    ChatDrawer.-open {
        display: block;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._model_line = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-header"):
            yield Static("Chat", id="chat-title")
            yield Button("+ New", id="chat-new", compact=True)
            yield Button("×", id="chat-close", compact=True)
        yield Static("", id="chat-model-line")
        yield RichLog(id="chat-log", markup=True, wrap=True, highlight=True)
        with Horizontal(id="chat-input-row"):
            yield SeamInput(placeholder="message the model…", id="chat-draft")
            yield Button("Send", id="chat-send", compact=True)

    @property
    def open(self) -> bool:
        return self.has_class("-open")

    def set_open(self, open: bool, *, focus: bool = True) -> None:
        """Open/close the drawer.

        `focus=False` is for programmatic opens (chat-mode latch from the
        command bar): the operator's next keystrokes belong to
        `#command-input`, so the drawer must not steal focus.
        """
        self.set_class(open, "-open")
        if open and focus:
            self.query_one("#chat-draft", Input).focus()

    def set_model_line(self, line: str) -> None:
        self._model_line = line
        self.query_one("#chat-model-line", Static).update(line)

    def write(self, text: str) -> None:
        self.query_one("#chat-log", RichLog).write(text)

    def clear_transcript(self) -> None:
        self.query_one("#chat-log", RichLog).clear()

    def focus_draft(self) -> None:
        self.query_one("#chat-draft", Input).focus()

    @on(Button.Pressed, "#chat-close")
    def _on_close(self) -> None:
        self.set_open(False)
        self.app.query_one("#command-input", Input).focus()

    @on(Button.Pressed, "#chat-new")
    def _on_new(self) -> None:
        self.app.start_new_chat()  # type: ignore[attr-defined]

    @on(Input.Submitted, "#chat-draft")
    def _on_draft_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if message:
            self.app._run_chat(message)  # type: ignore[attr-defined]
            event.input.value = ""

    @on(Button.Pressed, "#chat-send")
    def _on_send(self) -> None:
        field = self.query_one("#chat-draft", Input)
        message = field.value.strip()
        if message:
            field.value = ""
            self.app._run_chat(message)  # type: ignore[attr-defined]


class _DrawerRecordItem(ListItem):
    """One record row in the memories drawer."""

    def __init__(self, record_id: str, kind: str, preview: str, meta: str) -> None:
        super().__init__()
        self.record_id = record_id
        self.kind = kind
        self.preview = preview
        self.meta = meta

    def compose(self) -> ComposeResult:
        color = {
            "ENT": brand.MINT,
            "CLM": brand.CYAN,
            "REL": brand.LAVENDER,
            "RAW": brand.ORANGE,
        }.get(self.kind.upper(), brand.TEXT_MUTED)
        yield Static(
            f"[b {color}]{self.kind}[/]  [{brand.TEXT_MAIN}]{self.record_id}[/]",
            classes="drawer-record-id",
        )
        yield Static(self.preview, classes="drawer-record-preview")
        yield Static(self.meta, classes="drawer-record-meta")


class MemoriesDrawer(Vertical):
    """Right-hand memories overlay: count, recent activity, filter, records."""

    DEFAULT_CSS = """
    MemoriesDrawer {
        dock: right;
        width: 42;
        background: #1f2028;
        border-left: solid #3b3d57;
        display: none;
    }
    MemoriesDrawer.-open {
        display: block;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # id, kind, namespace, scope, updated_at, preview. Namespace and
        # scope stay separate so their filter prefixes cannot cross-match.
        self._rows: list[tuple[str, str, str, str, str, str]] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="drawer-header"):
            yield Static("All memories", id="drawer-title")
            yield Button("×", id="drawer-close", compact=True)
        yield Static("", id="drawer-count")
        yield Static("RECENT ACTIVITY", classes="pane-label")
        yield Static("", id="drawer-activity")
        yield SeamInput(
            placeholder="filter: text · kind:clm · ns:name · scope:…",
            id="drawer-filter",
        )
        yield Static(
            "tokens combine with AND · kind: · ns: · scope:",
            id="drawer-filter-hint",
        )
        with VerticalScroll(id="drawer-records"):
            yield ListView(id="drawer-record-list")

    @property
    def open(self) -> bool:
        return self.has_class("-open")

    def set_open(self, open: bool) -> None:
        self.set_class(open, "-open")
        if open:
            self.refresh_records()
            self.query_one("#drawer-filter", Input).focus()

    @on(Button.Pressed, "#drawer-close")
    def _on_close(self) -> None:
        self.set_open(False)
        self.app.query_one("#command-input", Input).focus()

    @on(Input.Changed, "#drawer-filter")
    def _on_filter(self, event: Input.Changed) -> None:
        self._render_records(event.value.strip())

    @on(ListView.Selected, "#drawer-record-list")
    def _on_record_selected(self, event: ListView.Selected) -> None:
        """Selecting a drawer record jumps the Memory section to it."""
        if not isinstance(event.item, _DrawerRecordItem):
            return
        self.set_open(False)
        app = self.app
        app._activate_section("memory")  # type: ignore[attr-defined]
        try:
            records = app.query_one("#memory-records")
            records.try_select_id(event.item.record_id)
        except Exception:
            pass

    # -- record walk (same store path as the records table) -----------------

    @work(thread=True, exclusive=True)
    def refresh_records(self) -> None:
        """Load recent records and workspace events off the event loop.

        The walk mirrors `MemoryRecordsPanel._load_rows`
        (`list_namespaces -> list_scopes -> list_record_summaries`) plus
        `iter_workspace_events` for the activity block, so the drawer and
        the records table can never disagree about what the store holds.
        """
        runtime = self.app.backend.runtime  # type: ignore[attr-defined]
        rows: list[tuple[str, str, str, str, str]] = []  # id, kind, ns, scope, updated
        try:
            for ns in runtime.store.list_namespaces():
                for scope in runtime.store.list_scopes(ns):
                    for row in runtime.store.list_record_summaries(ns, scope, limit=25):
                        rows.append(
                            (
                                str(row["id"]),
                                str(row["kind"]),
                                ns,
                                scope,
                                str(row["updated_at"]),
                            )
                        )
            rows.sort(key=lambda item: item[4], reverse=True)
            top = rows[:100]
            records_by_id = (
                runtime.store.load_ir(ids=[item[0] for item in top]).by_id()
                if top
                else {}
            )
            rendered: list[tuple[str, str, str, str, str, str]] = []
            for record_id, kind, ns, scope, updated_at in top:
                record = records_by_id.get(record_id)
                preview = _preview_attrs(record.attrs) if record else "(unavailable)"
                rendered.append((record_id, kind, ns, scope, updated_at, preview))
        except Exception as exc:
            self.app.call_from_thread(self._render_records_error, str(exc))
            return
        try:
            events = list(runtime.store.iter_workspace_events(limit=12))
        except Exception:
            events = []
        self.app.call_from_thread(self._render_loaded, rendered, events)

    def _render_loaded(
        self,
        rows: list[tuple[str, str, str, str, str, str]],
        events: list[dict[str, Any]],
    ) -> None:
        self._rows = rows
        count = self.query_one("#drawer-count", Static)
        if rows:
            count.update(f"[b {brand.MINT}]{len(rows)}[/] records")
        else:
            count.update(f"[{brand.TEXT_DIM}]no MIRL records yet — run compile to create some[/]")
        activity = self.query_one("#drawer-activity", Static)
        if not events:
            activity.update(f"[{brand.TEXT_DIM}]no workspace activity recorded yet[/]")
        else:
            lines: list[str] = []
            for event in reversed(events):
                kind = str(event.get("event_type", ""))
                created = str(event.get("created_at", ""))
                summary = _event_summary(event.get("payload") or {})
                lines.append(
                    f"[{brand.TEXT_DIM}]●[/] [{brand.TEXT_DIM}]{created}[/] "
                    f"[b {brand.CYAN}]{kind}[/]  [{brand.TEXT_MUTED}]{summary}[/]"
                )
            activity.update("\n".join(lines))
        self._render_records("")

    def _render_records(self, filter_text: str) -> None:
        """Render `self._rows` through the drawer's filter grammar.

        Tokens combine with AND; `kind:`, `ns:`, and `scope:` are field
        filters and everything else matches the id or the preview text —
        all client-side over rows already loaded, same contract as the
        records table's search box.
        """
        records = self.query_one("#drawer-record-list", ListView)
        records.clear()
        kind_filter = ""
        ns_filter = ""
        scope_filter = ""
        text_terms: list[str] = []
        for token in filter_text.lower().split():
            if token.startswith("kind:"):
                kind_filter = token.removeprefix("kind:")
            elif token.startswith("ns:"):
                ns_filter = token.removeprefix("ns:")
            elif token.startswith("scope:"):
                scope_filter = token.removeprefix("scope:")
            else:
                text_terms.append(token)
        visible = [
            row
            for row in self._rows
            if (not kind_filter or row[1].lower() == kind_filter)
            and (not ns_filter or ns_filter in row[2].lower())
            and (not scope_filter or scope_filter in row[3].lower())
            and all(
                term in row[0].lower() or term in row[5].lower()
                for term in text_terms
            )
        ]
        if not self._rows:
            records.append(ListItem(Static(f"[{brand.TEXT_DIM}]no records yet[/]")))
            return
        if not visible:
            records.append(
                ListItem(Static(f"[{brand.TEXT_DIM}]no records match {filter_text!r}[/]"))
            )
            return
        for record_id, kind, namespace, scope, updated_at, preview in visible:
            meta = f"{namespace} · {scope} · {updated_at}"
            records.append(_DrawerRecordItem(record_id, kind, preview, meta))

    def _render_records_error(self, message: str) -> None:
        self._rows = []
        records = self.query_one("#drawer-record-list", ListView)
        records.clear()
        records.append(ListItem(Static(f"[{brand.RED}]error:[/] {message}")))
        self.query_one("#drawer-count", Static).update(
            f"[{brand.RED}]record load failed[/]"
        )


class ConnectionsPopover(Vertical):
    """Right-hand connections overlay: the doctor report, on demand.

    Runs `doctor.build_doctor_report()` on a worker thread the moment the
    popover opens (it compiles a smoke record and benchmarks a lossless
    roundtrip, so it is far too heavy for the event loop) and renders
    exactly the checks it returns — never a simulated status tile.
    """

    DEFAULT_CSS = """
    ConnectionsPopover {
        dock: right;
        width: 46;
        background: #1f2028;
        border-left: solid #3b3d57;
        display: none;
    }
    ConnectionsPopover.-open {
        display: block;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._loaded = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="connections-header"):
            yield Static("Connections", id="connections-title")
            yield Button("×", id="connections-close", compact=True)
        yield Static("running doctor checks…", id="connections-body")

    @property
    def open(self) -> bool:
        return self.has_class("-open")

    def set_open(self, open: bool) -> None:
        self.set_class(open, "-open")
        if open and not self._loaded:
            self.refresh_report()

    def refresh_report(self) -> None:
        self._loaded = True
        self.query_one("#connections-body", Static).update(
            f"[{brand.TEXT_DIM}]running doctor checks…[/]"
        )
        self._load_report()

    @work(thread=True, exclusive=True)
    def _load_report(self) -> None:
        from ..doctor import build_doctor_report

        try:
            report = build_doctor_report()
        except Exception as exc:
            self.app.call_from_thread(self._render_error, str(exc))
            return
        self.app.call_from_thread(self._render_report, report)

    def _render_error(self, message: str) -> None:
        self.query_one("#connections-body", Static).update(
            f"[{brand.RED}]error:[/] {message}"
        )

    def _render_report(self, report: dict[str, Any]) -> None:
        status = str(report.get("status", ""))
        color = brand.MINT if status == "PASS" else brand.RED
        lines = [
            f"[b {color}]doctor: {status}[/]  "
            f"[{brand.TEXT_DIM}]python {report.get('python', '')}[/]"
        ]
        for section in (
            "smoke_compile",
            "lossless",
            "pgvector",
            "commit_gate",
            "streams",
            "stashes",
        ):
            value = report.get(section)
            if not isinstance(value, dict):
                continue
            check = str(value.get("status", ""))
            check_color = (
                brand.MINT
                if check == "PASS"
                else brand.YELLOW
                if check == "SKIP"
                else brand.RED
            )
            detail = {k: v for k, v in value.items() if k != "status"}
            lines.append(
                f"[{brand.TEXT_DIM}]●[/] [b {check_color}]{section}[/] "
                f"[{brand.TEXT_MUTED}]{detail}[/]"
            )
        dependencies = report.get("dependencies")
        if isinstance(dependencies, dict):
            missing = report.get("missing_required_dependencies") or []
            deps = " ".join(
                f"[{brand.MINT if name not in missing else brand.RED}]{name}[/]"
                for name in dependencies
            )
            lines.append(f"[{brand.TEXT_DIM}]●[/] [b {brand.LAVENDER}]dependencies[/] {deps}")
        self.query_one("#connections-body", Static).update("\n".join(lines))

    @on(Button.Pressed, "#connections-close")
    def _on_close(self) -> None:
        self.set_open(False)
        self.app.query_one("#command-input", Input).focus()
