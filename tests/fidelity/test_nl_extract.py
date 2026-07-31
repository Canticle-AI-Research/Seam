"""The opt-in rich extractor (Stage 4): the grounding firewall + compile_nl wiring.

CI-safe and model-free: a local Ollama model can't run in CI, so these pin the
DETERMINISTIC parts — `ground_extraction` (the fabrication gate) and the
`compile_nl(extractor=...)` integration with a stub extractor. The real-model
`sr`->~1.0 validation is recorded in HISTORY, not run here (the strict-no-skip
policy forbids a skipping test).
"""

from __future__ import annotations

import pytest

from seam_runtime.derived_fact_context import GROUNDED_CLM_V1, GROUNDED_CLM_V2
from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.nl_extract import (
    ExtractedClaim,
    ExtractedEntity,
    Extraction,
    GroundedSpan,
    _decode_model_json,
    extractor_from_env,
    ground_extraction,
)

# --- the grounding gate: only verbatim spans survive --------------------------

def test_ground_extraction_keeps_grounded_drops_hallucinated():
    text = "Priya owns the billing service."
    raw = {
        "entities": [
            {"name": "Priya", "type": "person"},
            {"name": "billing service", "type": "thing"},
            {"name": "Acme Corp", "type": "org"},  # not in text
        ],
        "claims": [
            {"subject": "Priya", "relation": "owns", "object": "the billing service"},
            {"subject": "Priya", "relation": "sold", "object": "the company"},  # ungrounded
        ],
    }
    ex = ground_extraction(raw, text)
    names = {e.name for e in ex.entities}
    assert "Priya" in names and "billing service" in names
    assert "Acme Corp" not in names  # fabrication firewall drops it
    relations = {c.relation for c in ex.claims}
    assert "owns" in relations and "sold" not in relations  # ungrounded claim dropped
    assert next(c for c in ex.claims if c.relation == "owns").epistemic_basis == "unknown"


def test_ground_extraction_empty_on_garbage_or_ungrounded():
    assert ground_extraction({}, "x").is_empty()
    assert ground_extraction("not a dict", "x").is_empty()
    # every span foreign to the text -> nothing survives
    raw = {"claims": [{"subject": "foo", "relation": "bar", "object": "baz"}]}
    assert ground_extraction(raw, "totally different sentence").is_empty()


@pytest.mark.parametrize(
    "text",
    [
        "John likes surfing, but Mary likes skiing.",
        "John likes surfing and Mary likes skiing.",
        "John likes surfing because Mary likes skiing.",
        "John said Mary likes skiing.",
        "John likes surfing\nMary likes skiing.",
    ],
)
def test_ground_extraction_rejects_cross_clause_recombination(text):
    raw = {
        "claims": [
            {
                "subject": "John",
                "relation": "likes",
                "object": "skiing",
            },
            {
                "subject": "Mary",
                "relation": "likes",
                "object": "surfing",
            },
        ]
    }
    assert ground_extraction(raw, text).claims == ()


@pytest.mark.parametrize(
    ("text", "subject", "obj"),
    [
        (
            "John likes surfing, but Mary likes skiing.",
            "John",
            "surfing, but Mary likes skiing",
        ),
        (
            "John likes surfing\nMary likes skiing.",
            "John",
            "surfing\nMary likes skiing",
        ),
        ("If John likes surfing.", "If John", "surfing"),
        (
            "Hypothetical John likes surfing.",
            "Hypothetical John",
            "surfing",
        ),
    ],
)
def test_ground_extraction_rejects_clause_markers_swallowed_by_fields(
    text,
    subject,
    obj,
):
    raw = {
        "claims": [{
            "subject": subject,
            "relation": "likes",
            "object": obj,
            "epistemic_basis": "explicit",
        }]
    }
    assert ground_extraction(raw, text).claims == ()


