from __future__ import annotations

import json

import pytest

from benchmarks.external.common.adjudication import (
    ADJUDICATION_SCHEMA,
    AdjudicatedScorer,
    load_adjudication_overlay,
)
from benchmarks.external.common.answerer import build_answer_prompt
from seam_runtime.conversation import (
    CONVERSATION_ADAPTER_V1,
    INFERENCE_HIGH_CONFIDENCE_V1,
    ConversationIntent,
    adapt_conversation_context,
    classify_conversation_intent,
)
from seam_runtime.self_improve import ScoreReport


def test_intent_classifier_detects_set_completion_and_inference():
    assert classify_conversation_intent("Which books did Maya mention?") == ConversationIntent.SET_COMPLETION
    assert classify_conversation_intent("How many exercises does John do?") == ConversationIntent.SET_COMPLETION
    assert classify_conversation_intent("What city is she likely describing?") == ConversationIntent.INFERENCE
    assert classify_conversation_intent("When is the meeting?") == ConversationIntent.DIRECT


def test_conversation_view_preserves_evidence_and_removes_only_exact_duplicates():
    context = "[Ana 2026-01-01] Hiking\n[Ben] Chess\n[Ana 2026-01-01] Hiking\n"
    adapted, intent = adapt_conversation_context(
        "Which activities were mentioned?",
        context,
        version=CONVERSATION_ADAPTER_V1,
    )
    assert intent == ConversationIntent.SET_COMPLETION
    assert "SEAM-CONV/1|intent=set-completion|evidence_count=2" in adapted
    assert "EVIDENCE|1|[Ana 2026-01-01] Hiking" in adapted
    assert "EVIDENCE|2|[Ben] Chess" in adapted
    assert adapted.count("[Ana 2026-01-01] Hiking") == 1


def test_conversation_view_preserves_significant_line_whitespace():
    adapted, _ = adapt_conversation_context(
        "What happened?",
        "  indented evidence  \n",
        version=CONVERSATION_ADAPTER_V1,
    )
    assert "EVIDENCE|1|  indented evidence  " in adapted


def test_adapter_off_is_byte_identical():
    context = "  exact context bytes\nsecond line  "
    adapted, _ = adapt_conversation_context("What happened?", context)
    assert adapted == context


def test_versioned_prompt_requires_complete_set_and_bounded_inference():
    prompt = build_answer_prompt(
        "Which activities did Ana mention?",
        "[Ana] hiking\n[Ana] chess",
        conversation_adapter=CONVERSATION_ADAPTER_V1,
        inference_policy=INFERENCE_HIGH_CONFIDENCE_V1,
    )
    assert "Scan every EVIDENCE row" in prompt
    assert "complete supported set" in prompt
    assert "one high-confidence interpretation" in prompt
    assert "rather than guess" in prompt


def test_unknown_policy_fails_closed():
    with pytest.raises(ValueError, match="unknown conversation adapter"):
        build_answer_prompt("q", "ctx", conversation_adapter="future/99")


class _RawScorer:
    name = "raw"
    profile_safe = True
    answer_policy_safe = True

    def score(self, runtime, flags=None):  # noqa: ARG002
        return ScoreReport(
            scorer=self.name,
            aggregate=0.5,
            n=2,
            per_category={"cat1": 0.5},
            per_case={"a": 0.0, "b": 1.0},
        )


def test_adjudication_overlay_keeps_raw_and_corrected_views_separate(tmp_path):
    path = tmp_path / "overlay.json"
    path.write_text(
        json.dumps(
            {
                "schema": ADJUDICATION_SCHEMA,
                "version": "private-review/1",
                "cases": [
                    {
                        "case_id": "a",
                        "category": "cat1",
                        "score": 1.0,
                        "disposition": "gold-defect",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scorer = AdjudicatedScorer(
        _RawScorer(),
        load_adjudication_overlay(path),
        category_by_case={"a": "cat1", "b": "cat1"},
    )
    corrected = scorer.score(None)
    assert scorer.last_raw_report.aggregate == 0.5
    assert scorer.last_views == {
        "raw": scorer.last_raw_report,
        "adjudicated": corrected,
    }
    assert corrected.scorer == "raw:adjudicated:private-review/1"
    assert corrected.aggregate == 1.0
    assert corrected.per_category == {"cat1": 1.0}


def test_adjudication_overlay_rejects_duplicate_case_ids(tmp_path):
    path = tmp_path / "bad.json"
    case = {"case_id": "a", "category": "cat1", "score": 1, "disposition": "gold-defect"}
    path.write_text(
        json.dumps({"schema": ADJUDICATION_SCHEMA, "version": "v1", "cases": [case, case]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_adjudication_overlay(path)


def test_adjudication_overlay_rejects_category_mismatch(tmp_path):
    path = tmp_path / "mismatch.json"
    path.write_text(
        json.dumps(
            {
                "schema": ADJUDICATION_SCHEMA,
                "version": "v1",
                "cases": [
                    {
                        "case_id": "a",
                        "category": "3",
                        "score": 1.0,
                        "disposition": "gold-defect",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    scorer = AdjudicatedScorer(
        _RawScorer(),
        load_adjudication_overlay(path),
        category_by_case={"a": "1", "b": "1"},
    )
    with pytest.raises(ValueError, match="category mismatch"):
        scorer.score(None)
