"""`seam improve cycle` CLI wiring (self-probe path, no external dataset)."""

from __future__ import annotations

import json

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
