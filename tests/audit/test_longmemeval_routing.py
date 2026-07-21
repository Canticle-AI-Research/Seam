"""Tests for LongMemEval dataset routing and dry-run validation."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _make_minimal_longmemeval_dataset():
    """Build a minimal LongMemEval-shaped dataset for validation testing."""
    return [
        {
            "sample_id": "lme-1",
            "conversation": [
                {"speaker": "user", "text": "I need to schedule a meeting for next Tuesday at 3pm."},
                {"speaker": "assistant", "text": "I've added that to your calendar."},
            ],
            "qa": [
                {"question": "When is the meeting?", "answer": "Tuesday at 3pm", "category": "information_extraction"},
                {"question": "Did the assistant confirm?", "answer": "Yes, added to calendar", "category": "multi_session_reasoning"},
            ],
        },
        {
            "sample_id": "lme-2",
            "conversation": [
                {"speaker": "user", "text": "My birthday is March 15."},
                {"speaker": "user", "text": "Actually, I was wrong — it's March 16."},
            ],
            "qa": [
                {"question": "When is the user's birthday now?", "answer": "March 16", "category": "knowledge_updates"},
            ],
        },
    ]


class TestLongMemEvalRouting:
    def test_dry_run_validates_dataset_shape(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_make_minimal_longmemeval_dataset(), f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.longmemeval.run",
                 "--dataset-path", tmp_path, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(result.stdout)
            assert report["mode"] == "dry-run"
            assert report["case_count"] == 3
            assert "information_extraction" in report["categories"]
            assert "knowledge_updates" in report["categories"]
            assert isinstance(report["fixture_hash"], str)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_missing_dataset_errors_cleanly(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.longmemeval.run",
             "--dataset-path", "/nonexistent/longmemeval.json", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_expected_500_questions_warning(self):
        """Report issues when case count != 500."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_make_minimal_longmemeval_dataset(), f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.longmemeval.run",
                 "--dataset-path", tmp_path, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(result.stdout)
            assert report["case_count"] == 3
            assert report["valid"] is False  # not 500 questions
            assert len(report["validation_issues"]) > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_missing_categories_reported(self):
        """Missing expected categories are listed."""
        dataset = [{
            "sample_id": "lme-single",
            "conversation": [{"speaker": "user", "text": "Hello."}],
            "qa": [{"question": "What was said?", "answer": "Hello", "category": "information_extraction"}],
        }]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dataset, f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.longmemeval.run",
                 "--dataset-path", tmp_path, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(result.stdout)
            assert len(report["missing_categories"]) >= 4
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_seam_cli_routes_longmemeval_dataset_dry_run(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_make_minimal_longmemeval_dataset(), f)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "seam", "bench", "external", "longmemeval",
                    "--dataset-path", tmp_path, "--dry-run", "--format", "json",
                ],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode != 2, result.stderr
            report = json.loads(result.stdout)
            assert report["mode"] == "dry-run"
            assert report["case_count"] == 3
            assert report["valid"] is False
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_official_cleaned_shape_parses_question_records(self):
        from benchmarks.external.longmemeval.run import _load_longmemeval_cases

        dataset = [
            {
                "question_id": "q-1",
                "question_type": "temporal-reasoning",
                "question": "What happened first?",
                "answer": "The car service",
                "question_date": "2023/04/20 (Thu) 10:00",
                "haystack_session_ids": ["session-1"],
                "answer_session_ids": ["session-1"],
                "haystack_dates": ["2023/04/10 (Mon) 17:50"],
                "haystack_sessions": [[
                    {"role": "user", "content": "I got my car serviced first."},
                    {"role": "assistant", "content": "Good to hear."},
                ]],
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dataset, f)
            tmp_path = f.name

        try:
            cases = _load_longmemeval_cases(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert len(cases) == 1
        assert cases[0].case_id == "q-1"
        assert cases[0].category == "temporal-reasoning"
        assert cases[0].gold_answer == "The car service"
        assert cases[0].conversation[0].speaker == "user"
        assert cases[0].metadata["question_date"] == "2023/04/20 (Thu) 10:00"
        assert cases[0].metadata["answer_session_ids"] == ("session-1",)

    def test_official_abstention_marker_is_preserved_without_relabeling_type(self, tmp_path):
        from benchmarks.external.longmemeval.run import _load_longmemeval_cases

        dataset_path = tmp_path / "longmemeval.json"
        dataset_path.write_text(json.dumps([{
            "question_id": "q-abs_abs",
            "question_type": "single-session-user",
            "question": "What instrument did I buy?",
            "answer": "The information provided is not enough",
            "question_date": "2023/04/20 (Thu) 10:00",
            "haystack_session_ids": ["session-1"],
            "haystack_dates": ["2023/04/10 (Mon) 17:50"],
            "haystack_sessions": [[
                {"role": "user", "content": "I listened to some music."},
                {"role": "assistant", "content": "That sounds relaxing."},
            ]],
            "answer_session_ids": [],
        }]), encoding="utf-8")

        case = _load_longmemeval_cases(str(dataset_path))[0]

        assert case.category == "single-session-user"
        assert case.metadata["is_abstention"] is True

    def test_official_session_date_mismatch_fails_closed(self, tmp_path):
        from benchmarks.external.longmemeval.run import _load_longmemeval_cases

        dataset_path = tmp_path / "longmemeval.json"
        dataset_path.write_text(json.dumps([{
            "question_id": "q-bad",
            "question_type": "single-session-user",
            "question": "What did I say?",
            "answer": "A fact",
            "haystack_session_ids": ["session-1"],
            "haystack_dates": [],
            "haystack_sessions": [[{"role": "user", "content": "A fact"}]],
        }]), encoding="utf-8")

        try:
            _load_longmemeval_cases(str(dataset_path))
        except ValueError as exc:
            assert "dates/session count mismatch" in str(exc)
        else:
            raise AssertionError("malformed official dataset was accepted")

    def test_real_execution_refuses_generic_local_scorer(self, tmp_path):
        dataset_path = tmp_path / "longmemeval.json"
        dataset_path.write_text(json.dumps(_make_minimal_longmemeval_dataset()), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.external.longmemeval.run",
                "--dataset-path",
                str(dataset_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert "local generic scorer is intentionally disabled" in result.stderr
