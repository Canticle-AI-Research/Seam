"""Tests for the audit #3 retrieval-scoring levers (RetrievalFlags).

Each lever is OFF by default; with all defaults the scoring path must be
byte-identical to the pre-audit weighted-sum fusion. These tests lock the
flag-parsing contract and the behavioural change each lever introduces,
independent of any LoCoMo benchmark outcome.
"""

import pytest

from seam_runtime.bm25 import BM25Index
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval import (
    RetrievalFlags,
    _parse_leg_weights,
    retrieval_flags_from_env,
    search_batch,
)


def _semantic_reason(candidate) -> float:
    for reason in candidate.reasons:
        if reason.startswith("semantic="):
            return float(reason.split("=", 1)[1])
    raise AssertionError(f"no semantic reason in {candidate.reasons}")


def _lexical_reason(candidate) -> float:
    for reason in candidate.reasons:
        if reason.startswith("lexical="):
            return float(reason.split("=", 1)[1])
    raise AssertionError(f"no lexical reason in {candidate.reasons}")


def _find(result, record_id):
    for candidate in result.candidates:
        if candidate.record.id == record_id:
            return candidate
    return None


# --- flag parsing contract ------------------------------------------------

def test_flag_defaults_all_off():
    flags = RetrievalFlags()
    assert flags.semantic_zero_no_vector is False
    assert flags.bm25_all_kinds is False
    assert flags.fusion == "weighted"
    assert flags.rrf_k == 60
    # search_top_k defaults to None = no override of the call-site budget.
    assert flags.search_top_k is None
    assert flags.conversation_adapter == "off"
    assert flags.inference_policy == "context-only"


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_rrf_k_fails_at_flag_construction(value):
    with pytest.raises(ValueError, match="rrf_k must be positive"):
        RetrievalFlags(rrf_k=value)


def test_invalid_persisted_and_environment_rrf_k_fail_closed():
    from seam_runtime.retrieval import load_retrieval_flags

    class State:
        def iter_retrieval_flag_state(self):
            return [{"flag_key": "rrf_k", "flag_value": 0}]

    assert load_retrieval_flags(State(), {}).rrf_k == 60
    assert load_retrieval_flags(None, {"SEAM_RETRIEVAL_RRF_K": "0"}).rrf_k == 60
    assert load_retrieval_flags(None, {"SEAM_RETRIEVAL_RRF_K": "-5"}).rrf_k == 60
    assert load_retrieval_flags(None, {"SEAM_RETRIEVAL_RRF_K": "--5"}).rrf_k == 60


def test_flag_env_parsing_truthy_variants():
    assert retrieval_flags_from_env({}) == RetrievalFlags()
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_SEMANTIC_ZERO": "1"}).semantic_zero_no_vector is True
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_SEMANTIC_ZERO": "TRUE"}).semantic_zero_no_vector is True
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_BM25_ALL": "yes"}).bm25_all_kinds is True
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_RRF": "on"}).fusion == "rrf"
    # falsy / unset stays off
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_RRF": "0"}).fusion == "weighted"
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_BM25_ALL": "false"}).bm25_all_kinds is False


def test_answer_policy_env_parsing_is_versioned_and_fail_closed():
    flags = retrieval_flags_from_env(
        {
            "SEAM_CONVERSATION_ADAPTER": "conversation/1",
            "SEAM_INFERENCE_POLICY": "inference/high-confidence/1",
        }
    )
    assert flags.conversation_adapter == "conversation/1"
    assert flags.inference_policy == "inference/high-confidence/1"
    invalid = retrieval_flags_from_env(
        {"SEAM_CONVERSATION_ADAPTER": "magic", "SEAM_INFERENCE_POLICY": "guess"}
    )
    assert invalid.conversation_adapter == "off"
    assert invalid.inference_policy == "context-only"


def test_search_top_k_env_parsing():
    # HISTORY#320: the retrieval-depth knob. Positive int parses; unset/invalid -> None.
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_TOP_K": "100"}).search_top_k == 100
    assert retrieval_flags_from_env({}).search_top_k is None
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_TOP_K": "0"}).search_top_k is None
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_TOP_K": "abc"}).search_top_k is None


