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


def test_inference_policy_alone_does_not_enable_set_completion():
    prompt = build_answer_prompt(
        "Which activities did Ana mention?",
        "[Ana] hiking\n[Ana] chess",
        inference_policy=INFERENCE_HIGH_CONFIDENCE_V1,
    )
    assert "one high-confidence interpretation" in prompt
    assert "complete supported set" not in prompt
    assert "complete supported answer" not in prompt
    assert "Reply with a concise answer" in prompt


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


def test_adjudication_overlay_rejects_unknown_case_id(tmp_path):
    path = tmp_path / "unknown.json"
    path.write_text(
        json.dumps(
            {
                "schema": ADJUDICATION_SCHEMA,
                "version": "v1",
                "cases": [
                    {
                        "case_id": "missing",
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
    with pytest.raises(ValueError, match="unknown case ids.*missing"):
        scorer.score(None)


# ---- temporal/1 + conversation/2 (HISTORY#386-record-driven levers) ----------


def test_temporal_policy_off_default_prompt_is_byte_identical():
    locked = build_answer_prompt("When did it happen?", "[Ana 2 May 2023] ctx")
    explicit_off = build_answer_prompt(
        "When did it happen?", "[Ana 2 May 2023] ctx", temporal_policy="off"
    )
    assert explicit_off == locked


def test_temporal_policy_directive_resolves_relative_dates():
    prompt = build_answer_prompt(
        "When did Melanie paint the sunrise?",
        "[Melanie 1:56 pm on 8 May, 2023] I painted that lake sunrise last year!",
        temporal_policy="temporal/1",
    )
    assert "bracketed prefix is the timestamp" in prompt
    assert "Resolve relative time expressions" in prompt
    assert "resolved event time, not the time of the message" in prompt
    assert "compute the duration from the resolved event times" in prompt
    # temporal grounding alone must not enable conversation projection or
    # world-knowledge inference
    assert "EVIDENCE|" not in prompt
    assert "one high-confidence interpretation" not in prompt
    # context bytes preserved (conversation adapter stays off)
    assert "[Melanie 1:56 pm on 8 May, 2023] I painted that lake sunrise last year!" in prompt


def test_temporal_policy_composes_with_conversation_and_inference():
    prompt = build_answer_prompt(
        "When did Ana start the class?",
        "[Ana 13 March 2023] Started my yoga class last Friday.",
        conversation_adapter=CONVERSATION_ADAPTER_V1,
        inference_policy=INFERENCE_HIGH_CONFIDENCE_V1,
        temporal_policy="temporal/1",
    )
    assert "Scan every EVIDENCE row" in prompt
    assert "Resolve relative time expressions" in prompt
    assert "one high-confidence interpretation" in prompt


def test_unknown_temporal_policy_fails_closed():
    with pytest.raises(ValueError, match="unknown temporal policy"):
        build_answer_prompt("q", "ctx", temporal_policy="temporal/99")


def test_conversation_v2_widens_set_detection_without_changing_v1():
    # Real miss shapes from the 2026-07-13 holdout record: perfect-tense
    # experience questions and generic plural category nouns.
    for question in (
        "What has Melanie painted?",
        "Which countries has Deborah traveled to?",
        "What musical artists has Melanie seen?",
    ):
        assert (
            classify_conversation_intent(question, adapter_version="conversation/1")
            == ConversationIntent.DIRECT
        ), question
        assert (
            classify_conversation_intent(question, adapter_version="conversation/2")
            == ConversationIntent.SET_COMPLETION
        ), question
    # v1 detections stay detections under v2
    assert (
        classify_conversation_intent(
            "Which books did Maya mention?", adapter_version="conversation/2"
        )
        == ConversationIntent.SET_COMPLETION
    )
    # plain direct questions stay direct under v2
    assert (
        classify_conversation_intent("When is the meeting?", adapter_version="conversation/2")
        == ConversationIntent.DIRECT
    )


def test_conversation_v2_intent_classifier_rejects_unknown_version():
    with pytest.raises(ValueError, match="unknown conversation adapter"):
        classify_conversation_intent("q", adapter_version="conversation/99")


def test_conversation_v1_directive_is_byte_stable():
    # conversation/2 must not change what conversation/1 renders: the v1
    # set-completion sentence is pinned verbatim.
    from seam_runtime.conversation import answer_method_directive

    directive = answer_method_directive(
        ConversationIntent.SET_COMPLETION,
        conversation_adapter=CONVERSATION_ADAPTER_V1,
    )
    assert (
        "Return the complete supported set; do not stop after the first match."
        in directive
    )
    assert "re-check the evidence" not in directive


def test_conversation_v2_set_directive_requires_exhaustive_sweep():
    prompt = build_answer_prompt(
        "What are Melanie's pets' names?",
        "[Melanie] Luna\n[Melanie] Oliver\n[Melanie] Bailey",
        conversation_adapter="conversation/2",
    )
    assert "SEAM-CONV/2|intent=set-completion" in prompt
    assert "separate turns far apart" in prompt
    assert "re-check the evidence" in prompt
    assert "full deduplicated set" in prompt


def test_conversation_v2_view_header_and_evidence_match_v1_projection():
    context = "[Ana 2026-01-01] Hiking\n[Ben] Chess\n[Ana 2026-01-01] Hiking\n"
    adapted_v1, _ = adapt_conversation_context(
        "Which activities were mentioned?", context, version=CONVERSATION_ADAPTER_V1
    )
    adapted_v2, intent = adapt_conversation_context(
        "Which activities were mentioned?", context, version="conversation/2"
    )
    assert intent == ConversationIntent.SET_COMPLETION
    # identical evidence projection, only the header version differs
    assert adapted_v2.replace("SEAM-CONV/2", "SEAM-CONV/1") == adapted_v1


# ---- conversation/3 + temporal/2 (HISTORY#391-record-driven levers) ----------


def test_conversation_v3_keeps_v2_scan_and_detection():
    # same wider detection as v2
    assert (
        classify_conversation_intent("What has Melanie painted?", adapter_version="conversation/3")
        == ConversationIntent.SET_COMPLETION
    )
    prompt = build_answer_prompt(
        "What are Melanie's pets' names?",
        "[Melanie] Luna\n[Melanie] Oliver\n[Melanie] Bailey",
        conversation_adapter="conversation/3",
    )
    assert "SEAM-CONV/3|intent=set-completion" in prompt
    assert "separate turns far apart" in prompt  # v2 sweep retained


def test_conversation_v3_bare_answer_output_contract():
    prompt = build_answer_prompt(
        "What are Melanie's pets' names?",
        "[Melanie] Luna\n[Melanie] Oliver",
        conversation_adapter="conversation/3",
    )
    assert "no numbering, no headers" in prompt
    assert "Never restate the question" in prompt
    assert "Reply with only the answer itself, no preamble." in prompt
    # applies to direct questions too (verbosity tax also hit cat4)
    direct = build_answer_prompt(
        "When is the meeting?",
        "[Ana] The meeting is Friday.",
        conversation_adapter="conversation/3",
    )
    assert "state only the answer itself" in direct
    assert "Reply with only the answer itself, no preamble." in direct


def test_conversation_v2_prompt_unchanged_by_v3_addition():
    # v2 is a validated configuration (0.7689 record); it must not inherit the
    # v3 output contract.
    prompt = build_answer_prompt(
        "What are Melanie's pets' names?",
        "[Melanie] Luna\n[Melanie] Oliver",
        conversation_adapter="conversation/2",
    )
    assert "no numbering, no headers" not in prompt
    assert "Reply with the complete supported answer, no preamble." in prompt


def test_temporal_v2_adds_instance_disambiguation_on_top_of_v1():
    v2 = build_answer_prompt(
        "When did Sam's friends mock him?",
        "[Sam 27 July 2023] They mocked me last Friday.\n[Sam 20 October 2023] It happened again.",
        temporal_policy="temporal/2",
    )
    assert "Resolve relative time expressions" in v2  # v1 core retained
    assert "list each candidate event with its resolved date" in v2
    assert "Never default to the first or most prominent mention" in v2
    v1 = build_answer_prompt(
        "When did Sam's friends mock him?",
        "[Sam 27 July 2023] They mocked me last Friday.",
        temporal_policy="temporal/1",
    )
    assert "list each candidate event" not in v1  # temporal/1 stays byte-stable


# ---- conversation/4 cardinality constraint (HISTORY#392-record-driven) --------


def test_conversation_v4_precision_clause_and_natural_output():
    prompt = build_answer_prompt(
        "What are Melanie's pets' names?",
        "[Melanie] Luna\n[Melanie] Oliver\n[Melanie] Bailey",
        conversation_adapter="conversation/4",
    )
    assert "SEAM-CONV/4|intent=set-completion" in prompt
    assert "separate turns far apart" in prompt          # v2 exhaustive scan retained
    assert "DIRECTLY answers the specific question" in prompt
    assert "do NOT add items that are merely related" in prompt
    assert "neither omitting a responsive one nor padding" in prompt
    # v4 must NOT inherit v3's regressed terse-format contract
    assert "no numbering, no headers" not in prompt
    assert "Reply with the complete supported answer, no preamble." in prompt


def test_conversation_v4_uses_wide_set_detection():
    for q in ("What has Melanie painted?", "Which countries has Deborah traveled to?"):
        assert (
            classify_conversation_intent(q, adapter_version="conversation/4")
            == ConversationIntent.SET_COMPLETION
        ), q


def test_conversation_v2_and_v3_unchanged_by_v4():
    # v2 is the validated 0.7689 champion; its directive must stay byte-stable.
    v2 = build_answer_prompt("What are Melanie's pets' names?", "[Melanie] Luna",
                             conversation_adapter="conversation/2")
    assert "return the full deduplicated set" in v2
    assert "DIRECTLY answers" not in v2
    # v3 keeps its (parked) terse contract, not the v4 precision clause
    v3 = build_answer_prompt("What are Melanie's pets' names?", "[Melanie] Luna",
                             conversation_adapter="conversation/3")
    assert "no numbering, no headers" in v3
    assert "neither omitting a responsive one" not in v3
