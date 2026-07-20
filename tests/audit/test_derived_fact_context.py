from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.derived_fact_context import (
    DERIVED_FACTS_EMBEDDING_CONFIG,
    DERIVED_FACTS_OFF,
    GROUNDED_CLM_V1,
    DerivedFact,
    configure_derived_facts,
    grounded_spans_match_source,
    is_eligible_derived_claim,
    resolve_derived_facts_policy,
    splice_derived_facts,
)
from seam_runtime.mirl import MIRLRecord, RecordKind, Status
from seam_runtime.nl import compile_nl
from seam_runtime.nl_extract import (
    ExtractedClaim,
    ExtractedEntity,
    Extraction,
    GroundedSpan,
    OllamaExtractor,
)


@pytest.fixture(autouse=True)
def _isolated_sqlite_vector_contract(monkeypatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)


def _rich_claim(*, status: Status = Status.ASSERTED) -> MIRLRecord:
    return MIRLRecord(
        id="clm:fact",
        kind=RecordKind.CLM,
        ns="locomo:user",
        scope="thread",
        status=status,
        evidence=["span:1"],
        ext={
            "derived_fact_policy": GROUNDED_CLM_V1,
            "extraction_method": "grounded_local_model",
            "epistemic_basis": "explicit",
            "grounded_spans": [
                {"field": "subject", "text": "John", "start": 0, "end": 4},
                {"field": "relation", "text": "likes", "start": 5, "end": 10},
                {"field": "object", "text": "surfing", "start": 11, "end": 18},
            ],
        },
        attrs={
            "subject": "ent:john",
            "subject_label": "John",
            "predicate": "likes",
            "object": "surfing",
        },
    )


def _fact(index: int, *, source_id: str | None = None) -> DerivedFact:
    return DerivedFact(
        claim_id=f"clm:{index}",
        subject=f"Person {index}",
        predicate="likes",
        obj=f"activity {index}",
        source_raw_id=source_id or f"raw:{index}",
        source_text=f"[Person {index} 2024-01-01] I like activity {index}.",
        score=1.0 - index / 1000,
        created_at="2024-01-01",
    )


def test_policy_off_is_identity_and_unknown_policy_fails_closed():
    results = [{"id": "raw:1", "memory": "one", "score": 1.0}]
    assert (
        splice_derived_facts(
            results,
            [_fact(1)],
            limit=10,
            policy=DERIVED_FACTS_OFF,
        )
        is results
    )
    with pytest.raises(ValueError, match="unsupported derived-facts policy"):
        resolve_derived_facts_policy("unknown/1")


def test_eligible_claim_requires_explicit_grounded_current_rich_clm():
    claim = _rich_claim()
    claim.ext["subject_resolution"] = {
        "method": "first_person_to_turn_speaker",
        "surface": "I",
        "speaker": "John",
    }
    assert is_eligible_derived_claim(claim)

    claim.ext["epistemic_basis"] = "inferred"
    assert not is_eligible_derived_claim(claim)
    claim.ext["epistemic_basis"] = "explicit"
    claim.status = Status.SUPERSEDED
    assert not is_eligible_derived_claim(claim)
    claim.status = Status.ASSERTED
    claim.attrs["subject_label"] = "I"
    assert not is_eligible_derived_claim(claim)

    unresolved = _rich_claim()
    unresolved.attrs["subject_label"] = "My favorite sport"
    assert not is_eligible_derived_claim(unresolved)


def test_persisted_grounded_spans_must_match_exact_raw():
    claim = _rich_claim()
    raw = "John likes surfing"
    assert grounded_spans_match_source(claim, raw)
    claim.attrs["predicate"] = "hates"
    assert not grounded_spans_match_source(claim, raw)
    claim.attrs["predicate"] = "likes"
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=5,
        evidence_end=len(raw),
    )
    claim.ext["grounded_spans"][2]["end"] = 17
    assert not grounded_spans_match_source(claim, raw)