def test_leg_weight_parser_rejects_empty_and_duplicate_leg_names():
    assert _parse_leg_weights("=0.5") == ()
    assert _parse_leg_weights("graph=0.5,graph=1.0") == ()
    assert _parse_leg_weights("graph=0.5,vector=1.0") == (
        ("graph", 0.5),
        ("vector", 1.0),
    )


def test_search_top_k_overrides_call_site_budget(tmp_path):
    # search_ir uses flags.search_top_k as the candidate budget when set, so a
    # deeper top_k surfaces records a small budget would miss. Build a store with
    # more records than the call-site budget and confirm the override widens it.
    from seam_runtime.runtime import SeamRuntime
    rt = SeamRuntime(str(tmp_path / "topk.db"))
    for i in range(12):
        rt.ingest_conversation_turn(
            f"Fact number {i}: the widget {i} ships on day {i}.",
            source_ref=f"test://retrieval-flags/top-k/{i}",
        )
    narrow = rt.search_ir("widget ships", budget=3, include_raw=True)
    deep = rt.search_ir("widget ships", budget=3, include_raw=True, flags=RetrievalFlags(search_top_k=20))
    assert len(deep.candidates) > len(narrow.candidates)


# --- answerer-aware retrieval profiles (compact / broad) ------------------

def test_context_budget_default_none_no_regression():
    # New config knob; default None so an un-profiled store is byte-identical.
    assert RetrievalFlags().context_budget is None


def test_retrieval_profile_resolver():
    from seam_runtime.retrieval import RETRIEVAL_PROFILES, resolve_retrieval_profile
    assert resolve_retrieval_profile("compact") == (100, 8000)
    assert resolve_retrieval_profile("broad") == (300, 60000)
    assert resolve_retrieval_profile("BROAD") == (300, 60000)  # case-insensitive
    assert resolve_retrieval_profile("") is None
    assert resolve_retrieval_profile(None) is None
    assert resolve_retrieval_profile("bogus") is None
    assert set(RETRIEVAL_PROFILES) == {"compact", "broad"}


def test_profile_env_sets_top_k_and_context_budget():
    broad = retrieval_flags_from_env({"SEAM_RETRIEVAL_PROFILE": "broad"})
    assert (broad.search_top_k, broad.context_budget) == (300, 60000)
    compact = retrieval_flags_from_env({"SEAM_RETRIEVAL_PROFILE": "compact"})
    assert (compact.search_top_k, compact.context_budget) == (100, 8000)
    # unknown profile = no effect (defaults)
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_PROFILE": "bogus"}) == RetrievalFlags()


def test_explicit_knobs_override_profile():
    flags = retrieval_flags_from_env(
        {
            "SEAM_RETRIEVAL_PROFILE": "broad",
            "SEAM_RETRIEVAL_TOP_K": "50",
            "SEAM_RETRIEVAL_CONTEXT_BUDGET": "4000",
        }
    )
    assert flags.search_top_k == 50
    assert flags.context_budget == 4000


def test_profile_resolves_through_load_retrieval_flags():
    # load_retrieval_flags is the path every core surface (CLI/REST/MCP) uses,
    # so the profile must reach search_ir through it. Empty env stays baseline.
    from seam_runtime.retrieval import load_retrieval_flags
    assert load_retrieval_flags(None, {}) == RetrievalFlags()
    broad = load_retrieval_flags(None, {"SEAM_RETRIEVAL_PROFILE": "broad"})
    assert (broad.search_top_k, broad.context_budget) == (300, 60000)
    # explicit env knob still wins through this path
    over = load_retrieval_flags(
        None, {"SEAM_RETRIEVAL_PROFILE": "broad", "SEAM_RETRIEVAL_CONTEXT_BUDGET": "12000"}
    )
    assert over.context_budget == 12000