@pytest.mark.parametrize(
    "text",
    [
        "John does not like skiing.",
        "Does John like skiing?",
        'Mary said "John like skiing."',
        'John wrote "like skiing".',
        "John pretended to like skiing.",
        "John wants to like skiing.",
        "John hopes to like skiing.",
        "John intends to like skiing.",
        "John has 0 cats.",
        "John has 3 cats.",
        "John ranked #2 nationally.",
        "¬John likes skiing.",
        "John ¬ likes skiing.",
        "«John like skiing.»",
        "‹John like skiing.›",
        "「John like skiing.」",
        "『John like skiing.』",
        "`John like skiing.`",
    ],
)
def test_ground_extraction_rejects_negated_question_or_reported_fact(text):
    subject = "John"
    relation = "like"
    obj = "skiing"
    if "cats" in text:
        relation = "has"
        obj = "cats"
    elif "ranked" in text:
        relation = "ranked"
        obj = "nationally"
    raw = {
        "claims": [
            {
                "subject": subject,
                "relation": relation,
                "object": obj,
            }
        ]
    }
    assert ground_extraction(raw, text).claims == ()


@pytest.mark.parametrize(
    ("text", "relation"),
    [
        ("John does not like skiing.", "does not like"),
        ("John really likes skiing.", "really likes"),
        ("John pretended to like skiing.", "pretended to like"),
    ],
)
def test_ground_extraction_keeps_gap_free_predicate_phrase(text, relation):
    raw = {
        "claims": [
            {
                "subject": "John",
                "relation": relation,
                "object": "skiing",
                "epistemic_basis": "explicit",
            }
        ]
    }
    [claim] = ground_extraction(raw, text).claims
    assert claim.relation == relation


@pytest.mark.parametrize(
    "text",
    [
        "[John 2024-01-01] Mary likes skiing.",
        "[John 2024-01-01] Mary said she likes skiing.",
    ],
)
def test_ground_extraction_rejects_speaker_prefix_as_claim_subject(text):
    raw = {
        "claims": [
            {
                "subject": "John",
                "relation": "likes",
                "object": "skiing",
            }
        ]
    }
    assert ground_extraction(raw, text).claims == ()


# --- compile_nl integration with a stub extractor (no Ollama) -----------------

class _StubExtractor:
    """Returns a fixed grounded extraction for the Priya sentence, empty otherwise
    (so the floor fallback is exercised)."""

    def extract(self, text: str) -> Extraction:
        if "Priya" in text:
            return Extraction(
                entities=(ExtractedEntity("Priya", "person"), ExtractedEntity("billing service", "thing")),
                claims=(ExtractedClaim("Priya", "owns", "the billing service"),),
            )
        return Extraction()


class _FirstPersonExtractor:
    def __init__(self):
        self.inputs = []

    def extract(self, text: str) -> Extraction:
        self.inputs.append(text)
        return ground_extraction(
            {
                "entities": [
                    {"name": "I", "type": "person"},
                    {"name": "surfing", "type": "activity"},
                ],
                "claims": [
                    {
                        "subject": "I",
                        "relation": "like",
                        "object": "surfing",
                        "epistemic_basis": "explicit",
                    }
                ],
            },
            text,
        )


def test_compile_nl_extractor_adds_real_triples_and_keeps_content():
    batch = compile_nl("Priya owns the billing service.", extractor=_StubExtractor())
    claims = [r for r in batch.records if r.kind == RecordKind.CLM]
    predicates = {c.attrs.get("predicate") for c in claims}
    # the floor's verbatim content claim is kept (coverage / temporal retention)
    assert "content" in predicates
    # the extractor's REAL relation lands as a claim
    assert "owns" in predicates
    # the object's common-noun entity is now extracted (the floor missed it)
    labels = {str(r.attrs.get("label", "")).lower() for r in batch.records if r.kind == RecordKind.ENT}
    assert "priya" in labels and "billing service" in labels
    # every claim subject resolves to a grounded ENT (no fabrication)
    ent_ids = {r.id for r in batch.records if r.kind == RecordKind.ENT}
    assert all(c.attrs.get("subject") in ent_ids for c in claims)


