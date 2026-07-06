"""Public-core allow-list: tools/release/public_manifest.py.

Fail-closed contract: a path is only eligible for the public seam-runtime
mirror if it's explicitly listed here (synced) or is one of the public
repo's own independently-owned bookkeeping paths. Everything else -- in
particular anything new added to the private repo later -- is private by
default until someone deliberately adds it to this manifest.
"""
from __future__ import annotations

import pytest

from tools.release.public_manifest import (
    is_allowed_on_public_mirror,
    is_public_owned_path,
    is_public_synced_path,
)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "LICENSE",
        "AGENTS.md",
        "pyproject.toml",
        "seam_runtime/mcp_protocol.py",
        "seam_runtime/webui/dashboard.html",
        "tests/audit/test_public_manifest.py",
        "test_seam_all/conftest.py",
        "installers/install_seam_linux.sh",
        "tools/h2/holdout_split.py",  # real seam_runtime.improvement runtime dependency
        "tools/history/new_entry.py",
        "tools/streams/verify_streams.py",
        "docs/MACOS.md",
        "docs/CODE_LAYOUT.md",
        "benchmarks/external/locomo/adapter.py",
        "benchmarks/README.md",
    ],
)
def test_public_synced_paths(path: str) -> None:
    assert is_public_synced_path(path)
    assert is_allowed_on_public_mirror(path)
    assert not is_public_owned_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "HISTORY.md",
        "HISTORY_INDEX.md",
        "PROJECT_STATUS.md",
        "REPO_LEDGER.md",
        ".seam/streams/history/log.md",
        ".seam/cross_index.md",
    ],
)
def test_public_owned_paths(path: str) -> None:
    assert is_public_owned_path(path)
    assert is_allowed_on_public_mirror(path)
    assert not is_public_synced_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/audits/2026-05-28-deep-health-audit.md",
        "docs/handoffs/2026-06-08-h2-self-improvement-loop.md",
        "docs/roadmap/COMPETITIVE_ROADMAP.md",
        "docs/SOP_TRACK_K_BIL_PHASE1_DEEPSEEK.md",
        "docs/engineering/08_INCIDENT_RESPONSE.md",
        "docs/progress_tables/benchmark_results.csv",
        "docs/prompts/DEEPSEEK_TRACK_K_BIL_PHASE1_PROMPT.md",
        "docs/archive/README.md",
        ".opencode/skills/seam-architect/SKILL.md",
        "skills/seam-engineer/SKILL.md",
        "archive/code/README.md",
        "benchmarks/BENCHMARK_LOG.md",
        "benchmarks/runs/20260417_111912_hash_projection.json",
        "tools/release/verify_public_safe.py",
        "tools/release/sync_public_mirror.py",
        "tools/ci/chroma_real_smoke.py",
        "tools/claude/preflight_protocol.sh",
        "tools/git-hooks/pre-push",
        "tools/skills/compiler.py",
        ".github/workflows/ci.yml",
        "some/brand/new/path/nobody/added/yet.md",
    ],
)
def test_private_by_default_paths(path: str) -> None:
    assert not is_public_synced_path(path)
    assert not is_public_owned_path(path)
    assert not is_allowed_on_public_mirror(path)