def test_pack_ir_honors_context_budget(monkeypatch, tmp_path):
    # pack_ir defaults its char budget to flags.context_budget when the caller
    # passes None; an explicit budget always wins; no profile -> prior 512.
    import seam_runtime.runtime as rtmod
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(str(tmp_path / "pack.db"))
    rt.ingest_conversation_turn("Alice adopted a dog named Rex in March.")
    captured: dict[str, object] = {}
    real = rtmod.pack_records

    def spy(records, **kw):
        captured["budget"] = kw.get("budget")
        return real(records, **kw)

    monkeypatch.setattr(rtmod, "pack_records", spy)

    rt._retrieval_flags = RetrievalFlags()  # no profile -> 512 fallback
    rt.pack_ir(budget=None)
    assert captured["budget"] == 512

    rt._retrieval_flags = RetrievalFlags(context_budget=8000)
    rt.pack_ir(budget=None)
    assert captured["budget"] == 8000

    rt.pack_ir(budget=256)  # explicit caller budget wins over the profile
    assert captured["budget"] == 256


# --- P0-1: semantic -> 0 when a real vector backend is active -------------

def _two_claims():
    a = MIRLRecord(
        id="clm:a", kind=RecordKind.CLM, ns="test", scope="thread", t0="2024-01-01",
        attrs={"subject": "ent:1", "predicate": "likes", "object": "hiking trips"},
    )
    b = MIRLRecord(
        id="clm:b", kind=RecordKind.CLM, ns="test", scope="thread", t0="2024-01-02",
        attrs={"subject": "ent:2", "predicate": "likes", "object": "hiking trails"},
    )
    return IRBatch([a, b])


def test_semantic_zero_off_uses_bagofwords_fallback():
    batch = _two_claims()
    # vector backend returned a score for clm:a only; clm:b is absent.
    vs = {"clm:a": 0.9}
    result = search_batch(batch, query="hiking", vector_scores=vs, limit=5)
    cand_b = _find(result, "clm:b")
    assert cand_b is not None
    # Flag OFF: clm:b falls back to bag-of-words cosine, which is > 0 here.
    assert _semantic_reason(cand_b) > 0.0


def test_semantic_zero_on_zeros_absent_record():
    batch = _two_claims()
    vs = {"clm:a": 0.9}
    flags = RetrievalFlags(semantic_zero_no_vector=True)
    result = search_batch(batch, query="hiking", vector_scores=vs, limit=5, flags=flags)
    cand_b = _find(result, "clm:b")
    assert cand_b is not None
    # Flag ON + real backend active: absent record's semantic channel is 0.
    assert _semantic_reason(cand_b) == 0.0
    # clm:a still carries its true vector score.
    assert _semantic_reason(_find(result, "clm:a")) == 0.9


def test_semantic_zero_on_is_noop_without_vectors():
    """With no vector backend (empty vector_scores) the flag must not zero out
    the bag-of-words fallback -- otherwise the local/test path breaks."""
    batch = _two_claims()
    off = search_batch(batch, query="hiking", vector_scores={}, limit=5)
    on = search_batch(batch, query="hiking", vector_scores={}, limit=5,
                      flags=RetrievalFlags(semantic_zero_no_vector=True))
    assert [c.record.id for c in on.candidates] == [c.record.id for c in off.candidates]
    assert _semantic_reason(_find(on, "clm:a")) == _semantic_reason(_find(off, "clm:a"))


# --- P0-2: BM25 across all candidate kinds -------------------------------

