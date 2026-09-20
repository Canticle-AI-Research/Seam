"""Behavioral acceptance tests for opt-in context-segments/1 formation."""

import json

import pytest

from seam_runtime.mirl import RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.nl import compile_nl
from seam_runtime.runtime import SeamRuntime


def test_candidate_preserves_unicode_propositions_with_exact_anchors() -> None:
    text = "東京が好きです。大阪に住んでいます。"

    baseline = compile_nl(text, allow_env_extractor=False)
    candidate = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )

    assert baseline.kind(RecordKind.SPAN) == []
    claims = candidate.kind(RecordKind.CLM)
    spans = candidate.kind(RecordKind.SPAN)
    assert [claim.attrs["object"] for claim in claims] == [
        "東京が好きです。",
        "大阪に住んでいます。",
    ]
    assert [text[span.attrs["start"] : span.attrs["end"]] for span in spans] == [
        claim.attrs["object"] for claim in claims
    ]


def test_candidate_respects_abbreviations_decimals_and_newline_boundaries() -> None:
    text = "Dr. Chen measured 3.14 units. Prof. Li agreed!\n東京も同意しました。"

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )

    assert [claim.attrs["object"] for claim in batch.kind(RecordKind.CLM)] == [
        "Dr. Chen measured 3.14 units.",
        "Prof. Li agreed!",
        "東京も同意しました。",
    ]


def test_candidate_hard_bound_prefers_whitespace_then_splits_by_character() -> None:
    cases = [
        ("alpha beta gamma", 10, ["alpha beta", "gamma"]),
        ("abcdefghij", 4, ["abcd", "efgh", "ij"]),
    ]

    for text, bound, expected in cases:
        batch = compile_nl(
            text,
            allow_env_extractor=False,
            formation_policy="context-segments/1",
            max_segment_chars=bound,
        )
        claims = batch.kind(RecordKind.CLM)
        spans = batch.kind(RecordKind.SPAN)
        assert [claim.attrs["object"] for claim in claims] == expected
        assert all(span.attrs["end"] - span.attrs["start"] <= bound for span in spans)
        assert [text[span.attrs["start"] : span.attrs["end"]] for span in spans] == expected


def test_candidate_long_input_remains_bounded_and_exactly_anchored() -> None:
    text = ("word " * 2000).rstrip()

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
        max_segment_chars=32,
    )
    spans = batch.kind(RecordKind.SPAN)
    claims = batch.kind(RecordKind.CLM)

    assert len(spans) == len(claims)
    assert len(spans) > 1
    assert all(span.attrs["end"] - span.attrs["start"] <= 32 for span in spans)
    assert [
        text[span.attrs["start"] : span.attrs["end"]] for span in spans
    ] == [claim.attrs["object"] for claim in claims]
    diagnostics = batch.kind(RecordKind.RAW)[0].ext["formation"]
    assert diagnostics["segment_count"] == len(spans)
    assert diagnostics["source_anchor_coverage"]["fraction"] == 1.0


def test_candidate_binds_only_unquoted_first_person_to_grounded_speaker() -> None:
    text = 'Alice: I moved. Bob stayed. Bob said "I left. I slept."\nBob: I hike.'

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)

    assert [claim.attrs["object"] for claim in claims] == [
        "Alice: I moved.",
        "Bob stayed.",
        'Bob said "I left.',
        'I slept."',
        "Bob: I hike.",
    ]
    assert [by_id[claim.attrs["subject"]].attrs["label"] for claim in claims] == [
        "Alice",
        "Bob",
        "Bob",
        "I",
        "Bob",
    ]
    unresolved = by_id[claims[3].attrs["subject"]]
    assert unresolved.ext["seam.entity_identity"].startswith(
        "context-segments/1:unresolved:"
    )
    first_person_entities = [
        entity
        for entity in batch.kind(RecordKind.ENT)
        if entity.attrs["label"].casefold() == "i"
    ]
    assert first_person_entities
    assert all(
        entity.ext.get("seam.entity_identity", "").startswith(
            "context-segments/1:unresolved:"
        )
        for entity in first_person_entities
    )


