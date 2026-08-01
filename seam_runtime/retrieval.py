from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from datetime import datetime
from typing import Iterable, Mapping, Protocol

from .bm25 import BM25Index
from .mirl import (
    IRBatch,
    MIRLRecord,
    RecordKind,
    SearchCandidate,
    SearchResult,
    Status,
    cosine_similarity,
    iter_textual_fields,
)
from .symbols import build_symbol_maps
from .temporal import parse_iso, temporal_distance_score


@dataclass(frozen=True)
class RetrievalFlags:
    """Versioned applied memory-to-answer policy (legacy public name).

    The class began as Audit #3 retrieval-scoring flags. H2's transactional
    proposal/apply/revert path and scorer protocol now use the same immutable
    value for retrieval, packing, conversation projection, and inference
    policy. The name and ``retrieval_flag_state`` storage remain for backward
    compatibility in v1; migrating to a generic applied-policy name is a
    separate schema/API change. With every field at its default, behavior is
    byte-identical to the locked baseline.
    """

    # P0-1: when a real vector backend is active (vector_scores is non-empty)
    # but a record is absent from the semantic top-K, treat its semantic score
    # as 0.0 instead of falling back to bag-of-words cosine (which double-counts
    # lexical signal). No effect when vector_scores is empty (local/test path).
    semantic_zero_no_vector: bool = False
    # P0-2: apply the BM25 lexical signal to every candidate kind, not just RAW.
    bm25_all_kinds: bool = False
    # P1-1: fuse the four channels with Reciprocal Rank Fusion instead of the
    # fixed weighted sum. ``rrf_k`` is a principled constant, not a tuned knob.
    fusion: str = "weighted"  # "weighted" | "rrf"
    rrf_k: int = 60
    # Substream isolation: confine the vector search to the query's namespace
    # so a shared vector pool cannot return another namespace's records. The
    # essential leak-seal is the ns-filtered candidate load in search_ir; this
    # flag additionally scopes the vector top-K (defense-in-depth + avoids
    # cross-ns crowding). ~0 measured LoCoMo recall impact; the value is
    # multi-tenant isolation. End-state ON for any multi-namespace store.
    scoped_vectors: bool = False
    # Entity-grounded graph scoring (cat1 aggregation lever, HISTORY#321/#323
    # coreference rebuild). The pre-existing "graph" channel (`_graph_score`)
    # is effectively dead for real compiled data: it looks up bonuses by a
    # record's OWN id in an adjacency map keyed by subject/object/src/dst ids,
    # which a claim's own id is never a member of. When this flag is on,
    # `_entity_grounded_score` replaces that lookup with the actually-intended
    # signal: resolve a candidate's grounding entity (a CLM's `subject`; a
    # REL's `src`/`dst`) to its ENT label and score 1.0 if that label shares a
    # token with the query. This only has real signal once entities are
    # cross-turn coreferenced (`storage.persist_ir`) and entity-entity `REL`
    # edges exist (the opt-in Ollama extractor, `nl.py`) - both landed
    # alongside this flag. OFF reproduces the exact prior (inert) graph score,
    # so a store without those upstream changes measures byte-identical.
    entity_grounded_scoring: bool = False
    # Per-leg weights for orchestrator reciprocal-rank fusion. Empty (the
    # default) is byte-identical to unweighted `reciprocal-rank-fusion/2`.
    #
    # Plain RRF sums one unweighted vote per leg, which is sound only when the
    # legs are INDEPENDENT retrievers. HISTORY#505 measured that on LoCoMo they
    # are not: the graph leg duplicated 87.43% of what SQL and vector already
    # returned and supplied ~25 unique records out of 200, of which only 0.114%
    # were ever selected. Its vote is therefore an echo, and the echo cost
    # -0.023854 context recall against a graph-free arm. A weight below 1.0
    # damps that amplification; 0.0 removes a leg from ranking while leaving it
    # in the trace, which is what makes an honest leg ablation possible.
    #
    # Env: SEAM_RETRIEVAL_LEG_WEIGHTS="graph=0.3,vector=1.0"
    fusion_leg_weights: tuple[tuple[str, float], ...] = ()
    # Retrieval DEPTH override (candidate count requested from search). None =
    # use the call-site `budget`. A measured win (HISTORY#320): the benchmark
    # default of 20 was STARVING recall - deeper retrieval lifts paid judge_score
    # 0.40->0.52 (knee at ~100). This is a CONFIG knob (env SEAM_RETRIEVAL_TOP_K),
    # deliberately NOT a self-improvement `candidate_lever`: search_top_k directly
    # controls candidate-set size, so it would trivially GAME the #290 self-probe
    # ("is the gold record in the candidate set"). Tuned by free-LoCoMo / paid
    # judge + a measured default, never by the self-probe watchdog.
    search_top_k: int | None = None
    # Context/pack CHAR budget the answerer reasons over. None = use the
    # call-site `budget`. Paired with search_top_k by the answerer-aware
    # retrieval PROFILES below: a weak/local answerer wants a TIGHT context
    # (dilution-averse) while a capable answerer converts a BROAD one into more
    # correct answers (holdout-validated cat1: a capable-answerer broad knee
    # lifted judged 0.566->0.705, +0.139, where the same broad context COLLAPSED
    # a weak 3B answerer). Like search_top_k this is a CONFIG knob (env
    # SEAM_RETRIEVAL_CONTEXT_BUDGET / SEAM_RETRIEVAL_PROFILE), deliberately NOT a
    # self-improvement candidate_lever: it is tuned by the free-LoCoMo
    # answer-quality scorer + operator-gated paid judge, never the self-probe.
    context_budget: int | None = None
    # Query-time semantic conversation projection. ``off`` preserves the
    # locked single-pass answer path. ``conversation/1`` turns retrieved turns
    # into a directly readable, provenance-preserving evidence table and gives
    # the answerer an explicit collect->resolve->validate->synthesize contract.
    # It lives in the applied policy state beside retrieval knobs so the H2
    # improvement loop can evaluate, promote, and revert the whole memory-to-
    # answer path rather than only ranking weights.
    conversation_adapter: str = "off"
    # Answer inference boundary. The baseline remains context-only.
    # ``inference/high-confidence/1`` licenses stable world knowledge only when
    # the retrieved evidence supports one unambiguous interpretation; otherwise
    # it requires abstention. Versioned separately from conversation assembly.
    inference_policy: str = "context-only"
    # Temporal grounding for answer generation. ``off`` preserves the locked
    # baseline. ``temporal/1`` requires resolving relative time expressions
    # ("last Friday", "last year") against each message's own timestamp before
    # answering, so event times are reported instead of mention times.
    # Versioned separately: temporal grounding applies whether or not a
    # conversation projection is active.
    temporal_policy: str = "off"
    # Answer-output contract. ``off`` preserves the locked baseline.
    # ``exact-answer/1`` adds a single-pass draft-then-verify directive that
    # composes on top of the collection policies: after drafting, it adds dropped
    # set items, prunes anything the question did not ask for, and anchors the
    # answer to the specific person/event/date referenced. Orthogonal to the
    # conversation projection; versioned so the loop can measure/promote/revert it.
    answer_contract: str = "off"
    # Query-time distinct-event/item count context. ``off`` preserves the exact
    # ranked-memory surface. ``event-count/distinct/1`` applies only to count-
    # shaped questions and adds a disposable, provenance-preserving SEAM-COUNT
    # projection. ``event-count/distinct/2`` preserves that boundary while
    # rendering explicit same-event groups and question-aware eligibility so
    # repeated descriptions cannot masquerade as separate countable rows. Both
    # remain default-off and never mutate durable MIRL or generate the answer.
    count_context_policy: str = "off"
    # Versioned knowledge-graph seeding policy. Zero seeds is the locked
    # lexical-only baseline. These fields use the existing proposal/apply/revert
    # substrate so every runtime surface observes one approved graph policy.
    graph_semantic_seeds: int = 0
    graph_semantic_min_score: float = 0.0
    # Weighted-fusion channel weights. These default to the locked pre-audit
    # tuple (lexical .40 / semantic .35 / graph .15 / temporal .10), so an
    # un-tuned store reproduces the baseline exactly. Unlike the boolean levers
    # these are a *continuous* apply target: the self-improvement proposer
    # searches them against the free self-probe gate. Reweighting cannot inflate
    # the self-probe signal (it is record-in-set at a fixed eval budget), so it
    # is safe to tune automatically. Magnitudes matter relatively, not in
    # absolute sum, so they are not constrained to sum to 1.
    w_lexical: float = 0.40
    w_semantic: float = 0.35
    w_graph: float = 0.15
    w_temporal: float = 0.10

    def weight_pairs(self) -> tuple[tuple[str, float], ...]:
        """Channel weights in the canonical order used by weighted fusion."""
        return (
            ("lexical", self.w_lexical),
            ("semantic", self.w_semantic),
            ("graph", self.w_graph),
            ("temporal", self.w_temporal),
        )


