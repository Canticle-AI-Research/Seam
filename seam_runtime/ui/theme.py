"""Color and token source-of-truth for the SEAM operator surface.

Rule: every hex literal used by logo/bars/animations/Textual CSS comes
from this module. If a color drifts, it drifts here, not in three files.

Rich markup consumes hex strings directly. Textual CSS can reference
these via f-string composition (see ``as_css_vars``) if we move CSS out
of the dashboard's inline ``CSS`` attribute in a later pass.

Palette rationale
-----------------
The base tones (``CYAN``, ``BLUE_DEEP``, ``ICE``) are the exact hexes the
current ``_refresh_logo`` already emits — keeping them here means wiring
is a literal drop-in rather than a visual shift.

Accents (``VIOLET``, ``BLOOM``, ``GOLD``) are introduced for signal
states (compression bloom, warning stripe, benchmark peak) and to give
the machine-language stream enough color surface to encode tag kinds
without looking muddy.

Semantic aliases map intent → tone so callers don't hardcode a
color for a meaning. If we want to repaint the brand later, the aliases
are the pivot layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# ---- Base tones (kept in sync with dashboard.py:_refresh_logo) -------------

BG_DEEP = "#050b1e"        # dashboard chrome background
BG_PANEL = "#08132a"       # panel interior (slightly lifted from chrome)
BG_SUNK = "#020613"        # below-panel shadow / CRT phosphor well

BLUE_DEEP = "#2f63ff"      # structural frame, dim grid
BLUE = "#4f8cfb"           # panel borders (matches existing logo-header border)
BLUE_SOFT = "#66b8ff"      # secondary text, separators
BLUE_FOG = "#5fc8ff"       # field labels
ICE = "#a6fcff"            # primary brand text (SEAM wordmark letters)
ICE_PALE = "#bfefff"       # field values
CYAN = "#7fe0ff"           # accent lines, highlights
CYAN_BRIGHT = "#8df6ff"    # logo-header foreground (existing css)

MINT = "#7efdb9"           # ok / configured / online
MINT_DIM = "#4bc08a"       # ok secondary

GOLD = "#f4d676"           # warning, attention, activity blip
GOLD_DIM = "#b9a04a"       # warning trailing

BLOOM = "#d391ff"          # compression success bloom, magenta highlight
VIOLET = "#9b6cff"         # MIRL tag accents (@ # >)
VIOLET_DIM = "#5a3fb3"     # violet shadow

RED = "#ff6b6b"            # error, stalled
RED_DIM = "#a83a3a"        # error trailing

GRID_DIM = "#1a2540"       # inactive pixel / off-state grid dot
GRID_MID = "#274063"       # idle fill

# ---- Semantic aliases -------------------------------------------------------
#
# Use these in renderer code. Never reach for a base tone by its physical
# name inside logo/bars/animations — always go through an alias so intent
# is explicit and the palette is repaintable.

ACCENT = CYAN                  # default highlight
SIGNAL = ICE                   # primary text on dark
SIGNAL_DIM = ICE_PALE          # secondary text
FRAME = BLUE                   # panel border
FRAME_DIM = BLUE_DEEP          # inactive / backgrounded frame
LABEL = BLUE_FOG               # "Model:", "Mode:", etc.
VALUE = ICE_PALE               # value shown after a label
BG = BG_DEEP                   # dashboard chrome

STATUS_OK = MINT
STATUS_WARN = GOLD
STATUS_ERR = RED
STATUS_IDLE = GRID_MID

TAG_ENTITY = ICE               # @
TAG_CLAIM = CYAN               # #
TAG_EVENT = GOLD               # !
TAG_RELATION = VIOLET          # >
TAG_STATE = MINT               # ~
TAG_EVIDENCE = BLOOM           # ^
TAG_SOURCE = BLUE_SOFT         # %
TAG_DELTA = GOLD_DIM           # +
TAG_ALIAS = CYAN_BRIGHT        # =

COMPRESSION_SOURCE = SIGNAL_DIM
COMPRESSION_MACHINE = BLOOM
COMPRESSION_PIPELINE = ACCENT

BAR_FILL_OK = MINT
BAR_FILL_WARN = GOLD
BAR_FILL_ERR = RED
BAR_FILL_RUN = ACCENT
BAR_TRACK = GRID_DIM


# ---- Tag table --------------------------------------------------------------

IR_TAG_COLORS: Mapping[str, str] = {
    "@": TAG_ENTITY,
    "#": TAG_CLAIM,
    "!": TAG_EVENT,
    ">": TAG_RELATION,
    "~": TAG_STATE,
    "^": TAG_EVIDENCE,
    "%": TAG_SOURCE,
    "+": TAG_DELTA,
    "=": TAG_ALIAS,
}


# ---- Rich markup helpers ----------------------------------------------------

def fg(color: str, text: str) -> str:
    """Wrap ``text`` in Rich foreground markup. Caller owns escaping."""
    return f"[{color}]{text}[/]"


def fg_bg(fgc: str, bgc: str, text: str) -> str:
    """Foreground + background — used by the half-block renderer."""
    return f"[{fgc} on {bgc}]{text}[/]"


# ---- CSS export -------------------------------------------------------------

@dataclass(frozen=True)
class CssVars:
    """Bundle of hex values ready to be interpolated into Textual CSS.

    Textual's ``CSS`` class attribute is a plain string, so we build one
    with ``str.format_map`` in dashboard.py to avoid duplicating hex
    literals across the Python source and the CSS.
    """

    bg: str = BG_DEEP
    bg_panel: str = BG_PANEL
    frame: str = FRAME
    frame_dim: str = FRAME_DIM
    signal: str = SIGNAL
    accent: str = ACCENT
    status_ok: str = STATUS_OK


def as_css_vars() -> dict[str, str]:
    vars_ = CssVars()
    return {k: getattr(vars_, k) for k in vars_.__dataclass_fields__}


# ---- Preview ---------------------------------------------------------------

def _preview() -> None:  # pragma: no cover - visual
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="SEAM palette", expand=False)
    table.add_column("token")
    table.add_column("hex")
    table.add_column("swatch")

    groups = [
        ("base — blues",  [("BG_DEEP", BG_DEEP), ("BG_PANEL", BG_PANEL),
                           ("BLUE_DEEP", BLUE_DEEP), ("BLUE", BLUE),
                           ("BLUE_SOFT", BLUE_SOFT), ("BLUE_FOG", BLUE_FOG),
                           ("ICE", ICE), ("ICE_PALE", ICE_PALE),
                           ("CYAN", CYAN), ("CYAN_BRIGHT", CYAN_BRIGHT)]),
        ("base — accents",[("MINT", MINT), ("MINT_DIM", MINT_DIM),
                           ("GOLD", GOLD), ("GOLD_DIM", GOLD_DIM),
                           ("BLOOM", BLOOM), ("VIOLET", VIOLET),
                           ("RED", RED)]),
        ("aliases",       [("ACCENT", ACCENT), ("SIGNAL", SIGNAL),
                           ("FRAME", FRAME), ("STATUS_OK", STATUS_OK),
                           ("STATUS_WARN", STATUS_WARN), ("STATUS_ERR", STATUS_ERR)]),
        ("tags",          [(f"TAG {t}", c) for t, c in IR_TAG_COLORS.items()]),
    ]
    for group, entries in groups:
        table.add_row(f"[bold]{group}[/]", "", "")
        for name, color in entries:
            swatch = f"[{color}]" + ("█" * 8) + "[/]"
            table.add_row(f"  {name}", color, swatch)
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    _preview()
