"""Animations for the MIRL panel.

Two pieces, both driven from one ``AnimationEngine`` so the dashboard's
existing 0.25s tick can stay one-callback simple:

1. ``MachineStream``  – emits MIRL/IR records one token at a time, fades
   older records with age. Always running, even when idle, so the panel
   is never a dead rectangle.

2. ``CompressionPipeline`` – RAW → IR → PACK stages with per-stage bars,
   activated when the user runs compile / compress / benchmark. Returns
   to the stream view ~4s after the last activation.

The shape of the output is a list of Rich-markup strings that
``Static.update`` (or our ``_TextualPanel.set_lines``) can drop straight
into a panel. No Textual / Rich classes are imported here — the engine
is pure Python so it can be unit-tested without a render surface.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from . import bars, theme

# ---- IR sample emission ---------------------------------------------------
#
# We pull from a small pool of canonical MIRL record templates. Each
# template is a list of (color_alias, text) fragments. The stream emits
# them char-by-char (or group-by-group) so the user sees the record
# build up rather than appearing whole.

@dataclass(frozen=True)
class _Fragment:
    color: str
    text: str


def _frag(color: str, text: str) -> _Fragment:
    return _Fragment(color=color, text=text)


# Ten templates covering the SEAM v0.1 IR tag set. Each tuple is one
# complete IR record split into colorable spans.
_TEMPLATES: tuple[tuple[_Fragment, ...], ...] = (
    (
        _frag(theme.TAG_ENTITY, "@"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "u:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "t="), _frag(theme.VALUE, "user"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "name="), _frag(theme.VALUE, '"terra"'),
    ),
    (
        _frag(theme.TAG_CLAIM, "#"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "c:42"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "s="), _frag(theme.VALUE, "p:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "p="), _frag(theme.VALUE, "goal"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "o="), _frag(theme.VALUE, '"compress wins"'),
    ),
    (
        _frag(theme.TAG_EVENT, "!"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "e:9"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "k="), _frag(theme.VALUE, "compile"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "t="), _frag(theme.VALUE, "12.4ms"),
    ),
    (
        _frag(theme.TAG_RELATION, ">"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "r:7"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "from="), _frag(theme.VALUE, "u:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "to="), _frag(theme.VALUE, "p:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "k="), _frag(theme.VALUE, "owns"),
    ),
    (
        _frag(theme.TAG_STATE, "~"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "s:3"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "of="), _frag(theme.VALUE, "p:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "v="), _frag(theme.VALUE, "active"),
    ),
    (
        _frag(theme.TAG_EVIDENCE, "^"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "ev:5"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "for="), _frag(theme.VALUE, "c:42"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "src="), _frag(theme.VALUE, "src:9"),
    ),
    (
        _frag(theme.TAG_SOURCE, "%"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "src:9"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "uri="), _frag(theme.VALUE, '"file://wins.md"'),
    ),
    (
        _frag(theme.TAG_DELTA, "+"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "d:11"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "to="), _frag(theme.VALUE, "c:42"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "op="), _frag(theme.VALUE, "amend"),
    ),
    (
        _frag(theme.TAG_ALIAS, "="), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "a:2"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "of="), _frag(theme.VALUE, "u:1"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "as="), _frag(theme.VALUE, '"the operator"'),
    ),
    (
        _frag(theme.TAG_CLAIM, "#"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.SIGNAL, "c:43"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "p="), _frag(theme.VALUE, "tooling"), _frag(theme.FRAME_DIM, "|"),
        _frag(theme.LABEL, "o="), _frag(theme.VALUE, '"seam runtime"'),
    ),
)


def _fragments_to_markup(frags: Iterable[_Fragment]) -> str:
    return "".join(theme.fg(f.color, f.text) for f in frags)


def _fragments_visible_text(frags: Iterable[_Fragment]) -> str:
    return "".join(f.text for f in frags)


# ---- MachineStream ---------------------------------------------------------

@dataclass
class _StreamLine:
    """One line in the rolling stream.

    ``frags`` is the full record. ``revealed`` is how many CHARACTERS of
    that record have been emitted so far; the line is "complete" when
    ``revealed >= len(visible_text)``. Once complete, ``born_at`` is set
    so we can fade it on age.
    """
    frags: tuple[_Fragment, ...]
    revealed: int = 0
    born_at: float | None = None


class MachineStream:
    """Streaming MIRL emitter.

    Holds up to ``height`` lines. On each tick:
      * advance the in-progress line by ``chars_per_tick`` characters
      * if the line just completed, mark its ``born_at`` and start a new line
      * recolor older completed lines dimmer (age-fade)
    """

    def __init__(self, height: int = 6, chars_per_tick: int = 6,
                 rng: random.Random | None = None) -> None:
        self.height = height
        self.chars_per_tick = chars_per_tick
        self.rng = rng or random.Random()
        self.lines: deque[_StreamLine] = deque(maxlen=height)
        self._start_new_line(now=time.monotonic())

    # -- driver -------------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        if not self.lines:
            self._start_new_line(now)
            return
        head = self.lines[-1]
        head_text = _fragments_visible_text(head.frags)
        if head.revealed < len(head_text):
            head.revealed = min(len(head_text), head.revealed + self.chars_per_tick)
            if head.revealed >= len(head_text):
                head.born_at = now
        else:
            self._start_new_line(now)

    def _start_new_line(self, now: float) -> None:
        template = self.rng.choice(_TEMPLATES)
        # Drop a head if we're full so the new line has room.
        if len(self.lines) == self.height:
            self.lines.popleft()
        self.lines.append(_StreamLine(frags=template, revealed=0, born_at=None))

    # -- render -------------------------------------------------------------

    def render(self, now: float | None = None) -> list[str]:
        if now is None:
            now = time.monotonic()
        out: list[str] = []
        n = len(self.lines)
        for i, line in enumerate(self.lines):
            visible = _fragments_visible_text(line.frags)
            if line.revealed < len(visible):
                # In-progress line — reveal first ``revealed`` chars colored
                # by their fragments, then a blinking cursor.
                cursor = theme.fg(theme.STATUS_OK, "▌")
                out.append(self._render_partial(line) + cursor)
            else:
                # Completed line — apply age fade based on position from
                # the head. Newer lines (closer to the bottom) are bright.
                from_head = (n - 1) - i
                out.append(self._render_completed(line, from_head))
        return out

    def _render_partial(self, line: _StreamLine) -> str:
        budget = line.revealed
        chunks: list[str] = []
        for frag in line.frags:
            if budget <= 0:
                break
            if budget >= len(frag.text):
                chunks.append(theme.fg(frag.color, frag.text))
                budget -= len(frag.text)
            else:
                chunks.append(theme.fg(frag.color, frag.text[:budget]))
                budget = 0
        return "".join(chunks)

    def _render_completed(self, line: _StreamLine, from_head: int) -> str:
        # 0 = bottom (newest, full color)
        # 1 = one above (slight fade)
        # 2+ = aged (dim)
        if from_head == 0:
            return _fragments_to_markup(line.frags)
        if from_head == 1:
            return _dim_markup(line.frags, theme.SIGNAL_DIM)
        return _dim_markup(line.frags, theme.GRID_MID)


def _dim_markup(frags: Iterable[_Fragment], dim_color: str) -> str:
    """Recolor every fragment to ``dim_color`` — keeps the structure
    visible but signals age."""
    return "".join(theme.fg(dim_color, f.text) for f in frags)


# ---- CompressionPipeline ---------------------------------------------------

@dataclass
class _StageState:
    name: str
    progress: float = 0.0           # 0 .. 1
    rate: float = 0.18              # progress per tick
    label: str = ""

    def step(self) -> None:
        self.progress = min(1.0, self.progress + self.rate)

    @property
    def done(self) -> bool:
        return self.progress >= 1.0


class CompressionPipeline:
    """Three-stage RAW → IR → PACK visualization.

    Activated by ``trigger`` with the source label and (optional) target
    token counts. While active, ``render`` returns a multi-line view:
    one bar per stage plus a header summarizing source vs machine
    tokens. When all stages complete + a small dwell time, ``active``
    flips to False and the dashboard can fall back to the stream.
    """

    DWELL_AFTER_DONE = 1.5  # seconds to keep the completed view visible

    def __init__(self) -> None:
        self.active: bool = False
        self.label: str = ""
        self.source_tokens: int = 0
        self.machine_tokens: int = 0
        self.stages: list[_StageState] = []
        self._completed_at: float | None = None

    # -- driver -------------------------------------------------------------

    def trigger(self, label: str,
                source_tokens: int = 0,
                machine_tokens: int = 0,
                kind: str = "compile") -> None:
        self.active = True
        self.label = label
        self.source_tokens = source_tokens
        self.machine_tokens = machine_tokens
        # Different kinds use different stage names — the pipeline is
        # the same shape but the labels read more naturally.
        if kind == "compile":
            stage_names = ("PARSE", "MIRL", "EMIT")
        elif kind == "compress":
            stage_names = ("RAW", "IR", "PACK")
        else:
            stage_names = ("LOAD", "RUN", "REPORT")
        # Slightly different rates per stage — feels less mechanical.
        self.stages = [
            _StageState(name=stage_names[0], rate=0.22),
            _StageState(name=stage_names[1], rate=0.16),
            _StageState(name=stage_names[2], rate=0.20),
        ]
        self._completed_at = None

    def tick(self, now: float | None = None) -> None:
        if not self.active:
            return
        if now is None:
            now = time.monotonic()
        # Advance the first not-yet-done stage.
        for stage in self.stages:
            if not stage.done:
                stage.step()
                break
        else:
            # All stages done.
            if self._completed_at is None:
                self._completed_at = now
            elif now - self._completed_at >= self.DWELL_AFTER_DONE:
                self.active = False

    # -- render -------------------------------------------------------------

    def render(self) -> list[str]:
        if not self.active and not self.has_completed_frame:
            return []
        header = self._header()
        bar_rows = [self._stage_row(s, i) for i, s in enumerate(self.stages)]
        return [header, ""] + bar_rows + [self._summary_row()]

    @property
    def has_completed_frame(self) -> bool:
        return bool(self.stages) and all(stage.done for stage in self.stages)

    def _header(self) -> str:
        title = theme.fg(theme.ACCENT, f"⟶ COMPRESS  {self.label}")
        kind = theme.fg(theme.LABEL, "stages:") + " " + theme.fg(
            theme.SIGNAL, " → ".join(s.name for s in self.stages)
        )
        return f"{title}   {kind}"

    def _stage_row(self, stage: _StageState, idx: int) -> str:
        # Determine which bar style to use:
        #   not started  → solid track only
        #   running      → indeterminate when progress > 0 and < 1
        #   done         → solid filled with OK style
        name = theme.fg(theme.SIGNAL, f"{idx + 1}. {stage.name:<6}")
        if stage.done:
            bar = bars.solid(1.0, width=28, style=bars.OK_STYLE)
        elif stage.progress > 0:
            bar = bars.solid(stage.progress, width=28, style=bars.RUN_STYLE)
        else:
            bar = bars.solid(0.0, width=28, style=bars.RUN_STYLE)
        return f"{name} {bar}"

    def _summary_row(self) -> str:
        if self.source_tokens <= 0:
            return ""
        ratio = (self.machine_tokens / self.source_tokens) if self.source_tokens else 0
        savings = max(0.0, 1.0 - ratio)
        line = (
            f"{theme.fg(theme.LABEL, 'source')} "
            f"{theme.fg(theme.COMPRESSION_SOURCE, str(self.source_tokens) + ' tok')}   "
            f"{theme.fg(theme.LABEL, 'machine')} "
            f"{theme.fg(theme.COMPRESSION_MACHINE, str(self.machine_tokens) + ' tok')}   "
            f"{theme.fg(theme.LABEL, 'savings')} "
            f"{theme.fg(theme.STATUS_OK, f'{savings * 100:5.1f}%')}"
        )
        return line


# ---- AnimationEngine -------------------------------------------------------

class AnimationEngine:
    """Single-callback driver the dashboard ticks.

    Usage:
        engine = AnimationEngine()
        # on user trigger:
        engine.trigger_compress("user-doc.txt", 1024, 380)
        # every tick:
        lines = engine.tick_and_render()
        panel.set_lines(lines)
    """

    def __init__(self, height: int = 6) -> None:
        self.stream = MachineStream(height=height)
        self.pipeline = CompressionPipeline()
        self._idle_lines = ["Idle. Run compile/compress/benchmark for live machine animation."]

    def trigger_compress(self, label: str,
                         source_tokens: int = 0,
                         machine_tokens: int = 0,
                         kind: str = "compress") -> None:
        self.pipeline.trigger(label, source_tokens, machine_tokens, kind)

    @property
    def active(self) -> bool:
        return self.pipeline.active

    @property
    def has_completed_frame(self) -> bool:
        return self.pipeline.has_completed_frame

    def tick_and_render(self, now: float | None = None) -> list[str]:
        if now is None:
            now = time.monotonic()
        if not self.pipeline.active:
            if self.pipeline.has_completed_frame:
                return self.pipeline.render() + ["", theme.fg(theme.STATUS_OK, "complete")]
            return list(self._idle_lines)
        self.stream.tick(now)
        was_active = self.pipeline.active
        self.pipeline.tick(now)
        if self.pipeline.active:
            # Show the pipeline on top, fade-out stream below.
            pipe = self.pipeline.render()
            stream_tail = self.stream.render(now)[-2:]
            return pipe + ["", theme.fg(theme.FRAME_DIM, "── live IR stream ──")] + stream_tail
        if was_active and self.pipeline.has_completed_frame:
            return self.pipeline.render() + ["", theme.fg(theme.STATUS_OK, "complete")]
        return list(self._idle_lines)


# ---- Preview ---------------------------------------------------------------

def _preview_stream() -> None:  # pragma: no cover - visual
    from rich.console import Console
    console = Console()
    console.print("[bold]MachineStream — 12 ticks[/]")
    rng = random.Random(7)
    stream = MachineStream(height=5, chars_per_tick=8, rng=rng)
    for tick in range(12):
        stream.tick(now=tick * 0.25)
        console.rule(f"tick {tick}", style="dim")
        for row in stream.render(now=tick * 0.25):
            console.print(row)


def _preview_pipeline() -> None:  # pragma: no cover - visual
    from rich.console import Console
    console = Console()
    console.print("[bold]CompressionPipeline — full run[/]")
    pipe = CompressionPipeline()
    pipe.trigger("user-doc.md", source_tokens=1024, machine_tokens=384, kind="compress")
    for tick in range(20):
        pipe.tick(now=tick * 0.25)
        if not pipe.active:
            console.print(f"[dim]tick {tick}: pipeline inactive[/]")
            break
        console.rule(f"tick {tick}", style="dim")
        for row in pipe.render():
            console.print(row)


def _preview_engine() -> None:  # pragma: no cover - visual
    from rich.console import Console
    console = Console()
    console.print("[bold]AnimationEngine — interleaved[/]")
    engine = AnimationEngine(height=5)
    for tick in range(8):
        engine.tick_and_render(now=tick * 0.25)
    engine.trigger_compress("hello.md", source_tokens=512, machine_tokens=180)
    for tick in range(8, 22):
        rows = engine.tick_and_render(now=tick * 0.25)
        console.rule(f"tick {tick}", style="dim")
        for row in rows:
            console.print(row)


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="SEAM animations preview")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--pipeline", action="store_true")
    parser.add_argument("--engine", action="store_true")
    args = parser.parse_args(argv)
    if args.stream:
        _preview_stream()
    elif args.pipeline:
        _preview_pipeline()
    elif args.engine:
        _preview_engine()
    else:
        _preview_stream()
        print()
        _preview_pipeline()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