def test_rebased_subject_must_match_first_person_and_grounded_raw_speaker():
    raw = "[John 2024-01-01] I like surfing"
    claim = _rich_claim()
    claim.attrs["predicate"] = "like"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "I",
            "start": raw.index("I"),
            "end": raw.index("I") + 1,
        },
        {
            "field": "relation",
            "text": "like",
            "start": raw.index("like"),
            "end": raw.index("like") + len("like"),
        },
        {
            "field": "object",
            "text": "surfing",
            "start": raw.index("surfing"),
            "end": raw.index("surfing") + len("surfing"),
        },
    ]
    claim.ext["subject_resolution"] = {
        "method": "first_person_to_turn_speaker",
        "surface": "I",
        "speaker": "John",
    }
    assert grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("I"),
    )
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="Mary",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("I"),
    )
    claim.ext["subject_resolution"]["surface"] = "Mary"
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("I"),
    )


@pytest.mark.parametrize("surface", ["¬I", "~I", "(I)"])
def test_symbol_wrapped_first_person_cannot_be_rebased(surface):
    raw = f"[John 2024-01-01] {surface} like surfing."
    claim = _rich_claim()
    claim.attrs["predicate"] = "like"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": surface,
            "start": raw.index(surface),
            "end": raw.index(surface) + len(surface),
        },
        {
            "field": "relation",
            "text": "like",
            "start": raw.index("like"),
            "end": raw.index("like") + len("like"),
        },
        {
            "field": "object",
            "text": "surfing",
            "start": raw.index("surfing"),
            "end": raw.index("surfing") + len("surfing"),
        },
    ]
    claim.ext["subject_resolution"] = {
        "method": "first_person_to_turn_speaker",
        "surface": surface,
        "speaker": "John",
    }
    assert not is_eligible_derived_claim(claim)
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index(surface),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "John likes surfing, but Mary likes skiing.",
        "[John 2024-01-01] Mary likes skiing.",
    ],
)
def test_persisted_fact_rejects_cross_clause_or_speaker_prefix_sro(raw):
    claim = _rich_claim()
    claim.attrs["predicate"] = "likes"
    claim.attrs["object"] = "skiing"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John"),
            "end": raw.index("John") + len("John"),
        },
        {
            "field": "relation",
            "text": "likes",
            "start": raw.index("likes"),
            "end": raw.index("likes") + len("likes"),
        },
        {
            "field": "object",
            "text": "skiing",
            "start": raw.index("skiing"),
            "end": raw.index("skiing") + len("skiing"),
        },
    ]
    assert not grounded_spans_match_source(claim, raw)


@pytest.mark.parametrize(
    "raw",
    [
        "If John likes skiing, he smiles.",
        "Unless John likes skiing, he stays home.",
        "John likes skiing if the weather is good.",
        "John likes skiing only in dreams.",
        "John likes skiing in 2020.",
        "John likes skiing according to Mary.",
        "Hypothetical: John likes skiing.",
        "Rumor: John likes skiing.",
        "According to Mary: John likes skiing.",
        "Mary claims: John likes skiing.",
        "In a dream: John likes skiing.",
        "[Mary says] John likes skiing.",
        "John likes skiing 夢だけ.",
        "¬John likes skiing.",
        "John ¬ likes skiing.",
    ],
)
def test_served_fact_cannot_drop_external_qualifiers(raw):
    claim = _rich_claim()
    claim.attrs["predicate"] = "likes"
    claim.attrs["object"] = "skiing"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John"),
            "end": raw.index("John") + len("John"),
        },
        {
            "field": "relation",
            "text": "likes",
            "start": raw.index("likes"),
            "end": raw.index("likes") + len("likes"),
        },
        {
            "field": "object",
            "text": "skiing",
            "start": raw.index("skiing"),
            "end": raw.index("skiing") + len("skiing"),
        },
    ]
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        require_evidence_bounds=True,
    )


