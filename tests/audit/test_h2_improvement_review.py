"""H2 slice 5: improvement proposal store + validation gate.

Pins the append-only contract (proposal body never edited; decisions append
never replace), the holdout-violation check against slice-4 manifests, the
status filtering on listing, the "no autonomous protocol writes" guardrail
(via API surface inspection), the promotion-blocking semantics, and the
CLI smoke for propose / list / show / approve / reject / summary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seam_runtime.improvement import (
    VALID_KINDS,
    VALID_STATUSES,
    proposal_blocks_promotion,
    validate_proposal,
)
from seam_runtime.storage import SQLiteStore
from tools.h2 import holdout_split as hs
from tools.h2 import improvement_review as ir


def _store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "h2.db")


def _quickstart_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "split.json"
    hs.update_manifest(manifest_path=manifest, source="quickstart")
    return manifest


def _holdout_pick(manifest_path: Path) -> str:
    return hs.holdout_case_ids(hs.load_manifest(manifest_path))[0]


def _dev_pick(manifest_path: Path) -> str:
    return hs.dev_case_ids(hs.load_manifest(manifest_path))[0]


# ---- storage: schema + write/iter --------------------------------------------


def test_tables_and_indexes_present(tmp_path):
    store = _store(tmp_path)
    with store._connect() as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert "improvement_proposal" in tables
        assert "proposal_decision" in tables
        idx = {row[0] for row in conn.execute("select name from sqlite_master where type='index'")}
        assert "idx_improvement_proposal_kind" in idx
        assert "idx_improvement_proposal_violation" in idx
        assert "idx_proposal_decision_proposal" in idx


def test_write_proposal_creates_pending_decision(tmp_path):
    store = _store(tmp_path)
    pid = store.write_improvement_proposal(
        kind="ranking_weight",
        summary="bump lexical weight",
        rationale="dev set recall dip on lexical-heavy queries",
        evidence_case_ids=["conv-1::q0"],
    )
    assert pid >= 1
    decisions = store.iter_proposal_decisions(pid)
    assert len(decisions) == 1
    assert decisions[0]["status"] == "pending"


def test_proposal_row_round_trips_all_fields(tmp_path):
    store = _store(tmp_path)
    pid = store.write_improvement_proposal(
        kind="ranking_weight",
        summary="bump lexical",
        rationale="dev recall dip",
        evidence_event_ids=[1, 2, 3],
        evidence_case_ids=["conv-1::q0", "conv-2::q1"],
        proposed_change={"weights": {"lexical": 0.55}, "tokenizer": "tiktoken"},
        holdout_violation=False,
        extra={"trace": "session-abc"},
    )
    [row] = store.iter_improvement_proposals()
    assert row["proposal_id"] == pid
    assert row["kind"] == "ranking_weight"
    assert row["summary"] == "bump lexical"
    assert row["evidence_event_ids"] == [1, 2, 3]
    assert row["evidence_case_ids"] == ["conv-1::q0", "conv-2::q1"]
    assert row["proposed_change"]["weights"]["lexical"] == 0.55
    assert row["extra"] == {"trace": "session-abc"}
    assert row["holdout_violation"] is False
    assert row["latest_status"] == "pending"


def test_required_fields_rejected_when_missing(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.write_improvement_proposal(kind="", summary="x")
    with pytest.raises(ValueError):
        store.write_improvement_proposal(kind="ranking_weight", summary="")


# ---- storage: append-only contract -------------------------------------------


def test_no_update_or_delete_methods_for_proposals(tmp_path):
    """Append-only by absence: no API exists to mutate a proposal row."""
    store = _store(tmp_path)
    for name in (
        "update_improvement_proposal",
        "delete_improvement_proposal",
        "purge_improvement_proposals",
        "edit_improvement_proposal",
        "delete_proposal_decision",
        "update_proposal_decision",
    ):
        assert not hasattr(store, name), f"SQLiteStore should not expose {name}"


def test_decisions_append_does_not_replace(tmp_path):
    store = _store(tmp_path)
    pid = store.write_improvement_proposal(kind="other", summary="trial")
    store.record_proposal_decision(proposal_id=pid, status="approved", reason="ok", actor="op")
    store.record_proposal_decision(proposal_id=pid, status="rejected", reason="undo", actor="op")
    decisions = store.iter_proposal_decisions(pid)
    # pending + approved + rejected, oldest first.
    assert [d["status"] for d in decisions] == ["pending", "approved", "rejected"]
    assert store.latest_proposal_status(pid)["status"] == "rejected"


def test_record_decision_rejects_unknown_status(tmp_path):
    store = _store(tmp_path)
    pid = store.write_improvement_proposal(kind="other", summary="x")
    with pytest.raises(ValueError):
        store.record_proposal_decision(proposal_id=pid, status="maybe")


def test_record_decision_rejects_unknown_proposal(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.record_proposal_decision(proposal_id=9999, status="approved")


# ---- storage: filtering ------------------------------------------------------


def test_status_filter_uses_latest_decision(tmp_path):
    store = _store(tmp_path)
    p1 = store.write_improvement_proposal(kind="ranking_weight", summary="a")
    p2 = store.write_improvement_proposal(kind="ranking_weight", summary="b")
    p3 = store.write_improvement_proposal(kind="schema_change", summary="c")
    store.record_proposal_decision(proposal_id=p2, status="approved")
    store.record_proposal_decision(proposal_id=p3, status="rejected")

    pending = store.iter_improvement_proposals(status="pending")
    assert [p["proposal_id"] for p in pending] == [p1]
    approved = store.iter_improvement_proposals(status="approved")
    assert [p["proposal_id"] for p in approved] == [p2]
    rejected = store.iter_improvement_proposals(status="rejected")
    assert [p["proposal_id"] for p in rejected] == [p3]

    assert store.count_improvement_proposals(status="pending") == 1
    assert store.count_improvement_proposals(status="approved") == 1


def test_kind_and_violation_filters(tmp_path):
    store = _store(tmp_path)
    store.write_improvement_proposal(kind="ranking_weight", summary="a", holdout_violation=False)
    store.write_improvement_proposal(kind="ranking_weight", summary="b", holdout_violation=True)
    store.write_improvement_proposal(kind="schema_change", summary="c")
    assert store.count_improvement_proposals(kind="ranking_weight") == 2
    assert store.count_improvement_proposals(holdout_violation=True) == 1
    assert store.count_improvement_proposals(holdout_violation=False) == 2


# ---- validation: holdout check ----------------------------------------------


def test_validate_proposal_clean_dev_case_passes(tmp_path):
    manifest = _quickstart_manifest(tmp_path)
    dev_case = _dev_pick(manifest)
    report = validate_proposal(
        kind="ranking_weight",
        summary="dev-only change",
        evidence_case_ids=[dev_case],
        holdout_assignment=hs.load_manifest(manifest),
    )
    assert report.holdout_violation is False
    assert report.holdout_case_ids == []


def test_validate_proposal_holdout_case_flags_violation(tmp_path):
    manifest = _quickstart_manifest(tmp_path)
    hold_case = _holdout_pick(manifest)
    report = validate_proposal(
        kind="ranking_weight",
        summary="touches holdout",
        evidence_case_ids=[hold_case],
        holdout_assignment=hs.load_manifest(manifest),
    )
    assert report.holdout_violation is True
    assert report.holdout_case_ids == [hold_case]


def test_validate_proposal_warns_on_unknown_case_ids(tmp_path):
    manifest = _quickstart_manifest(tmp_path)
    report = validate_proposal(
        kind="ranking_weight",
        summary="cites unknown case",
        evidence_case_ids=["bogus::q0"],
        holdout_assignment=hs.load_manifest(manifest),
    )
    assert report.holdout_violation is False
    assert any("not in holdout manifest" in w for w in report.warnings)


def test_validate_proposal_warns_on_unknown_kind():
    report = validate_proposal(kind="weird_thing", summary="x")
    assert any("conventional set" in w for w in report.warnings)


def test_validate_proposal_no_manifest_skips_check():
    """Without a holdout manifest the validator can still run for shape
    warnings, but it cannot decide violation -> defaults to False."""
    report = validate_proposal(
        kind="ranking_weight",
        summary="no manifest",
        evidence_case_ids=["conv-1::q0"],
    )
    assert report.holdout_violation is False


# ---- promotion gate ----------------------------------------------------------


def test_promotion_blocked_until_approved_and_violation_clear():
    pending = {"holdout_violation": False, "latest_status": "pending"}
    approved_clean = {"holdout_violation": False, "latest_status": "approved"}
    approved_violation = {"holdout_violation": True, "latest_status": "approved"}
    rejected = {"holdout_violation": False, "latest_status": "rejected"}
    assert proposal_blocks_promotion(pending) is True
    assert proposal_blocks_promotion(approved_clean) is False
    assert proposal_blocks_promotion(approved_violation) is True
    assert proposal_blocks_promotion(rejected) is True


# ---- "no autonomous protocol writes" guardrail -------------------------------


def test_cli_workflow_does_not_create_protocol_files(tmp_path):
    """Slice 5 must not write to AGENTS.md / REPO_LEDGER.md / PROJECT_STATUS.md.

    Drive the full CLI workflow inside a tmp dir and assert no such file
    exists afterward. Docstrings mentioning those names are fine; what we
    care about is that the runtime never creates them.
    """
    db = tmp_path / "h2.db"
    manifest = _quickstart_manifest(tmp_path)

    # Run every mutating subcommand at least once.
    ir.main([
        "propose", "--db", str(db),
        "--kind", "ranking_weight",
        "--summary", "smoke",
        "--evidence-cases", _dev_pick(manifest),
        "--holdout-manifest", str(manifest),
        "--json",
    ])
    ir.main(["approve", "--db", str(db), "1", "--json"])
    ir.main(["reject", "--db", str(db), "1", "--json"])
    ir.main(["list", "--db", str(db), "--json"])
    ir.main(["show", "--db", str(db), "1"])
    ir.main(["summary", "--db", str(db), "--json"])

    for name in ("AGENTS.md", "REPO_LEDGER.md", "PROJECT_STATUS.md"):
        assert not (tmp_path / name).exists(), (
            f"slice 5 wrote {name} into the working dir; this is a protocol-file violation"
        )


def test_valid_kinds_and_statuses_are_documented():
    assert "ranking_weight" in VALID_KINDS
    assert "other" in VALID_KINDS
    for s in ("pending", "approved", "rejected", "superseded"):
        assert s in VALID_STATUSES


# ---- CLI ---------------------------------------------------------------------


def test_cli_propose_writes_proposal_and_reports_violation(tmp_path, capsys):
    manifest = _quickstart_manifest(tmp_path)
    hold_case = _holdout_pick(manifest)
    db = tmp_path / "h2.db"
    rc = ir.main([
        "propose",
        "--db", str(db),
        "--kind", "ranking_weight",
        "--summary", "tries to use holdout case",
        "--rationale", "test",
        "--evidence-cases", hold_case,
        "--holdout-manifest", str(manifest),
        "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["proposal_id"] >= 1
    assert out["holdout_violation"] is True
    assert hold_case in out["holdout_case_ids"]


def test_cli_full_workflow_propose_list_show_approve_reject(tmp_path, capsys):
    db = tmp_path / "h2.db"
    # propose
    ir.main([
        "propose", "--db", str(db),
        "--kind", "ranking_weight",
        "--summary", "tune lexical weight",
        "--rationale", "dev recall low",
        "--evidence-events", "1,2,3",
        "--evidence-cases", "conv-1::q0",
        "--proposed-change-json", json.dumps({"weights": {"lexical": 0.55}}),
        "--json",
    ])
    pid = json.loads(capsys.readouterr().out)["proposal_id"]

    # list pending
    ir.main(["list", "--db", str(db), "--status", "pending", "--json"])
    lst = json.loads(capsys.readouterr().out)
    assert any(p["proposal_id"] == pid for p in lst)

    # approve
    ir.main([
        "approve", "--db", str(db), str(pid),
        "--reason", "looks good", "--actor", "operator", "--json",
    ])
    appr = json.loads(capsys.readouterr().out)
    assert appr["status"] == "approved"

    # show -> latest_status approved, blocks_promotion False
    ir.main(["show", "--db", str(db), str(pid)])
    show = json.loads(capsys.readouterr().out)
    assert show["proposal"]["latest_status"] == "approved"
    assert show["blocks_promotion"] is False
    assert [d["status"] for d in show["decisions"]] == ["pending", "approved"]

    # reject reverses; both decisions stay in audit trail
    ir.main(["reject", "--db", str(db), str(pid), "--reason", "second thoughts", "--json"])
    capsys.readouterr()
    ir.main(["show", "--db", str(db), str(pid)])
    show2 = json.loads(capsys.readouterr().out)
    assert show2["proposal"]["latest_status"] == "rejected"
    assert show2["blocks_promotion"] is True
    assert [d["status"] for d in show2["decisions"]] == ["pending", "approved", "rejected"]


def test_cli_show_returns_nonzero_for_unknown_id(tmp_path, capsys):
    db = tmp_path / "h2.db"
    SQLiteStore(db)  # initialize tables
    rc = ir.main(["show", "--db", str(db), "9999"])
    assert rc != 0


def test_cli_summary_reports_counts(tmp_path, capsys):
    db = tmp_path / "h2.db"
    store = SQLiteStore(db)
    p1 = store.write_improvement_proposal(kind="ranking_weight", summary="a")
    store.write_improvement_proposal(kind="schema_change", summary="b", holdout_violation=True)
    store.record_proposal_decision(proposal_id=p1, status="approved")

    ir.main(["summary", "--db", str(db), "--json"])
    summary = json.loads(capsys.readouterr().out)
    assert summary["total"] == 2
    assert summary["by_status"]["approved"] == 1
    assert summary["by_status"]["pending"] == 1
    assert summary["holdout_violations"] == 1
    # p1 approved + clean => not blocking; p2 pending + violation => blocking
    assert summary["blocking_promotion"] == 1
