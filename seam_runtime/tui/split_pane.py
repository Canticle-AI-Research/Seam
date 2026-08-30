"""Mouse- and keyboard-resizable dividers used by the designed TUI panes.

The operator-authored concept keeps the divider as a real control: dragging it
changes the primary pane width while the secondary pane consumes the remainder.
This module ports that contract to Textual cells.  It owns no page-specific
layout policy; callers provide the target id and bounds.
"""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

__all__ = ["PaneDivider"]


class PaneDivider(Static):
    """A one-cell split handle that emits bounded target widths."""

    can_focus = True
    BINDINGS = [
        Binding("left", "nudge(-2)", "Narrow pane", show=False),
        Binding("right", "nudge(2)", "Widen pane", show=False),
        Binding("shift+left", "nudge(-8)", "Narrow pane", show=False),
        Binding("shift+right", "nudge(8)", "Widen pane", show=False),
    ]

    class Resized(Message):
        """The target pane should adopt ``width`` terminal cells."""

        def __init__(self, width: int) -> None:
            super().__init__()
            self.width = width

    def __init__(
        self,
        *,
        target_id: str,
        minimum: int,
        maximum: int,
        other_minimum: int,
        **kwargs: object,
    ) -> None:
        super().__init__("│", **kwargs)  # type: ignore[arg-type]
        self.target_id = target_id
        self.minimum = minimum
        self.maximum = maximum
        self.other_minimum = other_minimum
        self._dragging = False
        self._start_screen_x = 0
        self._start_width = 0

    def _target_width(self) -> int:
        try:
            return self.screen.query_one(f"#{self.target_id}").region.width
        except Exception:
            return self.minimum

    def _bounded(self, width: int) -> int:
        parent_width = self.parent.content_size.width if self.parent is not None else 0
        available_maximum = max(self.minimum, parent_width - self.other_minimum - 1)
        return max(self.minimum, min(self.maximum, available_maximum, width))

    def _resize(self, width: int) -> None:
        self.post_message(self.Resized(self._bounded(width)))

    def action_nudge(self, amount: int) -> None:
        self._resize(self._target_width() + amount)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        event.stop()
        self.focus()
        self._dragging = True
        self._start_screen_x = event.screen_x
        self._start_width = self._target_width()
        self.add_class("-dragging")
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        event.stop()
        self._resize(self._start_width + event.screen_x - self._start_screen_x)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        event.stop()
        self._dragging = False
        self.remove_class("-dragging")
        self.release_mouse()
