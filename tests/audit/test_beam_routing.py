"""Tests for BEAM benchmark routing and dry-run validation."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

BEAM_QUESTION_TYPES = (
    "abstention",
    "contradiction_resolution",
    "event_ordering",
    "information_extraction",
    "instruction_following",
    "knowledge_update",
    "multi_session_reasoning",
    "preference_following",
    "summarization",
    "temporal_reasoning",
)


def _make_beam_dataset_dir(base_dir: str, conversation_count: int = 3):
    """Build a minimal BEAM-shaped dataset directory for validation testing."""
    root = Path(base_dir)
    for i in range(conversation_count):
        conv_dir = root / f"conv_{i:04d}"
        conv_dir.mkdir()
        qa_file = conv_dir / "questions.json"
        qa_file.write_text(json.dumps([
            {"question": f"Q{j} for conv {i}", "answer": f"A{j}", "category": "factual"}
            for j in range(5)
        ]))
    return root


def _make_official_local_beam(
    base_dir: Path,
    *,
    conversation_count: int = 1,
    questions_per_type: int = 2,
) -> Path:
    track_root = base_dir / "chats" / "1M"
    for conversation_index in range(1, conversation_count + 1):
        conversation_dir = track_root / str(conversation_index)
        questions_dir = conversation_dir / "probing_questions"
        questions_dir.mkdir(parents=True)
        (conversation_dir / "chat.json").write_text(
            json.dumps(
                [
                    {
                        "batch_number": 1,
                        "time_anchor": "2026-01-01T00:00:00Z",
                        "turns": [
                            [
                                {
                                    "role": "user",
                                    "content": f"Conversation {conversation_index} fact.",
                                    "time_anchor": "2026-01-01T00:00:00Z",
                                },
                                {
                                    "role": "assistant",
                                    "content": "Acknowledged.",
                                },
                            ]
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        probing_questions = {
            question_type: [
                {
                    "question": f"{question_type} question {question_index}?",
                    "answer": f"answer {question_index}",
                    "rubric": [f"State answer {question_index}."],
                }
                for question_index in range(questions_per_type)
            ]
            for question_type in BEAM_QUESTION_TYPES
        }
        (questions_dir / "probing_questions.json").write_text(
            json.dumps(probing_questions),
            encoding="utf-8",
        )
    return track_root


class TestBeamRouting:
    def test_dry_run_scans_dataset_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_beam_dataset_dir(tmp, conversation_count=3)
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.beam.run",
                 "--track", "1m", "--dataset-path", tmp, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(result.stdout)
            assert report["mode"] == "dry-run"
            assert report["conversation_count"] == 3
            assert report["total_questions"] == 15
            assert isinstance(report["fixture_hash"], str)
            assert report["valid"] is False  # not 100 conversations / 2000 questions

    def test_beam_10m_dry_run_reports_missing_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_beam_dataset_dir(tmp, conversation_count=1)
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.beam.run",
                 "--track", "10m", "--dataset-path", tmp, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode != 0
            report = json.loads(result.stdout)
            assert report["expected_conversations"] == 10
            assert report["expected_questions"] == 200

    def test_missing_dataset_directory_errors(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.beam.run",
             "--track", "1m", "--dataset-path", "/nonexistent/beam-dir", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_dry_run_reports_expected_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_beam_dataset_dir(tmp, conversation_count=5)
            result = subprocess.run(
                [sys.executable, "-m", "benchmarks.external.beam.run",
                 "--track", "1m", "--dataset-path", tmp, "--dry-run"],
                capture_output=True, text=True, timeout=30,
            )
            report = json.loads(result.stdout)
            assert report["expected_conversations"] == 35
            assert report["expected_questions"] == 700

    def test_seam_cli_routes_beam_1m_dataset_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_beam_dataset_dir(tmp, conversation_count=3)
            result = subprocess.run(
                [
                    sys.executable, "-m", "seam", "bench", "external", "beam",
                    "--track", "1m", "--dataset-path", tmp, "--dry-run", "--format", "json",
                ],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode != 2, result.stderr
            report = json.loads(result.stdout)
            assert report["mode"] == "dry-run"
            assert report["conversation_count"] == 3
            assert report["valid"] is False

    def test_huggingface_rows_shape_parses_cases(self, tmp_path):
        from benchmarks.external.beam.run import _load_beam_cases

        dataset_path = tmp_path / "beam_rows.json"
        dataset_path.write_text(json.dumps({
            "rows": [
                {
                    "row": {
                        "conversation_id": "conv-1",
                        "chat": [[
                            {"role": "user", "content": "I use Redis for caching.", "time_anchor": "March 1"},
                            {"role": "assistant", "content": "Redis can help reduce latency.", "time_anchor": "March 1"},
                        ]],
                        "probing_questions": repr({
                            "information_extraction": [
                                {
                                    "question": "What do I use for caching?",
                                    "answer": "Redis",
                                    "rubric": ["Response should state Redis."],
                                }
                            ]
                        }),
                    }
                }
            ]
        }), encoding="utf-8")

        cases = _load_beam_cases(dataset_path)

        assert len(cases) == 1
        assert cases[0].case_id == "conv-1::information_extraction::0"
        assert cases[0].category == "information_extraction"
        assert cases[0].gold_answer == "Redis\nRubric:\n- Response should state Redis."
        assert cases[0].conversation[0].text == "I use Redis for caching."
        assert cases[0].metadata["rubric_nuggets"] == ("Response should state Redis.",)

    def test_huggingface_list_root_and_rubric_object_parse(self, tmp_path):
        from benchmarks.external.beam.run import _load_beam_cases

        dataset_path = tmp_path / "beam_rows.json"
        dataset_path.write_text(json.dumps([{
            "conversation_id": "conv-2",
            "chat": [{
                "turns": [[
                    {"role": "user", "content": "I moved to Austin.", "time_anchor": "2025-01-01"},
                    {"role": "assistant", "content": "Welcome to Austin.", "time_anchor": "2025-01-01"},
                ]]
            }],
            "probing_questions": {
                "knowledge_update": [{
                    "question_text": "Where do I live?",
                    "rubric": {"nuggets": [{"description": "State Austin."}]},
                }]
            },
        }]), encoding="utf-8")

        case = _load_beam_cases(dataset_path)[0]

        assert case.question == "Where do I live?"
        assert case.conversation[0].text == "I moved to Austin."
        assert case.metadata["rubric_nuggets"] == ("State Austin.",)

    def test_legacy_directory_cases_are_not_executable(self, tmp_path):
        from benchmarks.external.beam.run import _load_beam_cases

        _make_beam_dataset_dir(str(tmp_path), conversation_count=1)

        try:
            _load_beam_cases(tmp_path, track="1m")
        except ValueError as exc:
            assert "official local BEAM 1M layout not found" in str(exc)
        else:
            raise AssertionError("legacy directory-only BEAM data was accepted for execution")

    def test_official_local_layout_loads_chat_questions_and_rubric(self, tmp_path):
        from benchmarks.external.beam.run import _load_beam_cases

        track_root = _make_official_local_beam(tmp_path)

        cases = _load_beam_cases(track_root)

        assert len(cases) == 20
        assert cases[0].conversation[0].text == "Conversation 1 fact."
        assert cases[0].conversation[0].timestamp == "2026-01-01T00:00:00Z"
        assert cases[0].metadata["dataset_format"] == "official-local-repo"
        assert set(case.category for case in cases) == set(BEAM_QUESTION_TYPES)

    def test_official_local_release_dry_run_validates_full_1m_shape(self, tmp_path):
        _make_official_local_beam(tmp_path, conversation_count=35)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.external.beam.run",
                "--track",
                "1m",
                "--dataset-path",
                str(tmp_path),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["valid"] is True
        assert report["dataset_format"] == "official-local-repo"
        assert report["conversation_count"] == 35
        assert report["total_questions"] == 700
        assert report["total_turns"] == 70
        assert report["source_file_count"] == 70
        assert report["source_root"] == str((tmp_path / "chats" / "1M").resolve())
        assert report["missing_question_types"] == []
        assert report["question_types"] == {
            question_type: 70 for question_type in BEAM_QUESTION_TYPES
        }

    def test_official_local_fixture_hash_is_root_independent(self, tmp_path):
        from benchmarks.external.beam.run import _scan_official_local_dataset

        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        _make_official_local_beam(first_root)
        _make_official_local_beam(second_root)

        first = _scan_official_local_dataset(first_root, "1m")
        second = _scan_official_local_dataset(second_root, "1m")

        assert first["fixture_hash"] == second["fixture_hash"]
        assert len(first["fixture_hash"]) == 64

    def test_official_local_layout_rejects_missing_rubric(self, tmp_path):
        track_root = _make_official_local_beam(tmp_path)
        questions_path = (
            track_root / "1" / "probing_questions" / "probing_questions.json"
        )
        questions = json.loads(questions_path.read_text(encoding="utf-8"))
        questions["abstention"][0]["rubric"] = []
        questions_path.write_text(json.dumps(questions), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.external.beam.run",
                "--track",
                "1m",
                "--dataset-path",
                str(tmp_path),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert "has no rubric nuggets" in result.stderr

    def test_official_local_layout_distinguishes_missing_questions_from_empty_chat(
        self,
        tmp_path,
    ):
        track_root = _make_official_local_beam(tmp_path)
        questions_path = (
            track_root / "1" / "probing_questions" / "probing_questions.json"
        )
        questions_path.write_text("{}", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.external.beam.run",
                "--track",
                "1m",
                "--dataset-path",
                str(tmp_path),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert "has no probing questions" in result.stderr
        assert "empty or unsupported chat" not in result.stderr

    def test_real_execution_refuses_generic_local_scorer(self):
        result = subprocess.run(
            [sys.executable, "-m", "benchmarks.external.beam.run", "--track", "1m"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode != 0
        assert "local generic scorer is intentionally disabled" in result.stderr
