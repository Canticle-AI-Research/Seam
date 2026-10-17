from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo_with_plan(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    plan = repo / "docs" / "delivery" / "current.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({
        "schema": "seam-delivery-plan/v1",
        "delivery_id": "missing-completion",
        "repository": "acme/widget",
        "next_action_after_verified": "Continue with the next bounded repair.",
    }) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "plan")
    return repo, plan


def _status(repo: Path, plan: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.delivery_status",
            "--repo-root",
            str(repo),
            "--plan",
            str(plan),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_delivery_status_is_unverified_when_completion_is_missing(
    tmp_path: Path,
) -> None:
    repo, plan = _repo_with_plan(tmp_path)

    result = _status(repo, plan)

    assert result.returncode != 0
    assert json.loads(result.stdout)["status"] == "UNVERIFIED"


def test_delivery_status_rejects_a_malformed_current_plan(tmp_path: Path) -> None:
    repo, plan = _repo_with_plan(tmp_path)
    value = json.loads(plan.read_text())
    value["unexpected"] = True
    plan.write_text(json.dumps(value))

    result = _status(repo, plan)

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "UNVERIFIED"
    assert "plan" in payload["reason"]
