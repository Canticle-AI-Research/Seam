"""Structured data panels for the SEAM TUI's non-Settings tabs.

The tabs used to be seven identical `RichLog` sinks: whatever text a command
happened to print was the only view of runtime state. That is fine for a
transcript but bad for "what records exist", "what did that search rank",
"what benchmark runs are on disk" — questions a table or tree answers in one
glance and a scrollback never does. Each class below owns one tab's
`DataTable` (or `Tree`, for provenance) plus the RichLog the tab already had,
so `app.py`'s `_write()` keeps landing command output in the same place while
the table shows live runtime state next to it.

Every panel loads data through `@work(thread=True)` and marshals results back
with `self.app.call_from_thread(...)` (REQUIREMENTS #1 from the task brief).
`DashboardApp.execute()` already proved why: SQLite and retrieval calls block
for real time, and running them on the event loop freezes the whole UI, not
just the tab that issued them.

Data comes from `SeamRuntime` and its `SQLiteStore`, not from parsing the
backend's free-text `result_body`. `seam_runtime.sdk.SeamSDK` was checked
first per the task brief but its surface is reasoning-session and
ingest/lifecycle oriented -- it has no listing API for records, benchmark
runs, documents, or workspace events, so every call below is either a
`SeamRuntime` method with its own clean signature or, where no runtime-level
wrapper exists, the underlying `store` method the runtime itself delegates
to. Every one of them is confirmed to exist by direct reading, not
guessed -- see the call site comments for exact source locations.
"""

from __future__ import annotations

import json
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, RichLog, Tree

from ..mirl import MIRLRecord, SearchCandidate, TraceGraph
from ..runtime import SeamRuntime
from . import brand

