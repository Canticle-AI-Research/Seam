"""The Memory section: record list on the left, record detail on the right.

The mockup's Memory screen is a three-pane workspace: a fixed-width record
list (with a Table/Graph toggle and a search box that doubles as an
id-jump), and a detail pane showing the selected record's header, its
attribute table, its raw MIRL form, and its provenance trace. The design's
double-click attribute editing is deliberately not implemented: records are
canonical MIRL and the runtime exposes no record-write verb for a panel to
call, so the detail pane is read-only rather than inventing a write path
(TUI_OPERATOR_SURFACE contract #1). The Graph toggle renders the selected
record's real evidence chain — `runtime.trace` edges — rather than the
mockup's decorative starfield, because that is the graph data the backend
actually owns.
"""

from __future__ import annotations

import json
from typing import Any

from rich.markup import escape
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, RichLog, Static

from . import brand
from .graph_canvas import ConstellationGraph
from .keys import SeamInput
from .panels import MemoryRecordsPanel, ProvPanel
from .split_pane import PaneDivider

__all__ = ["MemoryPage"]

#: Design token: record-kind badge colours (mockup `KIND_COLORS`).
KIND_COLORS: dict[str, str] = {
    "ENT": brand.MINT,
    "CLM": brand.CYAN,
    "REL": brand.LAVENDER,
    "RAW": brand.ORANGE,
}


def _kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind.upper(), brand.TEXT_MUTED)