def test_grounded_clm_rebases_first_person_to_explicit_turn_speaker():
    text = "[John 2023-05-01] I like surfing."
    floor = compile_nl(text)
    extractor = _FirstPersonExtractor()
    rich = compile_nl(
        text,
        extractor=extractor,
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V1,
    )

    floor_raw = next(record for record in floor.records if record.kind == RecordKind.RAW)
    rich_raw = next(record for record in rich.records if record.kind == RecordKind.RAW)
    assert extractor.inputs == ["I like surfing."]
    assert rich_raw.id == floor_raw.id
    assert rich_raw.attrs["content"] == floor_raw.attrs["content"] == text
    assert rich_raw.ext["source_metadata"] == {
        "format": "locomo-turn/1",
        "speaker": "John",
        "timestamp": "2023-05-01",
        "prefix_end": text.index("I"),
    }

    floor_content_ids = {
        record.id
        for record in floor.records
        if record.kind == RecordKind.CLM
        and record.attrs.get("predicate") == "content"
    }
    rich_content_ids = {
        record.id
        for record in rich.records
        if record.kind == RecordKind.CLM
        and record.attrs.get("predicate") == "content"
    }
    assert rich_content_ids == floor_content_ids
    floor_ids = {record.id for record in floor.records}
    candidate_only = [
        record for record in rich.records if record.id not in floor_ids
    ]
    assert candidate_only
    assert all(
        record.kind == RecordKind.CLM
        and record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
        for record in candidate_only
    )

    fact = next(
        record
        for record in rich.records
        if record.kind == RecordKind.CLM
        and record.attrs.get("predicate") == "like"
    )
    by_id = rich.by_id()
    speaker_ent = by_id[fact.attrs["subject"]]
    assert fact.id.startswith(f"clm:{floor_raw.id.split(':', 1)[1]}:derived:")
    assert fact.attrs["subject_label"] == "John"
    assert speaker_ent.attrs == {"entity_type": "person", "label": "John"}
    assert fact.attrs["facets"]["who"] == "John"
    assert fact.ext["subject_resolution"] == {
        "method": "first_person_to_turn_speaker",
        "surface": "I",
        "speaker": "John",
    }
    assert {
        span["field"] for span in fact.ext["grounded_spans"]
    } >= {"subject", "relation", "object"}
    assert all(
        text[span["start"]:span["end"]] == span["text"]
        for span in fact.ext["grounded_spans"]
    )
    labels = {
        str(record.attrs.get("label") or "").lower()
        for record in rich.records
        if record.kind == RecordKind.ENT
    }
    assert "i" not in labels


def test_speaker_metadata_is_ignored_when_rich_extraction_is_off():
    text = "[John 2023-05-01] I like surfing."
    baseline = compile_nl(text)
    annotated = compile_nl(
        text,
        speaker="John",
        source_timestamp="2023-05-01",
    )

    def stable(batch):
        payload = []
        for record in batch.records:
            item = record.to_dict()
            item.pop("created_at")
            item.pop("updated_at")
            payload.append(item)
        return payload

    assert stable(annotated) == stable(baseline)


def test_candidate_policy_does_not_index_rich_claim_without_canonical_turn():
    batch = compile_nl(
        "Mary likes skiing.",
        extractor=_StubExtractor(),
        speaker="John",
        source_timestamp="not-a-date",
        derived_fact_policy=GROUNDED_CLM_V1,
    )
    assert not any(
        record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
        for record in batch.records
    )
    assert {
        record.attrs.get("predicate")
        for record in batch.records
        if record.kind == RecordKind.CLM
    } == {"content"}