def test_possessive_determiners_keep_lexical_subjects_and_pronoun_is_unresolved() -> None:
    text = "Alice: My dog moved. My sister visited Bob. Mine broke."

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    subjects = [by_id[claim.attrs["subject"]] for claim in claims]

    assert [subject.attrs["label"] for subject in subjects] == [
        "dog",
        "sister",
        "Mine",
    ]
    assert "seam.entity_identity" not in subjects[0].ext
    assert "seam.entity_identity" not in subjects[1].ext
    assert subjects[2].ext["seam.entity_identity"].startswith(
        "context-segments/1:unresolved:"
    )


def test_quote_state_survives_sentences_and_size_cuts_then_closes() -> None:
    text = 'Alice: Bob said "I moved. I stayed for several days." I returned.'

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
        max_segment_chars=20,
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    stayed = next(
        claim for claim in claims if claim.attrs["object"].startswith("I stayed")
    )

    assert stayed.ext["formation_context"]["quoted"] is True
    assert by_id[stayed.attrs["subject"]].attrs["label"] == "I"
    assert by_id[stayed.attrs["subject"]].ext["seam.entity_identity"].startswith(
        "context-segments/1:unresolved:"
    )
    assert claims[-1].attrs["object"] == "I returned."
    assert by_id[claims[-1].attrs["subject"]].attrs["label"] == "Alice"
    assert claims[-1].ext["formation_context"]["quoted"] is False


@pytest.mark.parametrize("quote_pair", [('"', '"'), ("'", "'"), ("‘", "’")])
def test_quoted_first_person_is_scoped_for_supported_quote_styles(quote_pair) -> None:
    opening, closing = quote_pair
    text = f"Alice: {opening}I moved. I stayed.{closing} I returned."

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    quoted_claims = [claim for claim in claims if "I moved" in claim.attrs["object"] or "I stayed" in claim.attrs["object"]]

    assert len(quoted_claims) == 2
    for claim in quoted_claims:
        subject = by_id[claim.attrs["subject"]]
        assert subject.attrs["label"] == "I"
        assert subject.ext["seam.entity_identity"].startswith(
            "context-segments/1:unresolved:"
        )
    assert claims[-1].attrs["object"] == "I returned."
    assert by_id[claims[-1].attrs["subject"]].attrs["label"] == "Alice"


def test_possessive_apostrophe_does_not_open_quote_state() -> None:
    text = "Alice: I visited my parents' house. I returned."

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)

    assert [by_id[claim.attrs["subject"]].attrs["label"] for claim in claims] == [
        "Alice",
        "Alice",
    ]
    assert claims[-1].ext["formation_context"]["quoted"] is False


def test_nested_quote_styles_preserve_outer_quote_state() -> None:
    text = 'Alice: "Bob said \'I moved. I stayed.\' I waited." I returned.'

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    stayed = next(
        claim for claim in claims if claim.attrs["object"].startswith("I stayed")
    )

    assert stayed.ext["formation_context"]["quoted"] is True
    assert by_id[stayed.attrs["subject"]].attrs["label"] == "I"
    assert by_id[stayed.attrs["subject"]].ext[
        "seam.entity_identity"
    ].startswith("context-segments/1:unresolved:")
    assert claims[-1].attrs["object"] == "I returned."
    assert by_id[claims[-1].attrs["subject"]].attrs["label"] == "Alice"


@pytest.mark.parametrize(
    "quoted_text",
    [
        "'I'm happy. I stayed.'",
        "‘I’m happy. I stayed.’",
    ],
)
def test_intra_word_apostrophe_does_not_close_quote_state(quoted_text) -> None:
    text = f"Alice: {quoted_text} I returned."

    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    stayed = next(
        claim for claim in claims if claim.attrs["object"].startswith("I stayed")
    )

    assert stayed.ext["formation_context"]["quoted"] is True
    assert by_id[stayed.attrs["subject"]].attrs["label"] == "I"
    assert by_id[stayed.attrs["subject"]].ext[
        "seam.entity_identity"
    ].startswith("context-segments/1:unresolved:")
    assert claims[-1].attrs["object"] == "I returned."
    assert by_id[claims[-1].attrs["subject"]].attrs["label"] == "Alice"