class MemoryPage(Horizontal):
    """Memory: the record list pane and the record detail pane."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._view_mode = "table"
        self._detail_mode = "record"
        self._selected_id: str | None = None

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="memory-list-pane"):
            with Horizontal(id="memory-view-toggle"):
                yield Button("Table", id="view-table-btn", compact=True)
                yield Button("Graph", id="view-graph-btn", compact=True)
            yield SeamInput(
                placeholder="search records, or paste an id…",
                id="memory-search",
            )
            yield MemoryRecordsPanel(id="memory-records")
            with Vertical(id="memory-graph-pane"):
                with Vertical(id="graph-toolbar"):
                    with Horizontal(id="graph-controls"):
                        yield Button("−", id="graph-zoom-out", compact=True)
                        yield Static("100%", id="graph-zoom-label")
                        yield Button("+", id="graph-zoom-in", compact=True)
                        yield Button("0", id="graph-zoom-reset", compact=True)
                        yield Static(
                            "scroll: zoom · drag: orbit · shift+drag: pan",
                            id="graph-gesture-hint",
                        )
                    with Horizontal(id="graph-layout-controls"):
                        yield Button("[f] Force", id="layout-force", compact=True)
                        yield Button("[t] Tree", id="layout-tree", compact=True)
                        yield Button(
                            "[c] Constellation",
                            id="layout-constellation",
                            compact=True,
                        )
                yield Static(
                    "click node: inspect · scroll: zoom · drag: orbit · shift+drag: pan",
                    id="graph-help",
                )
                yield ConstellationGraph(id="constellation-graph")
        yield PaneDivider(
            target_id="memory-list-pane",
            minimum=35,
            maximum=90,
            other_minimum=40,
            id="memory-divider",
        )
        with Vertical(id="memory-detail-pane"):
            with Horizontal(id="detail-header"):
                yield Static("", id="detail-kind", classes="kind-badge")
                yield Static("", id="detail-id")
                yield Button("Copy ID", id="detail-copy", compact=True)
            yield Static("", id="detail-meta")
            with Horizontal(id="detail-mode-toggle"):
                yield Button("Record", id="detail-record-btn", compact=True)
                yield Button("MIRL", id="detail-mirl-btn", compact=True)
            with Vertical(id="detail-record-pane"):
                yield Static("", id="detail-summary")
                yield Static("ATTRIBUTES", classes="pane-label")
                yield DataTable(id="detail-attrs")
            with Vertical(id="detail-mirl-pane"):
                yield Static("RAW MIRL RECORD", classes="pane-label")
                yield RichLog(id="detail-mirl", highlight=True)
            yield Static("PROVENANCE TRACE", classes="pane-label")
            yield ProvPanel(id="memory-prov")

    def on_mount(self) -> None:
        attrs = self.query_one("#detail-attrs", DataTable)
        attrs.add_columns("key", "value")
        attrs.cursor_type = "row"
        self._render_no_record()
        self._sync_view_mode()
        self._sync_detail_mode()
        self._sync_graph_controls()

    def reload(self) -> None:
        """Reload the records list (and re-trace whatever is selected)."""
        self.query_one("#memory-records", MemoryRecordsPanel).reload()
        self.query_one("#memory-prov", ProvPanel).reload()
        if self._view_mode == "graph":
            self._load_graph()

    # -- view toggle (Table / Graph) ----------------------------------------

    def _sync_view_mode(self) -> None:
        graph = self._view_mode == "graph"
        self.query_one("#memory-records").display = not graph
        self.query_one("#memory-search").display = not graph
        self.query_one("#memory-graph-pane").display = graph
        table_btn = self.query_one("#view-table-btn", Button)
        graph_btn = self.query_one("#view-graph-btn", Button)
        table_btn.set_class(not graph, "-active")
        graph_btn.set_class(graph, "-active")

    @on(Button.Pressed, "#view-table-btn")
    def _on_view_table(self) -> None:
        self._view_mode = "table"
        self._sync_view_mode()

    @on(Button.Pressed, "#view-graph-btn")
    def _on_view_graph(self) -> None:
        self._view_mode = "graph"
        self._sync_view_mode()
        self._load_graph()

    # -- graph canvas --------------------------------------------------------

    def _sync_graph_controls(self) -> None:
        graph = self.query_one("#constellation-graph", ConstellationGraph)
        self.query_one("#graph-zoom-label", Static).update(f"{round(graph.zoom * 100)}%")
        for layout in ("force", "tree", "constellation"):
            self.query_one(f"#layout-{layout}", Button).set_class(
                graph.graph_layout == layout,
                "-active",
            )

    @on(Button.Pressed, "#graph-zoom-in")
    def _on_graph_zoom_in(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).zoom_by(0.1)

    @on(Button.Pressed, "#graph-zoom-out")
    def _on_graph_zoom_out(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).zoom_by(-0.1)

    @on(Button.Pressed, "#graph-zoom-reset")
    def _on_graph_zoom_reset(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).reset_view()

    @on(Button.Pressed, "#layout-force")
    def _on_graph_force(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).set_layout("force")

    @on(Button.Pressed, "#layout-tree")
    def _on_graph_tree(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).set_layout("tree")

    @on(Button.Pressed, "#layout-constellation")
    def _on_graph_constellation(self) -> None:
        self.query_one("#constellation-graph", ConstellationGraph).set_layout(
            "constellation"
        )

    @on(ConstellationGraph.ViewChanged)
    def _on_graph_view_changed(self) -> None:
        self._sync_graph_controls()

    @on(ConstellationGraph.NodeSelected)
    def _on_graph_node_selected(self, event: ConstellationGraph.NodeSelected) -> None:
        records = self.query_one("#memory-records", MemoryRecordsPanel)
        if records.try_select_id(event.node_id):
            return
        self._selected_id = event.node_id
        self.query_one("#detail-kind", Static).update(
            f"[b {brand.LAVENDER}]GRAPH[/]"
        )
        self.query_one("#detail-id", Static).update(
            f"[b {brand.TEXT_MAIN}]{event.node_id}[/]"
        )
        self.query_one("#detail-meta", Static).update(
            f"[{brand.TEXT_DIM}]knowledge-graph node[/]"
        )

    @work(thread=True, exclusive=True)
    def _load_graph(self) -> None:
        """Load the real bounded knowledge-graph projection from the runtime."""
        runtime = self.app.backend.runtime  # type: ignore[attr-defined]
        try:
            payload = runtime.knowledge_graph(limit=300, hops=2)
        except Exception as exc:
            self.app.call_from_thread(self._render_graph_error, str(exc))
            return
        self.app.call_from_thread(self._render_knowledge_graph, payload)

    def _render_knowledge_graph(self, payload: dict[str, object]) -> None:
        graph = self.query_one("#constellation-graph", ConstellationGraph)
        graph.set_graph(payload)
        graph.set_selected(self._selected_id)
        graph.tooltip = None
        self._sync_graph_controls()

    @on(PaneDivider.Resized)
    def _on_memory_resized(self, event: PaneDivider.Resized) -> None:
        self.query_one("#memory-list-pane").styles.width = event.width
        self.refresh(layout=True)

    # -- record search / id jump ---------------------------------------------

    @on(Input.Changed, "#memory-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        """Filter the loaded rows as the operator types.

        The records panel applies this filter client-side over rows it
        already loaded from `list_record_summaries`, which keeps the search
        instant and keeps the data path on the store's own API (no invented
        SQL, TUI_OPERATOR_SURFACE contract #1).
        """
        records = self.query_one("#memory-records", MemoryRecordsPanel)
        records.apply_filter(event.value.strip())

    @on(Input.Submitted, "#memory-search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        """Treat an exact submitted id as an explicit jump."""
        records = self.query_one("#memory-records", MemoryRecordsPanel)
        if event.value.strip():
            records.try_select_id(event.value.strip())

    # -- detail pane ----------------------------------------------------------

    def _sync_detail_mode(self) -> None:
        mirl = self._detail_mode == "mirl"
        self.query_one("#detail-record-pane").display = not mirl
        self.query_one("#detail-mirl-pane").display = mirl
        self.query_one("#detail-record-btn", Button).set_class(not mirl, "-active")
        self.query_one("#detail-mirl-btn", Button).set_class(mirl, "-active")

    @on(Button.Pressed, "#detail-record-btn")
    def _on_detail_record(self) -> None:
        self._detail_mode = "record"
        self._sync_detail_mode()

    @on(Button.Pressed, "#detail-mirl-btn")
    def _on_detail_mirl(self) -> None:
        self._detail_mode = "mirl"
        self._sync_detail_mode()

    @on(Button.Pressed, "#detail-copy")
    def _on_detail_copy(self) -> None:
        """Copy the selected record's id — the explicit copy path."""
        if not self._selected_id:
            return
        self.app.copy_to_clipboard(self._selected_id)
        try:
            self.app.query_one("#app-log", RichLog).write(
                f"[{brand.TEXT_DIM}]copied id ↓[/]\n{self._selected_id}"
            )
        except Exception:
            pass

    def _render_no_record(self) -> None:
        self.query_one("#detail-kind", Static).update("")
        self.query_one("#detail-id", Static).update(
            f"[{brand.TEXT_DIM}]no record selected[/]"
        )
        self.query_one("#detail-meta", Static).update(
            f"[{brand.TEXT_DIM}]select a row in the list to inspect it[/]"
        )
        self.query_one("#detail-attrs", DataTable).clear()
        self.query_one("#detail-mirl", RichLog).clear()
        self.query_one("#detail-summary", Static).update("")
        self.query_one("#constellation-graph", ConstellationGraph).set_selected(None)

    #: Fired by `MemoryRecordsPanel` whenever a row becomes the selected
    #: record — click, Enter, cursor move, or the search box's id-jump.
    @on(MemoryRecordsPanel.RecordSelected)
    def _on_record_selected(self, event: "MemoryRecordsPanel.RecordSelected") -> None:
        self._selected_id = event.record_id
        self._render_record(event.record_id, event.namespace, event.scope)
        # The designed detail pane always follows the selected record with
        # its provenance trace; selection is not a separate submit step.
        query = self.query_one("#prov-query", Input)
        if query.value != event.record_id:
            query.value = event.record_id
            query.post_message(Input.Submitted(query, event.record_id))

    def _render_record(self, record_id: str, namespace: str, scope: str) -> None:
        kind = record_id.split(":", 1)[0].upper()
        color = _kind_color(kind)
        self.query_one("#detail-kind", Static).update(f"[b {color}]{kind}[/]")
        self.query_one("#detail-id", Static).update(f"[b {brand.TEXT_MAIN}]{record_id}[/]")
        self.query_one("#detail-meta", Static).update(
            f"[{brand.TEXT_DIM}]{namespace} · {scope}[/]"
        )
        self._load_record(record_id)
        self.query_one("#constellation-graph", ConstellationGraph).set_selected(record_id)

    @work(thread=True, exclusive=True)
    def _load_record(self, record_id: str) -> None:
        runtime = self.app.backend.runtime  # type: ignore[attr-defined]
        try:
            records = runtime.store.load_ir(ids=[record_id]).by_id()
        except Exception as exc:
            self.app.call_from_thread(self._render_detail_error, str(exc))
            return
        record = records.get(record_id)
        self.app.call_from_thread(self._render_detail_record, record_id, record)

    def _render_detail_record(self, record_id: str, record: Any) -> None:
        attrs = self.query_one("#detail-attrs", DataTable)
        attrs.clear()
        mirl = self.query_one("#detail-mirl", RichLog)
        mirl.clear()
        if record is None:
            attrs.add_row(f"[{brand.RED}]unavailable[/]", "record could not be loaded")
            return
        summary_value = next(
            (
                record.attrs[key]
                for key in ("summary", "text", "claim", "content", "object")
                if key in record.attrs and record.attrs[key]
            ),
            record.id,
        )
        self.query_one("#detail-summary", Static).update(
            f"[b {brand.TEXT_MAIN}]{escape(str(summary_value))}[/]"
        )
        for key in sorted(record.attrs):
            value = record.attrs[key]
            if not isinstance(value, str):
                try:
                    value = json.dumps(value, sort_keys=True)
                except TypeError:
                    value = str(value)
            attrs.add_row(f"[{brand.LAVENDER}]{key}[/]", str(value))
        try:
            mirl.write(
                json.dumps(
                    {
                        "id": record.id,
                        "kind": record.kind.value,
                        "created_at": record.created_at,
                        "attrs": record.attrs,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        except TypeError:
            mirl.write(str(record.attrs))

    def _render_detail_error(self, message: str) -> None:
        attrs = self.query_one("#detail-attrs", DataTable)
        attrs.clear()
        attrs.add_row(f"[{brand.RED}]error[/]", message)

    def _render_graph_error(self, message: str) -> None:
        graph = self.query_one("#constellation-graph", ConstellationGraph)
        graph.set_graph({"nodes": [], "edges": []})
        graph.tooltip = f"Knowledge graph unavailable: {message}"
