"""The nav rail: the design's left column of sections and hotkey hints.

The mockup's navigation contract is a vertical rail of five sections
(Memory, Retrieval, Benchmarks, Compression, Settings) with a two-letter
glyph tile, a hotkey digit, and a Help row pinned to the bottom. The rail
replaces the old `TabbedContent` tab strip: section switching is an
explicit action on `#sections` (a `ContentSwitcher`), so the visual
language comes from the rail rather than textual's built-in tab chrome.

Chat is not a section in this information architecture — it is a topbar
overlay drawer — so it deliberately has no rail row. `tab chat` in the
command bar opens the drawer instead of switching a tab.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, ListItem, ListView, Static

from . import brand

__all__ = ["SECTIONS", "SectionSpec", "NavRail", "NavRailItem"]


@dataclass(frozen=True)
class SectionSpec:
    """One rail section: id, label, glyph tile, accent tone, and micro-tag."""

    id: str
    label: str
    glyph: str
    tone: str
    tag: str
    summary: str


#: The five sections, in rail order. Ids keep the previous tab ids so the
#: `tab` command, `_active_tab_id()`, and panel wiring stay stable.
SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        "memory", "Memory", "ME", brand.MINT, "CAPTURE / INSPECT",
        "Canonical MIRL records and their evidence chain.",
    ),
    SectionSpec(
        "retrieval", "Retrieval", "RT", brand.CYAN, "RECALL",
        "Ranked candidates plus live subsystem status.",
    ),
    SectionSpec(
        "benchmarks", "Benchmarks", "BN", brand.YELLOW, "MEASURE",
        "Persisted benchmark runs and their scores.",
    ),
    SectionSpec(
        "compression", "Compression", "CP", brand.ORANGE, "COMPRESS",
        "Document ingest state and MIRL conversion.",
    ),
    SectionSpec(
        "settings", "Settings", "ST", brand.LAVENDER, "CONFIGURE",
        "Every registry-backed runtime knob, editable.",
    ),
)

#: The support URL the mockup's Help row opens. In a terminal the honest
#: equivalent is copying the URL to the clipboard and echoing it, rather
#: than silently spawning a browser the operator did not ask for.
HELP_URL = "https://canticle.cc/wiki/seam/support"

_TONES = {
    brand.MINT: brand.MINT,
    brand.CYAN: brand.CYAN,
    brand.YELLOW: brand.YELLOW,
    brand.ORANGE: brand.ORANGE,
    brand.LAVENDER: brand.LAVENDER,
}


class NavRailItem(ListItem):
    """One keyboard-selectable rail row with a compact-safe glyph tile."""

    def __init__(self, section: SectionSpec, index: int) -> None:
        super().__init__(id=f"nav-{section.id}")
        self.section = section
        self.index_number = index
        self.tooltip = f"{index} · {section.label} — {section.summary}"

    def compose(self) -> ComposeResult:
        yield Static(str(self.index_number), classes="nav-hotkey")
        yield Static(
            self.section.glyph,
            classes="nav-glyph",
            markup=False,
        )
        yield Static(self.section.label, classes="nav-label")
        yield Static(self.section.summary, classes="nav-summary")


class NavRail(Vertical):
    """The left rail: section list, keymap hints, and the Help row."""

    DEFAULT_CSS = """
    NavRail {
        width: 26;
        background: #16161e;
        border-right: solid #3b3d57;
        padding: 1 1 0 1;
    }
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._sections = SECTIONS

    def compose(self) -> ComposeResult:
        yield ListView(
            *(NavRailItem(section, index) for index, section in enumerate(SECTIONS, 1)),
            id="nav-list",
        )
        yield Static(
            "1–5 sections · / commands\n! shell · ? chat",
            id="nav-hints",
        )
        yield Button("Help", id="nav-help", compact=True)

    def highlight(self, section_id: str) -> None:
        """Mark the rail row for `section_id` as the active one."""
        try:
            rail = self.query_one("#nav-list", ListView)
            rail.index = next(
                (i for i, section in enumerate(self._sections) if section.id == section_id),
                None,
            )
            for item in rail.query(NavRailItem):
                item.set_class(item.section.id == section_id, "-active")
        except Exception:
            # Mount/teardown races: on_mount performs the authoritative sync.
            return
