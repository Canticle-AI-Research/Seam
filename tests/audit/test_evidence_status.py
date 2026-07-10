"""Measurement-integrity regression tests for the conservative evidence
classifier (``scoring.evidence_status`` + ``run_record.classify_failure_conservative``).

The crude ``context_recall`` overlap mislabels correct "unknown" refusals as
answerer failures. Each case below is pinned to a real, documented false
positive from the 2026-07-09 cat1/cat3 DeepSeek holdout run (private records, not
committed) so the conservative classifier provably flips it without touching the
v1 ``context_recall`` / ``classify_failure`` fields (which stay recorded for
comparability). No network, no spend.
"""
from __future__ import annotations

from benchmarks.external.common.run_record import (
    RunRecord,
    classify_failure,
    classify_failure_conservative,
)
from benchmarks.external.common.scoring import (
    EVIDENCE_CLASSIFIER_VERSION,
    content_tokens,
    evidence_status,
    is_open_domain_category,
)


def test_version_pinned():
    assert EVIDENCE_CLASSIFIER_VERSION == "evidence/1"


def test_content_tokens_drops_generic():
    # dates, bare numbers, and yes/no fillers are not distinctive evidence
    assert content_tokens("19 October 2023") == []
    assert content_tokens("Yes") == []
    assert content_tokens("2023") == []
    # real content survives
    assert content_tokens("Voyageurs National Park") == ["voyageurs", "national", "park"]


def test_date_false_positive_is_uncertain_not_answerer_miss():
    """conv-26::q76: gold '19 October 2023', v1 context_recall=0.67 (because
    'october'/'2023' appear elsewhere in a 46k-char context) -> v1 answerer_miss.
    Conservative: the gold has no distinctive content tokens -> uncertain."""
    ctx = "We went on a hike back in october. Earlier in 2023 we moved house."
    status, rationale = evidence_status(ctx, "19 October 2023", category="1")
    assert status == "uncertain"
    assert "distinctive" in rationale
    assert classify_failure_conservative("incorrect", status) == "uncertain"
    # v1 still (wrongly) says answerer_miss when handed the crude float -> preserved
    assert classify_failure("incorrect", 0.67) == "answerer_miss"


def test_cat3_open_domain_never_retrieval_or_answerer_miss():
    """conv-43::q28 ('Harry Potter theme composer' -> 'John Williams') and
    conv-44::q44 ('Voyageurs National Park') are cat3 world-knowledge questions:
    gold-token overlap is not a retrieval signal, regardless of context."""
    for gold in ("John Williams", "Voyageurs National Park", "Connecticut"):
        status, _ = evidence_status("irrelevant context", gold, category="3")
        assert status == "open_domain"
        assert classify_failure_conservative("incorrect", status) == "open_domain_inference"
    # 'cat3' label form is accepted too
    assert is_open_domain_category("cat3")
    assert is_open_domain_category("3")
    assert not is_open_domain_category("1")


def test_yes_gold_false_positive():
    """conv-50::q7: gold 'Yes', context_recall=1.0 as a pure false positive.
    As cat3 -> open_domain; even as a non-cat3 the filler token yields uncertain."""
    assert evidence_status("anything at all", "Yes", category="3")[0] == "open_domain"
    assert evidence_status("anything at all", "Yes", category="1")[0] == "uncertain"


def test_single_common_name_is_weak_not_present():
    """A bare first name fully present in context is too weak to confirm evidence
    (documented 'john' generic false positive) -> uncertain, not answerer_miss."""
    status, _ = evidence_status("John said hello to everyone at the party.", "John", category="1")
    assert status == "uncertain"
    assert classify_failure_conservative("incorrect", status) == "uncertain"


def test_present_strong_stays_answerer_miss():
    """conv-41::q21: gold 'Pacific northwest, east coast' is genuinely present in
    context -> the retrieval attribution is answerer_miss (the score being wrong
    is a gold-incompleteness/judge issue, deliberately NOT reclassified here)."""
    ctx = "We drove up the pacific northwest and later the east coast for a wedding."
    status, _ = evidence_status(ctx, "Pacific northwest, east coast", category="1")
    assert status == "present"
    assert classify_failure_conservative("incorrect", status) == "answerer_miss"


def test_multi_token_gold_scattered_across_turns_is_uncertain():
    """A multi-token gold must not be 'present' merely because its words appear
    in unrelated turns. LoCoMo packs one turn per line; co-occurrence is required."""
    scattered = (
        "[Amy 9:00 am] I love swimming at the lake every summer.\n"
        "[Ben 10:00 am] The national museum downtown was closed for repairs.\n"
        "[Amy 11:00 am] We took the kids to a park by the river.\n"
    )
    # 'national' (turn 2) and 'park' (turn 3) never share a turn -> uncertain
    status, rationale = evidence_status(scattered, "national park", category="1")
    assert status == "uncertain"
    assert "scattered" in rationale
    assert classify_failure_conservative("incorrect", status) == "uncertain"

    # ... but co-located in a single turn IS present
    colocated = "[Amy 9:00 am] We hiked in the national park all afternoon.\n"
    status2, _ = evidence_status(colocated, "national park", category="1")
    assert status2 == "present"
    assert classify_failure_conservative("incorrect", status2) == "answerer_miss"


def test_absent_evidence_is_retrieval_miss():
    ctx = "Today's weather report mentions rain and a cold front."
    status, _ = evidence_status(ctx, "Voyageurs lakeshore trail", category="1")
    assert status == "absent"
    assert classify_failure_conservative("incorrect", status) == "retrieval_miss"


def test_correct_and_abstain_short_circuit():
    assert classify_failure_conservative("correct", "absent") == "answered_correct"
    assert classify_failure_conservative("abstain", "present") == "abstained"


def test_record_captures_conservative_fields_alongside_v1():
    """add_case records the conservative attribution AND preserves the v1
    fields; totals expose both count maps + the classifier version."""
    rec = RunRecord()
    # a date false-positive case: crude context_recall is high (v1 answerer_miss)
    # but the conservative classifier calls it uncertain.
    rec.add_case(
        case_id="c1", scope="conv-26", category="1", arm="a",
        question="When did John go on his hike after the road trip?",
        gold_answer="19 October 2023",
        raw_answer="unknown",
        verdict="incorrect", judge_score=0.0, judge_rationale="wrong",
        judge_model="stub",
        retrieved_context="We hiked in october. Back in 2023 we moved.",
        context_recall=0.67,
    )
    c = rec.cases[0]
    # v1 preserved
    assert c["context_recall"] == 0.67
    assert c["failure_class"] == "answerer_miss"
    # conservative added
    assert c["evidence_status"] == "uncertain"
    assert c["failure_class_conservative"] == "uncertain"
    assert c["evidence_classifier_version"] == EVIDENCE_CLASSIFIER_VERSION

    totals = rec.to_dict()["totals"]
    assert totals["failure_class_counts"] == {"answerer_miss": 1}
    assert totals["failure_class_conservative_counts"] == {"uncertain": 1}
    assert totals["evidence_status_counts"] == {"uncertain": 1}
    assert totals["evidence_classifier_version"] == EVIDENCE_CLASSIFIER_VERSION
