"""Behavioral contract for bounded Codex context-lifecycle decisions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.agents import context_guardian


@pytest.mark.parametrize(
    ("used_tokens", "at_milestone", "compactions", "expected"),
    [
        (44, False, 0, "CONTINUE"),
        (45, False, 0, "CHECKPOINT_NOW"),
        (64, False, 0, "CHECKPOINT_NOW"),
        (65, False, 0, "COMPACT_AT_MILESTONE"),
        (65, True, 0, "COMPACT_NOW"),
        (81, True, 1, "COMPACT_NOW"),
        (50, False, 2, "HANDOFF_REQUIRED"),
        (65, True, 2, "HANDOFF_REQUIRED"),
        (82, False, 0, "HANDOFF_REQUIRED"),
    ],
)
def test_policy_enforces_checkpoint_compaction_and_handoff_thresholds(
    used_tokens: int,
    at_milestone: bool,
    compactions: int,
    expected: str,
) -> None:
    decision = context_guardian.decide(
        used_tokens=used_tokens,
        context_limit=100,
        compactions_completed=compactions,
        at_coherent_milestone=at_milestone,
    )

    assert decision["action"] == expected
    assert decision["usage_percent"] == float(used_tokens)


@pytest.mark.parametrize(
    ("used_tokens", "context_limit", "compactions"),
    [(-1, 100, 0), (1, 0, 0), (101, 100, 0), (1, 100, -1), (1, 100, 3)],
)
def test_policy_rejects_impossible_or_unbounded_inputs(
    used_tokens: int, context_limit: int, compactions: int
) -> None:
    with pytest.raises(context_guardian.ContextGuardianError):
        context_guardian.decide(
            used_tokens=used_tokens,
            context_limit=context_limit,
            compactions_completed=compactions,
            at_coherent_milestone=False,
        )


def test_observe_updates_checkpoint_and_writes_successor_handoff_after_two_compactions(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "context"
    handoff_root = tmp_path / "handoffs"
    common = {
        "session_id": "session-guardian-1",
        "context_limit": 100,
        "summary": ["PR 238 closeout queue and context guardian are under test."],
        "next_step": "Run the orchestration audit suite.",
        "state_root": state_root,
        "handoff_root": handoff_root,
    }

    checkpointed = context_guardian.observe(
        used_tokens=45,
        at_coherent_milestone=False,
        **common,
    )
    checkpoint_path = Path(checkpointed["checkpoint_path"])
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpointed["action"] == "CHECKPOINT_NOW"
    assert checkpoint["summary"] == common["summary"]
    assert checkpoint_path.stat().st_mode & 0o777 == 0o600

    with pytest.raises(context_guardian.ContextGuardianError, match="COMPACT_NOW"):
        context_guardian.record_compaction(
            session_id="session-guardian-1", state_root=state_root
        )

    assert context_guardian.observe(
        used_tokens=65, at_coherent_milestone=True, **common
    )["action"] == "COMPACT_NOW"
    first = context_guardian.record_compaction(
        session_id="session-guardian-1",
        state_root=state_root,
        handoff_root=handoff_root,
    )
    assert context_guardian.observe(
        used_tokens=65, at_coherent_milestone=True, **common
    )["action"] == "COMPACT_NOW"
    second = context_guardian.record_compaction(
        session_id="session-guardian-1",
        state_root=state_root,
        handoff_root=handoff_root,
    )
    assert first["compactions_completed"] == 1
    assert second["compactions_completed"] == 2
    assert second["action"] == "HANDOFF_REQUIRED"
    handoff_path = Path(second["handoff_path"])
    assert handoff_path.is_file()
    with pytest.raises(context_guardian.ContextGuardianError, match="two compactions"):
        context_guardian.record_compaction(
            session_id="session-guardian-1",
            state_root=state_root,
            handoff_root=handoff_root,
        )

    handed_off = context_guardian.observe(
        used_tokens=50,
        at_coherent_milestone=False,
        **common,
    )
    assert handed_off["action"] == "HANDOFF_REQUIRED"
    assert "Run the orchestration audit suite." in handoff_path.read_text(
        encoding="utf-8"
    )


def test_observe_rejects_secret_shaped_checkpoint_content(tmp_path: Path) -> None:
    with pytest.raises(context_guardian.ContextGuardianError, match="sensitive"):
        context_guardian.observe(
            session_id="session-guardian-2",
            used_tokens=45,
            context_limit=100,
            at_coherent_milestone=False,
            summary=["safe summary\ninjected"],
            next_step="Continue safely.",
            state_root=tmp_path / "context",
            handoff_root=tmp_path / "handoffs",
        )


def test_cli_observes_usage_and_records_a_compaction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_root = tmp_path / "context"
    handoff_root = tmp_path / "handoffs"
    common = [
        "--session-id",
        "session-guardian-cli",
        "--state-root",
        str(state_root),
        "--handoff-root",
        str(handoff_root),
    ]

    assert context_guardian.main(
        [
            *common,
            "observe",
            "--used-tokens",
            "65",
            "--context-limit",
            "100",
            "--at-coherent-milestone",
            "--summary",
            "Closeout queue is green.",
            "--next-step",
            "Compact, then continue guardian verification.",
        ]
    ) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["action"] == "COMPACT_NOW"

    assert context_guardian.main([*common, "record-compaction"]) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["compactions_completed"] == 1


def test_observe_rejects_symlinked_guardian_state(tmp_path: Path) -> None:
    state_root = tmp_path / "context"
    arguments = {
        "session_id": "session-guardian-symlink",
        "used_tokens": 45,
        "context_limit": 100,
        "at_coherent_milestone": False,
        "summary": ["Checkpoint content."],
        "next_step": "Continue verification.",
        "state_root": state_root,
        "handoff_root": tmp_path / "handoffs",
    }
    context_guardian.observe(**arguments)
    state_path = state_root / "session-guardian-symlink.json"
    external = tmp_path / "external-state.json"
    state_path.replace(external)
    state_path.symlink_to(external)

    with pytest.raises(context_guardian.ContextGuardianError, match="regular file"):
        context_guardian.observe(**arguments)


def test_observe_rejects_symlinked_checkpoint_directory(tmp_path: Path) -> None:
    state_root = tmp_path / "context"
    state_root.mkdir()
    external = tmp_path / "external-checkpoints"
    external.mkdir()
    (state_root / "checkpoints").symlink_to(external, target_is_directory=True)

    with pytest.raises(context_guardian.ContextGuardianError, match="directory"):
        context_guardian.observe(
            session_id="session-guardian-checkpoint-link",
            used_tokens=45,
            context_limit=100,
            at_coherent_milestone=True,
            summary=["Checkpoint should remain inside state root."],
            next_step="Continue verification.",
            state_root=state_root,
            handoff_root=tmp_path / "handoffs",
        )

    assert list(external.iterdir()) == []


def test_record_compaction_rejects_symlinked_checkpoint_directory(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "context"
    context_guardian.observe(
        session_id="session-guardian-checkpoint-read-link",
        used_tokens=65,
        context_limit=100,
        at_coherent_milestone=True,
        summary=["Checkpoint must remain local."],
        next_step="Continue verification.",
        state_root=state_root,
        handoff_root=tmp_path / "handoffs",
    )
    checkpoint_root = state_root / "checkpoints"
    external = tmp_path / "external-checkpoints"
    checkpoint_root.replace(external)
    checkpoint_root.symlink_to(external, target_is_directory=True)

    with pytest.raises(context_guardian.ContextGuardianError, match="directory"):
        context_guardian.record_compaction(
            session_id="session-guardian-checkpoint-read-link",
            state_root=state_root,
            handoff_root=tmp_path / "handoffs",
        )


def test_record_compaction_rejects_fabricated_checkpoint_state(tmp_path: Path) -> None:
    state_root = tmp_path / "context"
    context_guardian.observe(
        session_id="session-guardian-fabricated",
        used_tokens=45,
        context_limit=100,
        at_coherent_milestone=False,
        summary=["Checkpoint content."],
        next_step="Continue verification.",
        state_root=state_root,
        handoff_root=tmp_path / "handoffs",
    )
    state_path = state_root / "session-guardian-fabricated.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["checkpoint_path"] = str(tmp_path / "fabricated.json")
    state["last_action"] = "COMPACT_NOW"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(context_guardian.ContextGuardianError, match="checkpoint"):
        context_guardian.record_compaction(
            session_id="session-guardian-fabricated", state_root=state_root
        )


def test_record_compaction_rejects_sensitive_checkpoint_content(tmp_path: Path) -> None:
    state_root = tmp_path / "context"
    context_guardian.observe(
        session_id="session-guardian-sensitive",
        used_tokens=65,
        context_limit=100,
        at_coherent_milestone=True,
        summary=["Safe checkpoint."],
        next_step="Continue verification.",
        state_root=state_root,
        handoff_root=tmp_path / "handoffs",
    )
    checkpoint_path = state_root / "checkpoints" / "session-guardian-sensitive.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["summary"] = ["safe checkpoint\ninjected"]
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises(context_guardian.ContextGuardianError, match="sensitive"):
        context_guardian.record_compaction(
            session_id="session-guardian-sensitive",
            state_root=state_root,
            handoff_root=tmp_path / "handoffs",
        )


def test_record_compaction_rejects_unsafe_checkpoint_timestamp(tmp_path: Path) -> None:
    state_root = tmp_path / "context"
    context_guardian.observe(
        session_id="session-guardian-timestamp",
        used_tokens=65,
        context_limit=100,
        at_coherent_milestone=True,
        summary=["Safe checkpoint."],
        next_step="Continue verification.",
        state_root=state_root,
        handoff_root=tmp_path / "handoffs",
    )
    checkpoint_path = state_root / "checkpoints" / "session-guardian-timestamp.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["observed_at"] = "2026-08-31T22:30:00Z\ninjected"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises(context_guardian.ContextGuardianError, match="sensitive"):
        context_guardian.record_compaction(
            session_id="session-guardian-timestamp",
            state_root=state_root,
            handoff_root=tmp_path / "handoffs",
        )
