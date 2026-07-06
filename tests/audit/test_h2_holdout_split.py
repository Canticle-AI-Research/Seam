"""H2 slice 4: deterministic dev/holdout split contract.

Pins the determinism guarantee (same salt + same case_id => same bucket
forever), the idempotent update semantics (new case_ids append; existing
case_ids are never reassigned without an explicit --rewrite), the
salt/ratio change guardrail, and the manifest round-trip shape.
"""

from __future__ import annotations

import json

import pytest

from benchmarks.external.common.dataset import load_quickstart_cases
from tools.h2 import holdout_split as hs


def _quickstart_case_ids() -> list[str]:
    return [c.case_id for c in load_quickstart_cases()]


# ---- assign_one / compute_assignments ----------------------------------------


def test_assign_one_is_deterministic_for_same_salt_and_case_id():
    a = hs.assign_one("conv-1::q0", salt="seam-locomo-v1", ratio=0.8)
    b = hs.assign_one("conv-1::q0", salt="seam-locomo-v1", ratio=0.8)
    assert a == b
    assert a in (hs.DEV, hs.HOLDOUT)


def test_assign_one_differs_under_different_salt_for_at_least_one_case():
    # With distinct salts the bucket boundary shifts; over a 10-case dataset
    # at least one case_id must flip. Pin this so a future refactor that
    # accidentally hard-codes the salt breaks the test.
    case_ids = _quickstart_case_ids()
    a = [hs.assign_one(cid, salt="salt-a", ratio=0.5) for cid in case_ids]
    b = [hs.assign_one(cid, salt="salt-b", ratio=0.5) for cid in case_ids]
    assert a != b


def test_assign_one_rejects_invalid_ratio():
    with pytest.raises(ValueError):
        hs.assign_one("conv-1::q0", salt="s", ratio=0.0)
    with pytest.raises(ValueError):
        hs.assign_one("conv-1::q0", salt="s", ratio=1.0)
    with pytest.raises(ValueError):
        hs.assign_one("conv-1::q0", salt="s", ratio=1.5)


def test_compute_assignments_covers_every_case_id_exactly_once():
    case_ids = _quickstart_case_ids()
    table = hs.compute_assignments(case_ids, salt="seam-locomo-v1", ratio=0.8)
    assert set(table.keys()) == set(case_ids)
    assert all(v in (hs.DEV, hs.HOLDOUT) for v in table.values())


def test_ratio_extremes_bias_buckets_as_expected():
    # ratio very close to 1.0 => almost all dev; very close to 0.0 => almost all holdout.
    case_ids = _quickstart_case_ids()
    high = hs.compute_assignments(case_ids, salt="s", ratio=0.99)
    low = hs.compute_assignments(case_ids, salt="s", ratio=0.01)
    assert sum(1 for v in high.values() if v == hs.DEV) >= len(case_ids) - 1
    assert sum(1 for v in low.values() if v == hs.HOLDOUT) >= len(case_ids) - 1


# ---- SplitAssignment dataclass invariants ------------------------------------


def test_split_assignment_rejects_invalid_ratio():
    with pytest.raises(ValueError):
        hs.SplitAssignment(salt="s", ratio=0.0, dataset_source="quickstart")
    with pytest.raises(ValueError):
        hs.SplitAssignment(salt="s", ratio=1.0, dataset_source="quickstart")


def test_split_assignment_rejects_unknown_split_labels():
    with pytest.raises(ValueError):
        hs.SplitAssignment(
            salt="s", ratio=0.5, dataset_source="quickstart",
            assignments={"conv-1::q0": "train"},
        )


# ---- manifest round-trip -----------------------------------------------------


def test_manifest_round_trips_via_save_and_load(tmp_path):
    case_ids = _quickstart_case_ids()
    table = hs.compute_assignments(case_ids, salt="seam-locomo-v1", ratio=0.8)
    original = hs.SplitAssignment(
        salt="seam-locomo-v1", ratio=0.8,
        dataset_source="quickstart", assignments=table,
    )
    path = tmp_path / "manifest.json"
    hs.save_manifest(path, original)
    loaded = hs.load_manifest(path)
    assert loaded == original


def test_manifest_keys_are_sorted_for_stable_diffs(tmp_path):
    # Inputs intentionally out of order
    assignment = hs.SplitAssignment(
        salt="s", ratio=0.5, dataset_source="quickstart",
        assignments={"z::q0": hs.DEV, "a::q0": hs.HOLDOUT, "m::q0": hs.DEV},
    )
    path = tmp_path / "manifest.json"
    hs.save_manifest(path, assignment)
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert list(blob["assignments"].keys()) == ["a::q0", "m::q0", "z::q0"]


def test_load_manifest_rejects_wrong_schema(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema": "some-other-schema/v0",
        "salt": "s", "ratio": 0.5, "dataset_source": "quickstart", "assignments": {},
    }))
    with pytest.raises(ValueError):
        hs.load_manifest(path)


# ---- helpers -----------------------------------------------------------------


