"""Unified command catalog spanning every SEAM surface.

The `/` palette is meant to answer "what can SEAM actually do", so it covers
all five surfaces rather than only the dashboard's own verbs:

======  ==========================================================
Source  Where it comes from
======  ==========================================================
DASH    `DashboardApp._build_command_parser()` — runnable in-app
CLI     `seam_runtime.cli.build_parser()` — the full nested tree
MCP     `seam_runtime.mcp.TOOL_METADATA` — agent-facing tools
API     `seam_runtime.server` route decorators
SDK     `seam_runtime.sdk.SeamSDK` public methods
======  ==========================================================

Every source is *derived*, never transcribed. A command added anywhere in the
codebase shows up here on the next launch, which is the property a
hand-maintained menu loses within a week. Each source is also independently
failure-tolerant: an optional dependency that is not installed removes its
section instead of breaking the palette.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field

__all__ = [
    "CommandSpec",
    "build_catalog",
    "filter_catalog",
    "SURFACES",
    "SURFACE_ORDER",
]

# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

#: surface key -> (section label, whether the TUI can execute it directly)
SURFACES: dict[str, tuple[str, bool]] = {
    "dash": ("Dashboard", True),
    "cli": ("CLI  ·  seam", False),
    "mcp": ("MCP tools  ·  agent-facing", False),
    "api": ("REST API", False),
    "sdk": ("Python SDK", False),
}

SURFACE_ORDER: tuple[str, ...] = ("dash", "cli", "mcp", "api", "sdk")

#: Sub-grouping for dashboard verbs, which are numerous enough to want it.
_DASH_GROUPS: dict[str, str] = {
    "search": "Retrieval", "plan": "Retrieval", "retrieve": "Retrieval",
    "context": "Retrieval",
    "compile": "Ingest", "compile-dsl": "Ingest", "index": "Ingest",
    "trace": "Provenance", "stats": "Provenance",
    "benchmark": "Compression", "compress-doc": "Compression",
    "readable-compress": "Compression", "readable-query": "Compression",
    "readable-rebuild": "Compression", "decompress-doc": "Compression",
    "decompress-last": "Compression",
    "help": "Session", "quit": "Session", "tab": "Session", "reload": "Session",
}

_DASH_SUMMARIES: dict[str, str] = {
    "help": "Show help, optionally for one topic",
    "quit": "Close the dashboard cleanly",
    "tab": "Switch to a dashboard tab",
    "compile": "Compile natural language into MIRL records",
    "compile-dsl": "Compile a MIRL DSL file",
    "search": "Search memory and show ranked records",
    "plan": "Show the retrieval plan without executing it",
    "retrieve": "Run full multi-leg retrieval",
    "context": "Assemble a context PACK for a query",
    "index": "Rebuild vector/graph indexes for a scope",
    "trace": "Trace an object id through its provenance chain",
    "benchmark": "Run a compression benchmark over a source",
    "compress-doc": "Losslessly compress a document",
    "readable-compress": "Readable-compress a document",
    "readable-query": "Query a readable-compressed document",
    "readable-rebuild": "Rebuild a readable-compressed document",
    "decompress-doc": "Decompress a compressed document",
    "decompress-last": "Decompress the most recent document",
    "stats": "Show runtime and store statistics",
    "reload": "Reload runtime state from disk",
}

#: Short blurbs for CLI groups, so a bare `surface encode` is not a mystery.
_CLI_GROUP_BLURBS: dict[str, str] = {
    "surface": "SEAM-HS/1 holographic surface library",
    "benchmark": "Benchmark runs, gates, and comparisons",
    "bench": "External benchmark sealing and publication",
    "knowledge": "Temporal knowledge-graph queries",
    "memory": "Direct memory record access",
    "mcp": "Model Context Protocol servers",
    "improve": "Self-improvement proposal loop",
    "demo": "Demonstrations",
}


@dataclass(frozen=True)
class CommandSpec:
    """One invocable or documented SEAM command, from any surface."""

    name: str
    surface: str = "dash"
    aliases: tuple[str, ...] = ()
    positionals: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    summary: str = ""
    group: str = ""
    choices: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """Return whether the TUI can run this directly."""
        return SURFACES.get(self.surface, ("", False))[1]

    @property
    def prefix(self) -> str:
        """Return the display prefix that identifies the surface."""
        return {
            "dash": "/", "cli": "seam ", "mcp": "", "api": "", "sdk": "sdk.",
        }.get(self.surface, "")

    @property
    def usage(self) -> str:
        parts = [f"{self.prefix}{self.name}"]
        parts.extend(f"<{p}>" for p in self.positionals)
        parts.extend(self.options)
        return " ".join(parts)

    @property
    def display(self) -> str:
        alias = f"  ({', '.join(self.aliases)})" if self.aliases else ""
        return f"{self.prefix}{self.name}{alias}"

    def matches(self, query: str) -> bool:
        if not query:
            return True
        haystacks = (self.name, *self.aliases, self.summary, self.group,
                     SURFACES.get(self.surface, ("",))[0])
        return any(query in h.lower() for h in haystacks)


# ---------------------------------------------------------------------------
# Source: dashboard + CLI argparse trees
# ---------------------------------------------------------------------------


def _subparser_action(parser: object) -> object | None:
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if choices and hasattr(choices, "items"):
            return action
    return None


def _describe(subparser: object) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]]]:
    positionals: list[str] = []
    options: list[str] = []
    option_choices: dict[str, tuple[str, ...]] = {}
    for arg in getattr(subparser, "_actions", []):
        if arg.dest == "help":
            continue
        if arg.option_strings:
            flag = arg.option_strings[-1]
            options.append(flag)
            if getattr(arg, "choices", None):
                option_choices[flag] = tuple(str(c) for c in arg.choices)
        else:
            positionals.append(arg.dest)
    return tuple(positionals), tuple(options), option_choices


def _walk_parser(parser: object, surface: str, prefix: str = "") -> list[CommandSpec]:
    """Recursively flatten an argparse tree into specs.

    Nested trees (``seam surface encode``) are emitted as full paths rather
    than as a bare parent, because the parent alone is not runnable.
    """
    action = _subparser_action(parser)
    if action is None:
        return []

    choices: dict[str, object] = dict(action.choices)  # type: ignore[attr-defined]
    by_parser: dict[int, list[str]] = {}
    for name, sub in choices.items():
        by_parser.setdefault(id(sub), []).append(name)

    specs: list[CommandSpec] = []
    seen: set[int] = set()
    for name, sub in choices.items():
        if id(sub) in seen:
            continue
        seen.add(id(sub))
        names = by_parser[id(sub)]
        canonical = names[0]
        aliases = tuple(n for n in names[1:] if n != canonical)
        path = f"{prefix} {canonical}".strip()

        nested = _walk_parser(sub, surface, path)
        if nested:
            specs.extend(nested)
            continue

        positionals, options, option_choices = _describe(sub)
        root = path.split()[0]
        if surface == "dash":
            summary = _DASH_SUMMARIES.get(canonical, "")
            group = _DASH_GROUPS.get(canonical, "Other")
        else:
            summary = (getattr(sub, "description", "") or "").strip().split("\n")[0]
            group = _CLI_GROUP_BLURBS.get(root, "")
        specs.append(
            CommandSpec(
                name=path, surface=surface, aliases=aliases,
                positionals=positionals, options=options,
                summary=summary, group=group, choices=option_choices,
            )
        )
    return specs


def _dashboard_specs(parser: object) -> list[CommandSpec]:
    return _walk_parser(parser, "dash")


def _cli_specs() -> list[CommandSpec]:
    try:
        from ..cli import build_parser
    except Exception:  # pragma: no cover - CLI unavailable
        return []
    try:
        return _walk_parser(build_parser(), "cli")
    except Exception:  # pragma: no cover
        return []


# ---------------------------------------------------------------------------
# Source: MCP tools
# ---------------------------------------------------------------------------


def _mcp_specs() -> list[CommandSpec]:
    try:
        from ..mcp import TOOL_METADATA
    except Exception:  # pragma: no cover - MCP unavailable
        return []
    specs: list[CommandSpec] = []
    for name, metadata in TOOL_METADATA.items():
        description = ""
        if isinstance(metadata, dict):
            description = str(metadata.get("description") or "")
        specs.append(
            CommandSpec(
                name=name, surface="mcp",
                summary=description.strip().split("\n")[0],
                group="MCP",
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Source: REST routes
# ---------------------------------------------------------------------------

#: Routes are declared with decorators inside a factory that needs a live
#: runtime, so they are read from the module source rather than by importing
#: FastAPI and constructing an app. Still derived -- adding a route to
#: `server.py` adds it here -- without paying an optional dependency.
_ROUTE_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"')


def _api_specs() -> list[CommandSpec]:
    try:
        from .. import server
        source = inspect.getsource(server)
    except Exception:  # pragma: no cover - server extra not installed
        return []
    specs: list[CommandSpec] = []
    seen: set[tuple[str, str]] = set()
    for verb, path in _ROUTE_RE.findall(source):
        key = (verb, path)
        if key in seen:
            continue
        seen.add(key)
        specs.append(
            CommandSpec(
                name=f"{verb.upper():6s} {path}", surface="api",
                group="Public /v1" if path.startswith("/v1") else "Operator",
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Source: Python SDK
# ---------------------------------------------------------------------------


def _sdk_specs() -> list[CommandSpec]:
    try:
        from ..sdk import SeamSDK
    except Exception:  # pragma: no cover
        return []
    specs: list[CommandSpec] = []
    for name in sorted(dir(SeamSDK)):
        if name.startswith("_"):
            continue
        attribute = getattr(SeamSDK, name, None)
        if not callable(attribute):
            continue
        doc = (inspect.getdoc(attribute) or "").strip().split("\n")[0]
        try:
            signature = str(inspect.signature(attribute)).replace("self, ", "").replace("self", "")
        except (TypeError, ValueError):  # pragma: no cover
            signature = "()"
        specs.append(
            CommandSpec(
                name=f"{name}{signature}", surface="sdk",
                summary=doc, group="SeamSDK",
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_catalog(dashboard_parser: object) -> tuple[CommandSpec, ...]:
    """Return every command across every surface, ordered for display."""
    specs: list[CommandSpec] = []
    specs.extend(_dashboard_specs(dashboard_parser))
    specs.extend(_cli_specs())
    specs.extend(_mcp_specs())
    specs.extend(_api_specs())
    specs.extend(_sdk_specs())

    def sort_key(spec: CommandSpec) -> tuple[int, str, str]:
        surface_rank = (SURFACE_ORDER.index(spec.surface)
                        if spec.surface in SURFACE_ORDER else len(SURFACE_ORDER))
        return (surface_rank, spec.group, spec.name)

    specs.sort(key=sort_key)
    return tuple(specs)


def filter_catalog(
    catalog: tuple[CommandSpec, ...],
    query: str,
    surface: str | None = None,
) -> tuple[CommandSpec, ...]:
    """Filter by free text and optionally by a single surface."""
    normalized = query.strip().lower().lstrip("/")
    matches = [c for c in catalog
               if (surface is None or c.surface == surface) and c.matches(normalized)]
    if not normalized:
        return tuple(matches)
    matches.sort(key=lambda c: (
        not c.name.lower().startswith(normalized),
        SURFACE_ORDER.index(c.surface) if c.surface in SURFACE_ORDER else 9,
        c.name,
    ))
    return tuple(matches)


def catalog_counts(catalog: tuple[CommandSpec, ...]) -> dict[str, int]:
    """Return per-surface counts, for the palette header."""
    counts: dict[str, int] = {}
    for spec in catalog:
        counts[spec.surface] = counts.get(spec.surface, 0) + 1
    return counts