__all__ = [
    "MemoryPanel",
    "MemoryRecordsPanel",
    "RetrievalPanel",
    "BenchmarksPanel",
    "CompressionPanel",
    "ChatPanel",
    "LivePanel",
    "ProvPanel",
    "PANEL_CLASSES",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = 80) -> str:
    """Collapse whitespace and cut to ``limit`` chars with an ellipsis."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


#: Checked in priority order. Record kinds do not share one text field --
#: ENT carries `label`, RAW carries `content`, CLM/REL carry a
#: subject/predicate/object triple (see `nl.py`'s record construction) -- so
#: this is a best-effort preview, not a schema guarantee.
_PREVIEW_TEXT_KEYS = ("text", "content", "label", "summary", "value")


def _preview_attrs(attrs: dict[str, Any], limit: int = 80) -> str:
    """Return a best-effort single-line preview of a MIRL record's payload.

    Never raises: a preview is cosmetic, not load-bearing, so a malformed
    payload degrades to a compact JSON dump rather than breaking the row.
    """
    for key in _PREVIEW_TEXT_KEYS:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate(value, limit)
    if {"subject", "predicate", "object"} <= attrs.keys():
        triple = f"{attrs.get('subject')} {attrs.get('predicate')} {attrs.get('object')}"
        return _truncate(triple, limit)
    if not attrs:
        return "(no attrs)"
    try:
        return _truncate(json.dumps(attrs, sort_keys=True, separators=(",", ":")), limit)
    except TypeError:
        return _truncate(str(attrs), limit)


def _status_row(table: DataTable, message: str, *, color: str, columns: int) -> None:
    """Write one explicit status row spanning the table's columns.

    REQUIREMENT #4: empty and error states must be visible rows, never a
    silently empty table.
    """
    cells = [f"[{color}]{message}[/]"] + ["—"] * (columns - 1)
    table.add_row(*cells)


class _RuntimePanel(Vertical):
    """Base for every panel that reads live runtime state (all but Chat)."""

    @property
    def _runtime(self) -> SeamRuntime:
        # `self.app` is Textual's generic `App`; `SeamTUI` (app.py) is the
        # concrete subclass that adds `.backend`, the `DashboardApp` this
        # whole TUI is a view over. `type: ignore` because Textual's `App`
        # type does not know about that attribute.
        return self.app.backend.runtime  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class MemoryRecordsPanel(_RuntimePanel):
    """The Memory tab's record table: recent MIRL records across every
    namespace and scope.

    Renamed from `MemoryPanel` when the operator asked for the table to
    "act like a table so I can copy IDs" with provenance below it on the
    same page: this class keeps everything about loading and rendering the
    table, `MemoryPanel` below is now the thin composite that stacks this,
    `ProvPanel`, and the tab's one shared log.
    """

    LIMIT = 50

    #: `y` bubbles up from the focused `DataTable` (which has no binding for
    #: it) to this container, matching Textual's normal action-lookup walk
    #: up the DOM from the focused widget -- see `action_yank_id` below.
    BINDINGS = [Binding("y", "yank_id", "Copy id", show=False)]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Source of truth for "the id under row N", in the same order
        # `_render_rows` adds them to the table. `[]` whenever a status/error
        # row is showing instead of real records, so `y` and row-selection
        # below can never mistake a status row's text (e.g. "no MIRL
        # records yet") for an id -- they index into this list, never the
        # table's rendered text.
        self._row_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield DataTable(id="memory-table")

    def on_mount(self) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.add_columns("id", "kind", "scope", "namespace", "text preview", "created")
        table.cursor_type = "row"
        self.refresh_records()

    def reload(self) -> None:
        """Reload the table.

        Named `reload` rather than `refresh` so it cannot collide with
        `Widget.refresh`, Textual's repaint method: overriding that would
        drop real repaint requests and tie rendering to database reads.
        """
        self.refresh_records()

    @work(thread=True, exclusive=True)
    def refresh_records(self) -> None:
        runtime = self._runtime
        try:
            rows = self._load_rows(runtime)
        except Exception as exc:  # surfaced below, never swallowed
            self.app.call_from_thread(self._render_error, str(exc))
            return
        self.app.call_from_thread(self._render_rows, rows)

    def _load_rows(
        self, runtime: SeamRuntime
    ) -> list[tuple[str, str, str, str, str, str]]:
        # There is no single "recent records across everything" call (grepped
        # storage.py -- the closest is per-namespace/scope), so this walks
        # `list_namespaces` -> `list_scopes` -> `list_record_summaries`
        # (storage.py:883, :891, :899) and sorts the union by `updated_at`.
        # Namespace/scope counts are small in practice; this runs off the
        # event loop regardless.
        summaries: list[tuple[str, str, str, str, str]] = []  # id, kind, scope, ns, updated_at
        for ns in runtime.store.list_namespaces():
            for scope in runtime.store.list_scopes(ns):
                for row in runtime.store.list_record_summaries(ns, scope, limit=self.LIMIT):
                    summaries.append(
                        (str(row["id"]), str(row["kind"]), scope, ns, str(row["updated_at"]))
                    )
        summaries.sort(key=lambda item: item[4], reverse=True)
        top = summaries[: self.LIMIT]

        # `list_record_summaries` has no text/created_at; load the full
        # records (storage.py:1725) for the preview and true `created_at`.
        ids = [item[0] for item in top]
        records_by_id: dict[str, MIRLRecord] = (
            runtime.store.load_ir(ids=ids).by_id() if ids else {}
        )

        rows: list[tuple[str, str, str, str, str, str]] = []
        for record_id, kind, scope, ns, updated_at in top:
            record = records_by_id.get(record_id)
            preview = _preview_attrs(record.attrs) if record else "(unavailable)"
            created = record.created_at if record else updated_at
            rows.append((record_id, kind, scope, ns, preview, created))
        return rows

    def _render_rows(self, rows: list[tuple[str, str, str, str, str, str]]) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.clear()
        self._row_ids = []
        if not rows:
            _status_row(table, "no MIRL records yet — run compile to create some",
                        color=brand.TEXT_DIM, columns=6)
            return
        for record_id, kind, scope, ns, preview, created in rows:
            table.add_row(record_id, kind, scope, ns, preview, created)
            self._row_ids.append(record_id)

    def _render_error(self, message: str) -> None:
        table = self.query_one("#memory-table", DataTable)
        table.clear()
        _status_row(table, f"error: {message}", color=brand.RED, columns=6)
        self._row_ids = []

    # -- copyable ids --------------------------------------------------

    def _record_id_at(self, row_index: int) -> str | None:
        """Map a table row index to its record id, or `None` for a status
        row / an out-of-range cursor (e.g. the empty-store status row, which
        occupies row 0 while `_row_ids` is `[]`)."""
        if 0 <= row_index < len(self._row_ids):
            return self._row_ids[row_index]
        return None

    def _log(self, text: str) -> None:
        """Write one line to the page's shared `#log-memory`.

        Reached via `self.app.query_one` rather than a sibling lookup, the
        same defensive `try/except` style `app.py::_write` already uses --
        this keeps the records panel usable even if it is ever mounted
        without a `#log-memory` sibling.
        """
        try:
            self.app.query_one("#log-memory", RichLog).write(text)
        except Exception:
            pass

    def action_yank_id(self) -> None:
        """`y`: copy the id under the table cursor to the clipboard.

        `App.copy_to_clipboard` (textual/app.py) writes an OSC 52 escape
        sequence the terminal may or may not honour, so the bare id is also
        echoed alone on its own line below -- a clean line an operator can
        drag-select is the fallback when OSC 52 is not wired up.
        """
        table = self.query_one("#memory-table", DataTable)
        record_id = self._record_id_at(table.cursor_row)
        if record_id is None:
            self._log(f"[{brand.TEXT_DIM}]no record under the cursor[/]")
            return
        self.app.copy_to_clipboard(record_id)
        self._log(f"[{brand.TEXT_DIM}]copied id ↓[/]\n{record_id}")

    @on(DataTable.RowSelected, "#memory-table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter or a click on the already-selected row: trace its id below.

        `DataTable.RowSelected` fires for both keyboard and mouse selection
        (`textual/widgets/_data_table.py` `action_select_cursor` and
        `_on_click` both post it), so one handler covers both. Selection is
        deliberately not a clipboard action: the full id remains visible and
        selectable in `#prov-query`, while `y` and the adjacent Copy ID button
        are the two explicit copy paths.
        """
        record_id = self._record_id_at(event.cursor_row)
        if record_id is None:
            self._log(f"[{brand.TEXT_DIM}]no record under the cursor[/]")
            return
        try:
            query = self.app.query_one("#prov-query", Input)
        except Exception:
            # No provenance sibling mounted -- there is nowhere to expose or
            # trace the selected id, but selecting the row must remain safe.
            self._log(f"[{brand.TEXT_DIM}]selected id (trace unavailable) ↓[/]\n{record_id}")
            return
        query.value = record_id
        # Posting `Submitted` directly -- rather than awaiting the widget's
        # own async `action_submit` -- fires the exact event
        # `ProvPanel._on_submit` below already reacts to, without needing
        # this handler to be async.
        query.post_message(Input.Submitted(query, record_id))
        self._log(f"[{brand.MINT}]selected id, tracing below ↓[/]\n{record_id}")


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class RetrievalPanel(_RuntimePanel):
    """Retrieval tab: a query box over ranked search results."""

    BUDGET = 10

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search memory… (press enter)", id="retrieval-query")
        yield DataTable(id="retrieval-table")
        yield RichLog(id="log-retrieval", markup=True, wrap=True, highlight=True)

    def on_mount(self) -> None:
        table = self.query_one("#retrieval-table", DataTable)
        table.add_columns("rank", "score", "kind", "id", "text preview")
        table.cursor_type = "row"
        _status_row(table, "type a query above and press enter",
                    color=brand.TEXT_DIM, columns=5)

    def reload(self) -> None:
        """Re-run the last query, if any. A blank query box is left alone."""
        query = self.query_one("#retrieval-query", Input).value.strip()
        if query:
            self._run_query(query)

    @on(Input.Submitted, "#retrieval-query")
    def _on_submit(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            self._run_query(query)

    @work(thread=True, exclusive=True)
    def _run_query(self, query: str) -> None:
        runtime = self._runtime
        try:
            # runtime.py:975 `search_ir` -- the same call the dashboard's
            # `search` verb makes (dashboard.py's `execute()`).
            result = runtime.search_ir(query, budget=self.BUDGET)
        except Exception as exc:
            self.app.call_from_thread(self._render_error, str(exc))
            return
        self.app.call_from_thread(self._render_candidates, result.candidates)

    def _render_candidates(self, candidates: list[SearchCandidate]) -> None:
        table = self.query_one("#retrieval-table", DataTable)
        table.clear()
        if not candidates:
            _status_row(table, "no matches", color=brand.TEXT_DIM, columns=5)
            return
        for rank, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(rank),
                f"{candidate.score:.3f}",
                candidate.record.kind.value,
                candidate.record.id,
                _preview_attrs(candidate.record.attrs),
            )

    def _render_error(self, message: str) -> None:
        table = self.query_one("#retrieval-table", DataTable)
        table.clear()
        _status_row(table, f"error: {message}", color=brand.RED, columns=5)


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


