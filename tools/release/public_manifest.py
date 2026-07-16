"""Allow-list defining the public-core subset of the Seam tree.

HISTORY#344 added `verify_public_safe.py`, a deny-list scanner that blocks
secret-shaped content from reaching the public `seam-runtime` mirror. A
deny-list fails *open*: any private file that isn't secret-shaped ships
anyway. HISTORY#355 found that's exactly what happened -- `HISTORY.md`,
`.seam/`, `docs/audits/`, and other internal bookkeeping had been fully
mirrored to the public repo since day one via a plain `git push main:main`.

This module is the fail-closed replacement: nothing leaves the private repo
via `sync_public_mirror.py` unless its path is explicitly listed here. Adding
a new private file requires no action; adding a new *public* file requires
adding it here first.

Two disjoint categories:
  - `is_public_synced_path`: copied verbatim from private `main`'s tree on
    every sync.
  - `is_public_owned_path`: the public repo's OWN independent bookkeeping
    (its own `HISTORY.md`, `PROJECT_STATUS.md`, etc.) -- seeded once, then
    left alone by every subsequent sync so the private repo's actual
    internal incident log and strategy notes are never copied over.

See `docs/PROTECTION_MODEL.md` for the reasoning behind this split.
"""

from __future__ import annotations

# Exact top-level files synced verbatim from private main's tree.
PUBLIC_FILES: frozenset[str] = frozenset(
    {
        ".env.example",
        ".gitattributes",
        ".gitignore",
        ".rgignore",
        "LICENSE",
        "NOTICE",
        "COMMERCIAL_LICENSE.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "QWEN.md",
        "ANTIGRAVITY.md",
        "ROADMAP.md",
        "SEAM_SPEC_V0.1.md",
        "MANIFEST.in",
        "pyproject.toml",
        "requirements.txt",
        "docker-compose.yaml",
        "pytest.ini",
        "seam.py",
        "server.json",
    }
)

# Directory prefixes synced verbatim (recursively) from private main's tree.
PUBLIC_DIR_PREFIXES: tuple[str, ...] = (
    "seam_runtime/",
    "tests/",
    "test_seam_all/",
    "installers/",
    "branding/",
    "scripts/",
    "tools/h2/",  # real seam_runtime.improvement runtime dependency, not dev-only tooling
    "tools/history/",  # protocol tooling AGENTS.md/CONTRIBUTING.md tell contributors to use
    "tools/streams/",  # multi-stream substrate AGENTS.md's Context Loop references
    "benchmarks/external/",
    "benchmarks/fixtures/",
    "benchmarks/fidelity/",
    "benchmarks/registry/",
    "docs/howto/",
)

# Individual doc files synced verbatim; docs/ is private-by-default otherwise
# (docs/audits/, docs/handoffs/, docs/roadmap/, docs/SOP_*.md, etc. are
# internal research/process material, not public product documentation).
PUBLIC_DOC_FILES: frozenset[str] = frozenset(
    {
        "docs/README.md",
        "docs/setup.md",
        "docs/errors.md",
        "docs/CODE_LAYOUT.md",
        "docs/DATA_ROUTING.md",
        "docs/MACOS.md",
        "docs/SEAM_OPERATOR_GUIDE.md",
        "docs/PGVECTOR_LOCAL.md",
        "docs/RAG_ARCHITECTURE.md",
        "docs/KNOWLEDGE_GRAPH.md",
        "docs/MIRL_V1.md",
        "docs/RETRIEVAL_EVAL_V1.md",
        "docs/HOLOGRAPHIC_SURFACE.md",
        "docs/PROTECTION_MODEL.md",
        "docs/BENCHMARK_SOP.md",
    }
)

PUBLIC_BENCHMARK_ROOT_FILES: frozenset[str] = frozenset(
    {
        "benchmarks/README.md",
        "benchmarks/SEAM_BENCHMARK_BLUEPRINT_V1.md",
    }
)

# tools/ root-level utility scripts that are benchmark/analysis harness code,
# not private dev/release tooling.
PUBLIC_TOOLS_ROOT_FILES: frozenset[str] = frozenset(
    {
        "tools/tokenization.py",
        "tools/extract_projection_metrics.py",
        "tools/projection_sbert_comparison.py",
        "tools/run_external_memory_benchmarks.py",
        "tools/run_projection_benchmarks.py",
        "tools/lossless_demo_input.txt",
    }
)

# Paths the public mirror owns independently. The sync never overwrites these
# once seeded -- they carry the PUBLIC repo's own bookkeeping trail, never a
# copy of the private repo's actual internal history/state/ledger content.
PUBLIC_OWNED_PATHS: frozenset[str] = frozenset(
    {
        "PROJECT_STATUS.md",
        "REPO_LEDGER.md",
        "HISTORY.md",
        "HISTORY_INDEX.md",
    }
)
PUBLIC_OWNED_DIR_PREFIXES: tuple[str, ...] = (".seam/",)


def is_public_synced_path(path: str) -> bool:
    """True if `path` is eligible to be copied verbatim from private main."""
    if (
        path in PUBLIC_FILES
        or path in PUBLIC_DOC_FILES
        or path in PUBLIC_BENCHMARK_ROOT_FILES
        or path in PUBLIC_TOOLS_ROOT_FILES
    ):
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_DIR_PREFIXES)


def is_public_owned_path(path: str) -> bool:
    """True if `path` is public-repo-owned bookkeeping the sync must never overwrite."""
    if path in PUBLIC_OWNED_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_OWNED_DIR_PREFIXES)


def is_allowed_on_public_mirror(path: str) -> bool:
    """True if `path` may legitimately exist on the public mirror at all --
    either synced from private main, or owned independently by the public repo."""
    return is_public_synced_path(path) or is_public_owned_path(path)