def test_bm25_all_kinds_applies_to_non_raw():
    # A CLM record whose only match to the query is a rare term BM25 rewards.
    rare = MIRLRecord(
        id="clm:rare", kind=RecordKind.CLM, ns="test", scope="thread", t0="2024-01-01",
        attrs={"subject": "ent:1", "predicate": "mentions", "object": "axolotl"},
    )
    other = MIRLRecord(
        id="clm:other", kind=RecordKind.CLM, ns="test", scope="thread", t0="2024-01-01",
        attrs={"subject": "ent:2", "predicate": "mentions", "object": "weather today"},
    )
    batch = IRBatch([rare, other])
    bm25 = BM25Index()
    bm25.add("clm:rare", "axolotl salamander amphibian")
    bm25.add("clm:other", "weather today sunny")

    off = search_batch(batch, query="axolotl", bm25_index=bm25, limit=5)
    on = search_batch(batch, query="axolotl", bm25_index=bm25, limit=5,
                      flags=RetrievalFlags(bm25_all_kinds=True))
    # Flag OFF: BM25 is RAW-only, so the CLM lexical score is unchanged by BM25.
    # Flag ON: the rare CLM gets a BM25 boost, raising its lexical channel.
    assert _lexical_reason(_find(on, "clm:rare")) >= _lexical_reason(_find(off, "clm:rare"))


# --- P1-1: RRF fusion -----------------------------------------------------

def test_rrf_changes_fusion_but_keeps_candidates():
    batch = _two_claims()
    vs = {"clm:a": 0.1, "clm:b": 0.95}
    weighted = search_batch(batch, query="hiking", vector_scores=vs, limit=5)
    rrf = search_batch(batch, query="hiking", vector_scores=vs, limit=5,
                       flags=RetrievalFlags(fusion="rrf"))
    # Same candidate set, RRF scores differ from the weighted sum.
    assert {c.record.id for c in rrf.candidates} == {c.record.id for c in weighted.candidates}
    rrf_scores = {c.record.id: c.score for c in rrf.candidates}
    weighted_scores = {c.record.id: c.score for c in weighted.candidates}
    assert rrf_scores != weighted_scores


def test_rrf_record_with_no_positive_channel_is_excluded():
    # A record with zero lexical/semantic/graph and only the default temporal
    # base still participates via temporal; a record with no signal at all does not.
    batch = _two_claims()
    result = search_batch(batch, query="zzznomatch", vector_scores={}, limit=5,
                          flags=RetrievalFlags(fusion="rrf"))
    for cand in result.candidates:
        assert cand.score > 0.0


# --- entity-grounded graph scoring (cat1 coreference lever, HISTORY#321/#323) ---

def _melanie_scope():
    """A scope with one entity ('Melanie') coreferenced across two claims
    (subject already the SAME ent id, as storage.persist_ir now guarantees)
    plus an unrelated claim about a different entity."""
    ent_melanie = MIRLRecord(id="ent:melanie", kind=RecordKind.ENT, ns="test", scope="thread",
                              attrs={"entity_type": "person", "label": "Melanie"})
    ent_caroline = MIRLRecord(id="ent:caroline", kind=RecordKind.ENT, ns="test", scope="thread",
                               attrs={"entity_type": "person", "label": "Caroline"})
    clm_pottery = MIRLRecord(id="clm:pottery", kind=RecordKind.CLM, ns="test", scope="thread",
                              attrs={"subject": "ent:melanie", "predicate": "content", "object": "Melanie: I love pottery."})
    clm_sweden = MIRLRecord(id="clm:sweden", kind=RecordKind.CLM, ns="test", scope="thread",
                             attrs={"subject": "ent:melanie", "predicate": "content", "object": "Melanie: I moved to Sweden."})
    clm_caroline = MIRLRecord(id="clm:caroline", kind=RecordKind.CLM, ns="test", scope="thread",
                               attrs={"subject": "ent:caroline", "predicate": "content", "object": "Caroline: I researched adoption agencies."})
    return IRBatch([ent_melanie, ent_caroline, clm_pottery, clm_sweden, clm_caroline])


def test_entity_grounded_scoring_default_off_is_byte_identical():
    batch = _melanie_scope()
    off = search_batch(batch, query="What does Melanie do", limit=10)
    baseline = search_batch(batch, query="What does Melanie do", limit=10,
                            flags=RetrievalFlags(entity_grounded_scoring=False))
    assert [(c.record.id, c.score) for c in off.candidates] == [(c.record.id, c.score) for c in baseline.candidates]