@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("Alice: If Bob agrees, I will move.", 21),
        ("Alice: Bob thinks I left because the train was late.", 17),
    ],
)
def test_hard_split_keeps_parent_context_without_rebinding_continuation(
    text, bound
) -> None:
    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
        max_segment_chars=bound,
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)
    continuation = next(
        claim for claim in claims if claim.attrs["object"].startswith("I ")
    )

    assert by_id[continuation.attrs["subject"]].attrs["label"] != "Alice"
    assert continuation.ext["formation_context"]["context_start"] == 0
    assert continuation.ext["formation_context"]["context_end"] == len(text)


@pytest.mark.parametrize("text", ["!!!", "---", "Alice:"])
def test_nonlexical_candidate_input_is_raw_only_with_zero_diagnostics(text) -> None:
    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )

    assert batch.kind(RecordKind.SPAN) == []
    assert batch.kind(RecordKind.CLM) == []
    diagnostics = batch.kind(RecordKind.RAW)[0].ext["formation"]
    assert diagnostics["segment_count"] == 0
    assert diagnostics["compilation_outcome"] == "empty"
    assert diagnostics["source_anchor_coverage"]["fraction"] is None
    assert diagnostics["attribution_preserved"]["fraction"] is None
    assert diagnostics["timestamp_preserved"]["fraction"] is None


def test_candidate_emits_content_free_versioned_formation_diagnostics() -> None:
    text = "Alice: I moved.\nBob: I stayed."
    batch = compile_nl(
        text,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
        max_segment_chars=32,
    )

    diagnostics = batch.kind(RecordKind.RAW)[0].ext["formation"]
    assert diagnostics == {
        "schema": "seam-formation-diagnostics/1",
        "version": "formation/1",
        "segmentation_policy": "context-segments/1",
        "source_characters": 30,
        "segment_count": 2,
        "segment_size": {
            "configured_max_characters": 32,
            "characters": {"total": 29, "minimum": 14, "maximum": 15},
            "tokens": {"available": False, "reason": "not measured"},
        },
        "boundary_signals": {"sentence": 2},
        "source_anchor_coverage": {"exact": 2, "emitted": 2, "fraction": 1.0},
        "attribution_preserved": {"preserved": 2, "eligible": 2, "fraction": 1.0},
        "timestamp_preserved": {"preserved": 0, "eligible": 0, "fraction": None},
        "timestamp_synthesized": 0,
        "entity_view_version": {"available": False, "reason": "deferred to M4"},
        "contradictions_retained": {
            "available": False,
            "reason": "deferred to M4",
        },
        "reingest_required": True,
        "compilation_outcome": "compiled",
    }
    serialized = json.dumps(diagnostics, sort_keys=True)
    assert all(fragment not in serialized for fragment in ("Alice", "Bob", "moved", "stayed"))
    for record in [
        *batch.kind(RecordKind.SPAN),
        *batch.kind(RecordKind.CLM),
    ]:
        assert record.ext["formation_context"]["schema"] == "seam-formation-context/1"
        assert not any(key.endswith("_id") for key in record.ext["formation_context"])

    empty = compile_nl(
        "",
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )
    empty_diagnostics = empty.kind(RecordKind.RAW)[0].ext["formation"]
    assert empty.kind(RecordKind.SPAN) == []
    assert empty.kind(RecordKind.CLM) == []
    assert empty_diagnostics["compilation_outcome"] == "empty"
    assert empty_diagnostics["source_anchor_coverage"]["fraction"] is None
    assert empty_diagnostics["attribution_preserved"]["fraction"] is None
    assert empty_diagnostics["timestamp_preserved"]["fraction"] is None


