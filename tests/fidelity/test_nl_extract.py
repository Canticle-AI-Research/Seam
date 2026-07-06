"""The opt-in rich extractor (Stage 4): the grounding firewall + compile_nl wiring.

CI-safe and model-free: a local Ollama model can't run in CI, so these pin the
DETERMINISTIC parts — `ground_extraction` (the fabrication gate) and the
`compile_nl(extractor=...)` integration with a stub extractor. The real-model
`sr`->~1.0 validation is recorded in HISTORY, not run here (the strict-no-skip
policy forbids a skipping test).
"""

from __future__ import annotations

from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.nl_extract import (
    ExtractedClaim,
    ExtractedEntity,
    Extraction,
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


def test_ground_extraction_empty_on_garbage_or_ungrounded():
    assert ground_extraction({}, "x").is_empty()
    assert ground_extraction("not a dict", "x").is_empty()
    # every span foreign to the text -> nothing survives
    raw = {"claims": [{"subject": "foo", "relation": "bar", "object": "baz"}]}
    assert ground_extraction(raw, "totally different sentence").is_empty()


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


def test_compile_nl_falls_back_to_floor_when_extractor_returns_empty():
    batch = compile_nl("The kettle is on the counter.", extractor=_StubExtractor())
    predicates = {r.attrs.get("predicate") for r in batch.records if r.kind == RecordKind.CLM}
    assert "content" in predicates  # floor path
    assert "owns" not in predicates  # the stub returned nothing for this text


def test_extractor_from_env_defaults_to_floor(monkeypatch):
    monkeypatch.delenv("SEAM_NL_EXTRACTOR", raising=False)
    assert extractor_from_env() is None
    monkeypatch.setenv("SEAM_NL_EXTRACTOR", "ollama")
    from seam_runtime.nl_extract import OllamaExtractor

    assert isinstance(extractor_from_env(), OllamaExtractor)
