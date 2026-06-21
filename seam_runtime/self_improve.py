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

import random
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable

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


def candidate_levers(
    baseline: RetrievalFlags, *, weight_step: float = 0.10, profile_levers: bool = False
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
    return candidates


def evaluate_candidates(
    runtime: "SeamRuntime",
    scorers: Sequence[Scorer],
    candidates: Sequence[Candidate],
    baseline: RetrievalFlags,
    *,
    noise_margin: float = DEFAULT_NOISE_MARGIN,
    regress_tol: float = DEFAULT_REGRESS_TOL,
) -> list[CandidateEvaluation]:
    """Score every candidate against every scorer relative to ``baseline``.

    A candidate ``is_improvement`` iff it beats ``noise_margin`` on at least one
    scorer's aggregate AND drops no scorer's aggregate and no per-category recall
    by more than ``regress_tol``. Eval budget is whatever each scorer was built
    with - hold it fixed across the sweep (the anti-gaming guard for the
    record-in-set signal).
    """
    base = {s.name: s.score(runtime, flags=baseline) for s in scorers}
    evaluations: list[CandidateEvaluation] = []
    for candidate in candidates:
        deltas: dict[str, float] = {}
        category_deltas: dict[str, dict[str, float]] = {}
        improved = False
        regressed_reason = ""
        for scorer in scorers:
            report = scorer.score(runtime, flags=candidate.flags)
            base_report = base[scorer.name]
            delta = report.aggregate - base_report.aggregate
            deltas[scorer.name] = delta
            if delta > noise_margin:
                improved = True
            if delta < -regress_tol and not regressed_reason:
                regressed_reason = f"{scorer.name} aggregate {delta:+.4f}"
            cat_d: dict[str, float] = {}
            for category, base_value in base_report.per_category.items():
                cat_delta = report.per_category.get(category, 0.0) - base_value
                cat_d[category] = cat_delta
                if cat_delta < -regress_tol and not regressed_reason:
                    regressed_reason = f"{scorer.name}/{category} {cat_delta:+.4f}"
            category_deltas[scorer.name] = cat_d
        is_improvement = improved and not regressed_reason
        if is_improvement:
            reason = "improves " + ", ".join(
                f"{name} {d:+.4f}" for name, d in deltas.items() if d > noise_margin
            )
        elif regressed_reason:
            reason = f"regresses {regressed_reason}"
        else:
            reason = "no change beyond noise"
        evaluations.append(
            CandidateEvaluation(candidate, deltas, category_deltas, is_improvement, reason)
        )
    return evaluations


def select_best_improvement(
    evaluations: Sequence[CandidateEvaluation],
) -> CandidateEvaluation | None:
    """The improving candidate with the largest total aggregate gain, or None."""
    improving = [e for e in evaluations if e.is_improvement]
    if not improving:
        return None
    return max(improving, key=lambda e: sum(e.deltas.values()))
