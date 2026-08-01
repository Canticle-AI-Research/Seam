"""Verify the single declared SEAM dependency-source contract."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

EXPECTED_SCHEMA = "seam-dependency-contract/1"
EXPECTED_RUNTIME_SOURCE = "project.dependencies"
EXPECTED_LOCK_POLICY = "bounded-direct-requirements"


def _dependency_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return match.group(1).lower().replace("_", "-") if match else ""


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def verify(repo_root: Path) -> list[str]:
    errors: list[str] = []
    pyproject_path = repo_root / "pyproject.toml"
    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = document["project"]
    contract = document.get("tool", {}).get("seam", {}).get("dependency-contract", {})

    if contract.get("schema") != EXPECTED_SCHEMA:
        errors.append(f"dependency contract schema must be {EXPECTED_SCHEMA!r}")
    if contract.get("runtime-source") != EXPECTED_RUNTIME_SOURCE:
        errors.append(f"runtime-source must be {EXPECTED_RUNTIME_SOURCE!r}")
    if contract.get("lock-policy") != EXPECTED_LOCK_POLICY:
        errors.append(f"lock-policy must be {EXPECTED_LOCK_POLICY!r}")

    mirror_name = str(contract.get("installer-mirror") or "")
    mirror_path = repo_root / mirror_name
    if not mirror_name or not mirror_path.is_file():
        errors.append("installer dependency mirror is missing")
    else:
        runtime_dependencies = list(project.get("dependencies", []))
        mirror_dependencies = _requirement_lines(mirror_path)
        if mirror_dependencies != runtime_dependencies:
            errors.append(
                f"{mirror_name} must exactly mirror project.dependencies in order and bounds"
            )

    extras = project.get("optional-dependencies", {})
    retired = {str(name) for name in contract.get("retired-extras", [])}
    present_retired = retired & set(extras)
    if present_retired:
        errors.append(f"retired extras remain declared: {sorted(present_retired)}")

    convenience_name = str(contract.get("convenience-extra") or "")
    members = [str(name) for name in contract.get("convenience-members", [])]
    excluded_packages = {
        str(name).lower().replace("_", "-")
        for name in contract.get("excluded-convenience-packages", [])
    }
    missing_members = [name for name in members if name not in extras]
    if missing_members:
        errors.append(f"convenience-extra members are undeclared: {missing_members}")
    if convenience_name not in extras:
        errors.append(f"convenience extra {convenience_name!r} is undeclared")
    elif not missing_members:
        expected: set[str] = set()
        for member in members:
            for requirement in extras[member]:
                if _dependency_name(requirement) not in excluded_packages:
                    expected.add(requirement)
        actual = set(extras[convenience_name])
        if actual != expected:
            errors.append(
                f"{convenience_name} differs from declared member union: "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )

    workflow_dir = repo_root / ".github" / "workflows"
    for workflow in sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))):
        text = workflow.read_text(encoding="utf-8")
        for raw_names in re.findall(r"\.\[([^\]]+)\]", text):
            for name in (item.strip() for item in raw_names.split(",")):
                if name in retired:
                    errors.append(f"{workflow.relative_to(repo_root)} installs retired extra {name!r}")
                elif name and name not in extras:
                    errors.append(f"{workflow.relative_to(repo_root)} installs unknown extra {name!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    errors = verify(args.repo_root.resolve())
    if errors:
        print("Dependency contract FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Dependency contract OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
