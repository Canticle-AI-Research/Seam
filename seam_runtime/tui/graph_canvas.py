"""Interactive terminal rendering of SEAM's real knowledge graph.

The operator-designed TUI defines three graph layouts plus zoom, reset,
orbit, pan, labelled edges, and clickable nodes.  A browser can paint that
model with positioned DOM nodes; Textual needs a cell renderer.  This widget
keeps the same state machine and projects the runtime's ``knowledge_graph``
payload into a dense terminal canvas instead of replacing it with a table.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from . import brand

__all__ = ["ConstellationGraph"]


_KIND_COLORS = {
    "ent": brand.MINT,
    "clm": brand.CYAN,
    "rel": brand.LAVENDER,
    "raw": brand.ORANGE,
    "episode": brand.YELLOW,
    "sym": brand.MAGENTA,
    "span": brand.BLUE,
    "pack": brand.MINT,
}

_KIND_GLYPHS = {
    "ent": "●",
    "clm": "◆",
    "rel": "◇",
    "raw": "■",
    "episode": "✦",
    "sym": "✶",
    "span": "○",
    "pack": "⬢",
}


@dataclass(frozen=True)
class _Node:
    id: str
    label: str
    kind: str
    degree: int


@dataclass(frozen=True)
class _Edge:
    source: str
    target: str
    predicate: str


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


class ConstellationGraph(Static):
    """A focusable, interactive rendering of the knowledge constellation."""

    can_focus = True
    BINDINGS = [
        Binding("+", "zoom(0.1)", "Zoom in", show=False),
        Binding("=", "zoom(0.1)", "Zoom in", show=False),
        Binding("-", "zoom(-0.1)", "Zoom out", show=False),
        Binding("0", "reset_view", "Reset", show=False),
        Binding("f", "layout('force')", "Force", show=False),
        Binding("t", "layout('tree')", "Tree", show=False),
        Binding("c", "layout('constellation')", "Constellation", show=False),
    ]

    class NodeSelected(Message):
        def __init__(self, node_id: str) -> None:
            super().__init__()
            self.node_id = node_id

    class ViewChanged(Message):
        """Controls should refresh their active state and zoom label."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("", *args, **kwargs)  # type: ignore[arg-type]
        self.graph_layout = "force"
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.tilt_x = -12.0
        self.tilt_y = 18.0
        self.selected_id: str | None = None
        self._graph_nodes: tuple[_Node, ...] = ()
        self._graph_edges: tuple[_Edge, ...] = ()
        self._positions: dict[str, tuple[float, float, float]] = {}
        self._screen_positions: dict[str, tuple[int, int]] = {}
        self._dragging = False
        self._drag_as_pan = False
        self._start_screen = (0, 0)
        self._start_pan = (0.0, 0.0)
        self._start_tilt = (0.0, 0.0)
        self.rendered_plain_text = ""

    @property
    def node_count(self) -> int:
        return len(self._graph_nodes)

    @property
    def edge_count(self) -> int:
        return len(self._graph_edges)

    def set_graph(self, payload: dict[str, object]) -> None:
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        nodes: list[_Node] = []
        for raw in raw_nodes if isinstance(raw_nodes, list) else []:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            nodes.append(
                _Node(
                    id=str(raw["id"]),
                    label=str(raw.get("label") or raw["id"]),
                    kind=str(raw.get("kind") or "").lower(),
                    degree=int(raw.get("degree") or 0),
                )
            )
        node_ids = {node.id for node in nodes}
        edges: list[_Edge] = []
        for raw in raw_edges if isinstance(raw_edges, list) else []:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source") or raw.get("src") or "")
            target = str(raw.get("target") or raw.get("dst") or "")
            if source not in node_ids or target not in node_ids:
                continue
            edges.append(
                _Edge(
                    source=source,
                    target=target,
                    predicate=str(raw.get("predicate") or raw.get("type") or "linked"),
                )
            )
        self._graph_nodes = tuple(nodes)
        self._graph_edges = tuple(edges)
        self._rebuild_layout()

    def set_selected(self, node_id: str | None) -> None:
        self.selected_id = node_id
        self.refresh()

    def set_layout(self, layout: str) -> None:
        if layout not in {"force", "tree", "constellation"}:
            return
        self.graph_layout = layout
        self._rebuild_layout()
        self.post_message(self.ViewChanged())

    def zoom_by(self, delta: float) -> None:
        self.zoom = max(0.4, min(3.0, round(self.zoom + delta, 2)))
        self.refresh()
        self.post_message(self.ViewChanged())

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.tilt_x = -12.0
        self.tilt_y = 18.0
        self.graph_layout = "force"
        self._rebuild_layout()
        self.post_message(self.ViewChanged())

    def action_zoom(self, delta: float) -> None:
        self.zoom_by(delta)

    def action_reset_view(self) -> None:
        self.reset_view()

    def action_layout(self, layout: str) -> None:
        self.set_layout(layout)

    def _rebuild_layout(self) -> None:
        if self.graph_layout == "tree":
            self._positions = self._tree_positions()
        elif self.graph_layout == "constellation":
            self._positions = self._constellation_positions()
        else:
            self._positions = self._force_positions()
        self.refresh()

    def _constellation_positions(self) -> dict[str, tuple[float, float, float]]:
        ordered = sorted(self._graph_nodes, key=lambda node: (-node.degree, node.id))
        total = max(1, len(ordered))
        golden_angle = math.radians(137.508)
        positions: dict[str, tuple[float, float, float]] = {}
        for index, node in enumerate(ordered):
            if index == 0:
                radius = 0.0
            else:
                radius = 0.18 + 0.76 * math.sqrt(index / max(1, total - 1))
            jitter = (_stable_fraction(node.id) - 0.5) * 0.14
            angle = index * golden_angle + jitter
            depth = (_stable_fraction(f"z:{node.id}") - 0.5) * 1.4
            positions[node.id] = (radius * math.cos(angle), radius * math.sin(angle), depth)
        return positions

    def _tree_positions(self) -> dict[str, tuple[float, float, float]]:
        if not self._graph_nodes:
            return {}
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self._graph_edges:
            adjacency[edge.source].append(edge.target)
            adjacency[edge.target].append(edge.source)
        root = self.selected_id if self.selected_id in adjacency else max(
            self._graph_nodes, key=lambda node: (node.degree, node.id)
        ).id
        layers: dict[int, list[str]] = defaultdict(list)
        seen = {root}
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        while queue:
            node_id, depth = queue.popleft()
            layers[depth].append(node_id)
            for neighbor in sorted(adjacency[node_id]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, depth + 1))
        leftovers = sorted(node.id for node in self._graph_nodes if node.id not in seen)
        if leftovers:
            layers[max(layers, default=0) + 1].extend(leftovers)
        max_depth = max(layers, default=0)
        positions: dict[str, tuple[float, float, float]] = {}
        for depth, ids in layers.items():
            for index, node_id in enumerate(ids):
                x = 0.0 if len(ids) == 1 else -0.9 + 1.8 * index / (len(ids) - 1)
                y = -0.82 + 1.64 * depth / max(1, max_depth)
                positions[node_id] = (x, y, depth * 0.08)
        return positions

    def _force_positions(self) -> dict[str, tuple[float, float, float]]:
        """Small deterministic force layout; cached until graph/layout changes."""
        nodes = list(self._graph_nodes)
        if not nodes:
            return {}
        seed = self._constellation_positions()
        positions = {node.id: [seed[node.id][0], seed[node.id][1]] for node in nodes}
        if len(nodes) > 180:
            return {node.id: (*positions[node.id], seed[node.id][2] * 0.35) for node in nodes}
        edges = [(edge.source, edge.target) for edge in self._graph_edges]
        ideal = max(0.12, 1.4 / math.sqrt(len(nodes)))
        for iteration in range(32):
            force = {node.id: [0.0, 0.0] for node in nodes}
            for index, left in enumerate(nodes):
                lx, ly = positions[left.id]
                for right in nodes[index + 1 :]:
                    rx, ry = positions[right.id]
                    dx, dy = lx - rx, ly - ry
                    dist2 = max(0.0025, dx * dx + dy * dy)
                    strength = 0.0028 / dist2
                    force[left.id][0] += dx * strength
                    force[left.id][1] += dy * strength
                    force[right.id][0] -= dx * strength
                    force[right.id][1] -= dy * strength
            for source, target in edges:
                sx, sy = positions[source]
                tx, ty = positions[target]
                dx, dy = tx - sx, ty - sy
                distance = max(0.01, math.hypot(dx, dy))
                strength = (distance - ideal) * 0.045
                fx, fy = dx / distance * strength, dy / distance * strength
                force[source][0] += fx
                force[source][1] += fy
                force[target][0] -= fx
                force[target][1] -= fy
            cooling = 1.0 - iteration / 40.0
            for node in nodes:
                x, y = positions[node.id]
                fx, fy = force[node.id]
                positions[node.id] = [
                    max(-0.94, min(0.94, x + max(-0.08, min(0.08, fx)) * cooling)),
                    max(-0.90, min(0.90, y + max(-0.08, min(0.08, fy)) * cooling)),
                ]
        return {
            node.id: (positions[node.id][0], positions[node.id][1], seed[node.id][2] * 0.5)
            for node in nodes
        }

    def _project(self, point: tuple[float, float, float], width: int, height: int) -> tuple[int, int]:
        x, y, z = point
        yaw = math.radians(self.tilt_y)
        pitch = math.radians(self.tilt_x)
        rotated_x = x * math.cos(yaw) + z * math.sin(yaw) * 0.28
        rotated_z = -x * math.sin(yaw) + z * math.cos(yaw)
        rotated_y = y * math.cos(pitch) - rotated_z * math.sin(pitch) * 0.35
        usable_w = max(4, width - 4)
        usable_h = max(3, height - 2)
        px = round(width / 2 + rotated_x * usable_w * 0.46 * self.zoom + self.pan_x)
        py = round(height / 2 + rotated_y * usable_h * 0.46 * self.zoom + self.pan_y)
        return px, py

    @staticmethod
    def _line_points(x0: int, y0: int, x1: int, y1: int) -> Iterable[tuple[int, int]]:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            yield x0, y0
            if x0 == x1 and y0 == y1:
                return
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def render(self) -> Text:
        width = max(1, self.content_size.width)
        height = max(1, self.content_size.height)
        chars = [[" " for _ in range(width)] for _ in range(height)]
        styles = [[brand.TEXT_DIM for _ in range(width)] for _ in range(height)]
        if self.graph_layout == "constellation":
            for y in range(height):
                for x in range(width):
                    star = (x * 31 + y * 17 + x * y * 3) % 113
                    if star == 0:
                        chars[y][x] = "·"
                        styles[y][x] = "#2f3149"

        self._screen_positions = {
            node_id: self._project(position, width, height)
            for node_id, position in self._positions.items()
        }
        label_cells: set[tuple[int, int]] = set()
        for edge_index, edge in enumerate(self._graph_edges):
            start = self._screen_positions.get(edge.source)
            end = self._screen_positions.get(edge.target)
            if start is None or end is None:
                continue
            selected = self.selected_id in {edge.source, edge.target}
            color = brand.CYAN if selected else "#3b3d57"
            points = list(self._line_points(*start, *end))
            for x, y in points[1:-1]:
                if 0 <= x < width and 0 <= y < height:
                    chars[y][x] = "·" if self.graph_layout == "constellation" else "─"
                    styles[y][x] = color
            if points and (selected or edge_index < 6):
                mx, my = points[len(points) // 2]
                label = edge.predicate[: max(0, min(12, width - mx - 1))]
                proposed = {(mx + offset, my) for offset in range(len(label))}
                if not proposed & label_cells:
                    label_cells.update(proposed)
                    for offset, char in enumerate(label):
                        x = mx + offset
                        if 0 <= x < width and 0 <= my < height:
                            chars[my][x] = char
                            styles[my][x] = color

        ranked_ids = {
            node.id for node in sorted(self._graph_nodes, key=lambda node: (-node.degree, node.id))[:8]
        }
        for node in self._graph_nodes:
            point = self._screen_positions.get(node.id)
            if point is None:
                continue
            x, y = point
            if not (0 <= x < width and 0 <= y < height):
                continue
            selected = node.id == self.selected_id
            color = _KIND_COLORS.get(node.kind, brand.TEXT_MUTED)
            chars[y][x] = "◉" if selected else _KIND_GLYPHS.get(node.kind, "●")
            styles[y][x] = f"bold {brand.TEXT_MAIN}" if selected else f"bold {color}"
            if selected or node.id in ranked_ids:
                label = (node.label or node.id).replace("\n", " ")
                limit = max(0, min(22, width - x - 2))
                for offset, char in enumerate(label[:limit], 2):
                    if x + offset < width:
                        chars[y][x + offset] = char
                        styles[y][x + offset] = brand.TEXT_MAIN if selected else brand.TEXT_MUTED

        if not self._graph_nodes:
            empty = "No knowledge-graph nodes in this scope"
            y = height // 2
            x = max(0, (width - len(empty)) // 2)
            for offset, char in enumerate(empty[:width]):
                chars[y][x + offset] = char
                styles[y][x + offset] = brand.TEXT_DIM

        status = (
            f"{self.graph_layout} · {len(self._graph_nodes)} nodes · "
            f"{len(self._graph_edges)} edges"
        )
        if height:
            for x, char in enumerate(status[:width]):
                chars[height - 1][x] = char
                styles[height - 1][x] = brand.TEXT_DIM

        output = Text(no_wrap=True, overflow="crop")
        for y, row in enumerate(chars):
            current_style: str | None = None
            segment = ""
            for char, style in zip(row, styles[y], strict=True):
                if style != current_style and segment:
                    output.append(segment, style=current_style)
                    segment = ""
                current_style = style
                segment += char
            if segment:
                output.append(segment, style=current_style)
            if y < height - 1:
                output.append("\n")
        self.rendered_plain_text = output.plain
        return output

    def _node_at(self, x: int, y: int) -> str | None:
        nearest: tuple[float, str] | None = None
        for node_id, (node_x, node_y) in self._screen_positions.items():
            distance = math.hypot(node_x - x, (node_y - y) * 2)
            if distance <= 2.5 and (nearest is None or distance < nearest[0]):
                nearest = (distance, node_id)
        return nearest[1] if nearest is not None else None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        event.stop()
        self.focus()
        offset = event.get_content_offset(self)
        if offset is not None:
            node_id = self._node_at(offset.x, offset.y)
            if node_id is not None:
                self.selected_id = node_id
                self.refresh()
                self.post_message(self.NodeSelected(node_id))
                return
        self._dragging = True
        self._drag_as_pan = event.shift
        self._start_screen = (event.screen_x, event.screen_y)
        self._start_pan = (self.pan_x, self.pan_y)
        self._start_tilt = (self.tilt_x, self.tilt_y)
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        event.stop()
        dx = event.screen_x - self._start_screen[0]
        dy = event.screen_y - self._start_screen[1]
        if self._drag_as_pan:
            self.pan_x = self._start_pan[0] + dx
            self.pan_y = self._start_pan[1] + dy
        else:
            self.tilt_x = self._start_tilt[0] - dy * 2.0
            self.tilt_y = self._start_tilt[1] + dx * 2.0
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        event.stop()
        self._dragging = False
        self.release_mouse()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self.zoom_by(0.1)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self.zoom_by(-0.1)
