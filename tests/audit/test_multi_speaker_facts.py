"""Unit tests for the DRAFT broadened multi-speaker grounded fact contract.

These pin the precision guards that let the contract take mem0's recall breadth
(named third-party facts) while keeping SEAM's grounding daylight: a fact may
name a third party, but only one literally present in its cited source sentence,
never via pronoun coreference and never a fabricated name.
"""

from __future__ import annotations

from seam_runtime.multi_speaker_facts import (
    declarative_evidence,
    validate_multi_speaker_fact,
    validate_multi_speaker_fact_with_reason,
)
from seam_runtime.sentence_grounded_facts import first_person_declarative_evidence


def _validate(fact: str, *, speaker: str, source: str, index: int = 0):
    return validate_multi_speaker_fact_with_reason(
        {"fact": fact, "evidence_sentence_index": index},
        speaker=speaker,
        source_text=source,
    )


def test_accepts_named_third_party_fact() -> None:
    # The live first-person contract refuses this; the broadened one keeps it.
    source = "My daughter Sara loves painting."
    fact, reason = _validate("Sara loves painting", speaker="John", source=source)
    assert reason is None
    assert fact is not None
    assert fact.evidence_sentence == source


def test_accepts_first_person_rebased_fact() -> None:
    fact, reason = _validate("John loves surfing", speaker="John", source="I love surfing.")
    assert reason is None
    assert fact is not None


def test_rejects_unresolved_pronoun_subject() -> None:
    # "She" is a coreference SEAM will not resolve at ingest.
    _, reason = _validate("She loves painting", speaker="John", source="My daughter Sara loves painting.")
    assert reason == "unresolved_pronoun_subject"


def test_rejects_fabricated_proper_noun() -> None:
    # Bailey never appears in the source sentence.
    _, reason = _validate("Bailey is a cat", speaker="John", source="Maria got a cat.")
    assert reason == "fabricated_proper_noun"


def test_rejects_dropped_number() -> None:
    _, reason = _validate("Sara has cats", speaker="John", source="Sara has 3 cats.")
    assert reason == "number_dropped"


def test_rejects_dropped_negation() -> None:
    _, reason = _validate("Sara likes painting", speaker="John", source="Sara does not like painting.")
    assert reason == "negation_dropped"


def test_rejects_ungrounded_subject() -> None:
    # No named subject shared with the source and not speaker-grounded.
    _, reason = _validate("The weather is nice", speaker="John", source="Sara loves painting.")
    # "The" is a leading capitalized token but not shared -> ungrounded (or
    # fabricated); either way it must not be accepted.
    assert reason in {
        "ungrounded_subject",
        "fabricated_proper_noun",
        "no_lexical_support",
    }
    assert (
        validate_multi_speaker_fact(
            {"fact": "The weather is nice", "evidence_sentence_index": 0},
            speaker="John",
            source_text="Sara loves painting.",
        )
        is None
    )


def test_broadens_eligibility_over_first_person_only() -> None:
    # A third-person named sentence is eligible here but not under the live gate.
    text = "Sara loves painting."
    assert declarative_evidence(text)  # non-empty
    assert first_person_declarative_evidence(text) == ()  # live contract refuses it


def test_evidence_index_out_of_range() -> None:
    _, reason = _validate("Sara loves painting", speaker="John", source="Sara loves painting.", index=5)
    assert reason == "evidence_index_out_of_range"


def test_ground_scope_turn_allows_cross_sentence_name() -> None:
    # "Sara" is introduced in sentence 0; the fact cites sentence 1 ("She loves
    # painting.") but names Sara. sentence-scope rejects it as fabricated;
    # turn-scope accepts because Sara is elsewhere in the same turn.
    source = "This is my daughter Sara. She really loves painting."
    strict, strict_reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Sara loves painting", "evidence_sentence_index": 1},
        speaker="John",
        source_text=source,
    )
    assert strict is None
    assert strict_reason == "fabricated_proper_noun"

    loose, loose_reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Sara loves painting", "evidence_sentence_index": 1},
        speaker="John",
        source_text=source,
        ground_scope="turn",
    )
    assert loose_reason is None
    assert loose is not None


def test_ground_scope_turn_rejects_ambiguous_antecedent() -> None:
    fact, reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Sara loves painting", "evidence_sentence_index": 1},
        speaker="John",
        source_text="Sara met Maria. She loves painting.",
        ground_scope="turn",
    )
    assert fact is None
    assert reason == "ambiguous_turn_subject"

    for ambiguous_fact in (
        "Sara and Maria love painting",
        "Sara loves painting with Maria",
    ):
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": ambiguous_fact, "evidence_sentence_index": 1},
            speaker="John",
            source_text="Sara met Maria. She loves painting.",
            ground_scope="turn",
        )
        assert fact is None
        assert reason == "ambiguous_turn_subject"


