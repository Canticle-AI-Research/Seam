"""CI-safe unit tests for the HISTORY#322 entity-aggregation lever (default OFF).

The lever is measured *marginal* on cat1 answer quality (see
docs/audits/2026-06-15-entity-aggregation-retrieval.md); these tests pin its
mechanics (entity extraction, subject re-attribution, query-relevance ranking,
cap, default-off) and the local Ollama answerer dispatch. All network-free.
"""

from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind


def _clm(subject_id: str, obj: str) -> MIRLRecord:
    return MIRLRecord(
        id=f"clm:{abs(hash((subject_id, obj)))}",
        kind=RecordKind.CLM,
        attrs={"subject": subject_id, "predicate": "content", "object": obj},
    )


def _ent(ent_id: str, label: str) -> MIRLRecord:
    return MIRLRecord(id=ent_id, kind=RecordKind.ENT, attrs={"label": label, "entity_type": "person"})


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def load_ir(self, ids=None, ns=None):
        return IRBatch(list(self._records))


class _FakeRuntime:
    def __init__(self, records):
        self.store = _FakeStore(records)


def test_question_entities_handles_multiword_acronym_and_stopword_trim():
    a = SeamLocomoAdapter(answerer=None)
    assert a._question_entities("What did Caroline research?") == ["Caroline"]
    # Sentence-start stopword glued into the run is trimmed.
    assert a._question_entities("Did Caroline make the bowl?") == ["Caroline"]
    # Multi-word proper noun + acronym both captured; title trimmed.
    assert a._question_entities("Where does Mr Smith live in New York?") == ["Smith", "New York"]
    assert a._question_entities("When did the LGBTQ group meet?") == ["LGBTQ"]
    # Pure pronoun question yields no entity.
    assert a._question_entities("How is she feeling?") == []


def test_stem_strips_common_suffixes():
    s = SeamLocomoAdapter._stem
    assert s("instruments") == "instrument"
    assert s("played") == "play"
    assert s("playing") == "play"
    assert s("plays") == "play"
    # Too-short stems are left intact.
    assert s("bus") == "bus"


def test_entity_aggregate_reattributes_subject_and_query_ranks():
    a = SeamLocomoAdapter(answerer=None)
    records = [
        _ent("ent:caroline", "Caroline"),
        _clm("ent:caroline", "I went hiking last weekend"),       # off-topic
        _clm("ent:caroline", "I researched adoption agencies"),   # the needle
    ]
    out = a._entity_aggregate(_FakeRuntime(records), "What did Caroline research?")
    # First-person object is re-attributed to the named entity (coreference fix).
    assert "Caroline: I researched adoption agencies" in out
    # Query-relevant claim ('research') ranks ABOVE the off-topic one.
    assert out.index("researched adoption") < out.index("went hiking")


def test_entity_aggregate_caps_to_max_claims_keeping_relevant_first():
    a = SeamLocomoAdapter(answerer=None)
    a._entity_agg_max_claims = 1
    records = [
        _ent("ent:caroline", "Caroline"),
        _clm("ent:caroline", "I went hiking last weekend"),
        _clm("ent:caroline", "I researched adoption agencies"),
    ]
    out = a._entity_aggregate(_FakeRuntime(records), "What did Caroline research?")
    assert "researched adoption" in out      # the relevant claim survives the cap
    assert "went hiking" not in out


def test_entity_aggregate_empty_without_entity():
    a = SeamLocomoAdapter(answerer=None)
    records = [_ent("ent:caroline", "Caroline"), _clm("ent:caroline", "I like tea")]
    assert a._entity_aggregate(_FakeRuntime(records), "How is it going?") == ""


def test_entity_aggregation_default_off():
    assert SeamLocomoAdapter(answerer=None)._entity_aggregation is False
    assert SeamLocomoAdapter(answerer=None, entity_aggregation=True)._entity_aggregation is True


def test_ollama_answerer_dispatch(monkeypatch):
    captured = {}

    def fake_ollama(model, prompt, **kwargs):
        captured["model"] = model
        return "Adoption agencies"

    monkeypatch.setattr(
        "benchmarks.external.locomo.adapters.seam._ollama_short_answer", fake_ollama
    )
    a = SeamLocomoAdapter(answerer="ollama")
    assert a._generate_answer("What did Caroline research?", "- Caroline: adoption agencies") == "Adoption agencies"
    assert captured["model"] == "qwen2.5:3b"