def retrieval_flag_field_types() -> dict[str, type]:
    """Map each ``RetrievalFlags`` field name to its scalar type.

    The H2 apply step and the loader both validate persisted/proposed flag
    payloads against this so an unknown key or wrong-typed value can never
    reach the scoring path. ``bool`` is reported as-is; callers must reject the
    ``bool``/``int`` cross (``True`` is an ``int`` subclass) themselves.
    """
    return {f.name: type(f.default) for f in dataclass_fields(RetrievalFlags)}


def coerce_flag_value(key: str, value: object) -> object | None:
    """Validate ``value`` against the ``RetrievalFlags`` field ``key`` and return
    the coerced value, or None if it is invalid for that field.

    Used by both the loader (persisted rows) and the apply step (proposal
    payloads) so the contract is identical on both sides. Rules: bool fields
    take only ``bool``; float fields take ``int`` or ``float`` (coerced to
    float) but never ``bool`` (which is an ``int`` subclass); int fields take
    only ``int`` (not ``bool``); ``fusion`` must be a known mode. An unknown key
    returns None.
    """
    expected = retrieval_flag_field_types().get(key)
    if expected is None:
        return None
    if expected is bool:
        return value if isinstance(value, bool) else None
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        resolved = float(value)
        if key == "graph_semantic_min_score" and not -1.0 <= resolved <= 1.0:
            return None
        return resolved
    if expected is int:
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        if key == "graph_semantic_seeds" and not 0 <= value <= 128:
            return None
        return value
    if expected is str:
        if not isinstance(value, str):
            return None
        if key == "fusion" and value not in ("weighted", "rrf"):
            return None
        if key == "conversation_adapter":
            from .conversation import CONVERSATION_ADAPTERS

            if value not in CONVERSATION_ADAPTERS:
                return None
        if key == "inference_policy":
            from .conversation import INFERENCE_POLICIES

            if value not in INFERENCE_POLICIES:
                return None
        if key == "temporal_policy":
            from .conversation import TEMPORAL_POLICIES

            if value not in TEMPORAL_POLICIES:
                return None
        if key == "answer_contract":
            from .conversation import ANSWER_CONTRACTS

            if value not in ANSWER_CONTRACTS:
                return None
        if key == "count_context_policy":
            from .event_count_context import EVENT_COUNT_POLICIES

            if value not in EVENT_COUNT_POLICIES:
                return None
        return value
    return value if isinstance(value, expected) else None