@pytest.mark.parametrize(
    ("body", "subject", "relation", "obj"),
    [
        ("Mary likes skiing.", "Mary", "likes", "skiing"),
        (
            "My favorite sport is surfing.",
            "My favorite sport",
            "is",
            "surfing",
        ),
        ("I've visited Paris.", "I've", "visited", "Paris"),
        ("We like surfing.", "We", "like", "surfing"),
        ("¬I like surfing.", "¬I", "like", "surfing"),
        ("~I like surfing.", "~I", "like", "surfing"),
        ("(I) like surfing.", "(I)", "like", "surfing"),
    ],
)
def test_candidate_policy_does_not_index_unresolved_subjects(
    body,
    subject,
    relation,
    obj,
):
    class UnresolvedExtractor:
        def extract(self, text):
            return ground_extraction(
                {
                    "entities": [
                        {"name": subject, "type": "person"},
                        {"name": obj, "type": "entity"},
                    ],
                    "claims": [{
                        "subject": subject,
                        "relation": relation,
                        "object": obj,
                        "epistemic_basis": "explicit",
                    }],
                },
                text,
            )

    text = f"[John 2023-05-01] {body}"
    baseline = compile_nl(text)
    candidate = compile_nl(
        text,
        extractor=UnresolvedExtractor(),
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V1,
    )
    assert not any(
        record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
        for record in candidate.records
    )
    assert {
        record.id for record in candidate.records
    } == {
        record.id for record in baseline.records
    }


def test_candidate_revalidates_extractor_attrs_before_indexing():
    class LyingExtractor:
        def extract(self, text):
            return Extraction(
                claims=(
                    ExtractedClaim(
                        "I",
                        "fabricated relation",
                        "fabricated object",
                        epistemic_basis="explicit",
                        source_spans=(
                            GroundedSpan("subject", "I", 0, 1),
                            GroundedSpan("relation", "like", 2, 6),
                            GroundedSpan("object", "surfing", 7, 14),
                        ),
                    ),
                ),
            )

    text = "[John 2023-05-01] I like surfing."
    baseline = compile_nl(text)
    candidate = compile_nl(
        text,
        extractor=LyingExtractor(),
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V1,
    )
    assert not any(
        record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
        for record in candidate.records
    )
    assert {record.id for record in candidate.records} == {
        record.id for record in baseline.records
    }


def test_quoted_or_conflicting_first_person_subject_fails_closed():
    for text in (
        '[John 2023-05-01] Mary said "I like surfing."',
        "[John 2023-05-01] Mary said 'I like surfing.'",
    ):
        quoted = compile_nl(
            text,
            extractor=_FirstPersonExtractor(),
            speaker="John",
            source_timestamp="2023-05-01",
            derived_fact_policy=GROUNDED_CLM_V1,
        )
        quoted_facts = [
            record
            for record in quoted.records
            if record.kind == RecordKind.CLM
            and record.attrs.get("predicate") == "like"
        ]
        assert quoted_facts == []

    conflicting = compile_nl(
        "Alice: I like surfing.",
        extractor=_FirstPersonExtractor(),
        speaker="John",
        derived_fact_policy=GROUNDED_CLM_V1,
    )
    conflicting_facts = [
        record
        for record in conflicting.records
        if record.kind == RecordKind.CLM
        and record.attrs.get("predicate") == "like"
    ]
    assert conflicting_facts == []


def test_compile_nl_falls_back_to_floor_when_extractor_returns_empty():
    batch = compile_nl("The kettle is on the counter.", extractor=_StubExtractor())
    predicates = {r.attrs.get("predicate") for r in batch.records if r.kind == RecordKind.CLM}
    assert "content" in predicates  # floor path
    assert "owns" not in predicates  # the stub returned nothing for this text