class BenchmarksPanel(_RuntimePanel):
    """Benchmarks tab: persisted suite runs from the `benchmark_runs` table.

    The columns deliberately differ from the task brief's sketch of
    (run id, source, codec, ratio, when): `benchmark_runs` persists one row
    per *suite* run (a mix of families -- lossless, readable, surface, ...),
    written by `run_benchmark_suite(..., persist=True)` (benchmarks.py:236,
    storage.py:3053 `write_benchmark_run`). There is no single codec or
    document source at that granularity -- only per-case codec choices
    nested inside each run's report. `suite` and `savings` (the run's p50
    token-savings percentile) are the closest fields that are actually
    stored, so those are what is shown rather than fabricating a codec/ratio
    pair the schema does not have.
    """

    LIMIT = 25

    def compose(self) -> ComposeResult:
        yield DataTable(id="benchmarks-table")
        yield RichLog(id="log-benchmarks", markup=True, wrap=True, highlight=True)

    def on_mount(self) -> None:
        table = self.query_one("#benchmarks-table", DataTable)
        table.add_columns("run id", "suite", "status", "savings (p50)", "when")
        table.cursor_type = "row"
        self.refresh_runs()

    def reload(self) -> None:
        """Reload the table."""
        self.refresh_runs()

    @work(thread=True, exclusive=True)
    def refresh_runs(self) -> None:
        runtime = self._runtime
        try:
            rows = self._load_rows(runtime)
        except Exception as exc:
            self.app.call_from_thread(self._render_error, str(exc))
            return
        self.app.call_from_thread(self._render_rows, rows)

    def _load_rows(self, runtime: SeamRuntime) -> list[tuple[str, str, str, str, str]]:
        rows: list[tuple[str, str, str, str, str]] = []
        # runtime.py:1317 `list_benchmark_runs` -> storage.py:3107.
        for run in runtime.list_benchmark_runs(limit=self.LIMIT):
            run_id = str(run["run_id"])
            suite = str(
                run.get("requested_suite")
                or ", ".join(run.get("executed_suites") or [])
                or "all"
            )
            status = str(run.get("status", "?"))
            savings = "—"
            try:
                # runtime.py:1314 `read_benchmark_run` -> storage.py:3100.
                report = runtime.read_benchmark_run(run_id)
            except Exception:
                # One row's detail failing does not invalidate the listing
                # above, but it must say so rather than showing a silent "—".
                savings = "(report unavailable)"
            else:
                p50 = report.get("summary", {}).get("token_savings_p50")
                if isinstance(p50, (int, float)):
                    savings = f"{p50:.1%}"
            rows.append((run_id, suite, status, savings, str(run.get("created_at", ""))))
        return rows

    def _render_rows(self, rows: list[tuple[str, str, str, str, str]]) -> None:
        table = self.query_one("#benchmarks-table", DataTable)
        table.clear()
        if not rows:
            _status_row(table, "no persisted benchmark runs yet",
                        color=brand.TEXT_DIM, columns=5)
            return
        for run_id, suite, status, savings, when in rows:
            colour = brand.MINT if status == "PASS" else brand.RED
            table.add_row(run_id, suite, f"[{colour}]{status}[/]", savings, when)

    def _render_error(self, message: str) -> None:
        table = self.query_one("#benchmarks-table", DataTable)
        table.clear()
        _status_row(table, f"error: {message}", color=brand.RED, columns=5)


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