@pytest.mark.parametrize(
    "quoted",
    [
        "«John likes skiing»",
        "‹John likes skiing›",
        "「John likes skiing」",
        "『John likes skiing』",
        "`John likes skiing`",
        "``John likes skiing``",
    ],
)
def test_persisted_fact_rejects_quoted_sro_with_canonical_metadata(quoted):
    raw = f"[John 2024-01-01] {quoted}."
    claim = _rich_claim()
    claim.attrs["predicate"] = "likes"
    claim.attrs["object"] = "skiing"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John", raw.index("]")),
            "end": raw.index("John", raw.index("]")) + len("John"),
        },
        {
            "field": "relation",
            "text": "likes",
            "start": raw.index("likes"),
            "end": raw.index("likes") + len("likes"),
        },
        {
            "field": "object",
            "text": "skiing",
            "start": raw.index("skiing"),
            "end": raw.index("skiing") + len("skiing"),
        },
    ]
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index(quoted),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_persisted_fact_cannot_drop_numeric_object_modifier():
    raw = "[John 2024-01-01] John has 0 cats."
    claim = _rich_claim()
    claim.attrs["predicate"] = "has"
    claim.attrs["object"] = "cats"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John", raw.index("]")),
            "end": raw.index("John", raw.index("]")) + len("John"),
        },
        {
            "field": "relation",
            "text": "has",
            "start": raw.index("has"),
            "end": raw.index("has") + len("has"),
        },
        {
            "field": "object",
            "text": "cats",
            "start": raw.index("cats"),
            "end": raw.index("cats") + len("cats"),
        },
    ]
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("John", raw.index("]")),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_persisted_fact_may_preserve_numeric_modifier_inside_object():
    raw = "[John 2024-01-01] John has 0 cats."
    claim = _rich_claim()
    claim.attrs["predicate"] = "has"
    claim.attrs["object"] = "0 cats"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John", raw.index("]")),
            "end": raw.index("John", raw.index("]")) + len("John"),
        },
        {
            "field": "relation",
            "text": "has",
            "start": raw.index("has"),
            "end": raw.index("has") + len("has"),
        },
        {
            "field": "object",
            "text": "0 cats",
            "start": raw.index("0 cats"),
            "end": raw.index("0 cats") + len("0 cats"),
        },
    ]
    assert grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("John", raw.index("]")),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_served_fact_may_preserve_qualifier_inside_object():
    raw = "John likes skiing only in dreams."
    claim = _rich_claim()
    claim.attrs["object"] = "skiing only in dreams"
    start = raw.index("skiing")
    claim.ext["grounded_spans"][2] = {
        "field": "object",
        "text": "skiing only in dreams",
        "start": start,
        "end": start + len("skiing only in dreams"),
    }
    assert grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        require_evidence_bounds=True,
    )


def test_fake_bracket_metadata_cannot_authorize_a_qualifier_prefix():
    raw = "[Mary says] John likes skiing."
    claim = _rich_claim()
    claim.attrs["predicate"] = "likes"
    claim.attrs["object"] = "skiing"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "John",
            "start": raw.index("John"),
            "end": raw.index("John") + len("John"),
        },
        {
            "field": "relation",
            "text": "likes",
            "start": raw.index("likes"),
            "end": raw.index("likes") + len("likes"),
        },
        {
            "field": "object",
            "text": "skiing",
            "start": raw.index("skiing"),
            "end": raw.index("skiing") + len("skiing"),
        },
    ]
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=len(raw),
        source_speaker="Mary",
        source_timestamp="says",
        source_prefix_end=raw.index("John"),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_persisted_fact_rejects_malformed_evidence_bounds():
    claim = _rich_claim()
    raw = "John likes surfing"
    assert not grounded_spans_match_source(
        claim,
        raw,
        require_evidence_bounds=True,
    )
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start="0",
        evidence_end=len(raw),
    )
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=0,
        evidence_end=None,
    )