# --- entity-to-entity REL edges (HISTORY#321/#323 cat1 aggregation lever) -----
#
# Real ir_edges only exist for retrieval if extractor-derived triples produce
# a genuine REL between two grounded entities, not just a verbatim CLM (whose
# `object` is text, never an id). See seam_runtime/storage.py's coreference
# pass for the other half (stable ids across turns).

class _EntityRelationExtractor:
    """Both subject and object of the one claim are extractor-flagged entities."""

    config_fingerprint = "entity-relation-fixture/1"

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "provider-free-fixture",
            "model": "none",
            "prompt_version": "fixture/1",
        }

    def extract(self, text: str) -> Extraction:
        if "mentored" in text:
            return Extraction(
                entities=(ExtractedEntity("Akira", "person"), ExtractedEntity("Priya", "person")),
                claims=(ExtractedClaim("Akira", "mentored", "Priya"),),
            )
        return Extraction()


def test_entity_to_entity_claim_emits_a_rel_edge():
    batch = compile_nl("Akira mentored Priya at the community center.", extractor=_EntityRelationExtractor())
    ents = {r.attrs["label"]: r.id for r in batch.records if r.kind == RecordKind.ENT}
    rels = [r for r in batch.records if r.kind == RecordKind.REL]
    assert len(rels) == 1
    assert rels[0].attrs["src"] == ents["Akira"]
    assert rels[0].attrs["predicate"] == "mentored"
    assert rels[0].attrs["dst"] == ents["Priya"]
    claim = batch.by_id()[rels[0].attrs["claim_id"]]
    assert claim.kind == RecordKind.CLM
    assert claim.attrs["subject"] == ents["Akira"]
    assert claim.attrs["predicate"] == "mentored"
    assert claim.attrs["object"] == "Priya"
    assert rels[0].evidence == claim.evidence
    assert rels[0].prov == claim.prov
    assert rels[0].ext["grounded_spans"] == claim.ext["grounded_spans"]
    assert rels[0].ext["extractor"] == _EntityRelationExtractor().config_metadata()
    assert (
        rels[0].ext["extractor_config_fingerprint"]
        == _EntityRelationExtractor.config_fingerprint
    )


def test_descriptive_object_does_not_emit_a_rel_edge():
    """A claim's object that is NOT a flagged entity (a description, not a
    thing to link) must not produce a spurious REL -- only the verbatim CLM."""

    class _DescriptiveObjectExtractor:
        def extract(self, text: str) -> Extraction:
            # "Priya" is the only flagged entity; the object is a plain
            # description the extractor never listed as an entity.
            return Extraction(
                entities=(ExtractedEntity("Priya", "person"),),
                claims=(ExtractedClaim("Priya", "teaches", "an evening pottery class"),),
            )

    batch = compile_nl("Priya teaches an evening pottery class.", extractor=_DescriptiveObjectExtractor())
    rels = [r for r in batch.records if r.kind == RecordKind.REL]
    assert rels == []


def test_rel_matches_object_despite_leading_determiner():
    """The claim object often carries a determiner ("the billing service")
    that the standalone entity name ("billing service") does not; the REL
    gate must match on content words, not exact string equality."""

    class _DeterminerExtractor:
        def extract(self, text: str) -> Extraction:
            return Extraction(
                entities=(ExtractedEntity("Priya", "person"), ExtractedEntity("billing service", "thing")),
                claims=(ExtractedClaim("Priya", "owns", "the billing service"),),
            )

    batch = compile_nl("Priya owns the billing service.", extractor=_DeterminerExtractor())
    rels = [r for r in batch.records if r.kind == RecordKind.REL]
    assert len(rels) == 1
    assert rels[0].attrs["predicate"] == "owns"


def test_extractor_from_env_defaults_to_floor(monkeypatch):
    monkeypatch.delenv("SEAM_NL_EXTRACTOR", raising=False)
    assert extractor_from_env() is None
    monkeypatch.setenv("SEAM_NL_EXTRACTOR", "ollama")
    from seam_runtime.nl_extract import OllamaExtractor

    assert isinstance(extractor_from_env(), OllamaExtractor)


