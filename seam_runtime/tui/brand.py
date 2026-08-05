"""Canticle-styled branding for the TUI.

The glyph engine already exists in `seam_runtime.ui.logo` (half-block wordmark
and mark rendering); this module supplies Canticle's palette to it rather than
introducing a second renderer. Colours are the literal tokens from
Canticle.cc `styles.css`, so the terminal banner and the website read as one
system.

The pastel ladder pink -> magenta -> lavender -> cyan -> mint mirrors the
gradient rule that sits on top of every `.tui-box` panel on the site.
"""

from __future__ import annotations

import re

from ..ui.logo import GlyphStyle, render_wordmark

__all__ = [
    "BG_DEEP",
    "LADDER",
    "PROMPT",
    "WORDMARK_STYLE",
    "MARK_STYLE",
    "splash",
    "brand_mark",
    "rule",
]

# ── Canticle tokens ────────────────────────────────────────────────────────
BG_DEEP = "#16161e"
BG_PANEL = "#1f2028"
PINK = "#ff6090"
MAGENTA = "#e478d0"
LAVENDER = "#c4a7e7"
CYAN = "#7dcfff"
MINT = "#9ece6a"
YELLOW = "#e0af68"
ORANGE = "#ff9e64"
RED = "#f7768e"
BLUE = "#7aa2f7"
ICE = "#b4f9f8"
TEXT_MAIN = "#c0caf5"
TEXT_DIM = "#565f89"
TEXT_MUTED = "#a9b1d6"

#: The `.tui-box` top-rule gradient, in order.
LADDER: tuple[str, ...] = (PINK, MAGENTA, LAVENDER, CYAN, MINT)

#: Canticle's prompt glyph.
PROMPT = "❯"

WORDMARK_STYLE = GlyphStyle(lit=PINK, background=BG_DEEP, shadow=MAGENTA)
MARK_STYLE = GlyphStyle(lit=CYAN, background=BG_DEEP, shadow=LAVENDER)


def rule(width: int = 60) -> str:
    """Render the Canticle gradient rule as a run of pastel block characters.

    Approximates the site's `linear-gradient(90deg, …)` top border by dividing
    the width across the pastel ladder, which is the closest a cell grid gets
    to a continuous gradient.
    """
    width = max(len(LADDER), width)
    span = width // len(LADDER)
    remainder = width - span * len(LADDER)
    parts = []
    for index, colour in enumerate(LADDER):
        cells = span + (1 if index < remainder else 0)
        parts.append(f"[{colour}]{'━' * cells}[/]")
    return "".join(parts)


#: The block used for the blinking terminal cursor, matching Canticle's caret.
CURSOR = "█"


def brand_mark(cursor_on: bool = True) -> str:
    """Return the compact brand mark, with Canticle's blinking caret.

    The caret is redrawn on a timer rather than styled with `blink`, because
    terminal blink support is inconsistent and frequently disabled outright.
    """
    caret = f"[{PINK}]{CURSOR}[/]" if cursor_on else " "
    return f"[{PINK}]{PROMPT}[/] [b {MAGENTA}]SEAM[/] {caret}"


#: `label:` at the start of a line — the shape most backend output uses.
_LABEL_RE = re.compile(r"^(\s*)([A-Za-z][\w .\-/]{0,38}):(?=\s)", re.MULTILINE)
#: Bare numbers, including decimals and thousands separators.
_NUMBER_RE = re.compile(r"(?<![\w.#\[])(\d[\d,]*\.?\d*)(?![\w.\]])")
#: SEAM reference ids such as `hs:abc123` or `mir:...`.
_REF_RE = re.compile(r"\b((?:hs|mir|ir|obj|run|ep|ent):[A-Za-z0-9_\-]+)\b")


def colorize(text: str) -> str:
    """Tint plain backend output so results are scannable, not a wall of grey.

    Only applied to text that carries no Rich markup of its own. The backend
    already emits styled output in places, and layering a second pass over it
    produces mismatched tags rather than better colour.
    """
    if not text or "[/" in text or "[/]" in text:
        return text
    text = _REF_RE.sub(rf"[{MINT}]\1[/]", text)
    text = _LABEL_RE.sub(rf"\1[{LAVENDER}]\2[/]:", text)
    text = _NUMBER_RE.sub(rf"[{CYAN}]\1[/]", text)
    return text


def splash(subtitle: str = "", width: int = 60) -> str:
    """Return the full welcome banner: gradient rule, wordmark, footer tag.

    The footer tag follows the Canticle cover brief's `[ NAME // SEAM ]` form.
    """
    lines: list[str] = ["", rule(width)]
    lines.extend(render_wordmark("SEAM", style=WORDMARK_STYLE))
    lines.append("")
    if subtitle:
        lines.append(f"[{TEXT_MUTED}]{subtitle}[/]")
    lines.append(f"[{TEXT_DIM}][ MEMORY // SEAM ][/]")
    lines.append(rule(width))
    return "\n".join(lines)
