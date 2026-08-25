"""Weighted reciprocal-rank fusion (HISTORY#508/#510 follow-up).

Plain RRF sums one unweighted 1/(k+rank) vote per leg. That is sound only when
the legs are independent retrievers. The measured LoCoMo reality is that they
are not: the graph leg duplicated 87.43% of what SQL and vector already
returned, so its vote is an echo, and the echo cost -0.023854 context recall.

The load-bearing property here is INERTNESS: absent or all-1.0 weights must
reproduce `reciprocal-rank-fusion/2` bit for bit, or every prior measurement
taken under that policy silently changes meaning.
"""

from __future__ import annotations

import pytest

from seam_runtime.retrieval import RetrievalFlags, retrieval_flags_from_env
from seam_runtime.retrieval_policy import (
    FUSION_RANK_CONSTANT,
    normalize_leg_weights,
    rank_normalized_contribution,
    weighted_fusion_score,
)

# -- scoring ------------------------------------------------------------


def test_absent_and_unit_weights_reproduce_plain_rrf():
    sources = {"sql": 1 / 61, "vector": 1 / 62, "graph": 1 / 63}
    plain = sum(sources.values())
    assert weighted_fusion_score(sources) == plain
    assert weighted_fusion_score(sources, {}) == plain
    assert weighted_fusion_score(
        sources, {"sql": 1.0, "vector": 1.0, "graph": 1.0}
    ) == plain


def test_zero_weight_removes_a_leg_from_ranking_only():
    sources = {"sql": 1 / 61, "graph": 1 / 61}
    assert weighted_fusion_score(sources, {"graph": 0.0}) == pytest.approx(1 / 61)


def test_graph_weight_flips_a_graph_carried_record():
    """A record carried mainly by the graph leg must yield to a true top hit.

    `carried` is ranked poorly by SQL (30) but 1st by graph, so plain RRF puts
    it above a record ranked 1st by vector alone. Damping the graph leg is what
    restores the true top hit — this is the displacement that cost -0.023854.
    """
    carried = {
        "sql": rank_normalized_contribution(30),
        "graph": rank_normalized_contribution(1),
    }
    true_top = {"vector": rank_normalized_contribution(1)}

    assert weighted_fusion_score(carried) > weighted_fusion_score(true_top)
    assert weighted_fusion_score(carried, {"graph": 0.0}) < weighted_fusion_score(
        true_top, {"graph": 0.0}
    )


def test_multi_leg_agreement_outranks_a_lone_top_hit_even_without_graph():
    """Documents a limit of the weight lever, so it is not oversold.

    Ranked 20th in BOTH SQL and vector, a record scores 2/80 = 0.025 and still
    beats a lone rank-1 vector hit at 1/61 = 0.0164. Leg-count amplification is
    inherent to RRF and is NOT graph-specific; zeroing the graph weight damps
    the graph echo only. Fixing the general case needs a different mechanism
    (novelty discounting or slot reservation), not a weight.
    """
    echoed = {
        "sql": rank_normalized_contribution(20),
        "vector": rank_normalized_contribution(20),
    }
    true_top = {"vector": rank_normalized_contribution(1)}
    assert weighted_fusion_score(echoed, {"graph": 0.0}) > weighted_fusion_score(
        true_top, {"graph": 0.0}
    )


def test_rank_constant_is_unchanged():
    assert FUSION_RANK_CONSTANT == 60


# -- validation ---------------------------------------------------------


@pytest.mark.parametrize("bad", [{"graph": "0.3"}, {"graph": True}, {"graph": None}])
def test_non_numeric_weights_rejected(bad):
    with pytest.raises(TypeError):
        normalize_leg_weights(bad)


@pytest.mark.parametrize("bad", [{"graph": -0.1}, {"graph": 1001.0}])
def test_out_of_range_weights_rejected(bad):
    with pytest.raises(ValueError):
        normalize_leg_weights(bad)


# -- env plumbing -------------------------------------------------------