def test_strict_ollama_extractor_fails_closed_and_records_config(monkeypatch):
    from seam_runtime.nl_extract import OllamaExtractor

    extractor = OllamaExtractor(
        model="unit-model",
        model_digest="sha256:unit-digest",
        timeout=1,
        num_predict=64,
        strict=True,
    )
    monkeypatch.setattr(
        extractor,
        "_installed_model_digest",
        lambda: "sha256:unit-digest",
    )
    monkeypatch.setattr(
        extractor,
        "_generate",
        lambda text: (_ for _ in ()).throw(TimeoutError("slow")),
    )
    with pytest.raises(RuntimeError, match="grounded fact extraction failed"):
        extractor.extract("John likes surfing.")

    metadata = extractor.config_metadata()
    assert metadata["model"] == "unit-model"
    assert metadata["model_digest"] == "sha256:unit-digest"
    assert metadata["num_predict"] == 64
    assert metadata["strict"] is True
    assert metadata["timeout"] == 1
    assert len(str(metadata["prompt_fingerprint"])) == 64


def test_strict_ollama_extractor_rejects_digest_drift(monkeypatch):
    from seam_runtime.nl_extract import OllamaExtractor

    extractor = OllamaExtractor(
        model="unit-model",
        model_digest="sha256:one",
        strict=True,
    )
    installed = iter(("sha256:one", "sha256:two"))
    monkeypatch.setattr(
        extractor,
        "_installed_model_digest",
        lambda: next(installed),
    )
    assert extractor.config_metadata()["model_digest"] == "sha256:one"
    monkeypatch.setattr(
        extractor,
        "_generate",
        lambda text: pytest.fail("drift must stop generation"),
    )
    with pytest.raises(RuntimeError, match="grounded fact extraction failed"):
        extractor.extract("John likes surfing.")


class _CompoundFirstPersonExtractor:
    """Emits the two per-clause triples a real model returns for a compound turn."""

    def extract(self, text: str) -> Extraction:
        return ground_extraction(
            {
                "entities": [{"name": "I", "type": "person"}],
                "claims": [
                    {"subject": "I", "relation": "love", "object": "surfing",
                     "epistemic_basis": "explicit"},
                    {"subject": "I", "relation": "go to",
                     "object": "the beach every weekend",
                     "epistemic_basis": "explicit"},
                ],
            },
            text,
        )


def _derived_facts(batch):
    from seam_runtime.derived_fact_context import is_eligible_derived_claim

    return [
        record
        for record in batch.records
        if record.kind == RecordKind.CLM
        and record.ext.get("derived_fact_policy")
        and is_eligible_derived_claim(record, policy=record.ext["derived_fact_policy"])
    ]


def test_clause_window_isolates_selfclaim_in_compound_sentence():
    from seam_runtime.nl_extract import clause_window

    src = "I love surfing and I go to the beach every weekend"
    # first clause: subject "I" [0:1], object "surfing" ends at 14
    assert src[slice(*clause_window(src, 0, 14))] == "I love surfing "
    # second clause: subject "I" at 19
    second = src.index("I", 15)
    assert src[slice(*clause_window(src, second, len(src)))].strip() == (
        "I go to the beach every weekend"
    )


def test_grounded_clm_v2_admits_clause_scoped_selfclaim_v1_rejects():
    text = "[John 2023-05-01] I love surfing and I go to the beach every weekend."
    strict = compile_nl(
        text,
        extractor=_CompoundFirstPersonExtractor(),
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V1,
    )
    relaxed = compile_nl(
        text,
        extractor=_CompoundFirstPersonExtractor(),
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V2,
    )
    # grounded-clm/1 requires the S-R-O to fill the whole proposition -> nothing.
    assert _derived_facts(strict) == []
    # grounded-clm/2 admits the clean self-claim inside the compound sentence,
    # rebased to the turn speaker.
    facts = _derived_facts(relaxed)
    rendered = {
        (f.attrs["subject_label"], f.attrs["predicate"], f.attrs["object"])
        for f in facts
    }
    assert ("John", "love", "surfing") in rendered


