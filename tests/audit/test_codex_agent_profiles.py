"""Contract tests for the project-scoped Codex orchestration team."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / ".codex" / "agents"
PACKET_SCHEMA = REPO_ROOT / "tools" / "agents" / "schemas" / "context-packet.schema.json"

EXPECTED_AGENTS = {
    "seam_root_orchestrator": "workspace-write",
    "seam_context_orchestrator": "read-only",
    "seam_delivery_orchestrator": "workspace-write",
    "seam_assurance_orchestrator": "read-only",
    "seam_release_orchestrator": "read-only",
}


def test_orchestration_team_is_flat_and_complete() -> None:
    profiles = sorted(AGENT_DIR.glob("*.toml"))

    assert {path.stem for path in profiles} == set(EXPECTED_AGENTS)
    for path in profiles:
        profile = tomllib.loads(path.read_text(encoding="utf-8"))
        assert profile["name"] == path.stem
        assert profile["description"].strip()
        assert profile["developer_instructions"].strip()
        assert profile["sandbox_mode"] == EXPECTED_AGENTS[path.stem]


def test_every_role_requires_root_supplied_context_and_bounded_reads() -> None:
    for path in AGENT_DIR.glob("*.toml"):
        instructions = tomllib.loads(path.read_text(encoding="utf-8"))[
            "developer_instructions"
        ]
        assert "CONTEXT_PACKET" in instructions, path.name
        assert "packet-listed" in instructions, path.name
        assert "MISSING_CONTEXT" in instructions, path.name
        assert "Do not read HISTORY.md" in instructions, path.name
        assert "Do not run an unbounded repository scan" in instructions, path.name
        assert "do not revert" in instructions.lower(), path.name


def test_delegation_depth_and_integration_authority_are_explicit() -> None:
    root = tomllib.loads(
        (AGENT_DIR / "seam_root_orchestrator.toml").read_text(encoding="utf-8")
    )["developer_instructions"]
    domains = [
        path
        for path in AGENT_DIR.glob("seam_*_orchestrator.toml")
        if path.stem != "seam_root_orchestrator"
    ]

    assert "root -> domain orchestrator -> specialist" in root
    assert "Root alone integrates" in root
    for path in domains:
        instructions = tomllib.loads(path.read_text(encoding="utf-8"))[
            "developer_instructions"
        ]
        assert "specialist_budget" in instructions, path.name
        assert "Specialists may not delegate" in instructions, path.name
        assert "Do not stage, commit, push, merge" in instructions, path.name


def test_context_packet_schema_carries_context_not_repo_reading_instructions() -> None:
    schema = json.loads(PACKET_SCHEMA.read_text(encoding="utf-8"))
    required = set(schema["required"])

    assert {
        "run_id",
        "task_id",
        "role",
        "objective",
        "acceptance_criteria",
        "supplied_context",
        "owned_paths",
        "allowed_reads",
        "forbidden_reads",
        "specialist_budget",
        "return_contract",
    } <= required
    assert schema["properties"]["specialist_budget"]["maximum"] == 2
    assert schema["additionalProperties"] is False