def test_persisted_fact_rejects_shrunken_span_that_hides_qualifier():
    raw = "[John 2024-01-01] If I like surfing."
    claim = _rich_claim()
    claim.attrs["predicate"] = "like"
    claim.ext["grounded_spans"] = [
        {
            "field": "subject",
            "text": "I",
            "start": raw.index("I"),
            "end": raw.index("I") + 1,
        },
        {
            "field": "relation",
            "text": "like",
            "start": raw.index("like"),
            "end": raw.index("like") + len("like"),
        },
        {
            "field": "object",
            "text": "surfing",
            "start": raw.index("surfing"),
            "end": raw.index("surfing") + len("surfing"),
        },
    ]
    claim.ext["subject_resolution"] = {
        "method": "first_person_to_turn_speaker",
        "surface": "I",
        "speaker": "John",
    }
    assert not grounded_spans_match_source(
        claim,
        raw,
        evidence_start=raw.index("I"),
        evidence_end=raw.index("surfing") + len("surfing"),
        source_speaker="John",
        source_timestamp="2024-01-01",
        source_prefix_end=raw.index("If"),
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_splice_caps_facts_at_twenty_percent_and_preserves_raw_floor():
    raw = [
        {
            "id": f"raw:{index}",
            "memory": f"raw {index}",
            "score": 1.0 - index / 1000,
            "created_at": "",
        }
        for index in range(200)
    ]
    mixed = splice_derived_facts(
        raw,
        [_fact(index) for index in range(50)],
        limit=200,
        policy=GROUNDED_CLM_V1,
    )
    assert len(mixed) == 200
    assert sum(str(item["id"]).startswith("clm:") for item in mixed) == 40
    assert sum(str(item["id"]).startswith("raw:") for item in mixed) == 160
    assert {f"raw:{index}" for index in range(40)} <= {
        str(item["id"]) for item in mixed
    }
    for size in range(1, len(mixed) + 1):
        prefix = mixed[:size]
        assert (
            sum(str(item["id"]).startswith("clm:") for item in prefix) * 5
            <= len(prefix)
        )
    assert [
        index
        for index, item in enumerate(mixed)
        if str(item["id"]).startswith("clm:")
    ][:4] == [4, 9, 14, 19]


def test_splice_deduplicates_facts_and_forces_missing_source_raw():
    facts = [_fact(1, source_id="raw:outside"), _fact(2)]
    duplicate = DerivedFact(
        claim_id="clm:duplicate",
        subject=facts[0].subject.upper(),
        predicate=facts[0].predicate,
        obj=facts[0].obj,
        source_raw_id=facts[0].source_raw_id,
        source_text="duplicate source",
        score=0.1,
    )
    mixed = splice_derived_facts(
        [
            {
                "id": f"raw:baseline:{index}",
                "memory": f"baseline {index}",
                "score": 0.8,
            }
            for index in range(8)
        ],
        [*facts, duplicate],
        limit=10,
        policy=GROUNDED_CLM_V1,
    )
    assert sum(str(item["id"]).startswith("clm:") for item in mixed) == 2
    assert "raw:outside" in {str(item["id"]) for item in mixed}
    fact_positions = [
        index
        for index, item in enumerate(mixed)
        if str(item["id"]).startswith("clm:")
    ]
    assert fact_positions == [4, 9]
    for position in fact_positions:
        fact_row = mixed[position]
        assert fact_row["memory"].startswith("SEAM-FACT/1|")
        assert "SEAM-SOURCE/1|" in fact_row["memory"]
        fact = next(
            item
            for item in facts
            if item.claim_id == fact_row["id"]
        )
        assert fact.source_raw_id in {
            str(item["id"]) for item in mixed[:position]
        }


def test_splice_caps_facts_against_sparse_actual_output():
    raw = [
        {
            "id": "raw:baseline",
            "memory": "baseline",
            "score": 0.8,
        }
    ]
    mixed = splice_derived_facts(
        raw,
        [_fact(index) for index in range(10)],
        limit=50,
        policy=GROUNDED_CLM_V1,
    )
    fact_count = sum(
        str(item["id"]).startswith("clm:")
        for item in mixed
    )
    assert fact_count * 5 <= len(mixed)


@dataclass
class _CountingExtractor:
    calls: int = 0

    def config_metadata(self) -> dict[str, object]:
        return {"type": "test", "version": 1}

    def extract(self, text: str) -> Extraction:
        self.calls += 1
        return Extraction(
            entities=(ExtractedEntity("John", "person"),),
            claims=(
                ExtractedClaim(
                    "John",
                    "likes",
                    "surfing",
                    source_spans=(
                        GroundedSpan("subject", "John", 0, 4),
                        GroundedSpan("relation", "likes", 5, 10),
                        GroundedSpan("object", "surfing", 11, 18),
                    ),
                ),
            ),
        )


def test_content_addressed_cache_replays_without_second_extractor_call(tmp_path):
    inner = _CountingExtractor()
    runtime = configure_derived_facts(
        tmp_path / "candidate",
        policy=GROUNDED_CLM_V1,
        extractor=inner,
    )
    first = runtime.extractor.extract("John likes surfing")
    second = runtime.extractor.extract("John likes surfing")
    assert first == second
    assert inner.calls == 1
    assert runtime.extractor.stats()["hits"] == 1
    assert runtime.extractor.stats()["misses"] == 1

    restarted_inner = _CountingExtractor()
    restarted = configure_derived_facts(
        tmp_path / "candidate",
        policy=GROUNDED_CLM_V1,
        extractor=restarted_inner,
    )
    assert restarted.extractor.extract("John likes surfing") == first
    assert restarted_inner.calls == 0


def test_scoped_cache_purge_preserves_shared_rows_until_last_owner(tmp_path):
    inner = _CountingExtractor()
    runtime = configure_derived_facts(
        tmp_path / "owned",
        policy=GROUNDED_CLM_V1,
        extractor=inner,
    )
    owner_a = runtime.extractor.bind("locomo:a")
    owner_b = runtime.extractor.bind("locomo:b")
    owner_a.extract("John likes surfing")
    owner_b.extract("John likes surfing")
    assert inner.calls == 1

    runtime.extractor.purge_owner("locomo:a")
    owner_b.extract("John likes surfing")
    assert inner.calls == 1

    runtime.extractor.purge_owner("locomo:b")
    owner_b.extract("John likes surfing")
    assert inner.calls == 2


def test_cache_rejects_extractor_configuration_mutation(tmp_path):
    class MutableExtractor(_CountingExtractor):
        version = 1

        def config_metadata(self):
            return {"type": "mutable-test", "version": self.version}

    inner = MutableExtractor()
    runtime = configure_derived_facts(
        tmp_path / "mutable",
        policy=GROUNDED_CLM_V1,
        extractor=inner,
    )
    inner.version = 2
    with pytest.raises(RuntimeError, match="configuration changed"):
        runtime.extractor.extract("John likes surfing")
    assert inner.calls == 0


def test_cache_rejects_ollama_decoder_mutation(
    monkeypatch,
    tmp_path,
):
    extractor = OllamaExtractor(
        model="unit",
        model_digest="digest-a",
        host="http://127.0.0.1:11434",
        strict=True,
    )
    monkeypatch.setattr(
        extractor,
        "_installed_model_digest",
        lambda: "digest-a",
    )
    runtime = configure_derived_facts(
        tmp_path / "ollama-mutable",
        policy=GROUNDED_CLM_V1,
        extractor=extractor,
    )
    extractor.seed += 1
    monkeypatch.setattr(
        extractor,
        "_generate",
        lambda text: pytest.fail("mutation must stop generation"),
    )
    with pytest.raises(RuntimeError, match="configuration changed"):
        runtime.extractor.extract("John likes surfing")


def test_extractor_errors_are_not_cached(tmp_path):
    class BrokenExtractor:
        calls = 0

        def config_metadata(self):
            return {"type": "broken", "version": 1}

        def extract(self, text):
            self.calls += 1
            raise RuntimeError("boom")

    inner = BrokenExtractor()
    runtime = configure_derived_facts(
        tmp_path / "candidate",
        policy=GROUNDED_CLM_V1,
        extractor=inner,
    )
    for _ in range(2):
        with pytest.raises(RuntimeError, match="boom"):
            runtime.extractor.extract("John likes surfing")
    assert inner.calls == 2


def test_manifest_refuses_warm_store_and_config_mismatch(tmp_path):
    warm = tmp_path / "warm"
    warm.mkdir()
    (warm / "scope.db").write_bytes(b"not-empty")
    with pytest.raises(RuntimeError, match="fresh shadow store"):
        configure_derived_facts(
            warm,
            policy=GROUNDED_CLM_V1,
            extractor=_CountingExtractor(),
        )

    candidate = tmp_path / "candidate"
    configure_derived_facts(
        candidate,
        policy=GROUNDED_CLM_V1,
        extractor=_CountingExtractor(),
    )

    class ChangedExtractor(_CountingExtractor):
        def config_metadata(self):
            return {"type": "test", "version": 2}

    with pytest.raises(RuntimeError, match="does not match"):
        configure_derived_facts(
            candidate,
            policy=GROUNDED_CLM_V1,
            extractor=ChangedExtractor(),
        )
    with pytest.raises(RuntimeError, match="cannot reuse an enriched"):
        configure_derived_facts(
            candidate,
            policy=DERIVED_FACTS_OFF,
        )


def test_manifest_binds_cache_identity_and_requires_cache_on_resume(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "candidate"
    cache_a = tmp_path / "cache-a.sqlite3"
    first = configure_derived_facts(
        root,
        policy=GROUNDED_CLM_V1,
        extractor=_CountingExtractor(),
        cache_path=cache_a,
    )
    with pytest.raises(RuntimeError, match="does not match"):
        configure_derived_facts(
            root,
            policy=GROUNDED_CLM_V1,
            extractor=_CountingExtractor(),
            cache_path=tmp_path / "cache-b.sqlite3",
        )

    original_is_file = Path.is_file
    expected_cache = Path(first.config.cache_path)
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: (
            False
            if self == expected_cache
            else original_is_file(self)
        ),
    )
    with pytest.raises(RuntimeError, match="cache is missing"):
        configure_derived_facts(
            root,
            policy=GROUNDED_CLM_V1,
            extractor=_CountingExtractor(),
            cache_path=cache_a,
        )


def test_ollama_candidate_requires_strict_loopback_and_digest_is_frozen(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        OllamaExtractor,
        "_installed_model_digest",
        lambda self: str(self.model_digest or "installed-digest"),
    )

    class UnfrozenExtractor:
        def extract(self, text):
            return Extraction()

    with pytest.raises(ValueError, match="config_metadata"):
        configure_derived_facts(
            tmp_path / "unfrozen",
            policy=GROUNDED_CLM_V1,
            extractor=UnfrozenExtractor(),
        )
    with pytest.raises(ValueError, match="strict=True"):
        configure_derived_facts(
            tmp_path / "nonstrict",
            policy=GROUNDED_CLM_V1,
            extractor=OllamaExtractor(
                model="unit",
                model_digest="digest-a",
                strict=False,
            ),
        )
    with pytest.raises(ValueError, match="loopback"):
        configure_derived_facts(
            tmp_path / "remote",
            policy=GROUNDED_CLM_V1,
            extractor=OllamaExtractor(
                model="unit",
                model_digest="digest-a",
                host="https://example.invalid",
                strict=True,
            ),
        )
    with pytest.raises(ValueError, match="credential-free"):
        configure_derived_facts(
            tmp_path / "credentialed",
            policy=GROUNDED_CLM_V1,
            extractor=OllamaExtractor(
                model="unit",
                model_digest="digest-a",
                host="http://user:password@127.0.0.1:11434",
                strict=True,
            ),
        )

    first = configure_derived_facts(
        tmp_path / "digest",
        policy=GROUNDED_CLM_V1,
        extractor=OllamaExtractor(
            model="unit",
            model_digest="digest-a",
            host="http://127.0.0.1:11434",
            strict=True,
        ),
    )
    assert first.config.payload["extractor"]["model_digest"] == "digest-a"
    with pytest.raises(RuntimeError, match="does not match"):
        configure_derived_facts(
            tmp_path / "digest",
            policy=GROUNDED_CLM_V1,
            extractor=OllamaExtractor(
                model="unit",
                model_digest="digest-b",
                host="http://127.0.0.1:11434",
                strict=True,
            ),
        )


def test_ollama_candidate_rejects_false_expected_digest(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        OllamaExtractor,
        "_installed_model_digest",
        lambda self: "installed-digest",
    )
    with pytest.raises(RuntimeError, match="digest mismatch"):
        configure_derived_facts(
            tmp_path / "false-attestation",
            policy=GROUNDED_CLM_V1,
            extractor=OllamaExtractor(
                model="unit",
                model_digest="claimed-digest",
                host="http://127.0.0.1:11434",
                strict=True,
            ),
        )


def test_candidate_rejects_shared_pgvector_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "SEAM_PGVECTOR_DSN",
        "postgresql://invalid.local/seam",
    )
    with pytest.raises(RuntimeError, match="requires SEAM_PGVECTOR_DSN"):
        configure_derived_facts(
            tmp_path / "candidate",
            policy=GROUNDED_CLM_V1,
            extractor=_CountingExtractor(),
        )