def test_env_parses_weight_map():
    flags = retrieval_flags_from_env(
        {"SEAM_RETRIEVAL_LEG_WEIGHTS": "graph=0.3,vector=1.0"}
    )
    assert flags.fusion_leg_weights == (("graph", 0.3), ("vector", 1.0))


@pytest.mark.parametrize(
    "raw",
    ["graph", "graph=abc", "graph=-1", "graph=1e9", "graph=0.3,vector"],
)
def test_malformed_env_is_ignored_wholesale(raw):
    """Never half-apply a weight map.

    A partially applied map would change ranking in a way the operator did not
    ask for, which is worse than ignoring the setting outright.
    """
    assert retrieval_flags_from_env({"SEAM_RETRIEVAL_LEG_WEIGHTS": raw}).fusion_leg_weights == ()


def test_default_flags_carry_no_weights():
    assert RetrievalFlags().fusion_leg_weights == ()


def test_unknown_leg_name_is_rejected_even_when_search_has_no_hits(tmp_path):
    """A misspelled leg must fail before candidate-dependent fusion runs."""

    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "unknown-leg.db", allow_pgvector_env=False)
    try:
        with pytest.raises(ValueError, match="unknown fusion leg.*vectro"):
            rt.retrieve(
                "empty retrieval",
                flags=RetrievalFlags(fusion_leg_weights=(("vectro", 1.0),)),
            )
    finally:
        rt.close()


def test_whitespace_padded_leg_name_is_rejected_at_runtime_boundary(tmp_path):
    """Direct runtime flags require an exact canonical fusion-leg name."""

    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "padded-leg.db", allow_pgvector_env=False)
    try:
        with pytest.raises(ValueError, match="unknown fusion leg.* vector "):
            rt.retrieve(
                "empty retrieval",
                flags=RetrievalFlags(fusion_leg_weights=((" vector ", 1.0),)),
            )
    finally:
        rt.close()


# -- end to end ---------------------------------------------------------


def _seed(tmp_path):
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "weights.db", allow_pgvector_env=False)
    for index, text in enumerate(
        [
            "Melanie adopted a tabby cat named Pepper in March.",
            "Caroline started a pottery class on Tuesday evenings.",
            "Melanie's cat Pepper knocked over the pottery vase.",
            "Caroline sold three bowls at the spring craft fair.",
        ]
    ):
        rt.ingest_conversation_turn(
            text,
            source_ref=f"local://weights-{index}",
            ns="local.default",
            scope="thread",
        )
    return rt


def test_unit_weights_are_byte_identical_end_to_end(tmp_path):
    rt = _seed(tmp_path)
    query = "What is Melanie's cat called?"

    base = rt.retrieve(query, budget=5, include_raw=True, mode="mix")
    unit = rt.retrieve(
        query,
        budget=5,
        include_raw=True,
        mode="mix",
        flags=RetrievalFlags(
            fusion_leg_weights=(("graph", 1.0), ("sql", 1.0), ("vector", 1.0))
        ),
    )

    assert [c.record.id for c in base.candidates] == [
        c.record.id for c in unit.candidates
    ]
    assert [c.score for c in base.candidates] == [c.score for c in unit.candidates]


def test_zeroed_graph_leg_still_appears_in_the_trace(tmp_path):
    """A zero weight must ablate ranking without hiding the leg.

    Losing the leg from the trace would make the ablation unauditable.
    """
    rt = _seed(tmp_path)
    result = rt.retrieve(
        "What is Melanie's cat called?",
        budget=5,
        include_raw=True,
        mode="mix",
        include_trace=True,
        flags=RetrievalFlags(fusion_leg_weights=(("graph", 0.0),)),
    )
    assert "graph" in (result.trace or {}).get("legs", {})
    assert result.trace["fusion"]["policy"] == "weighted-reciprocal-rank-fusion/1"
    assert result.trace["fusion"]["leg_weights"] == {"graph": 0.0}


# -- closed leg set completeness (S8 review repair) ---------------------


