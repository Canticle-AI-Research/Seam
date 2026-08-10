"""`seam improve cycle` CLI wiring (self-probe path, no external dataset)."""

from __future__ import annotations

import json

import pytest

from seam_runtime.cli import build_parser, run_cli


def test_improve_cycle_self_probe_propose_only(tmp_path, capsys):
    db = str(tmp_path / "s.db")
    run_cli(["--db", db, "compile-nl",
             "Backups run nightly in the west datacenter. Priya owns the billing service."])
    capsys.readouterr()  # drop ingest output

    run_cli(["--db", db, "improve", "cycle", "--probe-sample", "6", "--probe-budget", "5"])
    report = json.loads(capsys.readouterr().out)

    assert "self_probe" in report["baseline"]
    assert report["applied"] is False  # propose-only default
    # tiny corpus -> no free headroom -> proposes nothing (the honest watchdog)
    assert report["proposed"] is None


def test_improve_cycle_db_after_subcommand(tmp_path, capsys):
    db = str(tmp_path / "s.db")
    run_cli(["--db", db, "compile-nl", "The release train ships every other Friday."])
    capsys.readouterr()

    # --db given AFTER the subcommand must also work
    run_cli(["improve", "cycle", "--db", db, "--probe-sample", "4", "--probe-budget", "5"])
    report = json.loads(capsys.readouterr().out)
    assert "self_probe" in report["baseline"]


def test_improve_cycle_parser_exposes_cat_floors_and_adjudication():
    args = build_parser().parse_args(
        [
            "improve",
            "cycle",
            "--cat1-floor",
            "0.81",
            "--cat3-floor",
            "0.82",
            "--adjudication-overlay",
            "/tmp/overlay.json",
        ]
    )
    assert args.cat1_floor == 0.81
    assert args.cat3_floor == 0.82
    assert args.adjudication_overlay == "/tmp/overlay.json"


def test_improve_cycle_parser_exposes_experiment_bounds():
    args = build_parser().parse_args(
        [
            "improve",
            "cycle",
            "--experiment-label",
            "nightly retrieval policy",
            "--max-candidates",
            "12",
        ]
    )
    assert args.experiment_label == "nightly retrieval policy"
    assert args.max_candidates == 12
    defaults = build_parser().parse_args(["improve", "cycle"])
    assert defaults.max_candidates is None


@pytest.mark.parametrize("max_candidates", [-1, 0, 129])
def test_improve_cycle_rejects_invalid_candidate_bound(
    tmp_path, capsys, max_candidates
):
    run_cli(
        [
            "--db",
            str(tmp_path / "s.db"),
            "improve",
            "cycle",
            "--max-candidates",
            str(max_candidates),
        ]
    )
    assert json.loads(capsys.readouterr().out) == {
        "error": "--max-candidates must be within [1, 128]"
    }


@pytest.mark.parametrize("max_candidates", [1, 128])
def test_improve_cycle_accepts_candidate_boundaries(
    tmp_path, capsys, max_candidates
):
    run_cli(
        [
            "--db",
            str(tmp_path / "s.db"),
            "improve",
            "cycle",
            "--probe-sample",
            "1",
            "--probe-budget",
            "1",
            "--max-candidates",
            str(max_candidates),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert "error" not in report, report
    assert report["experiment_recorded"] is True
    assert isinstance(report["experiment_id"], str)
    assert report["n_candidates"] == min(
        max_candidates, report["candidate_space_count"]
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["improve", "experiments", "--verify"], "--verify requires --id"),
        (["improve", "experiments", "--limit", "0"], "--limit must be at least 1"),
    ],
)
def test_improve_experiments_rejects_invalid_argument_combinations(
    arguments, message, capsys
):
    with pytest.raises(SystemExit, match="2"):
        run_cli(arguments)
    assert message in capsys.readouterr().err


def test_improve_experiments_lists_and_verifies_cycle(tmp_path, capsys):
    db = str(tmp_path / "experiments.db")
    run_cli(
        [
            "--db",
            db,
            "compile-nl",
            "The release train ships every other Friday.",
        ]
    )
    capsys.readouterr()
    run_cli(
        [
            "--db",
            db,
            "improve",
            "cycle",
            "--probe-sample",
            "4",
            "--probe-budget",
            "5",
        ]
    )
    cycle = json.loads(capsys.readouterr().out)

    run_cli(["--db", db, "improve", "experiments"])
    [summary] = json.loads(capsys.readouterr().out)
    assert summary["experiment_id"] == cycle["experiment_id"]
    assert summary["status"] == "completed"

    run_cli(
        [
            "--db",
            db,
            "improve",
            "experiments",
            "--id",
            cycle["experiment_id"],
            "--verify",
        ]
    )
    detail = json.loads(capsys.readouterr().out)
    assert detail["verification"]["valid"] is True
    assert detail["events"][0]["event_kind"] == "started"


def test_improve_cycle_rejects_overlay_without_answer_quality_scorer(
    tmp_path, capsys
):
    run_cli(
        [
            "--db",
            str(tmp_path / "s.db"),
            "improve",
            "cycle",
            "--adjudication-overlay",
            str(tmp_path / "overlay.json"),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert "requires --locomo-dataset" in report["error"]


def test_improve_cycle_rejects_out_of_range_category_floor(tmp_path, capsys):
    run_cli(
        [
            "--db",
            str(tmp_path / "s.db"),
            "improve",
            "cycle",
            "--cat1-floor",
            "1.01",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert report == {"error": "--cat1-floor must be within [0, 1]"}


def test_graph_cycle_rejects_mixed_non_graph_scorers(tmp_path, capsys):
    run_cli(
        [
            "--db",
            str(tmp_path / "s.db"),
            "improve",
            "cycle",
            "--graph-probe-sample",
            "10",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert "--probe-sample 0" in report["error"]