def test_dev_and_holdout_case_id_helpers_are_partitions():
    table = hs.compute_assignments(_quickstart_case_ids(), salt="s", ratio=0.5)
    a = hs.SplitAssignment(salt="s", ratio=0.5, dataset_source="quickstart", assignments=table)
    dev = hs.dev_case_ids(a)
    hold = hs.holdout_case_ids(a)
    assert set(dev).isdisjoint(set(hold))
    assert set(dev) | set(hold) == set(table.keys())


def test_is_holdout_matches_assignment():
    table = {"conv-1::q0": hs.DEV, "conv-2::q0": hs.HOLDOUT}
    a = hs.SplitAssignment(salt="s", ratio=0.5, dataset_source="quickstart", assignments=table)
    assert hs.is_holdout(a, "conv-2::q0") is True
    assert hs.is_holdout(a, "conv-1::q0") is False
    # Unknown case_id is treated as not-holdout (caller must add it first).
    assert hs.is_holdout(a, "unknown::q9") is False


# ---- update_manifest semantics ----------------------------------------------


def test_update_creates_manifest_when_missing(tmp_path):
    manifest = tmp_path / "split.json"
    assignment, report = hs.update_manifest(
        manifest_path=manifest, source="quickstart"
    )
    assert manifest.exists()
    assert assignment.salt == hs.DEFAULT_SALT
    assert assignment.ratio == hs.DEFAULT_RATIO
    assert set(assignment.assignments.keys()) == set(_quickstart_case_ids())
    assert len(report.added) == len(_quickstart_case_ids())
    assert report.dev_count + report.holdout_count == len(_quickstart_case_ids())


def test_update_is_idempotent_for_same_inputs(tmp_path):
    manifest = tmp_path / "split.json"
    a1, _ = hs.update_manifest(manifest_path=manifest, source="quickstart")
    a2, r2 = hs.update_manifest(manifest_path=manifest, source="quickstart")
    assert a1 == a2
    assert r2.added == []  # nothing new
    assert len(r2.existing) == len(_quickstart_case_ids())


def test_update_appends_new_case_ids_without_disturbing_existing(tmp_path):
    """Pretend the dataset grew: simulate by seeding the manifest with a
    subset, then running update against the full quickstart fixture."""
    manifest = tmp_path / "split.json"
    case_ids = _quickstart_case_ids()
    seed = hs.SplitAssignment(
        salt=hs.DEFAULT_SALT, ratio=hs.DEFAULT_RATIO,
        dataset_source="quickstart",
        assignments=hs.compute_assignments(case_ids[:3], salt=hs.DEFAULT_SALT, ratio=hs.DEFAULT_RATIO),
    )
    hs.save_manifest(manifest, seed)
    updated, report = hs.update_manifest(manifest_path=manifest, source="quickstart")

    assert set(report.added) == set(case_ids[3:])
    assert set(report.existing) == set(case_ids[:3])
    # Pre-existing entries are unchanged.
    for cid in case_ids[:3]:
        assert updated.assignments[cid] == seed.assignments[cid]
    assert set(updated.assignments.keys()) == set(case_ids)


def test_update_rejects_salt_change_without_rewrite(tmp_path):
    manifest = tmp_path / "split.json"
    hs.update_manifest(manifest_path=manifest, source="quickstart", salt="salt-a")
    with pytest.raises(ValueError):
        hs.update_manifest(manifest_path=manifest, source="quickstart", salt="salt-b")


def test_update_rejects_ratio_change_without_rewrite(tmp_path):
    manifest = tmp_path / "split.json"
    hs.update_manifest(manifest_path=manifest, source="quickstart", ratio=0.7)
    with pytest.raises(ValueError):
        hs.update_manifest(manifest_path=manifest, source="quickstart", ratio=0.9)


def test_rewrite_flag_recomputes_every_assignment(tmp_path):
    manifest = tmp_path / "split.json"
    first, _ = hs.update_manifest(
        manifest_path=manifest, source="quickstart", salt="salt-a", ratio=0.5
    )
    second, report = hs.update_manifest(
        manifest_path=manifest, source="quickstart", salt="salt-b", ratio=0.5, rewrite=True
    )
    # Same case_ids on both sides, but salt changed -> at least one flips.
    assert set(first.assignments.keys()) == set(second.assignments.keys())
    assert any(
        first.assignments[cid] != second.assignments[cid]
        for cid in first.assignments
    )
    assert report.salt_changed is True
    # Under --rewrite, every case_id is counted as "added" (recomputed).
    assert len(report.added) == len(_quickstart_case_ids())


# ---- CLI ---------------------------------------------------------------------


def test_cli_creates_manifest_and_prints_summary(tmp_path, capsys):
    manifest = tmp_path / "split.json"
    rc = hs.main([
        "--source", "quickstart",
        "--manifest", str(manifest),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert str(manifest) in out
    assert "dev=" in out
    assert "holdout=" in out
    assert manifest.exists()
    loaded = hs.load_manifest(manifest)
    assert set(loaded.assignments.keys()) == set(_quickstart_case_ids())


def test_cli_rejects_salt_change_without_rewrite_flag(tmp_path):
    manifest = tmp_path / "split.json"
    hs.main(["--source", "quickstart", "--manifest", str(manifest), "--salt", "salt-a"])
    with pytest.raises(ValueError):
        hs.main([
            "--source", "quickstart",
            "--manifest", str(manifest),
            "--salt", "salt-b",
        ])
