from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_dataset(path: Path, sample_count: int = 3) -> None:
    rows = []
    for idx in range(sample_count):
        rows.append(
            {
                "sample_id": f"conv-{idx}",
                "conversation": {
                    "sessions": [
                        {
                            "date_time": "2026-06-01",
                            "dialogs": [
                                {
                                    "speaker": "Alice",
                                    "text": f"Conversation {idx} fact is teal.",
                                }
                            ],
                        }
                    ]
                },
                "qa": [
                    {
                        "question": f"What color is conversation {idx}?",
                        "answer": "teal",
                        "category": 1,
                    }
                ],
            }
        )
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_builds_first_scope_slice_and_paid_plan(tmp_path: Path) -> None:
    from tools.benchmarks.rung_c_paid import build_plan, write_scope_slice

    dataset = tmp_path / "locomo.json"
    slice_path = tmp_path / "slice.json"
    out_dir = tmp_path / "runs"
    _write_dataset(dataset, sample_count=3)

    summary = write_scope_slice(dataset, slice_path, scope_count=2)
    plan = build_plan(
        dataset_path=dataset,
        slice_path=slice_path,
        output_dir=out_dir,
        adapters=("seam", "mem0"),
        mem0_search_limit=32,
    )

    sliced = json.loads(slice_path.read_text(encoding="utf-8"))
    assert summary == {"scope_count": 2, "case_count": 2}
    assert [row["sample_id"] for row in sliced] == ["conv-0", "conv-1"]
    assert plan["paid_required"] is True
    assert plan["commands"]["seam"][0:3] == [
        sys.executable,
        "-m",
        "benchmarks.external.locomo.run",
    ]
    assert "--search-top-k" in plan["commands"]["seam"]
    assert "300" in plan["commands"]["seam"]
    assert "--context-budget" in plan["commands"]["seam"]
    assert "60000" in plan["commands"]["seam"]
    assert "--mem0-search-limit" in plan["commands"]["mem0"]
    assert "32" in plan["commands"]["mem0"]


def test_cli_prints_json_plan_without_paid_execution(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo.json"
    out_dir = tmp_path / "runs"
    _write_dataset(dataset, sample_count=2)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.benchmarks.rung_c_paid",
            "--dataset-path",
            str(dataset),
            "--output-dir",
            str(out_dir),
            "--scopes",
            "1",
            "--mem0-search-limit",
            "64",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["execute"] is False
    assert report["slice"]["scope_count"] == 1
    assert set(report["commands"]) == {"seam", "mem0"}
    assert "--confirm-paid" in report["operator_gate"]


def test_execute_requires_confirm_paid_unless_benchmark_dry_run(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo.json"
    _write_dataset(dataset, sample_count=1)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.benchmarks.rung_c_paid",
            "--dataset-path",
            str(dataset),
            "--output-dir",
            str(tmp_path / "runs"),
            "--execute",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--confirm-paid" in result.stderr