# Answerer-aware retrieval profiles: each maps to a coherent
# (search_top_k, context_budget) pair tuned to the answerer's capability. The
# memory layer is local; the caller declares its answerer tier (env
# SEAM_RETRIEVAL_PROFILE or a flags override) and every surface that goes
# through `load_retrieval_flags` (CLI/REST/MCP/dashboard/benchmark) inherits it.
# Holdout-validated on LoCoMo cat1; explicit SEAM_RETRIEVAL_TOP_K /
# SEAM_RETRIEVAL_CONTEXT_BUDGET override the preset. No profile set = unchanged
# defaults (no regression).
RETRIEVAL_PROFILES: dict[str, tuple[int, int]] = {
    "compact": (100, 8000),   # small/local answerers: tight context, dilution-averse
    "broad": (300, 60000),    # capable answerers: high coverage, aggregation-friendly
}


def resolve_retrieval_profile(name: str | None) -> tuple[int, int] | None:
    """Return the (search_top_k, context_budget) pair for a profile name, or None.

    Unknown/empty names return None so the caller falls back to defaults.
    """
    if not name:
        return None
    return RETRIEVAL_PROFILES.get(name.strip().lower())


def _parse_leg_weights(raw: str) -> tuple[tuple[str, float], ...]:
    """Parse "graph=0.3,vector=1.0" into sorted (leg, weight) pairs.

    Malformed input yields () rather than a partial map: half-applying weights
    would change ranking in a way the operator never asked for.
    """
    raw = (raw or "").strip()
    if not raw:
        return ()
    parsed: list[tuple[str, float]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        leg, sep, value = part.partition("=")
        if not sep:
            return ()
        try:
            weight = float(value.strip())
        except ValueError:
            return ()
        if not 0.0 <= weight <= 1_000.0:
            return ()
        parsed.append((leg.strip(), weight))
    return tuple(sorted(parsed))


def _retrieval_env_overrides(env: Mapping[str, str]) -> dict[str, object]:
    """Return only the flag fields whose env var is *explicitly* set.

    Unset vars are omitted (not defaulted) so this dict can be overlaid on top
    of persisted applied-state without an unset var clobbering an applied flag
    back to its default. An explicit value (including a falsey one like ``0``)
    is an operator override and always wins.
    """

    def _present(name: str) -> bool:
        return env.get(name, "").strip() != ""

    def _truthy(name: str) -> bool:
        return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    out: dict[str, object] = {}
    # Profile preset first; the explicit knob vars below override it.
    profile = resolve_retrieval_profile(env.get("SEAM_RETRIEVAL_PROFILE", ""))
    if profile is not None:
        out["search_top_k"], out["context_budget"] = profile
    if _present("SEAM_RETRIEVAL_SEMANTIC_ZERO"):
        out["semantic_zero_no_vector"] = _truthy("SEAM_RETRIEVAL_SEMANTIC_ZERO")
    if _present("SEAM_RETRIEVAL_BM25_ALL"):
        out["bm25_all_kinds"] = _truthy("SEAM_RETRIEVAL_BM25_ALL")
    if _present("SEAM_RETRIEVAL_RRF"):
        out["fusion"] = "rrf" if _truthy("SEAM_RETRIEVAL_RRF") else "weighted"
    if _present("SEAM_RETRIEVAL_RRF_K"):
        raw = env["SEAM_RETRIEVAL_RRF_K"].strip()
        if raw.lstrip("-").isdigit():
            out["rrf_k"] = int(raw)
    if _present("SEAM_RETRIEVAL_SCOPED_VECTORS"):
        out["scoped_vectors"] = _truthy("SEAM_RETRIEVAL_SCOPED_VECTORS")
    if _present("SEAM_RETRIEVAL_ENTITY_GROUNDED"):
        out["entity_grounded_scoring"] = _truthy("SEAM_RETRIEVAL_ENTITY_GROUNDED")
    if _present("SEAM_RETRIEVAL_LEG_WEIGHTS"):
        out["fusion_leg_weights"] = _parse_leg_weights(
            env["SEAM_RETRIEVAL_LEG_WEIGHTS"]
        )
    if _present("SEAM_RETRIEVAL_TOP_K"):
        raw = env["SEAM_RETRIEVAL_TOP_K"].strip()
        if raw.isdigit() and int(raw) > 0:
            out["search_top_k"] = int(raw)
    if _present("SEAM_RETRIEVAL_CONTEXT_BUDGET"):
        raw = env["SEAM_RETRIEVAL_CONTEXT_BUDGET"].strip()
        if raw.isdigit() and int(raw) > 0:
            out["context_budget"] = int(raw)
    if _present("SEAM_CONVERSATION_ADAPTER"):
        raw = env["SEAM_CONVERSATION_ADAPTER"].strip()
        if coerce_flag_value("conversation_adapter", raw) is not None:
            out["conversation_adapter"] = raw
    if _present("SEAM_INFERENCE_POLICY"):
        raw = env["SEAM_INFERENCE_POLICY"].strip()
        if coerce_flag_value("inference_policy", raw) is not None:
            out["inference_policy"] = raw
    if _present("SEAM_TEMPORAL_POLICY"):
        raw = env["SEAM_TEMPORAL_POLICY"].strip()
        if coerce_flag_value("temporal_policy", raw) is not None:
            out["temporal_policy"] = raw
    if _present("SEAM_ANSWER_CONTRACT"):
        raw = env["SEAM_ANSWER_CONTRACT"].strip()
        if coerce_flag_value("answer_contract", raw) is not None:
            out["answer_contract"] = raw
    if _present("SEAM_COUNT_CONTEXT_POLICY"):
        raw = env["SEAM_COUNT_CONTEXT_POLICY"].strip()
        if coerce_flag_value("count_context_policy", raw) is not None:
            out["count_context_policy"] = raw
    if _present("SEAM_GRAPH_SEMANTIC_SEEDS"):
        raw = env["SEAM_GRAPH_SEMANTIC_SEEDS"].strip()
        if raw.lstrip("-").isdigit():
            value = int(raw)
            if coerce_flag_value("graph_semantic_seeds", value) is not None:
                out["graph_semantic_seeds"] = value
    if _present("SEAM_GRAPH_SEMANTIC_MIN_SCORE"):
        raw = env["SEAM_GRAPH_SEMANTIC_MIN_SCORE"].strip()
        try:
            value = float(raw)
        except ValueError:
            pass
        else:
            if coerce_flag_value("graph_semantic_min_score", value) is not None:
                out["graph_semantic_min_score"] = value
    return out


def retrieval_flags_from_env(env: Mapping[str, str] | None = None) -> RetrievalFlags:
    env = os.environ if env is None else env
    graph_overrides = _retrieval_env_overrides(env)

    def _on(name: str) -> bool:
        return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    def _pos_int(name: str) -> int | None:
        raw = env.get(name, "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else None


    def _policy(name: str, key: str, default: str) -> str:
        raw = env.get(name, "").strip()
        return raw if coerce_flag_value(key, raw) is not None else default

    profile = resolve_retrieval_profile(env.get("SEAM_RETRIEVAL_PROFILE", ""))
    p_top_k = profile[0] if profile else None
    p_budget = profile[1] if profile else None
    return RetrievalFlags(
        semantic_zero_no_vector=_on("SEAM_RETRIEVAL_SEMANTIC_ZERO"),
        bm25_all_kinds=_on("SEAM_RETRIEVAL_BM25_ALL"),
        fusion="rrf" if _on("SEAM_RETRIEVAL_RRF") else "weighted",
        scoped_vectors=_on("SEAM_RETRIEVAL_SCOPED_VECTORS"),
        entity_grounded_scoring=_on("SEAM_RETRIEVAL_ENTITY_GROUNDED"),
        fusion_leg_weights=_parse_leg_weights(env.get("SEAM_RETRIEVAL_LEG_WEIGHTS", "")),
        # explicit knob var wins over the profile preset
        search_top_k=_pos_int("SEAM_RETRIEVAL_TOP_K") or p_top_k,
        context_budget=_pos_int("SEAM_RETRIEVAL_CONTEXT_BUDGET") or p_budget,
        conversation_adapter=_policy("SEAM_CONVERSATION_ADAPTER", "conversation_adapter", "off"),
        inference_policy=_policy("SEAM_INFERENCE_POLICY", "inference_policy", "context-only"),
        temporal_policy=_policy("SEAM_TEMPORAL_POLICY", "temporal_policy", "off"),
        answer_contract=_policy("SEAM_ANSWER_CONTRACT", "answer_contract", "off"),
        count_context_policy=_policy(
            "SEAM_COUNT_CONTEXT_POLICY", "count_context_policy", "off"
        ),
        graph_semantic_seeds=int(graph_overrides.get("graph_semantic_seeds", 0)),
        graph_semantic_min_score=float(
            graph_overrides.get("graph_semantic_min_score", 0.0)
        ),
    )


class _FlagStateStore(Protocol):
    def iter_retrieval_flag_state(self) -> list[dict[str, object]]: ...


def load_retrieval_flags(
    store: _FlagStateStore | None, env: Mapping[str, str] | None = None
) -> RetrievalFlags:
    """Resolve effective retrieval flags from three layers, lowest first:

    1. ``RetrievalFlags()`` defaults (the locked baseline).
    2. Persisted applied state (the H2 self-improvement loop's apply output).
    3. Environment overrides (operator kill switch), which always win.

    With an empty flag-state table and no env vars set this returns
    ``RetrievalFlags()`` byte-identical, so an un-improved store reproduces the
    locked retrieval baseline exactly. Malformed persisted rows (unknown field
    or wrong scalar type) are skipped, never raised, so a bad row can never take
    down the search path.
    """
    env = os.environ if env is None else env
    values = asdict(RetrievalFlags())
    field_types = retrieval_flag_field_types()

    iter_state = getattr(store, "iter_retrieval_flag_state", None)
    if callable(iter_state):
        for row in iter_state():
            key = row.get("flag_key")
            if key not in field_types:
                continue
            coerced = coerce_flag_value(key, row.get("flag_value"))
            if coerced is None:
                continue
            values[key] = coerced

    values.update(_retrieval_env_overrides(env))
    return RetrievalFlags(**values)


_WEIGHTS = (("lexical", 0.4), ("semantic", 0.35), ("graph", 0.15), ("temporal", 0.10))
_CURRENT_EXCLUDED_STATUSES = {
    Status.CONTRADICTED,
    Status.SUPERSEDED,
    Status.DEPRECATED,
    Status.DELETED_SOFT,
}


def search_batch(batch: IRBatch, query: str, scope: str | None = None, limit: int = 5, vector_scores: dict[str, float] | None = None, namespace: str | None = None, include_raw: bool = False, bm25_index: BM25Index | None = None, temporal_window: tuple[datetime, datetime] | None = None, temporal_reference: datetime | None = None, flags: RetrievalFlags | None = None) -> SearchResult:
    flags = flags or RetrievalFlags()
    _, symbol_to_expansion = build_symbol_maps(batch.records, namespace=namespace)
    expanded_query = _expand_query(query, symbol_to_expansion)
    tokens = _tokens(expanded_query)
    query_vector = Counter(tokens)
    batch_by_id = batch.by_id()
    records = [
        record
        for record in batch.records
        if (scope is None or record.scope == scope)
        and record.status not in _CURRENT_EXCLUDED_STATUSES
    ]
    graph = _graph(records)
    ent_labels = {r.id: str(r.attrs.get("label", "")) for r in records if r.kind == RecordKind.ENT}
    vector_scores = vector_scores or {}

    candidate_kinds = {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL}
    if include_raw:
        candidate_kinds = candidate_kinds | {RecordKind.RAW}
    bm25_scores: dict[str, float] = bm25_index.score(query) if bm25_index else {}
    max_bm25 = max(bm25_scores.values()) if bm25_scores else 1.0

    # First pass: per-channel scores for every candidate record.
    scored: list[tuple[MIRLRecord, dict[str, float]]] = []
    for record in records:
        if record.kind not in candidate_kinds:
            continue
        lexical = _lexical_score(record, tokens)
        bm25_applies = record.id in bm25_scores and (flags.bm25_all_kinds or record.kind == RecordKind.RAW)
        if bm25_applies:
            lexical = max(lexical, bm25_scores[record.id] / max(max_bm25, 1.0))
        if record.id in vector_scores:
            semantic = vector_scores[record.id]
        elif flags.semantic_zero_no_vector and vector_scores:
            semantic = 0.0
        else:
            semantic = _semantic_score(record, query_vector)
        if flags.entity_grounded_scoring:
            graph_bonus = _entity_grounded_score(record, tokens, ent_labels)
        else:
            graph_bonus = _graph_score(record, tokens, graph)
        if temporal_reference is not None:
            temporal = temporal_distance_score(temporal_reference, parse_iso(record.t0))
        elif temporal_window is not None:
            t0_parsed = parse_iso(record.t0)
            if t0_parsed and temporal_window[0] <= t0_parsed <= temporal_window[1]:
                temporal = 1.0
            else:
                temporal = 0.0
        else:
            temporal = _temporal_score(record)
        scored.append((record, {"lexical": lexical, "semantic": semantic, "graph": graph_bonus, "temporal": temporal}))

    if flags.fusion == "rrf":
        candidates = _fuse_rrf(scored, batch_by_id, k=flags.rrf_k)
    else:
        candidates = _fuse_weighted(scored, batch_by_id, flags.weight_pairs())

    return SearchResult(query=expanded_query, candidates=sorted(candidates, key=lambda item: item.score, reverse=True)[:limit])


def _reasons(channels: dict[str, float]) -> list[str]:
    return [f"{name}={channels[name]:.2f}" for name, _ in _WEIGHTS]


def _fuse_weighted(scored: list[tuple[MIRLRecord, dict[str, float]]], batch_by_id: dict[str, MIRLRecord], weights: tuple[tuple[str, float], ...] = _WEIGHTS) -> list[SearchCandidate]:
    candidates: list[SearchCandidate] = []
    for record, channels in scored:
        score = sum(weight * channels[name] for name, weight in weights)
        if score <= 0:
            continue
        evidence = [batch_by_id[ev] for ev in record.evidence if ev in batch_by_id]
        candidates.append(SearchCandidate(record=record, score=score, reasons=_reasons(channels), evidence=evidence))
    return candidates


def _fuse_rrf(scored: list[tuple[MIRLRecord, dict[str, float]]], batch_by_id: dict[str, MIRLRecord], k: int) -> list[SearchCandidate]:
    # Per-channel descending rank; only records with a positive channel score
    # participate in that channel. RRF score = sum_c 1/(k + rank_c).
    rrf: dict[str, float] = defaultdict(float)
    for name, _ in _WEIGHTS:
        ranked = sorted(
            ((channels[name], record) for record, channels in scored if channels[name] > 0),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for rank, (_score, record) in enumerate(ranked):
            rrf[record.id] += 1.0 / (k + rank)
    candidates: list[SearchCandidate] = []
    for record, channels in scored:
        score = rrf.get(record.id, 0.0)
        if score <= 0:
            continue
        evidence = [batch_by_id[ev] for ev in record.evidence if ev in batch_by_id]
        candidates.append(SearchCandidate(record=record, score=score, reasons=_reasons(channels), evidence=evidence))
    return candidates


def raw_search(records: Iterable[MIRLRecord], query: str, limit: int = 5) -> SearchResult:
    tokens = _tokens(query)
    candidates: list[SearchCandidate] = []
    for record in records:
        if record.kind != RecordKind.RAW:
            continue
        content = str(record.attrs.get("content", ""))
        overlap = len(set(tokens) & set(_tokens(content)))
        if overlap == 0:
            continue
        candidates.append(SearchCandidate(record=record, score=float(overlap), reasons=[f"raw_overlap={overlap}"]))
    return SearchResult(query=query, candidates=sorted(candidates, key=lambda item: item.score, reverse=True)[:limit])


def _graph(records: list[MIRLRecord]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.kind == RecordKind.REL:
            src = str(record.attrs.get("src"))
            dst = str(record.attrs.get("dst"))
            graph[src].add(dst)
            graph[dst].add(src)
        elif record.kind == RecordKind.CLM:
            subject = str(record.attrs.get("subject"))
            obj = record.attrs.get("object")
            if isinstance(obj, str) and obj.startswith(("ent:", "clm:", "evt:", "sta:", "sym:")):
                graph[subject].add(obj)
                graph[obj].add(subject)
    return graph


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_:-]+", text.lower())


def _lexical_score(record: MIRLRecord, query_tokens: list[str]) -> float:
    record_tokens = set(_tokens(" ".join(iter_textual_fields(record))))
    if not record_tokens:
        return 0.0
    return len(set(query_tokens) & record_tokens) / max(len(set(query_tokens)), 1)


def _semantic_score(record: MIRLRecord, query_vector: Counter[str]) -> float:
    record_vector = Counter(_tokens(" ".join(iter_textual_fields(record))))
    return cosine_similarity(dict(query_vector), dict(record_vector))


def _graph_score(record: MIRLRecord, query_tokens: list[str], graph: dict[str, set[str]]) -> float:
    neighbors = graph.get(record.id, set())
    if not neighbors:
        return 0.0
    matched = sum(1 for neighbor in neighbors if any(token in neighbor.lower() for token in query_tokens))
    return matched / max(len(neighbors), 1)


def _grounding_entity_ids(record: MIRLRecord) -> list[str]:
    """The entity ids a candidate is grounded to: a CLM's ``subject``, or a
    REL's ``src``/``dst``. Empty for STA/EVT (no grounding attr today)."""
    if record.kind == RecordKind.CLM:
        subject = record.attrs.get("subject")
        return [str(subject)] if subject is not None else []
    if record.kind == RecordKind.REL:
        return [str(v) for v in (record.attrs.get("src"), record.attrs.get("dst")) if v is not None]
    return []


def _entity_grounded_score(record: MIRLRecord, query_tokens: list[str], ent_labels: dict[str, str]) -> float:
    """Entry-point-entity aggregation signal (cat1 lever): 1.0 if any entity
    this record is grounded to has a label sharing a token with the query,
    else 0.0. Only fires once cross-turn coreference + entity-entity REL
    edges give ``ent_labels``/grounding real, non-per-turn-fresh ids."""
    query_token_set = set(query_tokens)
    if not query_token_set:
        return 0.0
    for ent_id in _grounding_entity_ids(record):
        label = ent_labels.get(ent_id)
        if label and set(_tokens(label)) & query_token_set:
            return 1.0
    return 0.0


def _temporal_score(record: MIRLRecord) -> float:
    return 1.0 if record.t0 else 0.2


def _expand_query(query: str, symbol_to_expansion: dict[str, str]) -> str:
    parts = []
    for token in query.split():
        parts.append(symbol_to_expansion.get(token, token))
    return " ".join(parts)
