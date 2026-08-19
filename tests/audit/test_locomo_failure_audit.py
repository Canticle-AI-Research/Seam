from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from benchmarks.external.locomo.audit import (
    _classify,
    _context_format_kind,
    run_audit,
    run_context_replay,
    write_markdown,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_result_case(case_id, context_recall=0.0, answer_em=0.0, answer_f1=0.0,
                       prediction="unknown", judge_verdict="incorrect",
                       judge_score=0.0, judge_rationale="", category="1") -> dict:
    case = {
        "case_id": case_id,
        "category": category,
        "scores": {
            "context_recall": context_recall,
            "answer_em": answer_em,
            "answer_f1": answer_f1,
        },
        "retrieval_latency_ms": 100.0,
        "answer_latency_ms": 200.0,
        "_prediction": prediction,
    }
    if judge_verdict is not None:
        case["judge"] = {
            "verdict": judge_verdict,
            "score": judge_score,
            "rationale": judge_rationale,
            "judge_name": "openai",
            "judge_model": "gpt-5-nano",
        }
    return case


def _make_result_json(cases: list[dict], scores_override: dict | None = None) -> dict:
    scores = scores_override or {
        "context_recall_mean": 0.5,
        "answer_em_mean": 0.1,
        "answer_f1_mean": 0.1,
        "judge_score_mean": 0.3,
        "judge_count": len(cases),
        "correct_count": 0,
        "partial_count": 0,
        "incorrect_count": len(cases),
        "per_category": {},
    }
    return {
        "version": "1",
        "benchmark": "locomo",
        "adapter": "seam",
        "dataset": {"source": "/tmp/ds.json", "case_count": len(cases)},
        "run_started_at": "2026-01-01T00:00:00Z",
        "elapsed_seconds": 100.0,
        "scores": scores,
        "cases": cases,
        "integrity_hash": "abc123",
    }


def _make_dataset_item(sample_id, qa_pairs):
    """qa_pairs: list of (question, answer, category) tuples."""
    conversation = {
        "session_1": [{"speaker": "A", "text": "hello"}],
        "session_1_date_time": "2023-01-01",
    }
    return {
        "sample_id": sample_id,
        "conversation": conversation,
        "qa": [{"question": q, "answer": a, "category": c} for q, a, c in qa_pairs],
        "event_summary": "",
        "observation": "",
        "session_summary": "",
    }


def _write_dataset_json(items: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(items, f)
    return path


def _write_result_json(result: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(result, f)
    return path


def test_context_replay_closes_its_owned_adapter(monkeypatch, tmp_path):
    """Audit replay deterministically releases its temporary runtime root."""

    from benchmarks.external.locomo.adapters import seam as seam_adapter_module

    closed: list[bool] = []

    class _Adapter:
        def __init__(self, *, answerer):
            assert answerer is None

        def close(self):
            closed.append(True)

    monkeypatch.setattr(seam_adapter_module, "SeamLocomoAdapter", _Adapter)
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps({"cases": []}), encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")

    assert run_context_replay(str(result_path), str(dataset_path)) == []
    with pytest.raises(FileNotFoundError):
        run_context_replay(
            str(tmp_path / "missing-result.json"),
            str(dataset_path),
        )
    assert closed == [True, True]


# ---------------------------------------------------------------------------
# bucket classification
# ---------------------------------------------------------------------------

def test_classify_zero_recall():
    assert _classify(_make_result_case("a", context_recall=0.0)) == "zero_recall"


def test_classify_low_recall():
    assert _classify(_make_result_case("a", context_recall=0.1)) == "low_recall"
    assert _classify(_make_result_case("a", context_recall=0.05)) == "low_recall"
    assert _classify(_make_result_case("a", context_recall=0.19)) == "low_recall"


def test_classify_medium_recall():
    assert _classify(_make_result_case("a", context_recall=0.3)) == "medium_recall"
    assert _classify(_make_result_case("a", context_recall=0.5)) == "medium_recall"
    assert _classify(_make_result_case("a", context_recall=0.79)) == "medium_recall"


def test_classify_high_recall():
    assert _classify(_make_result_case("a", context_recall=0.8,
                                        prediction="some answer")) == "high_recall"
    assert _classify(_make_result_case("a", context_recall=1.0,
                                        prediction="Paris")) == "high_recall"


def test_classify_high_recall_unknown():
    assert _classify(_make_result_case("a", context_recall=0.9,
                                        prediction="unknown")) == "high_recall_unknown"
    assert _classify(_make_result_case("a", context_recall=1.0,
                                        prediction="unknown")) == "high_recall_unknown"


# ---------------------------------------------------------------------------
# unknown prediction counting
# ---------------------------------------------------------------------------

def test_unknown_count():
    result = _make_result_json([
        _make_result_case("a", prediction="unknown"),
        _make_result_case("b", prediction="Paris"),
        _make_result_case("c", prediction="unknown"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q1", "A1", "1"), ("Q2", "A2", "2"), ("Q3", "A3", "3")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["prediction_distribution"].get("unknown") == 2
    assert audit["prediction_distribution"].get("Paris") == 1


# ---------------------------------------------------------------------------
# judge error counting
# ---------------------------------------------------------------------------

def test_judge_error_counting():
    result = _make_result_json([
        _make_result_case("a", prediction="x", judge_verdict="correct", judge_score=1.0),
        _make_result_case("b", prediction="y", judge_verdict="incorrect", judge_score=0.0),
    ])
    # Override case b to have a judge error
    result["cases"][1]["judge"] = {"error": "judge returned invalid verdict"}

    ds = [_make_dataset_item("conv-1", [("Q1", "A1", "1"), ("Q2", "A2", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["judge_error_count"] == 1
    assert "b" in audit["judge_error_case_ids"]


def test_judge_none_counting():
    result = _make_result_json([
        _make_result_case("a", prediction="x", judge_verdict=None),
    ])
    result["cases"][0]["judge"] = None
    ds = [_make_dataset_item("conv-1", [("Q1", "A1", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["judge_error_count"] == 1


# ---------------------------------------------------------------------------
# missing / extra / duplicate case IDs
# ---------------------------------------------------------------------------

def test_missing_case_ids():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
        _make_result_case("conv-1::q2", prediction="y"),
    ])
    # Dataset only has q0 and q1
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1"), ("Q1", "A1", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    # conv-1::q2 is in result but not in dataset
    assert "conv-1::q2" in audit["missing_from_dataset"]
    # conv-1::q1 is in dataset but not in result
    assert "conv-1::q1" in audit["extra_in_result"]


def test_duplicate_case_ids():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
        _make_result_case("conv-1::q0", prediction="y"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert "conv-1::q0" in audit["duplicate_ids"]


def test_no_integrity_issues():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
        _make_result_case("conv-1::q1", prediction="y"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1"), ("Q1", "A1", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["missing_from_dataset"] == []
    assert audit["extra_in_result"] == []
    assert audit["duplicate_ids"] == []


# ---------------------------------------------------------------------------
# markdown output
# ---------------------------------------------------------------------------

def test_markdown_contains_sections():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="Paris", judge_verdict="correct",
                           judge_score=1.0, judge_rationale="matches"),
        _make_result_case("conv-1::q1", prediction="unknown", judge_verdict="incorrect",
                           judge_score=0.0, judge_rationale="no answer"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1"), ("Q1", "A1", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)

    fd, md_path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    write_markdown(audit, md_path)
    with open(md_path) as f:
        md = f.read()

    assert "# LoCoMo Baseline Audit" in md
    assert "## Dataset / Source Integrity" in md
    assert "## Score Summary" in md
    assert "## Category Summary" in md
    assert "## Prediction Distribution" in md
    assert "## Bucket Counts" in md
    assert "## Sample:" in md
    assert "## Key Findings" in md
    assert "Paris" in md
    assert "unknown" in md


def test_markdown_judge_errors_section():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x", judge_verdict="correct", judge_score=1.0),
    ])
    result["cases"][0]["judge"] = {"error": "judge returned invalid verdict"}
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)

    fd, md_path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    write_markdown(audit, md_path)
    with open(md_path) as f:
        md = f.read()
    assert "## Judge Errors" in md
    assert "conv-1::q0" in md


def test_context_snippets_detected_when_present():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
    ])
    result["cases"][0]["retrieved_context"] = "some context text"
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["context_snippets_present"] is True


def test_context_snippets_detected_as_missing():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["context_snippets_present"] is False


def test_context_snippets_detected_via_context_field():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
    ])
    result["cases"][0]["context"] = "some context from alternate key"
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["context_snippets_present"] is True


# ---------------------------------------------------------------------------
# case-insensitive unknown counting
# ---------------------------------------------------------------------------

def test_unknown_ci_count():
    result = _make_result_json([
        _make_result_case("a", prediction="unknown"),
        _make_result_case("b", prediction="Unknown"),
        _make_result_case("c", prediction="UNKNOWN"),
        _make_result_case("d", prediction="Paris"),
    ])
    ds = [_make_dataset_item("conv-1", [
        ("Q0", "A0", "1"), ("Q1", "A1", "2"), ("Q2", "A2", "3"), ("Q3", "A3", "4"),
    ])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["unknown_ci_count"] == 3


def test_unknown_ci_count_none():
    result = _make_result_json([
        _make_result_case("a", prediction="Paris"),
        _make_result_case("b", prediction="London"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1"), ("Q1", "A1", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["unknown_ci_count"] == 0


# ---------------------------------------------------------------------------
# fixture hash
# ---------------------------------------------------------------------------

def test_fixture_hash_present():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x"),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert "dataset_fixture_hash" in audit
    assert len(audit["dataset_fixture_hash"]) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# success bucket
# ---------------------------------------------------------------------------

def test_success_bucket_has_non_unknown_high_recall():
    result = _make_result_json([
        _make_result_case("a", prediction="Paris", context_recall=0.9),
        _make_result_case("b", prediction="London", context_recall=1.0),
    ])
    ds = [_make_dataset_item("conv-1", [("Q0", "A0", "1"), ("Q1", "A1", "2")])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["bucket_counts"]["high_recall"] == 2
    assert audit["bucket_counts"]["high_recall_unknown"] == 0


# ---------------------------------------------------------------------------
# context format detection
# ---------------------------------------------------------------------------

def test_context_format_empty():
    assert _context_format_kind("") == "empty"
    assert _context_format_kind("   ") == "empty"


def test_context_format_raw_text():
    assert _context_format_kind("hello world") == "raw_text"


def test_context_format_turn_brackets_not_json():
    """[Speaker timestamp] format must not be classified as JSON."""
    assert _context_format_kind("[Caroline 2:24 pm] Some text here") == "raw_text"
    assert _context_format_kind("[Gina 1:26 pm on 3 April, 2023] Yeah, I have plans") == "raw_text"


def test_context_format_valid_json_is_pack_json():
    assert _context_format_kind('{"key": "value"}') == "pack_json"
    assert _context_format_kind('[{"id": 1}, {"id": 2}]') == "pack_json"


def test_context_format_bracket_not_json():
    """[text] that isn't valid JSON is raw_text."""
    assert _context_format_kind("[not valid json at all") == "raw_text"


# ---------------------------------------------------------------------------
# no network / API dependency
# ---------------------------------------------------------------------------

def test_no_api_client_imports():
    """audit module must not import openai/anthropic clients or their SDKs."""
    import ast

    from benchmarks.external.locomo import audit as audit_mod

    src = Path(audit_mod.__file__).read_text()
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    banned = {"openai", "anthropic"}
    found = banned & imports
    assert not found, f"audit.py imports network APIs: {found}"


# ---------------------------------------------------------------------------
# bucket count correctness
# ---------------------------------------------------------------------------

def test_bucket_counts_add_up():
    result = _make_result_json([
        _make_result_case("conv-1::q0", prediction="x", context_recall=0.0),
        _make_result_case("conv-1::q1", prediction="y", context_recall=0.1),
        _make_result_case("conv-1::q2", prediction="z", context_recall=0.5),
        _make_result_case("conv-1::q3", prediction="w", context_recall=0.85),
        _make_result_case("conv-1::q4", prediction="unknown", context_recall=0.9),
    ])
    ds = [_make_dataset_item("conv-1", [
        ("Q0", "A0", "1"), ("Q1", "A1", "2"), ("Q2", "A2", "3"),
        ("Q3", "A3", "4"), ("Q4", "A4", "5"),
    ])]
    result_path = _write_result_json(result)
    ds_path = _write_dataset_json(ds)
    audit = run_audit(result_path, ds_path)
    assert audit["bucket_counts"] == {
        "zero_recall": 1,
        "low_recall": 1,
        "medium_recall": 1,
        "high_recall": 1,
        "high_recall_unknown": 1,
        "success": 0,
    }