def test_candidate_uses_exact_canonical_envelope_as_context_not_content() -> None:
    speaker = "A" * 40
    timestamp = "2026-09-01"
    text = f"[{speaker} {timestamp}] I moved to Oslo. Bob stayed."

    batch = compile_nl(
        text,
        speaker=speaker,
        source_timestamp=timestamp,
        allow_env_extractor=False,
        formation_policy="context-segments/1",
        max_segment_chars=32,
    )
    by_id = batch.by_id()
    claims = batch.kind(RecordKind.CLM)

    assert [claim.attrs["object"] for claim in claims] == [
        "I moved to Oslo.",
        "Bob stayed.",
    ]
    assert [by_id[claim.attrs["subject"]].attrs["label"] for claim in claims] == [
        speaker,
        "Bob",
    ]
    assert all(
        span.attrs["end"] - span.attrs["start"] <= 32
        for span in batch.kind(RecordKind.SPAN)
    )
    assert batch.kind(RecordKind.RAW)[0].ext["formation"]["timestamp_preserved"] == {
        "preserved": 2,
        "eligible": 2,
        "fraction": 1.0,
    }


def test_empty_canonical_timestamp_remains_unknown_in_diagnostics() -> None:
    text = "[Alice ] I moved."

    batch = compile_nl(
        text,
        speaker="Alice",
        source_timestamp="",
        allow_env_extractor=False,
        formation_policy="context-segments/1",
    )

    diagnostics = batch.kind(RecordKind.RAW)[0].ext["formation"]
    assert diagnostics["timestamp_preserved"] == {
        "preserved": 0,
        "eligible": 0,
        "fraction": None,
    }
    assert diagnostics["timestamp_synthesized"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speaker": "Alice"},
        {"source_timestamp": "2026-09-01"},
        {"speaker": "Bob", "source_timestamp": "2026-09-01"},
        {"speaker": "Alice", "source_timestamp": "2026-09-02"},
    ],
)
def test_candidate_rejects_malformed_supplied_envelope_without_echoing_source(
    kwargs,
) -> None:
    source = "[Alice 2026-09-01] PRIVATE_MARKER I moved."

    with pytest.raises(ValueError, match="invalid context-segments/1 source envelope") as exc:
        compile_nl(
            source,
            allow_env_extractor=False,
            formation_policy="context-segments/1",
            **kwargs,
        )

    assert "PRIVATE_MARKER" not in str(exc.value)


def test_candidate_rejects_enrichment_and_invalid_configuration(monkeypatch) -> None:
    source = "PRIVATE_MARKER Alice moved."
    invalid_calls = [
        {"formation_policy": "unknown-PRIVATE_MARKER"},
        {"formation_policy": "context-segments/1", "max_segment_chars": 0},
        {"formation_policy": "context-segments/1", "extractor": object()},
        {"formation_policy": "context-segments/1", "derived_fact_policy": "candidate"},
        {"formation_policy": "context-segments/1", "id_salt": ""},
    ]
    for kwargs in invalid_calls:
        with pytest.raises(ValueError) as exc:
            compile_nl(source, allow_env_extractor=False, **kwargs)
        assert "PRIVATE_MARKER" not in str(exc.value)

    monkeypatch.setenv("SEAM_NL_REGEX_ENRICH", "1")
    with pytest.raises(ValueError, match="requires deterministic formation"):
        compile_nl(
            source,
            allow_env_extractor=False,
            formation_policy="context-segments/1",
        )
    monkeypatch.delenv("SEAM_NL_REGEX_ENRICH")
    monkeypatch.setenv("SEAM_NL_EXTRACTOR", "local")
    with pytest.raises(ValueError, match="requires deterministic formation"):
        compile_nl(source, formation_policy="context-segments/1")


def test_explicit_baseline_preserves_legacy_unbounded_unicode_behavior() -> None:
    unicode_text = "東京が好きです。大阪に住んでいます。"
    long_text = "word " * 2000

    for text in (unicode_text, long_text):
        implicit = compile_nl(text, allow_env_extractor=False)
        explicit = compile_nl(
            text,
            allow_env_extractor=False,
            formation_policy="baseline",
            max_segment_chars=4,
        )
        assert [
            (record.id, record.kind, record.attrs, record.ext)
            for record in implicit.records
        ] == [
            (record.id, record.kind, record.attrs, record.ext)
            for record in explicit.records
        ]

    assert implicit.kind(RecordKind.SPAN)[0].attrs["end"] == 9999


