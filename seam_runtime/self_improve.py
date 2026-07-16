"""Self-supervised improvement signal for the H2 loop's front half.

Free, deterministic, paid-free measurement of retrieval quality generated from
the runtime's OWN stored memory corpus - no external benchmark dataset, no judge
calls. A probe takes a stored record as gold, derives a query that record should
answer, runs retrieval, and scores a binary hit (was the source record returned
in the candidate set). Aggregate recall over a held-out probe set is the signal
the auto-proposer optimizes.

Why binary-recall-on-own-corpus is the right driver:

* Free + deterministic: no judge, no API, re-runnable every loop iteration.
* Not gameable by context budget: the gold is "the source record is in the
  candidate set or not", so inflating the packed-context char budget (which
  mechanically lifts LoCoMo's token-overlap ``context_recall``) does not move
  this score. That closes the budget-gaming hazard at the root.
* On-distribution: it optimizes retrieval on the user's real memories.

Probe *difficulty* is the deliberate next lever (paraphrase / multi-hop /
temporal styles): a trivially lexical probe is retrieved regardless of flag
settings and so cannot discriminate between lever configurations. v1 here is
extractive; the ``Scorer`` mechanism, the per-category breakdown, and the
deterministic sampling are what this module pins.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Mapping, Protocol, Sequence, runtime_checkable

from .mirl import MIRLRecord, RecordKind, iter_textual_fields
from .retrieval import RETRIEVAL_PROFILES, RetrievalFlags

if TYPE_CHECKING:  # avoid import cycle / heavy import at module load
    from .runtime import SeamRuntime

# The kinds a probe may target by default = exactly the kinds `search_ir` can
# return as candidates (see `retrieval.search_batch` candidate_kinds). Probing
# RAW (not a default search candidate) or PROV/SPAN/ENT (whose only text is an
# id/label, not content) yields structurally-unhittable or degenerate cloze
# queries that always miss, diluting the signal; the content claim carries the
# verbatim proposition, so restricting to these loses no content.
_DEFAULT_PROBE_KINDS = (RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL)


@dataclass(frozen=True)
class Probe:
    """One self-supervised retrieval case. ``case_id`` and ``gold_record_id`` are
    the source record's id; a hit is that id appearing in the candidate set.
    ``masked`` is the salient span removed from the record text to form the
    query (the "answer" the query no longer contains) - kept for proposal
    rationale and debugging."""

    case_id: str
    query: str
    gold_record_id: str
    category: str
    masked: str = ""
    style: str = "cloze"


@dataclass(frozen=True)
class GraphProbe:
    """A deterministic test case generated from a knowledge-graph motif."""

    case_id: str
    motif: str
    query: str
    expected_node_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...] = ()
    evidence_episode_ids: tuple[str, ...] = ()
    expected_action: str = "retrieve"
    rationale: str = ""


@dataclass(frozen=True)
class ScoreReport:
    """Outcome of a :class:`Scorer` run.

    ``aggregate`` is mean binary recall over the cases; ``per_category`` is the
    same split by category so the proposer can detect a lever that helps one
    category while regressing another (the #273 R1 lesson). ``per_case`` keeps
    the case->hit map so a proposal can cite the exact dev case_ids as evidence.
    """

    scorer: str
    aggregate: float
    n: int
    per_category: dict[str, float] = field(default_factory=dict)
    # binary hit (self-probe) or fractional recall (LoCoMo context_recall)
    per_case: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class Scorer(Protocol):
    """A free, deterministic, per-case dev scorer. External benchmarks (NIAH,
    LoCoMo string-match) and the paid judged tier implement the same shape."""

    name: str
    # Optional. True iff this scorer is DILUTION-SENSITIVE: it measures answer
    # quality, so enlarging search_top_k/context_budget cannot inflate it - a
    # bigger budget that merely floods the context degrades a weak answerer
    # instead. The loop proposes the profile knobs (search_top_k/context_budget)
    # ONLY when every scorer is profile_safe; self-probe and context_recall are
    # NOT (a bigger budget mechanically lifts them), so they leave it unset and
    # `getattr(scorer, "profile_safe", False)` treats them as unsafe. See the
    # answer-quality scorer and the Strand-B wiring.
    profile_safe: bool = False
    # True iff the scorer measures generated-answer quality and can therefore
    # evaluate semantic-conversation / inference-policy candidates. Retrieval-
    # only scorers leave this false because answer policies cannot move them.
    answer_policy_safe: bool = False

    def score(self, runtime: "SeamRuntime", flags: "RetrievalFlags | None" = None) -> ScoreReport: ...


_WORD_RE = re.compile(r"[^\W\d_]+|\d[\w'./-]*")

# Minimum residual word count for a cloze query to be a usable probe: shorter
# than this and the masked sentence is too thin to identify a record.
_MIN_RESIDUAL_WORDS = 3


def _category_of(record: MIRLRecord) -> str:
    kind = getattr(record, "kind", None)
    return getattr(kind, "value", None) or str(kind)


_REF_RE = re.compile(r"^(?:ent|raw|clm|span|prov|sta|evt|rel|sym):\S*$")


def _looks_like_ref(value: str) -> bool:
    """True if ``value`` is a SEAM record-id reference (e.g. a claim's subject
    ``ent:contract:<hash>``) rather than natural-language content."""
    return bool(_REF_RE.match(value))


def _record_text(record: MIRLRecord) -> str | None:
    """The most content-bearing textual field of a record (the cloze source).

    Excludes id-reference fields (a claim's ``subject`` is an ``ent:...`` id, not
    content), so a short-object enrichment claim does not produce a degenerate
    cloze over its subject id. None when the record has no usable text."""
    texts = [t.strip() for t in iter_textual_fields(record) if t and t.strip() and not _looks_like_ref(t.strip())]
    if not texts:
        return None
    return max(texts, key=len)


def _salient_index(tokens: list[str]) -> int:
    """Index of the most answer-bearing token to mask, deterministically.

    Priority: a token containing a digit (number / date / code) > a non
    sentence-initial Capitalized token (proper noun) > the longest token. Ties
    break on earliest position.
    """
    for i, token in enumerate(tokens):
        if any(ch.isdigit() for ch in token):
            return i
    for i, token in enumerate(tokens):
        if i > 0 and token[:1].isupper():
            return i
    return max(range(len(tokens)), key=lambda i: len(tokens[i]))


def _cloze(text: str) -> tuple[str, str] | None:
    """Mask the salient word and return (query, masked_surface).

    The query is rebuilt by re-joining the *remaining* word tokens with spaces -
    not by slicing the raw string - so it normalizes both natural text and the
    underscore/slug form SEAM stores compiled records in (e.g.
    ``maria_adopted_..._2021``). The query no longer contains the answer token,
    so a retrieval hit means the record was found from surrounding context, not
    lexical echo. None when there is no maskable span or the residual is too
    thin to identify a record.
    """
    tokens = [m.group() for m in _WORD_RE.finditer(text)]
    if len(tokens) <= _MIN_RESIDUAL_WORDS:
        return None
    pick = _salient_index(tokens)
    residual = tokens[:pick] + tokens[pick + 1 :]
    if len(residual) < _MIN_RESIDUAL_WORDS:
        return None
    return " ".join(residual), tokens[pick]


def generate_probes(
    runtime: "SeamRuntime",
    *,
    ns: str | None = None,
    scope: str | None = None,
    load_limit: int | None = 500,
    sample: int | None = 50,
    seed: int = 1234,
    kinds: Sequence[RecordKind] | None = None,
) -> list[Probe]:
    """Build a deterministic cloze probe set from the runtime's stored corpus.

    Each probe masks the salient span of a record's text (see :func:`_cloze`),
    so the query is a near-paraphrase missing the answer token and a hit means
    retrieval found the record from context, not lexical echo. Records whose
    text has no maskable salient span (labels, too-short fields) are skipped.

    ``kinds=None`` (the default) targets only the kinds retrieval can actually
    return (``_DEFAULT_PROBE_KINDS`` = CLM/STA/EVT/REL); this excludes RAW (not a
    default search candidate) and PROV/SPAN/ENT (id/label-only text), whose probes
    would always miss and silently dilute the signal. Pass an explicit ``kinds``
    tuple to override (e.g. ``kinds=(RAW,)`` to probe RAW specifically).

    Determinism (fixed ``seed``) is required so the SAME probe set scores a
    config before and after an ``improvement apply`` - that identity is what
    makes the no-regression ratchet meaningful. An empty/too-small corpus simply
    yields fewer (or zero) probes - the loop no-ops on cold start rather than
    failing.
    """
    batch = runtime.store.load_ir(ns=ns, scope=scope, limit=load_limit)
    kind_set = set(kinds) if kinds is not None else set(_DEFAULT_PROBE_KINDS)
    candidates: list[Probe] = []
    for record in batch.records:
        if kind_set is not None and record.kind not in kind_set:
            continue
        text = _record_text(record)
        if not text:
            continue
        cloze = _cloze(text)
        if cloze is None:
            continue
        query, masked = cloze
        candidates.append(
            Probe(
                case_id=record.id,
                query=query,
                gold_record_id=record.id,
                category=_category_of(record),
                masked=masked,
            )
        )

    rng = random.Random(seed)
    rng.shuffle(candidates)
    if sample is not None:
        candidates = candidates[:sample]
    return candidates


def generate_graph_probes(
    connection: sqlite3.Connection,
    *,
    namespace: str | None = None,
    scope: str | None = None,
    sample: int | None = 100,
    seed: int = 1234,
) -> list[GraphProbe]:
    """Generate free deterministic probes from the live graph projection.

    The seven motif families cover 5W1H completeness, multi-hop paths, causal
    and temporal relations, contradictions, provenance recovery, and
    unsupported-claim abstention. The graph supplies both the prompt and gold
    ids; no model or external judge participates in generation.
    """

    from .knowledge_graph import _trust_profiles, predicate_family

    node_where = [
        "status not in ('contradicted','superseded','deprecated','deleted_soft')",
    ]
    node_params: list[object] = []
    edge_where = [
        "expired_at is null",
        "status not in ('contradicted','superseded','deprecated','deleted_soft')",
    ]
    edge_params: list[object] = []
    if namespace:
        node_where.append("ns = ?")
        edge_where.append("ns = ?")
        node_params.append(namespace)
        edge_params.append(namespace)
    if scope:
        node_where.append("scope = ?")
        edge_where.append("scope = ?")
        node_params.append(scope)
        edge_params.append(scope)
    nodes = connection.execute(
        "select * from knowledge_nodes "
        f"where {' and '.join(node_where)} order by id limit 5000",
        node_params,
    ).fetchall()
    edges = connection.execute(
        "select * from knowledge_edges "
        f"where {' and '.join(edge_where)} order by id limit 10000",
        edge_params,
    ).fetchall()
    by_id = {str(row["id"]): row for row in nodes}
    outgoing: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for edge in edges:
        outgoing[str(edge["src_id"])].append(edge)
    trust = _trust_profiles(connection, nodes, at=None, include_history=False)

    probes: list[GraphProbe] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def add(
        motif: str,
        query: str,
        expected: Sequence[str],
        *,
        source_records: Sequence[str] = (),
        episodes: Sequence[str] = (),
        action: str = "retrieve",
        rationale: str,
    ) -> None:
        expected_ids = tuple(dict.fromkeys(str(value) for value in expected if value))
        key = motif, expected_ids
        if not expected_ids or key in seen:
            return
        seen.add(key)
        material = json.dumps(
            [motif, query, expected_ids, tuple(source_records), tuple(episodes), action],
            sort_keys=True,
            separators=(",", ":"),
        )
        probes.append(GraphProbe(
            case_id=f"graph:{motif}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}",
            motif=motif,
            query=query,
            expected_node_ids=expected_ids,
            source_record_ids=tuple(dict.fromkeys(str(value) for value in source_records if value)),
            evidence_episode_ids=tuple(dict.fromkeys(str(value) for value in episodes if value)),
            expected_action=action,
            rationale=rationale,
        ))

    # 5W1H+Then completeness probes.
    for row in nodes:
        properties = json.loads(row["properties_json"] or "{}")
        facets = properties.get("facets")
        if not isinstance(facets, dict) or len(facets) < 2:
            continue
        names = ", ".join(key for key in ("who", "what", "when", "where", "why", "how", "then") if key in facets)
        add(
            "five_w_one_h_then",
            f"Recover the {names} context for {row['label']}",
            [str(row["id"])],
            source_records=[str(row["source_record_id"] or "")],
            rationale="tests recovery of grounded 5W1H+Then facets",
        )

    # Typed single-edge motifs.
    for edge in edges:
        src_id = str(edge["src_id"])
        dst_id = str(edge["dst_id"])
        if src_id not in by_id or dst_id not in by_id:
            continue
        predicate = str(edge["predicate"])
        family = predicate_family(predicate, str(edge["edge_kind"]))
        motif = None
        if family == "causal":
            motif = "causal"
        elif family == "temporal":
            motif = "temporal"
        elif predicate.lower() in {"contradicts", "refutes"}:
            motif = "contradiction"
        if motif:
            add(
                motif,
                f"What does {by_id[src_id]['label']} {predicate} with respect to {by_id[dst_id]['label']}?",
                [src_id, dst_id],
                source_records=[str(edge["source_record_id"])],
                action="surface_dispute" if motif == "contradiction" else "retrieve",
                rationale=f"tests the graph's {family} relation path",
            )

    # Two-edge paths are deterministic multi-hop probes.
    for first in edges:
        start = str(first["src_id"])
        middle = str(first["dst_id"])
        for second in outgoing.get(middle, ())[:3]:
            end = str(second["dst_id"])
            if len({start, middle, end}) != 3 or not {start, middle, end} <= by_id.keys():
                continue
            add(
                "multi_hop",
                f"Trace from {by_id[start]['label']} through {by_id[middle]['label']} to {by_id[end]['label']}",
                [start, middle, end],
                source_records=[str(first["source_record_id"]), str(second["source_record_id"])],
                rationale="tests a factual two-edge traversal",
            )

    # Episode-to-record provenance probes.
    provenance_where = ["ep.status = 'active'"]
    provenance_params: list[object] = []
    if namespace:
        provenance_where.append("ep.ns = ?")
        provenance_params.append(namespace)
    if scope:
        provenance_where.append("ep.scope = ?")
        provenance_params.append(scope)
    episode_links = connection.execute(
        "select distinct ne.node_id, ep.id as episode_id, ep.source_ref, ep.source_record_id "
        "from knowledge_node_episodes ne join knowledge_episodes ep on ep.id = ne.episode_id "
        f"where {' and '.join(provenance_where)} order by ne.node_id, ep.id limit 10000",
        provenance_params,
    ).fetchall()
    for link in episode_links:
        node_id = str(link["node_id"])
        if node_id not in by_id:
            continue
        add(
            "provenance",
            f"Which episode supports or produced {by_id[node_id]['label']}?",
            [node_id],
            source_records=[str(link["source_record_id"])],
            episodes=[str(link["episode_id"])],
            rationale="tests traceability from projected knowledge back to an episode",
        )

    # Unsupported knowledge must generate an abstention/verification probe.
    for node_id, profile in sorted(trust.items()):
        if profile["trust_state"] != "unverified" or node_id not in by_id:
            continue
        add(
            "unsupported",
            f"Can SEAM assert this as established knowledge: {by_id[node_id]['label']}?",
            [node_id],
            source_records=[str(by_id[node_id]["source_record_id"] or "")],
            action="abstain_or_qualify",
            rationale="tests that model-only or evidence-free claims are not silently asserted",
        )

    probes.sort(key=lambda probe: probe.case_id)
    rng = random.Random(seed)
    rng.shuffle(probes)
    if sample is not None:
        probes = probes[:max(0, sample)]
    return probes


@dataclass
class SelfProbeScorer:
    """Scores a probe set: fraction of probes whose gold record is in the
    retrieved candidate set, overall and per category."""

    probes: Sequence[Probe]
    budget: int = 5
    name: str = "self_probe"

    def score(self, runtime: "SeamRuntime", flags: "RetrievalFlags | None" = None) -> ScoreReport:
        per_case: dict[str, bool] = {}
        cat_hits: dict[str, list[bool]] = defaultdict(list)
        for probe in self.probes:
            result = runtime.search_ir(probe.query, budget=self.budget, flags=flags)
            hit = any(c.record.id == probe.gold_record_id for c in result.candidates)
            per_case[probe.case_id] = hit
            cat_hits[probe.category].append(hit)
        n = len(self.probes)
        aggregate = (sum(per_case.values()) / n) if n else 0.0
        per_category = {cat: sum(hits) / len(hits) for cat, hits in cat_hits.items()}
        return ScoreReport(
            scorer=self.name,
            aggregate=aggregate,
            n=n,
            per_category=per_category,
            per_case=dict(per_case),
        )


# --- proposer core: generate candidate levers + evaluate against free scorers ---

# Default decision thresholds. ``noise_margin`` is the measured self-probe noise
# floor (~0.002 -> use a safer 0.005); a candidate must beat it on at least one
# scorer to count as an improvement. ``regress_tol`` is the per-scorer and
# per-category drop a candidate may not exceed - the no-regression half of the
# ratchet, so a lever that helps one signal/category while hurting another is
# rejected (the #273 R1 lesson, enforced automatically).
DEFAULT_NOISE_MARGIN = 0.005
DEFAULT_REGRESS_TOL = 0.005

STRICT_RATCHET_FAMILIES = frozenset({
    "aggregate",
    "category",
    "integrity",
    "trust",
    "temporal",
    "provenance",
    "holdout",
})


@dataclass(frozen=True)
class RatchetGateEvidence:
    """One auditable pass/fail fact used by the strict ratchet."""

    name: str
    family: str
    passed: bool
    baseline: float | None = None
    candidate: float | None = None
    threshold: float | None = None
    details: str = ""
    refs: tuple[str, ...] = ()
    holdout_violation: bool = False


@dataclass(frozen=True)
class StrictRatchetDecision:
    """Fail-closed decision; a pass is still only pending operator approval."""

    status: str
    accepted_for_review: bool
    requires_approval: bool
    can_apply: bool
    failed_gates: tuple[str, ...]
    evidence: tuple[RatchetGateEvidence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "accepted_for_review": self.accepted_for_review,
            "requires_approval": self.requires_approval,
            "can_apply": self.can_apply,
            "failed_gates": list(self.failed_gates),
            "evidence": [
                {
                    "name": gate.name,
                    "family": gate.family,
                    "passed": gate.passed,
                    "baseline": gate.baseline,
                    "candidate": gate.candidate,
                    "threshold": gate.threshold,
                    "details": gate.details,
                    "refs": list(gate.refs),
                    "holdout_violation": gate.holdout_violation,
                }
                for gate in self.evidence
            ],
        }


def strict_ratchet_decision(
    gates: Sequence[RatchetGateEvidence],
) -> StrictRatchetDecision:
    """Reject on any failed or missing gate; never auto-approve a passing run.

    Rejected evidence remains in the returned append-ready decision object.
    Passing all gates yields ``pending_approval`` with ``can_apply=False`` so an
    operator decision remains a separate, explicit transition.
    """

    evidence = tuple(gates)
    present: set[str] = set()
    failed: list[str] = []
    seen_names: set[str] = set()

    for index, gate in enumerate(evidence):
        name = gate.name.strip() if isinstance(gate.name, str) else ""
        family = gate.family.strip() if isinstance(gate.family, str) else ""
        gate_key = name or f"gate[{index}]"
        valid = True
        if not name:
            failed.append(f"invalid:{gate_key}:blank-metric")
            valid = False
        elif name in seen_names:
            failed.append(f"duplicate:{name}")
            valid = False
        else:
            seen_names.add(name)
        if family not in STRICT_RATCHET_FAMILIES:
            failed.append(f"invalid:{gate_key}:unknown-family:{family or '<blank>'}")
            valid = False
        refs = gate.refs if isinstance(gate.refs, (tuple, list)) else ()
        if not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            failed.append(f"invalid:{gate_key}:blank-refs")
            valid = False
        for metric_name in ("baseline", "candidate", "threshold"):
            value = getattr(gate, metric_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                failed.append(f"invalid:{gate_key}:non-finite-{metric_name}")
                valid = False
        if not isinstance(gate.passed, bool):
            failed.append(f"invalid:{gate_key}:non-boolean-result")
            valid = False
        elif not gate.passed:
            failed.append(gate_key)
        if gate.holdout_violation:
            failed.append(f"holdout-violation:{gate_key}")
            valid = False
        if valid:
            present.add(family)

    failed.extend(
        f"missing:{family}"
        for family in STRICT_RATCHET_FAMILIES
        if family not in present
    )
    failed = sorted(dict.fromkeys(failed))
    if failed:
        return StrictRatchetDecision(
            status="rejected",
            accepted_for_review=False,
            requires_approval=True,
            can_apply=False,
            failed_gates=tuple(failed),
            evidence=evidence,
        )
    return StrictRatchetDecision(
        status="pending_approval",
        accepted_for_review=True,
        requires_approval=True,
        can_apply=False,
        failed_gates=(),
        evidence=evidence,
    )


@dataclass(frozen=True)
class Candidate:
    """A proposed lever change relative to the current baseline flags.

    ``change`` is the minimal ``{field: value}`` overlay - exactly the
    ``proposed_change["flags"]`` payload the #289 apply step consumes. ``flags``
    is the fully-resolved RetrievalFlags used to score the counterfactual.
    """

    label: str
    change: dict[str, object]
    flags: RetrievalFlags


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    deltas: dict[str, float]                       # scorer -> aggregate delta vs baseline
    category_deltas: dict[str, dict[str, float]]   # scorer -> {category -> delta}
    is_improvement: bool
    reason: str
    floor_progress: float = 0.0
    view_deltas: dict[str, dict[str, float]] = field(default_factory=dict)


def score_report_views(
    scorer: Scorer,
    runtime: "SeamRuntime",
    flags: RetrievalFlags,
) -> tuple[ScoreReport, dict[str, ScoreReport]]:
    """Run one scorer call and return its primary and named score views.

    Ordinary scorers expose only ``primary``. Wrappers such as
    ``AdjudicatedScorer`` publish ``last_views`` after the same underlying call,
    allowing the loop to report and guard raw plus corrected outcomes without
    executing generation or judging twice.
    """

    report = scorer.score(runtime, flags=flags)
    views = getattr(scorer, "last_views", None)
    if not isinstance(views, Mapping):
        return report, {"primary": report}
    valid = {
        str(name): view
        for name, view in views.items()
        if isinstance(name, str) and isinstance(view, ScoreReport)
    }
    return report, valid or {"primary": report}


def _category_floor(floors: Mapping[str, float], category: str) -> float | None:
    """Resolve LoCoMo's numeric category ids and human ``catN`` aliases."""

    if category in floors:
        return floors[category]
    alias = f"cat{category}" if category.isdigit() else None
    return floors.get(alias) if alias is not None else None


def candidate_levers(
    baseline: RetrievalFlags,
    *,
    weight_step: float = 0.10,
    profile_levers: bool = False,
    answer_policy_levers: bool = False,
) -> list[Candidate]:
    """Bounded candidate set: the boolean/enum levers (when not already set on
    the baseline) plus single-channel weight perturbations (+/- ``weight_step``).

    Deliberately small and interpretable - the loop tries one lever at a time so
    an accepted change has a clear attribution. Negative weights are skipped.

    ``profile_levers`` (default off) additionally proposes switching to each named
    answerer-aware ``RETRIEVAL_PROFILES`` preset (the search_top_k/context_budget
    pair). These are gated OFF by default because a bigger budget games the
    self-probe and context_recall scorers; the loop turns them on ONLY when every
    scorer is dilution-sensitive (``profile_safe``), so the answer-quality scorer
    can tune the knee to the configured answerer (compact for a weak local model,
    broad for a capable one) without the gaming hazard.
    """
    candidates: list[Candidate] = []
    for field_name, value in (
        ("semantic_zero_no_vector", True),
        ("bm25_all_kinds", True),
        ("fusion", "rrf"),
    ):
        if getattr(baseline, field_name) != value:
            candidates.append(
                Candidate(
                    label=f"{field_name}={value}",
                    change={field_name: value},
                    flags=replace(baseline, **{field_name: value}),
                )
            )
    for field_name in ("w_lexical", "w_semantic", "w_graph", "w_temporal"):
        for delta in (weight_step, -weight_step):
            new_value = round(getattr(baseline, field_name) + delta, 4)
            if new_value < 0:
                continue
            candidates.append(
                Candidate(
                    label=f"{field_name}{delta:+g}",
                    change={field_name: new_value},
                    flags=replace(baseline, **{field_name: new_value}),
                )
            )
    if profile_levers:
        current = (baseline.search_top_k, baseline.context_budget)
        for name, (top_k, budget) in RETRIEVAL_PROFILES.items():
            if (top_k, budget) == current:
                continue
            candidates.append(
                Candidate(
                    label=f"profile={name}",
                    change={"search_top_k": top_k, "context_budget": budget},
                    flags=replace(baseline, search_top_k=top_k, context_budget=budget),
                )
            )
    if answer_policy_levers:
        from .conversation import (
            CONVERSATION_ADAPTER_V1,
            CONVERSATION_ADAPTER_V2,
            CONVERSATION_ADAPTER_V3,
            CONVERSATION_ADAPTER_V4,
            INFERENCE_HIGH_CONFIDENCE_V1,
            INFERENCE_HIGH_CONFIDENCE_V2,
            TEMPORAL_GROUNDING_V1,
            TEMPORAL_GROUNDING_V2,
        )

        for field_name, value in (
            ("conversation_adapter", CONVERSATION_ADAPTER_V1),
            ("conversation_adapter", CONVERSATION_ADAPTER_V2),
            ("conversation_adapter", CONVERSATION_ADAPTER_V3),
            ("conversation_adapter", CONVERSATION_ADAPTER_V4),
            ("inference_policy", INFERENCE_HIGH_CONFIDENCE_V1),
            ("inference_policy", INFERENCE_HIGH_CONFIDENCE_V2),
            ("temporal_policy", TEMPORAL_GROUNDING_V1),
            ("temporal_policy", TEMPORAL_GROUNDING_V2),
        ):
            if getattr(baseline, field_name) == value:
                continue
            candidates.append(
                Candidate(
                    label=f"{field_name}={value}",
                    change={field_name: value},
                    flags=replace(baseline, **{field_name: value}),
                )
            )
    return candidates


def evaluate_candidates(
    runtime: "SeamRuntime",
    scorers: Sequence[Scorer],
    candidates: Sequence[Candidate],
    baseline: RetrievalFlags,
    *,
    noise_margin: float = DEFAULT_NOISE_MARGIN,
    regress_tol: float = DEFAULT_REGRESS_TOL,
    category_floors: Mapping[str, float] | None = None,
    baseline_reports: Mapping[str, ScoreReport] | None = None,
    baseline_views: Mapping[str, Mapping[str, ScoreReport]] | None = None,
) -> list[CandidateEvaluation]:
    """Score every candidate against every scorer relative to ``baseline``.

    A candidate ``is_improvement`` iff it beats ``noise_margin`` on at least one
    scorer's aggregate AND drops no scorer's aggregate and no per-category recall
    by more than ``regress_tol``. Eval budget is whatever each scorer was built
    with - hold it fixed across the sweep (the anti-gaming guard for the
    record-in-set signal).
    """
    base: dict[str, ScoreReport] = dict(baseline_reports or {})
    base_views: dict[str, dict[str, ScoreReport]] = {
        scorer_name: dict(views)
        for scorer_name, views in (baseline_views or {}).items()
    }
    for scorer in scorers:
        if scorer.name not in base:
            report, views = score_report_views(scorer, runtime, baseline)
            base[scorer.name] = report
            base_views[scorer.name] = views
        elif scorer.name not in base_views:
            base_views[scorer.name] = {"primary": base[scorer.name]}
    floors = dict(category_floors or {})
    evaluations: list[CandidateEvaluation] = []
    for candidate in candidates:
        deltas: dict[str, float] = {}
        category_deltas: dict[str, dict[str, float]] = {}
        improved = False
        floor_progress = 0.0
        view_deltas: dict[str, dict[str, float]] = {}
        regressed_reason = ""
        for scorer in scorers:
            report, candidate_views = score_report_views(
                scorer, runtime, candidate.flags
            )
            base_report = base[scorer.name]
            delta = report.aggregate - base_report.aggregate
            deltas[scorer.name] = delta
            if delta > noise_margin:
                improved = True
            if delta < -regress_tol and not regressed_reason:
                regressed_reason = f"{scorer.name} aggregate {delta:+.4f}"
            cat_d: dict[str, float] = {}
            for category, base_value in base_report.per_category.items():
                candidate_value = report.per_category.get(category, 0.0)
                cat_delta = candidate_value - base_value
                cat_d[category] = cat_delta
                floor = _category_floor(floors, category)
                if floor is not None:
                    floor_progress += min(candidate_value, floor) - min(base_value, floor)
                if cat_delta < -regress_tol and not regressed_reason:
                    regressed_reason = f"{scorer.name}/{category} {cat_delta:+.4f}"
            category_deltas[scorer.name] = cat_d
            scorer_view_deltas: dict[str, float] = {}
            for view_name, candidate_view in candidate_views.items():
                base_view = base_views[scorer.name].get(view_name)
                if base_view is None:
                    continue
                view_delta = candidate_view.aggregate - base_view.aggregate
                scorer_view_deltas[view_name] = view_delta
                if view_delta < -regress_tol and not regressed_reason:
                    regressed_reason = (
                        f"{scorer.name}/{view_name} aggregate {view_delta:+.4f}"
                    )
                for category, base_value in base_view.per_category.items():
                    cat_delta = (
                        candidate_view.per_category.get(category, 0.0) - base_value
                    )
                    if cat_delta < -regress_tol and not regressed_reason:
                        regressed_reason = (
                            f"{scorer.name}/{view_name}/{category} {cat_delta:+.4f}"
                        )
            view_deltas[scorer.name] = scorer_view_deltas
        if floor_progress > noise_margin:
            improved = True
        is_improvement = improved and not regressed_reason
        if is_improvement:
            parts = [
                f"{name} {d:+.4f}" for name, d in deltas.items() if d > noise_margin
            ]
            if floor_progress > noise_margin:
                parts.append(f"category-floor progress {floor_progress:+.4f}")
            reason = "improves " + ", ".join(parts)
        elif regressed_reason:
            reason = f"regresses {regressed_reason}"
        else:
            reason = "no change beyond noise"
        evaluations.append(
            CandidateEvaluation(
                candidate,
                deltas,
                category_deltas,
                is_improvement,
                reason,
                floor_progress,
                view_deltas,
            )
        )
    return evaluations


def select_best_improvement(
    evaluations: Sequence[CandidateEvaluation],
) -> CandidateEvaluation | None:
    """The improving candidate with the largest total aggregate gain, or None."""
    improving = [e for e in evaluations if e.is_improvement]
    if not improving:
        return None
    return max(improving, key=lambda e: (e.floor_progress, sum(e.deltas.values())))