class CompressionPanel(_RuntimePanel):
    """Compression tab: `document_status` rows for ingested/compressed sources."""

    LIMIT = 30

    def compose(self) -> ComposeResult:
        yield DataTable(id="compression-table")
        yield RichLog(id="log-compression", markup=True, wrap=True, highlight=True)

    def on_mount(self) -> None:
        table = self.query_one("#compression-table", DataTable)
        table.add_columns("source ref", "hash", "indexed", "size (bytes)")
        table.cursor_type = "row"
        self.refresh_documents()

    def reload(self) -> None:
        """Reload the table."""
        self.refresh_documents()

    @work(thread=True, exclusive=True)
    def refresh_documents(self) -> None:
        runtime = self._runtime
        try:
            # No runtime-level wrapper exists for this; storage.py:1294
            # `list_document_status` is the store method the task brief
            # says to fall back to.
            rows = runtime.store.list_document_status(limit=self.LIMIT)
        except Exception as exc:
            self.app.call_from_thread(self._render_error, str(exc))
            return
        self.app.call_from_thread(self._render_rows, rows)

    def _render_rows(self, rows: list[dict[str, Any]]) -> None:
        table = self.query_one("#compression-table", DataTable)
        table.clear()
        if not rows:
            _status_row(table, "no documents indexed yet", color=brand.TEXT_DIM, columns=4)
            return
        for row in rows:
            table.add_row(
                str(row.get("source_ref", "")),
                _truncate(str(row.get("source_hash", "")), 16),
                str(row.get("indexed_status", "")),
                str(row.get("byte_count", "")),
            )

    def _render_error(self, message: str) -> None:
        table = self.query_one("#compression-table", DataTable)
        table.clear()
        _status_row(table, f"error: {message}", color=brand.RED, columns=4)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatPanel(Vertical):
    """Chat tab: transcript only -- no DataTable, per the task brief.

    `DashboardApp`'s command parser (dashboard.py `_build_command_parser`)
    has no `chat` verb, so there is nothing structured to load here. The
    RichLog below is the same output surface `app._write("chat", ...)`
    already targets, and the app's global command bar at the bottom of the
    screen is this tab's Input -- adding a second one would just fight it
    for focus without giving the operator anything the global bar does not
    already do.
    """

    def compose(self) -> ComposeResult:
        yield RichLog(id="log-chat", markup=True, wrap=True, highlight=True)

    def reload(self) -> None:
        """No-op: nothing here is loaded from storage. Present so every
        panel answers to the same `reload()` call from the app."""