def test_runtime_ingests_candidate_records_and_formation_diagnostics(tmp_path) -> None:
    text = "東京が好きです。大阪に住んでいます。"
    with SeamRuntime(
        tmp_path / "candidate.db",
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as runtime:
        outcome = runtime.ingest_conversation_turn(
            text,
            source_ref="fixture://unicode",
            formation_policy="context-segments/1",
            max_segment_chars=32,
            allow_env_extractor=False,
        )
        stored = runtime.store.load_ir(ids=outcome.stored_ids)

    claims = stored.kind(RecordKind.CLM)
    spans = stored.kind(RecordKind.SPAN)
    assert [claim.attrs["object"] for claim in claims] == [
        "東京が好きです。",
        "大阪に住んでいます。",
    ]
    assert [text[span.attrs["start"] : span.attrs["end"]] for span in spans] == [
        claim.attrs["object"] for claim in claims
    ]
    assert outcome.document["chunk_count"] == 2
    assert outcome.document["metadata"]["formation"] == stored.kind(RecordKind.RAW)[
        0
    ].ext["formation"]


def test_runtime_config_replay_and_supersession_are_source_scoped(tmp_path) -> None:
    text = "Alice: I moved to Oslo. I enjoy painting."
    database = tmp_path / "config-replay.db"
    with SeamRuntime(
        database,
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as runtime:
        first = runtime.ingest_text(
            text,
            source_ref="fixture://a",
            formation_policy="context-segments/1",
            max_segment_chars=32,
        )
        first_replay = runtime.ingest_text(
            text,
            source_ref="fixture://a",
            formation_policy="context-segments/1",
            max_segment_chars=32,
        )
        control = runtime.ingest_text(
            text,
            source_ref="fixture://b",
            formation_policy="context-segments/1",
            max_segment_chars=32,
        )
        changed = runtime.ingest_text(
            text,
            source_ref="fixture://a",
            formation_policy="context-segments/1",
            max_segment_chars=64,
        )
        changed_replay = runtime.ingest_text(
            text,
            source_ref="fixture://a",
            formation_policy="context-segments/1",
            max_segment_chars=64,
        )

        statuses = runtime.store.list_document_status(limit=20)

    assert first_replay.document["document_id"] == first.document["document_id"]
    assert first_replay.superseded_document_ids == []
    assert changed.document["document_id"] != first.document["document_id"]
    assert changed.superseded_document_ids == [first.document["document_id"]]
    assert changed_replay.document["document_id"] == changed.document["document_id"]
    assert changed_replay.superseded_document_ids == []
    active = [status for status in statuses if status["deleted_at"] is None]
    assert {status["document_id"] for status in active} == {
        changed.document["document_id"],
        control.document["document_id"],
    }


def test_runtime_source_envelope_changes_identity_and_malformed_input_is_atomic(
    tmp_path,
) -> None:
    text = "[Alice 2026-09-01] I moved."
    database = tmp_path / "envelope-replay.db"
    with SeamRuntime(
        database,
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as runtime:
        absent = runtime.ingest_conversation_turn(
            text,
            source_ref="fixture://envelope",
            formation_policy="context-segments/1",
            allow_env_extractor=False,
        )
        provided = runtime.ingest_conversation_turn(
            text,
            source_ref="fixture://envelope",
            speaker="Alice",
            source_timestamp="2026-09-01",
            formation_policy="context-segments/1",
            allow_env_extractor=False,
        )
        replay = runtime.ingest_conversation_turn(
            text,
            source_ref="fixture://envelope",
            speaker="Alice",
            source_timestamp="2026-09-01",
            formation_policy="context-segments/1",
            allow_env_extractor=False,
        )
        statuses_before = runtime.store.list_document_status(limit=20)
        records_before = [record.to_dict() for record in runtime.store.load_ir().records]

        with pytest.raises(
            ValueError, match="invalid context-segments/1 source envelope"
        ):
            runtime.ingest_conversation_turn(
                text,
                source_ref="fixture://envelope",
                speaker="Bob",
                source_timestamp="2026-09-01",
                formation_policy="context-segments/1",
                allow_env_extractor=False,
            )

        statuses_after = runtime.store.list_document_status(limit=20)
        records_after = [record.to_dict() for record in runtime.store.load_ir().records]

    assert provided.document["document_id"] != absent.document["document_id"]
    assert provided.superseded_document_ids == [absent.document["document_id"]]
    assert replay.document["document_id"] == provided.document["document_id"]
    assert replay.superseded_document_ids == []
    assert statuses_after == statuses_before
    assert records_after == records_before


def test_runtime_baseline_candidate_baseline_transition_retires_prior_generation(
    tmp_path,
) -> None:
    text = "Alice remembers TRANSITION_MARKER."
    with SeamRuntime(
        tmp_path / "policy-transition.db",
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as runtime:
        baseline = runtime.ingest_text(text, source_ref="fixture://transition")
        candidate = runtime.ingest_text(
            text,
            source_ref="fixture://transition",
            formation_policy="context-segments/1",
            max_segment_chars=32,
        )
        restored = runtime.ingest_text(text, source_ref="fixture://transition")
        result = runtime.search_ir(
            "TRANSITION_MARKER",
            ns="local.default",
            scope="thread",
            budget=20,
        )
        statuses = runtime.store.list_document_status(limit=20)

    assert candidate.document["document_id"] != baseline.document["document_id"]
    assert candidate.superseded_document_ids == [baseline.document["document_id"]]
    assert restored.document["document_id"] == baseline.document["document_id"]
    assert restored.superseded_document_ids == [candidate.document["document_id"]]
    assert not set(candidate.stored_ids) & {
        item.record.id for item in result.candidates
    }
    active = [status for status in statuses if status["deleted_at"] is None]
    assert [status["document_id"] for status in active] == [
        baseline.document["document_id"]
    ]


def test_runtime_correction_delete_and_reopen_do_not_resurrect_retired_content(
    tmp_path,
) -> None:
    database = tmp_path / "candidate-lifecycle.db"
    with SeamRuntime(
        database,
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as runtime:
        original = runtime.ingest_text(
            "Alice remembers RETIRED_A_MARKER.",
            source_ref="fixture://a",
            ns="tenant-a",
            formation_policy="context-segments/1",
        )
        corrected = runtime.ingest_text(
            "Alice remembers the correction.",
            source_ref="fixture://a",
            ns="tenant-a",
            formation_policy="context-segments/1",
        )
        source_b = runtime.ingest_text(
            "Bob remembers DELETED_B_MARKER.",
            source_ref="fixture://b",
            ns="tenant-a",
            formation_policy="context-segments/1",
        )
        planned = runtime.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=source_b.stored_ids,
            idempotency_key="delete-source-b",
            actor="operator",
        )
        applied = runtime.apply_scoped_delete(
            tenant_id="tenant-a",
            operation_id=str(planned["operation_id"]),
            actor="operator",
        )

    with SeamRuntime(
        database,
        embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    ) as reopened:
        rebuilt = reopened.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )
        products = reopened.graph_products(namespace="tenant-a", scope="thread")
        retired = reopened.search_ir(
            "RETIRED_A_MARKER", ns="tenant-a", scope="thread", budget=20
        )
        deleted = reopened.search_ir(
            "DELETED_B_MARKER", ns="tenant-a", scope="thread", budget=20
        )

    assert corrected.superseded_document_ids == [original.document["document_id"]]
    assert applied["state"] == "applied"
    assert rebuilt["accepted_fact_count"] >= 1
    assert "RETIRED_A_MARKER" not in repr(products)
    assert "DELETED_B_MARKER" not in repr(products)
    assert not set(original.stored_ids) & {
        item.record.id for item in retired.candidates
    }
    assert not set(source_b.stored_ids) & {
        item.record.id for item in deleted.candidates
    }
