"""Pixel-art SEAM logo for the Textual dashboard header.

Why pixel-art in a terminal
---------------------------
The dashboard is a TUI. SVGs, PNGs, and CSS gradients don't render.
The one tool that does: half-block Unicode glyphs (U+2580 ▀, U+2584 ▄,
U+2588 █) painted with truecolor Rich markup. Each terminal row then
carries two pixel rows, halving the vertical pixel cost of the art.

Budget
------
The dashboard header is ``height: 4``. That's four terminal rows → eight
pixel rows. All glyphs in this module fit inside 8 pixel rows. If the
header ever grows, the renderer scales by adding more row-pairs, not by
resizing glyphs.

Grids
-----
Glyphs are stored as strings of ``1`` / ``0`` / ``.`` characters (``.`` is
treated as off). Row-major. Each row must be the same width. The
renderer pairs adjacent rows and emits one terminal row per pair using
the half-block char table.

Preview
-------
``python -m seam_runtime.ui.logo`` prints the logo + wordmark. Use
``--mark`` / ``--wordmark`` / ``--header`` to isolate a piece.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

from . import theme

# ---- Glyph grids -----------------------------------------------------------
#
# Each grid is a tuple of row strings. ``1`` = lit, anything else = off.
# Width must be uniform. Height may be odd — the renderer pads the final
# row-pair with blanks.

PIXEL_S_MARK: tuple[str, ...] = (
    ".111111.",
    "11......",
    "11......",
    "11......",
    ".111111.",
    "......11",
    "......11",
    "111111..",
)

_S_WORD: tuple[str, ...] = (
    ".1111",
    "1....",
    "1....",
    ".111.",
    "....1",
    "....1",
    "1111.",
)

_E_WORD: tuple[str, ...] = (
    "11111",
    "1....",
    "1....",
    "1111.",
    "1....",
    "1....",
    "11111",
)

_A_WORD: tuple[str, ...] = (
    ".111.",
    "1...1",
    "1...1",
    "11111",
    "1...1",
    "1...1",
    "1...1",
)

_M_WORD: tuple[str, ...] = (
    "1...1",
    "11.11",
    "1.1.1",
    "1.1.1",
    "1...1",
    "1...1",
    "1...1",
)

WORDMARK_LETTERS: dict[str, tuple[str, ...]] = {
    "S": _S_WORD,
    "E": _E_WORD,
    "A": _A_WORD,
    "M": _M_WORD,
}


# ---- Rendering -------------------------------------------------------------

def _pad_to_even(grid: Sequence[str]) -> list[str]:
    rows = list(grid)
    if len(rows) % 2:
        rows.append(" " * len(rows[0]))
    return rows


def _lit(ch: str) -> bool:
    return ch == "1"


def _half_char(top: bool, bot: bool) -> str:
    if top and bot:
        return "█"
    if top:
        return "▀"
    if bot:
        return "▄"
    return " "


@dataclass(frozen=True)
class GlyphStyle:
    """Colors applied to a single glyph.

    ``lit`` is the pixel foreground. ``background`` is applied behind
    every half-block char (so the unlit halves have a solid color rather
    than terminal default). ``shadow`` is currently unused but reserved
    for a future drop-shadow row variant.
    """

    lit: str = theme.SIGNAL
    background: str = theme.BG_PANEL
    shadow: str = theme.VIOLET_DIM


DEFAULT_MARK_STYLE = GlyphStyle(lit=theme.ICE, background=theme.BG_DEEP)
DEFAULT_WORDMARK_STYLE = GlyphStyle(lit=theme.CYAN_BRIGHT, background=theme.BG_DEEP)
DIM_STYLE = GlyphStyle(lit=theme.BLUE_SOFT, background=theme.BG_DEEP)


def render_glyph(grid: Sequence[str], style: GlyphStyle = DEFAULT_MARK_STYLE) -> list[str]:
    """Render a grid to a list of Rich-markup terminal rows.

    Every half-block cell is emitted with its own ``[fg on bg]...[/]``
    wrapper. That's verbose but lets callers mix multiple glyphs on the
    same row without color bleed.
    """
    rows = _pad_to_even(grid)
    width = len(rows[0])
    out: list[str] = []
    for i in range(0, len(rows), 2):
        top = rows[i]
        bot = rows[i + 1] if i + 1 < len(rows) else " " * width
        cells: list[str] = []
        for c in range(width):
            top_on = _lit(top[c])
            bot_on = _lit(bot[c])
            ch = _half_char(top_on, bot_on)
            if ch == " ":
                cells.append(theme.fg_bg(style.background, style.background, " "))
            else:
                cells.append(theme.fg_bg(style.lit, style.background, ch))
        out.append("".join(cells))
    return out


def render_row_concat(glyph_rows: Iterable[list[str]], gap: int = 1,
                      gap_bg: str = theme.BG_DEEP) -> list[str]:
    """Concatenate multiple rendered glyphs side-by-side.

    ``gap`` is a cell count (cells = columns, one char each). The gap is
    filled with the given background so the logo reads as one continuous
    object instead of floating islands.
    """
    glyphs = [list(g) for g in glyph_rows]
    if not glyphs:
        return []
    height = max(len(g) for g in glyphs)
    # Pad every glyph to the max height with blank rows.
    blank_width_for = {id(g): _visual_width_blank(g) for g in glyphs}
    for g in glyphs:
        while len(g) < height:
            g.append(theme.fg_bg(gap_bg, gap_bg, " " * blank_width_for[id(g)]))
    gap_cell = theme.fg_bg(gap_bg, gap_bg, " " * gap) if gap > 0 else ""
    joined: list[str] = []
    for row_index in range(height):
        row_pieces = [g[row_index] for g in glyphs]
        joined.append(gap_cell.join(row_pieces))
    return joined


def _visual_width_blank(rows: list[str]) -> int:
    """Return the visual column width of a rendered glyph.

    Rich markup wraps each cell — we can't use ``len(row)``. Instead we
    recover the width by counting how many ``[fg on bg]X[/]`` groups the
    first row contains. The renderer always emits one group per cell, so
    group-count == column-count.
    """
    if not rows:
        return 0
    first = rows[0]
    return first.count("[/]")


def render_wordmark(word: str = "SEAM",
                    style: GlyphStyle = DEFAULT_WORDMARK_STYLE,
                    gap: int = 1) -> list[str]:
    """Render a string using ``WORDMARK_LETTERS``. Unknown chars = blank."""
    glyphs: list[list[str]] = []
    for ch in word.upper():
        if ch == " ":
            blank = tuple(" " * 3 for _ in range(7))
            glyphs.append(render_glyph(blank, style))
            continue
        grid = WORDMARK_LETTERS.get(ch)
        if grid is None:
            continue  # silently skip unknown letters for now
        glyphs.append(render_glyph(grid, style))
    return render_row_concat(glyphs, gap=gap, gap_bg=style.background)


def render_mark(style: GlyphStyle = DEFAULT_MARK_STYLE) -> list[str]:
    return render_glyph(PIXEL_S_MARK, style)


# ---- Box-drawing logo (matches reference design) ---------------------------
#
# The pixel-art half-block approach above is kept for compatibility, but
# ``render_header`` now uses box-drawing chars instead — they render
# crisply at any terminal width and match the branding reference image
# (seam_terminal_preview.py / branding/references/seam-dashboard-reference.png).

_BOX_LOGO: tuple[tuple[str, str], ...] = (
    ("   ╭──────╮  ", theme.CYAN),
    ("╭──╯ ╭──╮ ╰──╮", theme.VIOLET),
    ("╰──╮ ╰──╯ ╭──╯", theme.CYAN),
    ("   ╰──────╯  ", theme.VIOLET),
)

# Figlet block wordmark — 6 rows × 36 cols.
# ``render_header`` shows the first 4 rows (readable body);
# rows 4-5 (closing serifs) are shown in the extended preview only.
_BOX_SEAM: tuple[str, ...] = (
    "███████╗███████╗ █████╗ ███╗   ███╗",
    "██╔════╝██╔════╝██╔══██╗████╗ ████║",
    "███████╗█████╗  ███████║██╔████╔██║",
    "╚════██║██╔══╝  ██╔══██║██║╚██╔╝██║",
    "███████║███████╗██║  ██║██║ ╚═╝ ██║",
    "╚══════╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝",
)


# ---- Full header composition ----------------------------------------------

@dataclass
class HeaderFields:
    """Runtime fields shown beside the logo.

    Mirrors what ``dashboard._refresh_logo`` currently emits so the
    wiring pass can pass these values straight through.
    """

    version: str = "v0.1.0"
    tagline: str = "MIRL Interpreter & Persistence Engine"
    launch_dir: str = ""
    shell_cwd: str = ""
    model: str = ""
    chat_status: str = "offline"      # "configured" | "offline"
    mode: str = "hybrid"
    glow: bool = True


def render_header(fields: HeaderFields,
                  mark_style: GlyphStyle = DEFAULT_MARK_STYLE,
                  wordmark_style: GlyphStyle = DEFAULT_WORDMARK_STYLE) -> list[str]:
    """Compose the 4-row dashboard header using box-drawing art.

    Layout (left → right):
        [box-drawing S mark, 4 rows]  [figlet SEAM rows 0-3]  [info strip]

    mark_style / wordmark_style are accepted for API compatibility but
    ignored — colors come from ``_BOX_LOGO`` and ``theme.CYAN_BRIGHT``.
    """
    info_rows = _build_info_strip(fields)
    height = len(_BOX_LOGO)  # 4 rows

    composed: list[str] = []
    for i in range(height):
        mark_text, mark_color = _BOX_LOGO[i]
        mark_part = theme.fg(mark_color, mark_text)
        word_part = theme.fg(theme.CYAN_BRIGHT, _BOX_SEAM[i]) if i < len(_BOX_SEAM) else ""
        info_part = info_rows[i] if i < len(info_rows) else ""
        composed.append(f"{mark_part}  {word_part}   {info_part}")
    return composed


def _pad_rows(rows: list[str], target_height: int, bg: str | None) -> list[str]:
    if len(rows) >= target_height:
        return rows
    padded = list(rows)
    if bg is None:
        pad = ""
    else:
        pad = theme.fg_bg(bg, bg, " ")
    while len(padded) < target_height:
        padded.append(pad)
    return padded


def _build_info_strip(fields: HeaderFields) -> list[str]:
    """The four-row info block (version / paths / model / mode).

    Layout-wise: row 0 is the big tagline, rows 1–3 are label/value
    pairs. Values are escaped minimally — callers should not pass
    user-entered Rich markup here without pre-escaping.
    """
    version = theme.fg(theme.ACCENT, fields.version)
    tagline = theme.fg(theme.SIGNAL, fields.tagline)
    sep = theme.fg(theme.FRAME_DIM, "::")

    chat_color = theme.STATUS_OK if fields.chat_status == "configured" else theme.STATUS_WARN
    glow_text = theme.fg(theme.BLOOM if fields.glow else theme.GRID_MID,
                         "GLOW=ON" if fields.glow else "GLOW=OFF")

    seam_label = f"[bold {theme.SIGNAL}]SEAM[/]"
    line0 = f"{sep} {seam_label} {sep} {version} {sep} {tagline} {sep}"
    line1 = (
        f"{theme.fg(theme.LABEL, 'Launched from:')} {theme.fg(theme.VALUE, fields.launch_dir)}"
    )
    line2 = (
        f"{theme.fg(theme.LABEL, 'Shell cwd:')}     {theme.fg(theme.VALUE, fields.shell_cwd)}"
    )
    line3 = (
        f"{theme.fg(theme.LABEL, 'Model:')} {theme.fg(theme.VALUE, fields.model)} "
        f"{theme.fg(theme.FRAME_DIM, '(')}{theme.fg(chat_color, fields.chat_status)}"
        f"{theme.fg(theme.FRAME_DIM, ')')}   "
        f"{theme.fg(theme.LABEL, 'Mode:')} {theme.fg(theme.VALUE, fields.mode)}   "
        f"{glow_text}"
    )
    return [line0, line1, line2, line3]


def header_markup(fields: HeaderFields) -> str:
    """Convenience: return the header as one newline-joined markup string,
    the shape ``Static.update`` wants."""
    return "\n".join(render_header(fields))


# ---- Preview ---------------------------------------------------------------

def _preview(which: str = "header") -> None:  # pragma: no cover - visual
    from rich.console import Console

    console = Console()

    if which in ("mark", "all"):
        console.print("[bold]mark (pixel-S, 8×8)[/]")
        for row in render_mark():
            console.print(row)
        console.print()

    if which in ("wordmark", "all"):
        console.print("[bold]wordmark (SEAM, 7 rows)[/]")
        for row in render_wordmark("SEAM"):
            console.print(row)
        console.print()

    if which in ("header", "all"):
        console.print("[bold]full header[/]")
        fields = HeaderFields(
            version="v0.1.0",
            tagline="MIRL Interpreter & Persistence Engine",
            launch_dir=r"C:\Users\iwana\OneDrive\Documents\Codex",
            shell_cwd=r"C:\Users\iwana\OneDrive\Documents\Codex",
            model="gpt-4o-mini",
            chat_status="configured",
            mode="hybrid",
            glow=True,
        )
        for row in render_header(fields):
            console.print(row)


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="SEAM logo preview")
    parser.add_argument("--mark", action="store_true")
    parser.add_argument("--wordmark", action="store_true")
    parser.add_argument("--header", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.all or not any([args.mark, args.wordmark, args.header]):
        _preview("all")
    else:
        for flag in ("mark", "wordmark", "header"):
            if getattr(args, flag):
                _preview(flag)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