def test_rejects_name_only_semantic_nonsequitur() -> None:
    fact, reason = validate_multi_speaker_fact_with_reason(
        {
            "fact": "Sara exists because water is wet",
            "evidence_sentence_index": 0,
        },
        speaker="John",
        source_text="Sara loves painting.",
    )
    assert fact is None
    assert reason == "no_lexical_support"

    for unsupported_fact in (
        "Sara hates painting",
        "Sara teaches painting",
        "Sara loves running",
    ):
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": unsupported_fact, "evidence_sentence_index": 0},
            speaker="John",
            source_text="Sara loves painting.",
        )
        assert fact is None
        assert reason == "no_lexical_support"


def test_rejects_speaker_rebase_without_first_person_evidence() -> None:
    fact, reason = validate_multi_speaker_fact_with_reason(
        {"fact": "John likes painting", "evidence_sentence_index": 0},
        speaker="John",
        source_text="Sara likes painting.",
    )
    assert fact is None
    assert reason == "ungrounded_subject"


def test_turn_scope_cannot_override_named_evidence_subject() -> None:
    fact, reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Maria likes painting", "evidence_sentence_index": 1},
        speaker="John",
        source_text="Maria arrived. Sara likes painting.",
        ground_scope="turn",
    )
    assert fact is None
    assert reason == "ambiguous_turn_subject"


def test_rejects_dropped_modality_state_and_reporting() -> None:
    unsupported = (
        ("Sara is painting", "Sara might be painting.", "no_lexical_support"),
        (
            "Sara is painting",
            "Sara plans to start painting.",
            "no_lexical_support",
        ),
        ("Sara has cats", "Sara wants to have cats.", "no_lexical_support"),
        ("Sara has cats", "Sara used to have cats.", "no_lexical_support"),
        (
            "Sara likes painting",
            "Sara said Maria likes painting.",
            "reported_claim",
        ),
        ("Sara painting", "Sara hates painting.", "no_lexical_support"),
        ("Sara painting", "Sara stopped painting.", "no_lexical_support"),
    )
    for fact_text, source, expected_reason in unsupported:
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": fact_text, "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == expected_reason


def test_rejects_compound_clause_recombination() -> None:
    unsafe = (
        ("Sara likes running", "Sara likes painting and hates running."),
        ("Sara owns dogs", "Sara owns cats and feeds dogs."),
        ("Maria likes painting", "Sara likes painting and Maria likes running."),
        ("Maria owns cats", "Sara owns cats and Maria owns dogs."),
        ("Sara visited Paris", "Sara visited London and Maria visited Paris."),
    )
    for fact_text, source in unsafe:
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": fact_text, "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == "compound_evidence"

    for connector in ("&", "/", "—", "then", "plus"):
        source = f"Sara likes painting {connector} Maria likes running."
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": "Sara likes running", "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == "compound_evidence"

    for fact_text, source in (
        ("Sara owns dogs", "Sara owns cats meanwhile Maria feeds dogs."),
        ("Sara owns dogs", "Sara owns cats that chase dogs."),
    ):
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": fact_text, "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == "compound_evidence"


def test_rejects_quoted_and_suffix_reported_claims() -> None:
    reported = (
        "Maria likes painting, according to Sara.",
        '"Maria likes painting."',
        "'Maria likes painting.'",
        "`Maria likes painting.`",
        "Maria likes painting, Sara explained.",
    )
    for source in reported:
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": "Maria likes painting", "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == "reported_claim"


def test_ordered_binding_preserves_simple_named_relation() -> None:
    fact, reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Sara visited Paris", "evidence_sentence_index": 0},
        speaker="John",
        source_text="Sara visited Paris.",
    )
    assert reason is None
    assert fact is not None


def test_preserves_tense_across_narrow_equivalence_classes() -> None:
    unsafe = (
        ("Sara has cats", "Sara had cats."),
        ("Sara owns cats", "Sara owned cats."),
        ("Sara likes painting", "Sara liked painting."),
        ("Sara enjoys painting", "Sara enjoyed painting."),
    )
    for fact_text, source in unsafe:
        fact, reason = validate_multi_speaker_fact_with_reason(
            {"fact": fact_text, "evidence_sentence_index": 0},
            speaker="John",
            source_text=source,
        )
        assert fact is None
        assert reason == "no_lexical_support"


def test_ground_scope_turn_still_blocks_fabrication() -> None:
    # A name in neither the sentence nor the turn is still fabricated under turn.
    _, reason = validate_multi_speaker_fact_with_reason(
        {"fact": "Bailey loves painting", "evidence_sentence_index": 0},
        speaker="John",
        source_text="This is my daughter Sara. She loves painting.",
        ground_scope="turn",
    )
    assert reason == "fabricated_proper_noun"


def test_ground_scope_invalid_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        validate_multi_speaker_fact_with_reason(
            {"fact": "Sara paints", "evidence_sentence_index": 0},
            speaker="John",
            source_text="Sara paints.",
            ground_scope="bogus",
        )