# ---------------------------------------------------------------------------
# Live
# ---------------------------------------------------------------------------


#: Checked in priority order for a one-line event summary.
_EVENT_SUMMARY_KEYS = ("status", "message", "detail", "model")


def _event_summary(payload: dict[str, Any], limit: int = 80) -> str:
    for key in _EVENT_SUMMARY_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate(value, limit)
    if not payload:
        return "(no payload)"
    try:
        return _truncate(json.dumps(payload, sort_keys=True, separators=(",", ":")), limit)
    except TypeError:
        return _truncate(str(payload), limit)


class LivePanel(_RuntimePanel):
    """Live tab: recent workspace events across every run."""

    FETCH_LIMIT = 200
    DISPLAY_LIMIT = 50

    def compose(self) -> ComposeResult:
        yield DataTable(id="live-table")
        yield RichLog(id="log-live", markup=True, wrap=True, highlight=True)

    def on_mount(self) -> None:
        table = self.query_one("#live-table", DataTable)
        table.add_columns("ts", "kind", "run id", "summary")
        table.cursor_type = "row"
        self.refresh_events()

    def reload(self) -> None:
        """Reload the table."""
        self.refresh_events()

    @work(thread=True, exclusive=True)
    def refresh_events(self) -> None:
        runtime = self._runtime
        try:
            # No runtime-level wrapper exists for this; storage.py:3816
            # `iter_workspace_events` is the same call the REST
            # `/workspace/events` route makes (server.py:760).
            events = runtime.store.iter_workspace_events(limit=self.FETCH_LIMIT)
        except Exception as exc:
            self.app.call_from_thread(self._render_error, str(exc))
            return
        # `iter_workspace_events` orders ascending by `event_id`; the
        # operator wants newest first, so take the tail and reverse it.
        recent = list(reversed(events[-self.DISPLAY_LIMIT :]))
        self.app.call_from_thread(self._render_events, recent)

    def _render_events(self, events: list[dict[str, Any]]) -> None:
        table = self.query_one("#live-table", DataTable)
        table.clear()
        if not events:
            _status_row(table, "no workspace activity recorded yet",
                        color=brand.TEXT_DIM, columns=4)
            return
        for event in events:
            table.add_row(
                str(event.get("created_at", "")),
                str(event.get("event_type", "")),
                str(event.get("run_id", "")),
                _event_summary(event.get("payload") or {}),
            )

    def _render_error(self, message: str) -> None:
        table = self.query_one("#live-table", DataTable)
        table.clear()
        _status_row(table, f"error: {message}", color=brand.RED, columns=4)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class ProvPanel(_RuntimePanel):
    """Provenance trace panel: one object id through its evidence/edge chain.

    No longer its own tab -- `TABS` in app.py dropped `("prov",
    "Provenance")` when the operator asked to put provenance below the
    memory table on one page. `MemoryPanel` below mounts this directly
    beneath `MemoryRecordsPanel`; selecting a record there sets `#prov-query`
    and traces it here. No RichLog of its own either: nothing writes to
    `#log-prov` now that "prov" is not a tab, and the page already has one
    shared log (`#log-memory`, owned by the composite `MemoryPanel`).
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="memory-id-controls"):
            yield Input(
                placeholder="select a row or paste an object id…",
                id="prov-query",
                select_on_focus=True,
            )
            yield Button("Copy ID", id="memory-copy-id")
        yield Tree("(enter an id above)", id="prov-tree")

    def reload(self) -> None:
        """Re-trace the last id, if any."""
        obj_id = self.query_one("#prov-query", Input).value.strip()
        if obj_id:
            self._run_trace(obj_id)

    @on(Input.Submitted, "#prov-query")
    def _on_submit(self, event: Input.Submitted) -> None:
        obj_id = event.value.strip()
        if obj_id:
            self._run_trace(obj_id)

    @on(Button.Pressed, "#memory-copy-id")
    def _on_copy_id(self) -> None:
        """Copy the full visible id only after an explicit button press."""
        obj_id = self.query_one("#prov-query", Input).value.strip()
        if not obj_id:
            try:
                self.app.query_one("#log-memory", RichLog).write(
                    f"[{brand.TEXT_DIM}]select or paste an id before copying[/]"
                )
            except Exception:
                pass
            return
        self.app.copy_to_clipboard(obj_id)
        try:
            self.app.query_one("#log-memory", RichLog).write(
                f"[{brand.TEXT_DIM}]copied id ↓[/]\n{obj_id}"
            )
        except Exception:
            pass

    @work(thread=True, exclusive=True)
    def _run_trace(self, obj_id: str) -> None:
        runtime = self._runtime
        try:
            # runtime.py:1232 `trace` -> storage.py:2758, raising KeyError
            # (storage.py:2762) when the id does not exist.
            graph = runtime.trace(obj_id)
        except Exception as exc:
            self.app.call_from_thread(self._render_error, obj_id, str(exc))
            return
        self.app.call_from_thread(self._render_graph, graph)

    def _render_graph(self, graph: TraceGraph) -> None:
        tree = self.query_one("#prov-tree", Tree)
        tree.clear()
        tree.root.set_label(f"[{brand.MINT}]{graph.root_id}[/]")

        # `graph.nodes` is BFS order from the root (storage.py's `trace()`
        # discovers each node from an already-visited one), so a node's
        # parent is whichever earlier node it shares an edge with. Walking
        # nodes in that order and consuming the first matching edge
        # reconstructs a tree without re-running the BFS here.
        tree_nodes = {graph.root_id: tree.root}
        remaining_edges = list(graph.edges)
        for node in graph.nodes[1:]:
            parent_node = tree.root
            edge_label = "linked"
            for index, edge in enumerate(remaining_edges):
                src, dst = edge.get("src"), edge.get("dst")
                other = dst if src == node.id else (src if dst == node.id else None)
                if other is not None and other in tree_nodes:
                    parent_node = tree_nodes[other]
                    edge_label = str(edge.get("type", "linked"))
                    del remaining_edges[index]
                    break
            label = (
                f"[{brand.LAVENDER}]{edge_label}[/] → "
                f"[{brand.CYAN}]{node.kind.value}[/] {node.id}  "
                f"[{brand.TEXT_MUTED}]{_preview_attrs(node.attrs, 50)}[/]"
            )
            tree_nodes[node.id] = parent_node.add(label, expand=True)
        tree.root.expand()

    def _render_error(self, obj_id: str, message: str) -> None:
        tree = self.query_one("#prov-tree", Tree)
        tree.clear()
        tree.root.set_label(f"[{brand.RED}]error tracing {obj_id}: {message}[/]")
        tree.root.expand()


# ---------------------------------------------------------------------------
# Memory page (composite: records table + provenance-below + one shared log)
# ---------------------------------------------------------------------------


class MemoryPanel(_RuntimePanel):
    """Memory tab: the record table, its provenance trace, and the tab's log.

    This is the page the operator asked for -- "the memory tab should act
    like a table so I can copy IDs ... put provenance below memory, making
    it easier to search". `MemoryRecordsPanel` sits on top, `ProvPanel`
    directly beneath it (selecting a record above traces it here, see
    `MemoryRecordsPanel._on_row_selected`), and exactly one `RichLog`
    (`#log-memory`) closes the page -- `app.py::_write("memory", ...)` and
    `action_clear_output` keep targeting that one id unchanged.
    """

    def compose(self) -> ComposeResult:
        yield MemoryRecordsPanel(id="memory-records")
        yield ProvPanel(id="memory-prov")
        yield RichLog(id="log-memory", markup=True, wrap=True, highlight=True)

    def reload(self) -> None:
        """Reload both children.

        `app.py::_refresh_panel` calls `reload()` on whatever it finds at
        `#panel-memory` after any command runs on this tab; both children
        already answer to a query/id left in their own Input if any, so
        this just forwards to both rather than duplicating that logic.
        """
        self.query_one("#memory-records", MemoryRecordsPanel).reload()
        self.query_one("#memory-prov", ProvPanel).reload()


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

#: Tab id -> panel class. `app.py` composes from this instead of a parallel
#: if/elif chain, so a tab added here is a tab added in the app.
PANEL_CLASSES: dict[str, type[Vertical]] = {
    "memory": MemoryPanel,
    "retrieval": RetrievalPanel,
    "benchmarks": BenchmarksPanel,
    "compression": CompressionPanel,
    "chat": ChatPanel,
    "live": LivePanel,
}