def test_grounded_clm_v2_still_rejects_non_first_person_like_v1():
    # A bare non-first-person turn yields no derived fact under either policy.
    text = "[John 2023-05-01] The weather is nice today."
    for policy in (GROUNDED_CLM_V1, GROUNDED_CLM_V2):
        batch = compile_nl(
            text,
            extractor=_CompoundFirstPersonExtractor(),
            speaker="John",
            source_timestamp="2023-05-01",
            derived_fact_policy=policy,
        )
        # extractor grounds against the (non-matching) body -> no rebased claim
        assert _derived_facts(batch) == []


def test_v2_policy_plumbing_and_rendering():
    from seam_runtime.derived_fact_context import (
        DerivedFactsConfig,
        resolve_derived_facts_policy,
    )
    from seam_runtime.vector import SQLiteVectorIndex

    assert resolve_derived_facts_policy("grounded-clm/2") == GROUNDED_CLM_V2
    assert DerivedFactsConfig(policy=GROUNDED_CLM_V2, fingerprint="x", payload={}).enabled

    relaxed = compile_nl(
        "[John 2023-05-01] I love surfing and I go to the beach every weekend.",
        extractor=_CompoundFirstPersonExtractor(),
        speaker="John",
        source_timestamp="2023-05-01",
        derived_fact_policy=GROUNDED_CLM_V2,
    )
    fact = _derived_facts(relaxed)[0]
    # a v2 fact renders as "subject predicate object" for embedding, same as v1
    assert SQLiteVectorIndex.render_record_text(fact) == "John love surfing"


def test_decode_model_json_accepts_a_bare_object():
    decoded = _decode_model_json('{"entities": [], "claims": []}')
    assert decoded == {"entities": [], "claims": []}


def test_decode_model_json_unwraps_a_markdown_fence():
    """Ollama's ``format`` schema constrains JSON shape, not fencing.

    Gemma 4 returns a fenced block. Before this, ``json.loads`` raised and the
    non-strict path returned an empty Extraction, so a formatting difference read
    as zero extractable facts (measured: 0.0 items/turn, then 3.8 after the fix).
    """
    fenced = '```json\n{"entities": [{"name": "Maria", "type": "person"}], "claims": []}\n```'
    assert _decode_model_json(fenced) == {
        "entities": [{"name": "Maria", "type": "person"}],
        "claims": [],
    }


def test_decode_model_json_unwraps_an_unlabelled_fence():
    assert _decode_model_json('```\n{"claims": []}\n```') == {"claims": []}


def test_decode_model_json_rejects_non_json():
    """Unwrapping is presentation-level and must not become a salvage path."""
    with pytest.raises(ValueError):
        _decode_model_json("I could not find any claims in that sentence.")
    with pytest.raises(ValueError):
        _decode_model_json("```json\nnot json at all\n```")


def test_fenced_output_still_passes_the_grounding_gate():
    """Unwrapping grants no trust: fabricated spans are dropped exactly as before."""
    text = "Maria got a cat named Bailey."
    raw = _decode_model_json(
        '```json\n{"entities": [{"name": "Bailey", "type": "pet"},'
        ' {"name": "Reginald", "type": "person"}],'
        ' "claims": [{"subject": "Maria", "relation": "got", "object": "a cat named Bailey"},'
        ' {"subject": "Maria", "relation": "sold", "object": "a boat"}]}\n```'
    )
    extraction = ground_extraction(raw, text)
    assert [entity.name for entity in extraction.entities] == ["Bailey"]
    assert [claim.obj for claim in extraction.claims] == ["a cat named Bailey"]