def test_candidate_rejects_remote_embedding_environment(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("SEAM_EMBEDDING_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="local benchmark embedding"):
        configure_derived_facts(
            tmp_path / "candidate",
            policy=GROUNDED_CLM_V1,
            extractor=_CountingExtractor(),
        )


def test_locomo_adapter_forwards_speaker_without_rewriting_raw(tmp_path):
    captured = {}

    class FakeRuntime:
        def ingest_conversation_turn(self, **kwargs):
            captured.update(kwargs)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path / "candidate"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_CountingExtractor(),
    )
    adapter._runtime = lambda scope_id: FakeRuntime()
    adapter.ingest_turn(
        "scope",
        ConversationTurn(
            speaker="John",
            text="I like surfing.",
            timestamp="2023-05-01",
        ),
    )

    assert captured["text"] == "[John 2023-05-01] I like surfing."
    assert captured["speaker"] == "John"
    assert captured["source_timestamp"] == "2023-05-01"
    assert captured["derived_fact_policy"] == GROUNDED_CLM_V1
    assert captured["extractor"]._cache is adapter._derived_facts.extractor
    assert captured["extractor"].owner == "locomo:scope"
    assert captured["allow_env_extractor"] is False


def test_candidate_accepts_official_locomo_timestamp_contract(tmp_path):
    captured = {}

    class FirstPersonExtractor:
        def extract(self, text):
            return Extraction(
                entities=(
                    ExtractedEntity("I", "person"),
                    ExtractedEntity("surfing", "activity"),
                ),
                claims=(
                    ExtractedClaim(
                        "I",
                        "like",
                        "surfing",
                        epistemic_basis="explicit",
                        source_spans=(
                            GroundedSpan("subject", "I", 0, 1),
                            GroundedSpan("relation", "like", 2, 6),
                            GroundedSpan("object", "surfing", 7, 14),
                        ),
                    ),
                ),
            )

    class FakeRuntime:
        def ingest_conversation_turn(self, **kwargs):
            captured.update(kwargs)

    adapter = SeamLocomoAdapter(
        db_path=str(tmp_path / "official-timestamp"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_CountingExtractor(),
    )
    assert (
        adapter._derived_facts.config.payload["embedding"]
        == DERIVED_FACTS_EMBEDDING_CONFIG
    )
    adapter._runtime = lambda scope_id: FakeRuntime()
    adapter.ingest_turn(
        "scope",
        ConversationTurn(
            speaker="John",
            text="I like surfing.",
            timestamp="1:56 pm on 8 May, 2023",
        ),
    )
    assert captured["text"] == (
        "[John 1:56 pm on 8 May, 2023] I like surfing."
    )
    batch = compile_nl(
        captured["text"],
        extractor=FirstPersonExtractor(),
        speaker=captured["speaker"],
        source_timestamp=captured["source_timestamp"],
        derived_fact_policy=captured["derived_fact_policy"],
        allow_env_extractor=False,
    )
    rich = [
        record
        for record in batch.records
        if record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
    ]
    assert rich
    assert rich[0].attrs["subject_label"] == "John"
    assert (
        rich[0].ext["subject_resolution"]["method"]
        == "first_person_to_turn_speaker"
    )
    raw = next(
        record
        for record in batch.records
        if record.kind == RecordKind.RAW
    )
    assert raw.ext["source_metadata"]["timestamp"] == (
        "1:56 pm on 8 May, 2023"
    )


def test_floor_adapter_blocks_legacy_env_extractor(monkeypatch, tmp_path):
    import seam_runtime.nl_extract as nl_extract

    monkeypatch.setenv("SEAM_NL_EXTRACTOR", "ollama")
    monkeypatch.setattr(
        nl_extract,
        "extractor_from_env",
        lambda: pytest.fail("legacy env extractor must stay disabled"),
    )
    batch = compile_nl(
        "John likes surfing.",
        allow_env_extractor=False,
    )
    assert {
        record.attrs.get("predicate")
        for record in batch.records
        if record.kind == RecordKind.CLM
    } == {"content"}

    captured = {}

    class FakeRuntime:
        def ingest_conversation_turn(self, **kwargs):
            captured.update(kwargs)

    adapter = SeamLocomoAdapter(db_path=str(tmp_path / "floor"))
    adapter._runtime = lambda scope_id: FakeRuntime()
    adapter.ingest_turn(
        "scope",
        ConversationTurn(
            speaker="John",
            text="I like surfing.",
            timestamp="2023-05-01",
        ),
    )
    assert captured["extractor"] is None
    assert captured["speaker"] is None
    assert captured["source_timestamp"] is None
    assert captured["derived_fact_policy"] is None
    assert captured["allow_env_extractor"] is False
