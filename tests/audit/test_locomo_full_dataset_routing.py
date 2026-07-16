"""Tests for full LoCoMo dataset routing and dry-run validation."""
import json
import subprocess
import sys
from pathlib import Path

QUICKSTART_PATH = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "external" / "locomo" / "fixtures" / "quickstart.json"


class TestLoCoMoFullDatasetRouting:
    def test_quickstart_dry_run_validates_categories(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Dry-run failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["mode"] == "dry-run"
        assert report["case_count"] == 10
        assert report["valid"] is True  # quickstart uses numeric synthetic categories
        fh = report["fixture_hash"]
        assert isinstance(fh, str) and len(fh) == 64
        # Numeric synthetic categories (1, 2) should not produce validation errors
        assert len(report["validation_issues"]) == 0

    def test_dry_run_reports_fixture_hash(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        report = json.loads(result.stdout)
        fh1 = report["fixture_hash"]
        result2 = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        report2 = json.loads(result2.stdout)
        assert fh1 == report2["fixture_hash"], "Fixture hash should be deterministic"

    def test_dry_run_reports_category_counts(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        report = json.loads(result.stdout)
        cats = report["categories"]
        assert len(cats) > 0, "Expected category breakdown"
        total = sum(cats.values())
        assert total == report["case_count"]

    def test_missing_dataset_path_errors_cleanly(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--dataset-path", "/nonexistent/path/locomo.json", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr.lower()

    def test_dry_run_estimates_judge_calls(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run", "--judge", "stub"],
            capture_output=True, text=True, timeout=30,
        )
        report = json.loads(result.stdout)
        assert report["estimated_judge_calls"] == 0  # stub judge is not counted

    def test_dry_run_outputs_valid_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        report = json.loads(result.stdout)
        required_keys = ["dataset_path", "case_count", "categories", "fixture_hash", "mode"]
        for key in required_keys:
            assert key in report, f"Missing key: {key}"

    def test_full_dataset_json_validation(self):
        """Validate that the quickstart fixture passes category checks when used as --dataset-path."""
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run",
             "--dataset-path", str(QUICKSTART_PATH), "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Dry-run via --dataset-path failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["case_count"] == 10
        # Synthetic numeric categories accepted; no validation errors
        assert len(report["validation_issues"]) == 0

    def test_official_locomo_session_numbered_format(self, tmp_path):
        dataset_path = tmp_path / "locomo-official-shape.json"
        dataset_path.write_text(json.dumps([
            {
                "sample_id": "sample-1",
                "conversation": {
                    "speaker_a": "Caroline",
                    "speaker_b": "Melanie",
                    "session_1_date_time": "1:56 pm on 8 May, 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "I visited the support group on 7 May."},
                        {"speaker": "Melanie", "dia_id": "D1:2", "text": "That sounds meaningful."},
                    ],
                    "session_2_date_time": "1:14 pm on 25 May, 2023",
                    "session_2": [
                        {"speaker": "Caroline", "dia_id": "D2:1", "text": "I started a new art class."},
                    ],
                },
                "qa": [
                    {
                        "question": "When did Caroline visit the support group?",
                        "answer": "7 May",
                        "category": 2,
                    }
                ],
            }
        ]), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, "-m", "benchmarks.external.locomo.run",
                "--dataset-path", str(dataset_path), "--dry-run",
            ],
            capture_output=True, text=True, timeout=30,
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["mode"] == "dry-run"
        assert report["case_count"] == 1
        assert report["valid"] is True

    def test_official_locomo_answerless_adversarial_rows_are_skipped(self, tmp_path):
        dataset_path = tmp_path / "locomo-adversarial-shape.json"
        dataset_path.write_text(json.dumps([
            {
                "sample_id": "sample-1",
                "conversation": {
                    "session_1_date_time": "1:56 pm on 8 May, 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "I visited the support group on 7 May."},
                    ],
                },
                "qa": [
                    {
                        "question": "When did Caroline visit the support group?",
                        "answer": "7 May",
                        "category": 2,
                    },
                    {
                        "question": "What did Caroline realize after her charity race?",
                        "adversarial_answer": "self-care is important",
                        "category": 5,
                    },
                ],
            }
        ]), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, "-m", "benchmarks.external.locomo.run",
                "--dataset-path", str(dataset_path), "--dry-run",
            ],
            capture_output=True, text=True, timeout=30,
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["case_count"] == 1
        assert report["valid"] is True

    def test_official_locomo_scalar_answers_are_normalized_to_strings(self, tmp_path):
        from benchmarks.external.common.dataset import load_locomo_cases

        dataset_path = tmp_path / "locomo-scalar-answer.json"
        dataset_path.write_text(json.dumps([
            {
                "sample_id": "sample-1",
                "conversation": {
                    "session_1": [
                        {"speaker": "Caroline", "text": "I have visited Paris 3 times."},
                    ],
                },
                "qa": [
                    {
                        "question": "How many times has Caroline visited Paris?",
                        "answer": 3,
                        "category": 2,
                    },
                ],
            }
        ]), encoding="utf-8")

        cases = load_locomo_cases(dataset_path)

        assert cases[0].gold_answer == "3"

    def test_seam_cli_routes_locomo_dataset_dry_run(self):
        result = subprocess.run(
            [
                sys.executable, "-m", "seam", "bench", "external", "locomo",
                "--dataset-path", str(QUICKSTART_PATH), "--dry-run", "--format", "json",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["mode"] == "dry-run"
        assert report["case_count"] == 10


class TestLoCoMoSplitFlag:
    """--split must reproduce the exact dev/holdout partition used by
    ``seam improve validate`` (tools.h2.holdout_split, default salt/ratio),
    so comparator adapters are scored on the same cases as SEAM holdout runs."""

    def _dry_run(self, *extra):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.locomo.run",
             "--quickstart", "--dry-run", *extra],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Dry-run failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_split_partitions_cases_exactly(self):
        from benchmarks.external.locomo.run import load_quickstart_cases
        from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, assign_one

        all_report = self._dry_run()
        dev_report = self._dry_run("--split", "dev")
        holdout_report = self._dry_run("--split", "holdout")
        assert dev_report["case_count"] + holdout_report["case_count"] == all_report["case_count"]

        cases = load_quickstart_cases()
        expected_holdout = sum(
            1 for c in cases
            if assign_one(c.case_id, salt=DEFAULT_SALT, ratio=DEFAULT_RATIO) == "holdout"
        )
        assert holdout_report["case_count"] == expected_holdout

    def test_split_applies_before_limit(self):
        holdout_total = self._dry_run("--split", "holdout")["case_count"]
        limited = self._dry_run("--split", "holdout", "--limit", "1")
        assert limited["case_count"] == min(1, holdout_total)

    def test_split_default_is_all(self):
        assert self._dry_run()["case_count"] == self._dry_run("--split", "all")["case_count"]