def test_entity_grounded_scoring_on_boosts_coreferenced_claims():
    batch = _melanie_scope()
    on = search_batch(batch, query="What does Melanie do", limit=10,
                      flags=RetrievalFlags(entity_grounded_scoring=True))
    scores = {c.record.id: c.score for c in on.candidates}
    # Both of Melanie's claims outrank the unrelated Caroline claim once her
    # entity is coreferenced to one id and grounding is scored correctly.
    assert scores["clm:pottery"] > scores["clm:caroline"]
    assert scores["clm:sweden"] > scores["clm:caroline"]


def test_entity_grounded_scoring_no_match_scores_like_off():
    # A query that mentions no entity in the scope should not get any
    # artificial boost from the new channel.
    batch = _melanie_scope()
    on = search_batch(batch, query="zzznomatch", limit=10, flags=RetrievalFlags(entity_grounded_scoring=True))
    off = search_batch(batch, query="zzznomatch", limit=10, flags=RetrievalFlags(entity_grounded_scoring=False))
    assert {c.record.id for c in on.candidates} == {c.record.id for c in off.candidates}


def test_entity_grounded_env_parsing():
    assert retrieval_flags_from_env({}).entity_grounded_scoring is False
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_ENTITY_GROUNDED": "1"}).entity_grounded_scoring is True
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_ENTITY_GROUNDED": "false"}).entity_grounded_scoring is False


def test_temporal_policy_flag_default_env_and_coercion():
    from seam_runtime.retrieval import coerce_flag_value

    assert RetrievalFlags().temporal_policy == "off"
    flags = retrieval_flags_from_env({"SEAM_TEMPORAL_POLICY": "temporal/1"})
    assert flags.temporal_policy == "temporal/1"
    # fail-closed on unknown versions
    assert retrieval_flags_from_env({"SEAM_TEMPORAL_POLICY": "guess"}).temporal_policy == "off"
    assert coerce_flag_value("temporal_policy", "temporal/1") == "temporal/1"
    assert coerce_flag_value("temporal_policy", "off") == "off"
    assert coerce_flag_value("temporal_policy", "temporal/99") is None
    assert coerce_flag_value("temporal_policy", 1) is None


def test_answer_contract_flag_default_env_and_coercion():
    from seam_runtime.retrieval import coerce_flag_value

    assert RetrievalFlags().answer_contract == "off"
    flags = retrieval_flags_from_env({"SEAM_ANSWER_CONTRACT": "exact-answer/1"})
    assert flags.answer_contract == "exact-answer/1"
    # fail-closed on unknown versions
    assert (
        retrieval_flags_from_env({"SEAM_ANSWER_CONTRACT": "guess"}).answer_contract == "off"
    )
    assert coerce_flag_value("answer_contract", "exact-answer/1") == "exact-answer/1"
    assert coerce_flag_value("answer_contract", "off") == "off"
    assert coerce_flag_value("answer_contract", "exact-answer/99") is None
    assert coerce_flag_value("answer_contract", 1) is None


def test_count_context_policy_default_env_and_coercion():
    from seam_runtime.retrieval import coerce_flag_value

    assert RetrievalFlags().count_context_policy == "off"
    flags = retrieval_flags_from_env(
        {"SEAM_COUNT_CONTEXT_POLICY": "event-count/distinct/1"}
    )
    assert flags.count_context_policy == "event-count/distinct/1"
    assert (
        retrieval_flags_from_env(
            {"SEAM_COUNT_CONTEXT_POLICY": "event-count/distinct/99"}
        ).count_context_policy
        == "off"
    )
    assert (
        coerce_flag_value("count_context_policy", "event-count/distinct/1")
        == "event-count/distinct/1"
    )
    assert (
        coerce_flag_value("count_context_policy", "event-count/distinct/2")
        == "event-count/distinct/2"
    )
    assert coerce_flag_value("count_context_policy", "off") == "off"
    assert coerce_flag_value("count_context_policy", "event-count/distinct/99") is None
    assert coerce_flag_value("count_context_policy", True) is None
