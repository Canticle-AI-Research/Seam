"""Contract tests for the project-scoped Codex orchestration team."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / ".codex" / "agents"
PACKET_SCHEMA = REPO_ROOT / "tools" / "agents" / "schemas" / "context-packet.schema.json"
AGENTS_POLICY = REPO_ROOT / "AGENTS.md"
REPO_LEDGER = REPO_ROOT / "REPO_LEDGER.md"
ORCHESTRATION_SOP = REPO_ROOT / "docs" / "SOP_AGENT_ORCHESTRATION.md"

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


def test_root_profile_activates_the_bounded_context_guardian() -> None:
    root = tomllib.loads(
        (AGENT_DIR / "seam_root_orchestrator.toml").read_text(encoding="utf-8")
    )["developer_instructions"]

    assert "tools.agents.context_guardian" in root
    assert "45%" in root
    assert "65%" in root
    assert "82%" in root
    assert "two compactions" in root
    assert "HANDOFF_REQUIRED" in root


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


def test_orchestration_policy_is_codex_only_and_preserves_other_model_styles() -> None:
    agents_policy = AGENTS_POLICY.read_text(encoding="utf-8")
    ledger = REPO_LEDGER.read_text(encoding="utf-8")
    sop = ORCHESTRATION_SOP.read_text(encoding="utf-8")

    assert "Model-specific orchestration stays in each model's own configuration" in agents_policy
    assert "### Codex-Only Delegated Context Fast Path" in agents_policy
    assert "This fast path applies only to Codex" in agents_policy
    assert "Codex-only root-supplied agent orchestration" in ledger
    assert "This SOP applies only to Codex" in sop
    assert "Claude, Gemini, DeepSeek" in sop
    assert "keep their own orchestration styles" in sop
    assert "Codex review/merge handling remains local and non-agentic" in ledger
