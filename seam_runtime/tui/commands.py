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
    "TASK_GROUPS",
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

#: One task vocabulary shared by every surface. The palette groups on this,
#: not on where a command's code happens to live -- "what does an operator
#: want to do", not "which module defines it". Order here is display order.
TASK_GROUPS: tuple[str, ...] = (
    "Capture", "Recall", "Context", "Provenance", "Knowledge graph",
    "Compression", "Benchmarks", "Improve", "Serve & surfaces",
    "Lifecycle & admin", "Session",
)

#: Sub-grouping for dashboard verbs, which are numerous enough to want it.
#: Values are task-vocabulary members (former "Ingest"/"Retrieval" renamed to
#: "Capture"/"Recall" so dash shares the same vocabulary as every other
#: surface); this dict itself stays hand-maintained per-surface, same as
#: `_DASH_SUMMARIES` -- only its *values* are now shared language.
_DASH_GROUPS: dict[str, str] = {
    "search": "Recall", "plan": "Recall", "retrieve": "Recall",
    "context": "Recall",
    "compile": "Capture", "compile-dsl": "Capture", "index": "Capture",
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

#: CLI root command -> shared task. One entry per root, not per subcommand:
#: every `surface encode`/`surface decode`/... leaf inherits "surface"'s
#: task, which is what keeps this a ~40-entry rule set instead of a 66-entry
#: (let alone 153-entry) hand-written table.
_CLI_TASK_ROOTS: dict[str, str] = {
    "ingest": "Capture", "compile-nl": "Capture", "compile-dsl": "Capture",
    "verify": "Capture", "persist": "Capture", "index": "Capture",
    "promote-symbols": "Capture",
    "search": "Recall", "plan": "Recall", "retrieve": "Recall",
    "compare": "Recall", "memory": "Recall",
    "context": "Context", "pack": "Context", "decompile": "Context",
    "trace": "Provenance", "stats": "Provenance",
    "knowledge": "Knowledge graph", "reconcile": "Knowledge graph",
    "benchmark": "Benchmarks", "bench": "Benchmarks",
    "improve": "Improve",
    "surface": "Serve & surfaces", "mcp": "Serve & surfaces",
    "shell": "Serve & surfaces", "dashboard": "Serve & surfaces",
    "serve": "Serve & surfaces", "webui": "Serve & surfaces",
    "doctor": "Lifecycle & admin", "transpile": "Lifecycle & admin",
    "reindex": "Lifecycle & admin", "export-symbols": "Lifecycle & admin",
    "demo": "Compression",
}
#: Root-name prefixes that share a task without one dict entry per command
#: (lossless-compress/lossless-decompress/lossless-benchmark, readable-*,
#: lx1-* are all token-savings notation, i.e. Compression).
_CLI_TASK_PREFIXES: tuple[tuple[str, str], ...] = (
    ("lossless-", "Compression"),
    ("readable-", "Compression"),
    ("lx1-", "Compression"),
)


def _cli_task_group(root: str) -> str:
    """Map a top-level CLI command word to its shared task."""
    if root in _CLI_TASK_ROOTS:
        return _CLI_TASK_ROOTS[root]
    for prefix, group in _CLI_TASK_PREFIXES:
        if root.startswith(prefix):
            return group
    return "Lifecycle & admin"


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


def _subparser_help(action: object) -> dict[str, str]:
    """Return canonical name -> ``add_parser(..., help=...)`` text.

    argparse stores that string on the *parent* subparsers action's
    ``_choices_actions`` pseudo-action list -- one pseudo-action per canonical
    name, not per alias -- never on the child parser itself (``sub.description``
    is a separate, independently-set argparse field). ``_choices_actions`` is
    a private attribute; a future argparse without it degrades to an empty
    map here, and the caller falls back to ``sub.description``.
    """
    help_map: dict[str, str] = {}
    for pseudo in getattr(action, "_choices_actions", None) or []:
        name = getattr(pseudo, "dest", None)
        text = getattr(pseudo, "help", None)
        if name and text:
            help_map[name] = text
    return help_map


def _walk_parser(parser: object, surface: str, prefix: str = "") -> list[CommandSpec]:
    """Recursively flatten an argparse tree into specs.

    Nested trees (``seam surface encode``) are emitted as full paths rather
    than as a bare parent, because the parent alone is not runnable.
    """
    action = _subparser_action(parser)
    if action is None:
        return []

    choices: dict[str, object] = dict(action.choices)  # type: ignore[attr-defined]
    help_map = _subparser_help(action)
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
            summary = help_map.get(canonical) or (getattr(sub, "description", "") or "").strip().split("\n")[0]
            group = _cli_task_group(root)
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

#: MCP tool name, after the shared ``seam_`` prefix -> shared task, matched
#: by the longest known prefix (checked in order) so ``surface_*`` tools
#: share one entry rather than six.
_MCP_TASK_PREFIXES: tuple[tuple[str, str], ...] = (
    ("memory_", "Recall"),
    ("retrieve", "Recall"),
    ("ingest", "Capture"),
    ("knowledge_", "Knowledge graph"),
    ("identity_merges", "Knowledge graph"),
    ("context", "Context"),
    ("stats", "Provenance"),
    ("documents", "Provenance"),
    ("index_status", "Provenance"),
    ("doctor", "Lifecycle & admin"),
    ("surface_", "Serve & surfaces"),
    ("benchmark_", "Benchmarks"),
)


def _mcp_task_group(name: str) -> str:
    tail = name.removeprefix("seam_")
    for prefix, group in _MCP_TASK_PREFIXES:
        if tail.startswith(prefix):
            return group
    return "Lifecycle & admin"


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
                group=_mcp_task_group(name),
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
#:
#: `summary="..."` is optional and, when present, is always the argument
#: immediately following the path string (server.py's convention) -- so a
#: decorator with no summary still matches (the whole group is optional)
#: instead of dropping the route.
_ROUTE_RE = re.compile(
    r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"'
    r'(?:\s*,\s*summary="([^"]*)")?'
)

#: REST path segment (after the leading slash, before any `{param}`) ->
#: shared task. `/v1/*` is dispatched one level deeper because the public
#: `/v1/memories` (write) and `/v1/memories/recall` (read) split across two
#: different tasks despite sharing a path prefix.
_API_TASK_SEGMENTS: dict[str, str] = {
    "stats": "Provenance", "workspace": "Provenance", "trace": "Provenance",
    "knowledge-graph": "Knowledge graph", "knowledge-node": "Knowledge graph",
    "identity-merges": "Knowledge graph",
    "benchmark": "Benchmarks",
    "compile": "Capture", "compile-dsl": "Capture", "persist": "Capture",
    "search": "Recall",
    "context": "Context",
    "lossless-compress": "Compression",
    "tree": "Serve & surfaces", "sys-metrics": "Serve & surfaces",
    "chat": "Serve & surfaces",
}


def _api_task_group(path: str) -> str:
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "Serve & surfaces"  # the bare "/" dashboard index
    head = segments[0]
    if head == "v1":
        sub = segments[1] if len(segments) > 1 else ""
        if sub == "memories":
            return "Recall" if segments[2:3] == ["recall"] else "Capture"
        return _API_TASK_SEGMENTS.get(sub, "Context")
    return _API_TASK_SEGMENTS.get(head, "Lifecycle & admin")


def _api_specs() -> list[CommandSpec]:
    try:
        from .. import server
        source = inspect.getsource(server)
    except Exception:  # pragma: no cover - server extra not installed
        return []
    specs: list[CommandSpec] = []
    seen: set[tuple[str, str]] = set()
    for verb, path, summary in _ROUTE_RE.findall(source):
        key = (verb, path)
        if key in seen:
            continue
        seen.add(key)
        specs.append(
            CommandSpec(
                name=f"{verb.upper():6s} {path}", surface="api",
                summary=summary,
                group=_api_task_group(path),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Source: Python SDK
# ---------------------------------------------------------------------------

#: `SeamSDK` method name -> shared task. Reasoning-run lifecycle (start/reopen
#: a run) is Provenance -- it records how a conclusion was reached, before any
#: of it is promoted into the graph; the promotion pipeline itself (propose ->
#: review -> apply/reverse) writes into the knowledge graph, so it belongs
#: there instead.
_SDK_TASK_NAMES: dict[str, str] = {
    "ingest": "Capture",
    "knowledge": "Knowledge graph",
    "rebuild_graph_products": "Knowledge graph",
    "graph_products": "Knowledge graph",
    "graph_product_history": "Knowledge graph",
    "context": "Context",
    "start_reasoning": "Provenance",
    "reasoning": "Provenance",
    "promotion": "Knowledge graph",
    "promotion_eligibility": "Knowledge graph",
    "promotions": "Knowledge graph",
    "apply_promotion": "Knowledge graph",
    "reverse_promotion": "Knowledge graph",
    "review_promotion": "Knowledge graph",
    "plan_delete": "Lifecycle & admin",
    "apply_delete": "Lifecycle & admin",
    "batch_ingest": "Lifecycle & admin",
    "resume_operation": "Lifecycle & admin",
    "lifecycle_operation": "Lifecycle & admin",
    "recoverable_operations": "Lifecycle & admin",
    "close": "Session",
}


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
                summary=doc,
                group=_SDK_TASK_NAMES.get(name, "Lifecycle & admin"),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_catalog(dashboard_parser: object) -> tuple[CommandSpec, ...]:
    """Return every command across every surface, ordered for display.

    Executable dash verbs (the only things the palette can actually run) sort
    ahead of every reference-only row, matching the palette's Run/Reference
    split. Within each of those two sections, commands group by shared task
    rather than by surface, so the CLI form, the REST route, and the MCP tool
    for the same task land next to each other; surface is only the tiebreak.
    """
    specs: list[CommandSpec] = []
    specs.extend(_dashboard_specs(dashboard_parser))
    specs.extend(_cli_specs())
    specs.extend(_mcp_specs())
    specs.extend(_api_specs())
    specs.extend(_sdk_specs())

    def sort_key(spec: CommandSpec) -> tuple[int, int, int, str]:
        section_rank = 0 if spec.executable else 1
        group_rank = (TASK_GROUPS.index(spec.group)
                      if spec.group in TASK_GROUPS else len(TASK_GROUPS))
        surface_rank = (SURFACE_ORDER.index(spec.surface)
                        if spec.surface in SURFACE_ORDER else len(SURFACE_ORDER))
        return (section_rank, group_rank, surface_rank, spec.name)

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
