"""Typed bar / meter library for the SEAM dashboard.

Replaces the single-purpose ``_bar`` helper in ``dashboard.py`` with a
small family of bar types, each with a clear semantic meaning:

    solid          – classic filled bar for a ratio in [0, 1]
    segmented      – discrete ticks, useful for step counts or stages
    indeterminate  – animated scan-wave for "running, no ETA" state
    stalled        – flat grey bar with a warning highlight
    error          – red filled bar — something actually failed

All bars return Rich-markup strings. The caller decides how to stack
them in a panel; this module only concerns itself with the shape and
color of one bar.

Width
-----
``width`` is the number of cells the bar occupies. A bar with
``width=24`` emits 24 glyph characters inside the bracket wrapper, so
total visual width is ``width + 2 + trailing_label_length``.

Glyphs
------
Uses ``█`` (U+2588) for fully-lit cells, ``▓`` (U+2593) for mid-intensity
(75% density), ``▒`` (U+2592) for low-intensity (50% density), ``░``
(U+2591) for track, and space for unlit cells inside indeterminate
windows. No Nerd Font dependency.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Literal

from . import theme

# ---- Types -----------------------------------------------------------------

BarKind = Literal["solid", "segmented", "indeterminate", "stalled", "error"]


@dataclass(frozen=True)
class BarStyle:
    fill: str = theme.BAR_FILL_RUN
    track: str = theme.BAR_TRACK
    bracket: str = theme.FRAME_DIM
    label: str = theme.LABEL


OK_STYLE = BarStyle(fill=theme.BAR_FILL_OK)
WARN_STYLE = BarStyle(fill=theme.BAR_FILL_WARN)
ERR_STYLE = BarStyle(fill=theme.BAR_FILL_ERR)
RUN_STYLE = BarStyle(fill=theme.BAR_FILL_RUN)


# ---- Helpers ---------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _wrap_brackets(body: str, style: BarStyle) -> str:
    return f"{theme.fg(style.bracket, '[')}{body}{theme.fg(style.bracket, ']')}"


def _label(text: str, style: BarStyle) -> str:
    return theme.fg(style.label, text)


# ---- Bar implementations ---------------------------------------------------

def solid(ratio: float, width: int = 24,
          style: BarStyle = RUN_STYLE,
          show_pct: bool = True) -> str:
    """Classic filled bar. ``ratio`` is clamped to [0, 1]."""
    r = _clamp(ratio)
    filled = int(round(r * width))
    empty = width - filled

    body = (
        theme.fg(style.fill, "█" * filled)
        + theme.fg(style.track, "░" * empty)
    )
    bar = _wrap_brackets(body, style)
    if show_pct:
        return f"{bar} {_label(f'{r * 100:5.1f}%', style)}"
    return bar


def segmented(steps_done: int, steps_total: int,
              style: BarStyle = RUN_STYLE,
              cell_width: int = 3,
              separator: str = "│") -> str:
    """Discrete-step bar.

    Renders one cell per step with a vertical separator between cells.
    Useful for pipelines like RAW → IR → PACK → LENS where the four
    segments are semantically distinct.
    """
    steps_total = max(1, steps_total)
    steps_done = max(0, min(steps_total, steps_done))
    sep = theme.fg(style.bracket, separator)
    cells: list[str] = []
    for i in range(steps_total):
        if i < steps_done:
            cells.append(theme.fg(style.fill, "█" * cell_width))
        else:
            cells.append(theme.fg(style.track, "░" * cell_width))
    body = sep.join(cells)
    bar = _wrap_brackets(body, style)
    return f"{bar} {_label(f'{steps_done}/{steps_total}', style)}"


def indeterminate(phase: int, width: int = 24,
                  window: int = 5,
                  style: BarStyle = RUN_STYLE) -> str:
    """Scan-wave bar for running-with-no-ETA state.

    ``phase`` is an integer frame counter — caller advances it each tick.
    A lit window of ``window`` cells sweeps across the track, bouncing
    off both ends so the motion has a clear rhythm. At the center of the
    window we emit a full block; fading outward we use ``▓ ▒``.
    """
    if width <= 0:
        return ""
    # Ping-pong the leading edge across [0, width-1].
    period = 2 * max(1, (width - 1))
    pos = phase % period
    head = pos if pos < width else period - pos

    glyphs: list[str] = []
    for c in range(width):
        dist = abs(c - head)
        if dist == 0:
            glyphs.append(theme.fg(style.fill, "█"))
        elif dist == 1:
            glyphs.append(theme.fg(style.fill, "▓"))
        elif dist == 2 and window >= 3:
            glyphs.append(theme.fg(style.fill, "▒"))
        else:
            glyphs.append(theme.fg(style.track, "░"))
    body = "".join(glyphs)
    bar = _wrap_brackets(body, style)
    return f"{bar} {_label('…running', style)}"


def stalled(width: int = 24,
            style: BarStyle = WARN_STYLE,
            note: str = "stalled") -> str:
    """Flat warning bar. No fill, amber warning stripe at the head."""
    track = theme.fg(theme.GRID_DIM, "░" * max(0, width - 1))
    warn = theme.fg(style.fill, "▓")
    body = track + warn
    bar = _wrap_brackets(body, style)
    return f"{bar} {_label(note, style)}"


def error(ratio: float = 1.0, width: int = 24,
          style: BarStyle = ERR_STYLE,
          note: str = "failed") -> str:
    """Error bar. Fill is red, shown up to ``ratio``. Remainder uses a
    dimmer red so the failure extent is visible rather than hidden."""
    r = _clamp(ratio)
    filled = int(round(r * width))
    empty = width - filled
    body = (
        theme.fg(style.fill, "█" * filled)
        + theme.fg(theme.RED_DIM, "▒" * empty)
    )
    bar = _wrap_brackets(body, style)
    return f"{bar} {_label(note, style)}"


# ---- Unified entry point ---------------------------------------------------

def render(kind: BarKind, *,
           ratio: float = 0.0,
           steps_done: int = 0,
           steps_total: int = 4,
           phase: int = 0,
           width: int = 24,
           note: str | None = None,
           style: BarStyle | None = None) -> str:
    """Dispatch on ``kind``. Unused kwargs are silently ignored."""
    if kind == "solid":
        return solid(ratio, width, style or RUN_STYLE)
    if kind == "segmented":
        return segmented(steps_done, steps_total, style or RUN_STYLE)
    if kind == "indeterminate":
        return indeterminate(phase, width, style=style or RUN_STYLE)
    if kind == "stalled":
        return stalled(width, style or WARN_STYLE, note or "stalled")
    if kind == "error":
        return error(ratio, width, style or ERR_STYLE, note or "failed")
    raise ValueError(f"unknown bar kind: {kind!r}")


# ---- Preview ---------------------------------------------------------------

def _preview() -> None:  # pragma: no cover - visual
    from rich.console import Console

    console = Console()
    console.print("[bold]solid — cycle through fill ratios[/]")
    for r in (0.0, 0.15, 0.5, 0.82, 1.0):
        console.print(f"  r={r:.2f}  {solid(r)}")
    console.print()

    console.print("[bold]solid — OK / WARN / ERR styles[/]")
    console.print(f"  ok   {solid(0.72, style=OK_STYLE)}")
    console.print(f"  warn {solid(0.72, style=WARN_STYLE)}")
    console.print(f"  err  {solid(0.72, style=ERR_STYLE)}")
    console.print()

    console.print("[bold]segmented — RAW → IR → PACK → LENS[/]")
    for done in range(5):
        console.print(f"  step {done}/4  {segmented(done, 4)}")
    console.print()

    console.print("[bold]indeterminate — 10 frames[/]")
    for f in range(10):
        console.print(f"  f={f:02d}  {indeterminate(f)}")
    console.print()

    console.print("[bold]stalled[/]")
    console.print(f"  {stalled(note='awaiting model')}")
    console.print()

    console.print("[bold]error[/]")
    console.print(f"  {error(0.4, note='compile failed at row 12')}")


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="SEAM bars preview")
    parser.parse_args(argv)
    _preview()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
