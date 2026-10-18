"""Retained linked worktrees can satisfy the local pre-push dirt gate."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PRE_PUSH = REPO / "tools" / "git-hooks" / "pre-push"
SCHEMA = "seam-workspace-cleanup-ledger/v1"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("GIT_"):
            env.pop(name)
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture()
def retained_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "test@example.com")
    _git(primary, "config", "user.name", "Test")
    _git(primary, "config", "commit.gpgsign", "false")
    (primary / "README.md").write_text("primary\n", encoding="utf-8")
    _git(primary, "add", "README.md")
    _git(primary, "commit", "-q", "-m", "initial")

    linked = tmp_path / "retained"
    _git(primary, "worktree", "add", "-q", "-b", "retained-test", str(linked))
    (linked / "operator-wip.txt").write_text("preserve me\n", encoding="utf-8")

    item: dict[str, object] = {
        "path": str(linked.resolve()),
        "task": "retained-test",
        "branch": "retained-test",
        "head": _git(linked, "rev-parse", "HEAD").stdout.strip(),
        "status": "retained",
        "owner": "test-owner",
        "reason": "operator work remains active",
        "created_at": "2026-10-17T00:00:00+00:00",
        "review_after": "2099-01-01T00:00:00+00:00",
        "retained_artifacts": [],
    }
    _write_ledger(primary, [item])
    return primary, linked, item


def _write_ledger(
    primary: Path,
    items: object,
    *,
    schema: str = SCHEMA,
    primary_root: str | None = None,
) -> Path:
    ledger = primary / ".seam" / "orchestration" / "cleanup-ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": schema,
        "primary_root": primary_root or str(primary.resolve()),
        "cleanup_suspended": True,
        "items": items,
    }
    ledger.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return ledger


def _verify(primary: Path, linked: Path, *, env: dict[str, str] | None = None):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.git.verify_retained_worktree",
            "--repo-root",
            str(primary),
            "--worktree",
            str(linked),
        ],
        cwd=REPO,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_hook(
    primary: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SEAM_ALLOW_DIRTY_WORKTREES", None)
    env["SEAM_HOOK_PYTHON"] = sys.executable
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO), env.get("PYTHONPATH", "")) if part
    )
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(PRE_PUSH), "origin", "https://github.com/example/private"],
        cwd=primary,
        env=env,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )


def test_normal_pre_push_accepts_exact_retained_dirty_worktree(retained_repo):
    primary, _linked, _item = retained_repo

    result = _run_hook(primary)

    assert result.returncode == 0, result.stderr
    assert "SEAM_ALLOW_DIRTY_WORKTREES=1 set" not in result.stderr


def test_verifier_accepts_exact_retained_record_while_cleanup_is_suspended(retained_repo):
    primary, linked, _item = retained_repo

    result = _verify(primary, linked)

    assert result.returncode == 0, result.stderr


def test_verifier_rejects_missing_ledger(retained_repo):
    primary, linked, _item = retained_repo
    (primary / ".seam" / "orchestration" / "cleanup-ledger.json").unlink()

    result = _verify(primary, linked)

    assert result.returncode == 1
    assert "ledger" in result.stderr.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "active"),
        ("head", "0" * 40),
        ("branch", "other-branch"),
        ("owner", "  "),
        ("reason", ""),
        ("review_after", "2020-01-01T00:00:00+00:00"),
        ("review_after", "2099-01-01T00:00:00"),
    ],
)
def test_verifier_rejects_invalid_or_drifted_retention_fields(
    retained_repo,
    field: str,
    value: object,
):
    primary, linked, item = retained_repo
    changed = dict(item)
    changed[field] = value
    _write_ledger(primary, [changed])

    result = _verify(primary, linked)

    assert result.returncode == 1


def test_verifier_rejects_noncanonical_or_mismatched_path(retained_repo):
    primary, linked, item = retained_repo
    changed = dict(item)
    changed["path"] = str(linked / ".." / linked.name)
    _write_ledger(primary, [changed])

    result = _verify(primary, linked)

    assert result.returncode == 1


def test_verifier_rejects_duplicate_path_records(retained_repo):
    primary, linked, item = retained_repo
    _write_ledger(primary, [item, dict(item)])

    result = _verify(primary, linked)

    assert result.returncode == 1
    assert "duplicate" in result.stderr.lower()


def test_verifier_rejects_malformed_ledger(retained_repo):
    primary, linked, _item = retained_repo
    ledger = primary / ".seam" / "orchestration" / "cleanup-ledger.json"
    ledger.write_text("{not json\n", encoding="utf-8")

    result = _verify(primary, linked)

    assert result.returncode == 1
    assert "json" in result.stderr.lower()


@pytest.mark.parametrize("invalid_items", [{}, "retained", None])
def test_verifier_rejects_invalid_items_collection(retained_repo, invalid_items):
    primary, linked, _item = retained_repo
    _write_ledger(primary, invalid_items)

    result = _verify(primary, linked)

    assert result.returncode == 1


def test_verifier_rejects_wrong_schema(retained_repo):
    primary, linked, item = retained_repo
    _write_ledger(primary, [item], schema="seam-workspace-cleanup-ledger/v0")

    result = _verify(primary, linked)

    assert result.returncode == 1


def test_verifier_rejects_wrong_primary_root(retained_repo, tmp_path: Path):
    primary, linked, item = retained_repo
    _write_ledger(primary, [item], primary_root=str((tmp_path / "other").resolve()))

    result = _verify(primary, linked)

    assert result.returncode == 1


def test_verifier_rejects_failed_git_read(retained_repo):
    primary, linked, _item = retained_repo
    (linked / ".git").rename(linked / ".git-disabled")

    result = _verify(primary, linked)

    assert result.returncode == 1
    assert "git" in result.stderr.lower()


def test_hook_fails_closed_when_linked_status_cannot_be_read(retained_repo):
    primary, linked, _item = retained_repo
    linked.rename(linked.parent / "retained-missing")

    result = _run_hook(primary)

    assert result.returncode == 1
    assert "cannot inspect linked worktree" in result.stderr.lower()


def test_hook_cannot_hide_untracked_dirt_with_git_config(retained_repo):
    primary, linked, item = retained_repo
    changed = dict(item)
    changed["status"] = "active"
    _write_ledger(primary, [changed])
    _git(linked, "config", "status.showUntrackedFiles", "no")

    result = _run_hook(
        primary,
        env_overrides={
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "status.showUntrackedFiles",
            "GIT_CONFIG_VALUE_0": "no",
        },
    )

    assert result.returncode == 1
    assert "uncommitted work" in result.stderr.lower()


def test_verifier_clears_inherited_git_environment(retained_repo):
    primary, linked, _item = retained_repo

    result = _verify(
        primary,
        linked,
        env={"GIT_DIR": "/does/not/exist", "GIT_WORK_TREE": "/also/missing"},
    )

    assert result.returncode == 0, result.stderr


def test_verifier_rejects_unstable_git_or_ledger_observation(retained_repo, monkeypatch):
    primary, linked, _item = retained_repo
    from tools.git import verify_retained_worktree as verifier

    stable = verifier._capture_observation(primary, linked)
    changed = dataclasses.replace(stable, head="f" * 40)
    observations = iter((stable, changed))
    monkeypatch.setattr(verifier, "_capture_observation", lambda *_args: next(observations))

    with pytest.raises(verifier.RetentionValidationError, match="changed"):
        verifier.verify_retained_worktree(primary, linked)


@pytest.mark.parametrize("duplicate_level", ["root", "item"])
def test_verifier_rejects_duplicate_json_object_keys(retained_repo, duplicate_level: str):
    primary, linked, item = retained_repo
    item_json = json.dumps(item, separators=(",", ":"))
    if duplicate_level == "item":
        item_json = item_json.replace(
            '"status":"retained"',
            '"status":"active","status":"retained"',
        )
    schema_fields = f'"schema":"{SCHEMA}"'
    if duplicate_level == "root":
        schema_fields = f'"schema":"wrong",{schema_fields}'
    payload = (
        "{"
        f"{schema_fields},"
        f'"primary_root":{json.dumps(str(primary.resolve()))},'
        f'"cleanup_suspended":true,"items":[{item_json}]'
        "}\n"
    )
    ledger = primary / ".seam" / "orchestration" / "cleanup-ledger.json"
    ledger.write_text(payload, encoding="utf-8")

    result = _verify(primary, linked)

    assert result.returncode == 1
    assert "duplicate json key" in result.stderr.lower()