def test_closed_leg_set_covers_every_leg_the_engine_can_emit():
    """The closed set must equal the engine's canonical retrieval sources.

    A closed set that omits an emitted leg is worse than no closed set: it
    rejects a working ablation while leaving that leg silently at weight 1.0,
    because `weighted_fusion_score` falls back to the default for any source
    key it was not given.
    """

    import re
    from pathlib import Path

    from seam_runtime.reasoning_graph import RETRIEVAL_SOURCES
    from seam_runtime.retrieval_policy import FUSION_LEG_NAMES

    assert RETRIEVAL_SOURCES == FUSION_LEG_NAMES

    adapters = Path("seam_runtime/retrieval_orchestrator/adapters.py").read_text()
    emitted = set(re.findall(r'LegHit\(\s*leg="([a-z_]+)"', adapters))
    # `legacy_weighted` is the pre-refactor control; it never reaches weighted
    # fusion, so it is deliberately not a weightable fusion leg.
    assert emitted - {"legacy_weighted"} <= FUSION_LEG_NAMES


def test_chroma_backed_semantic_leg_is_weightable():
    """`chroma` is an emitted fusion source, so it must accept a weight.

    `ChromaSemanticAdapter` tags its hits `leg="chroma"`, so fusion groups them
    under that key. Rejecting the name made a Chroma-backed leg ablation
    impossible while `{"vector": 0.0}` silently left the leg fully weighted.
    """

    assert normalize_leg_weights({"chroma": 0.0}) == {"chroma": 0.0}
    sources = {"sql": 1 / 61, "chroma": 1 / 61}
    assert weighted_fusion_score(sources, {"chroma": 0.0}) == pytest.approx(1 / 61)


# -- where each half of the name contract is enforced (S8 review repair) ----


def test_env_surface_normalizes_padding_then_still_requires_a_known_name():
    """`SEAM_RETRIEVAL_LEG_WEIGHTS` owns whitespace; it does not own spelling.

    `graph=0.3, vector=1.0` is the natural way to write the variable, so the
    env parser strips around each name. That normalization is the ONLY
    latitude: a name that is not a canonical leg still reaches the runtime
    boundary intact and fails there, before any search runs.
    """

    assert retrieval_flags_from_env(
        {"SEAM_RETRIEVAL_LEG_WEIGHTS": "graph=0.3, vector=1.0"}
    ).fusion_leg_weights == (("graph", 0.3), ("vector", 1.0))
    assert retrieval_flags_from_env(
        {"SEAM_RETRIEVAL_LEG_WEIGHTS": " vector =0"}
    ).fusion_leg_weights == (("vector", 0.0),)
    # Padding is normalized; a misspelling survives parsing on purpose.
    assert retrieval_flags_from_env(
        {"SEAM_RETRIEVAL_LEG_WEIGHTS": " vectr =1.0"}
    ).fusion_leg_weights == (("vectr", 1.0),)


def test_env_sourced_unknown_leg_name_fails_before_search(tmp_path):
    """The env surface must fail closed at the boundary, not silently ignore."""

    from seam_runtime.runtime import SeamRuntime

    flags = retrieval_flags_from_env({"SEAM_RETRIEVAL_LEG_WEIGHTS": "vectr=1.0"})
    rt = SeamRuntime(tmp_path / "env-unknown-leg.db", allow_pgvector_env=False)
    try:
        with pytest.raises(ValueError, match="unknown fusion leg.*vectr"):
            rt.retrieve("empty retrieval", flags=flags)
    finally:
        rt.close()


def test_direct_flags_still_require_an_exact_canonical_name(tmp_path):
    """Programmatic callers get no normalization latitude at all."""

    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(tmp_path / "direct-padded-leg.db", allow_pgvector_env=False)
    try:
        with pytest.raises(ValueError, match="unknown fusion leg"):
            rt.retrieve(
                "empty retrieval",
                flags=RetrievalFlags(fusion_leg_weights=((" vector ", 1.0),)),
            )
    finally:
        rt.close()
