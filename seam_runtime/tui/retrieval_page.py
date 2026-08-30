"""The Retrieval section: retrieval query, subsystem status, and activity.

The mockup's Retrieval screen is a dashboard of score cards, subsystem
status tiles, and a timeline. Two of the three have honest data sources
here and one does not:

* **SEAM status** tiles come from the backend's own metrics collector
  (`DashboardApp._collect_metrics`, the exact method the `stats` verb
  uses) plus `runtime.check_ready()`, so the tiles can never disagree with
  the CLI.
* **The timeline** renders real workspace events (`iter_workspace_events`,
  the same call the REST `/workspace/events` route makes). They are run
  lifecycle events, not per-query retrieval logs — the section title says
  "activity", not "retrievals", for exactly that reason.
* **Score cards** (Recall@10 / MRR / nDCG@10 / latency) have no persisted
  source: the store records benchmark suite runs, not per-retrieval
  metric history. The cards keep their design shape but read
  "no data yet" with what would populate them, rather than simulating
  numbers.

The interactive retrieval query box and ranked-candidate table from the
previous Retrieval tab stay at the top: the dashboard describes the
subsystem, the query box is how the operator actually uses it.
"""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from . import brand
from .panels import RetrievalPanel, _event_summary

__all__ = ["RetrievalPage", "_StatusCard", "_ScoreCard"]

#: The design's four score cards. Labels stay as designed; values render
#: only when a real source exists for them (none does yet — see module
#: docstring), so the cards carry an explicit no-data state instead.
_SCORE_CARDS: tuple[tuple[str, str], ...] = (
    ("Recall@10", "retrieval evaluation runs"),
    ("MRR", "retrieval evaluation runs"),
    ("nDCG@10", "retrieval evaluation runs"),
    ("Fusion latency p50", "latency-instrumented runs"),
)


class _StatusCard(Vertical):
    """One subsystem tile: label, value badge, and one-line detail."""

    def __init__(self, label: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._label = label

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="status-label")
        yield Static("…", classes="status-value")
        yield Static("", classes="status-detail")

    def set_state(self, value: str, detail: str, *, ok: bool = True) -> None:
        color = brand.MINT if ok else brand.YELLOW
        self.query_one(".status-value", Static).update(f"[b {color}]{value}[/]")
        self.query_one(".status-detail", Static).update(detail)


class _ScoreCard(Vertical):
    """One metric card: label, big value, trend line."""

    def __init__(self, label: str, hint: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._label = label
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Static(self._label.upper(), classes="score-label")
        yield Static(f"[{brand.TEXT_DIM}]—[/]", classes="score-value")
        yield Static(f"no data yet · {self._hint}", classes="score-trend")


class RetrievalPage(VerticalScroll):
    """Retrieval: query box + ranked results, subsystem status, activity."""

    def compose(self) -> ComposeResult:
        yield Static("Retrieval", classes="page-title")
        yield Static(
            "Query the live engine, then read the subsystem's state below.",
            classes="page-subtitle",
        )
        yield RetrievalPanel(id="retrieval-panel")

        yield Static("RETRIEVAL SCORES", classes="pane-label")
        with Horizontal(id="retrieval-scores"):
            for label, hint in _SCORE_CARDS:
                yield _ScoreCard(label, hint)

        yield Static("SEAM STATUS", classes="pane-label")
        with Vertical(id="seam-status-grid"):
            with Horizontal(classes="status-row"):
                yield _StatusCard("SQLite store", id="status-sqlite")
                yield _StatusCard("Vector index", id="status-vector")
                yield _StatusCard("Namespaces", id="status-namespaces")
            with Horizontal(classes="status-row"):
                yield _StatusCard("Embedding model", id="status-embedding")
                yield _StatusCard("pgvector leg", id="status-pgvector")
                yield _StatusCard("Benchmark runs", id="status-benchmarks")

        yield Static("RECENT ACTIVITY", classes="pane-label")
        yield Static("", id="retrieval-timeline", classes="timeline")

    def on_mount(self) -> None:
        self._load_status()

    def reload(self) -> None:
        self.query_one("#retrieval-panel", RetrievalPanel).reload()
        self._load_status()

    @work(thread=True, exclusive=True)
    def _load_status(self) -> None:
        backend = self.app.backend  # type: ignore[attr-defined]
        runtime = backend.runtime
        ready = True
        try:
            runtime.check_ready()
        except Exception:
            ready = False
        try:
            # `DashboardApp._collect_metrics` is the collector behind the
            # backend's own `stats` verb — the same read the CLI performs.
            metrics = backend._collect_metrics()
            run_count = len(runtime.list_benchmark_runs(limit=25))
        except Exception as exc:
            self.app.call_from_thread(self._render_status_error, str(exc))
            return
        try:
            events = list(runtime.store.iter_workspace_events(limit=200))
        except Exception:
            events = []
        self.app.call_from_thread(
            self._render_status, metrics, run_count, ready, events[-12:][::-1]
        )

    def _render_status(
        self,
        metrics: Any,
        run_count: int,
        ready: bool,
        events: list[dict[str, Any]],
    ) -> None:
        self.query_one("#status-sqlite", _StatusCard).set_state(
            "ok" if ready else "degraded",
            f"{metrics.total_records} records · {metrics.db_size}",
            ok=ready,
        )
        self.query_one("#status-vector", _StatusCard).set_state(
            "ok",
            f"{metrics.vector_entries} vectors · {metrics.vector_adapter_name}",
        )
        self.query_one("#status-namespaces", _StatusCard).set_state(
            "ok",
            f"{metrics.namespaces} namespaces · {metrics.scopes} scopes",
        )
        self.query_one("#status-embedding", _StatusCard).set_state(
            "ok",
            f"{metrics.model_name} · {metrics.execution_mode}",
        )
        self.query_one("#status-pgvector", _StatusCard).set_state(
            "configured" if metrics.pgvector_configured else "off",
            "SEAM_PGVECTOR_DSN is unset"
            if not metrics.pgvector_configured
            else "dsn configured",
        )
        self.query_one("#status-benchmarks", _StatusCard).set_state(
            "ok" if run_count else "none",
            f"{run_count} persisted run(s)",
        )

        timeline = self.query_one("#retrieval-timeline", Static)
        if not events:
            timeline.update(f"[{brand.TEXT_DIM}]no workspace activity recorded yet[/]")
            return
        lines: list[str] = []
        for event in events:
            kind = str(event.get("event_type", ""))
            created = str(event.get("created_at", ""))
            summary = _event_summary(event.get("payload") or {})
            lines.append(
                f"[{brand.TEXT_DIM}]●[/] [{brand.TEXT_DIM}]{created}[/] "
                f"[b {brand.CYAN}]{kind}[/]  "
                f"[{brand.TEXT_MUTED}]{summary}[/]"
            )
        timeline.update("\n".join(lines))

    def _render_status_error(self, message: str) -> None:
        for card_id in (
            "#status-sqlite",
            "#status-vector",
            "#status-namespaces",
            "#status-embedding",
            "#status-pgvector",
            "#status-benchmarks",
        ):
            self.query_one(card_id, _StatusCard).set_state("error", message, ok=False)
