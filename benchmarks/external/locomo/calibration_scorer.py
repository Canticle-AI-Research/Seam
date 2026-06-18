"""Free LoCoMo calibration scorer — executable teeth for the epistemic policy.

Operationalizes `docs/engineering/09_EPISTEMIC_CALIBRATION.md`: it turns the
"calibrated truthfulness" policy (reward justified abstention, penalize confident
errors harder, never reward abstaining-on-everything) into a measured property
over the real LoCoMo split, with NO paid call.

Answerability label comes straight from the dataset, no inference required:
  - cat5 (adversarial) loads with `gold_answer == ""`  -> answerable = False
    (the loader coerces the dataset's `answer: null` to "" and does NOT leak the
    `adversarial_answer` trap as gold).
  - cat1-4 load with a non-empty gold                  -> answerable = True

This is exactly the policy's requirement to label answerability explicitly
instead of inferring unanswerability from a weak retrieval score (which would
confound retrieval failure with genuinely-absent evidence).

The reward matrix mirrors the policy doc's table (the magnitudes are ORDINAL
policy, not calibrated truth — the load-bearing part is the ordering:
fabrication << wrong < unnecessary-abstention < correct == justified-abstention).
v1 cannot detect fabricated *evidence/citations* (the loader drops the evidence
annotations), so the -5 hard-fail row and the "labeled as inference" partial-credit
rows are out of scope and reported as `fabricated_evidence = None`.

FREE: drive the adapter with `answerer="ollama"` (local, deterministic via the
#323 seed+top_k=1 path) for real runs; CI uses a stub adapter (no Ollama, no API).
"""

from __future__ import annotations

import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.scoring import token_f1
from benchmarks.external.common.types import BenchmarkCase
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from benchmarks.external.locomo.recall_scorer import _group_by_scope, _select_split
from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import ScoreReport
from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, DEV

# --- abstention vocabulary -------------------------------------------------
# The adapter answerer is instructed to emit exactly "unknown" when the context
# has no answer candidate, and the abstain-threshold path also emits "unknown".
# The rest are defensive variants so a slightly chattier answerer still counts.
_ABSTENTION_MARKERS = (
    "unknown",
    "i don't know",
    "i dont know",
    "not mentioned",
    "not specified",
    "no information",
    "not enough information",
    "insufficient information",
    "cannot answer",
    "can't answer",
    "not in the conversation",
    "n/a",
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def is_abstention(answer: str | None) -> bool:
    """True when the model declined to answer. ``None``/empty counts as an
    abstention (no answer was produced). A short answer that *is* an abstention
    marker counts; a long answer that merely contains the word does not (so
    "the status is unknown to the team" is not mis-read as an abstention)."""
    norm = _normalize(answer)
    if not norm:
        return True
    if norm in _ABSTENTION_MARKERS:
        return True
    # short hedge like "unknown." / "answer: unknown"
    return len(norm.split()) <= 4 and any(m in norm for m in _ABSTENTION_MARKERS)


# --- reward matrix (mirrors 09_EPISTEMIC_CALIBRATION.md) --------------------
REWARDS = {
    "correct": 2,            # answerable, attempted, correct
    "wrong": -3,             # answerable, attempted, incorrect assertion
    "abstained_answerable": -1,   # answerable, abstained (unnecessary abstention)
    "justified_abstention": 2,    # unanswerable, abstained (desired)
    "hallucination": -4,     # unanswerable, confident answer
}


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    category: str | None
    answerable: bool
    abstained: bool
    f1: float
    outcome: str          # key into REWARDS
    reward: int


def classify_case(
    gold_answer: str, generated_answer: str | None, *, tau: float
) -> tuple[str, float, bool]:
    """Return (outcome_key, token_f1, abstained). ``tau`` is the token_f1
    threshold above which an attempted answerable case counts as correct."""
    answerable = bool(_normalize(gold_answer))
    abstained = is_abstention(generated_answer)
    if answerable:
        if abstained:
            return "abstained_answerable", 0.0, True
        f1 = token_f1(generated_answer or "", gold_answer)
        return ("correct" if f1 >= tau else "wrong"), f1, False
    # unanswerable (cat5): the correct move is to abstain
    if abstained:
        return "justified_abstention", 0.0, True
    return "hallucination", 0.0, False


@dataclass
class CalibrationReport:
    scorer: str
    n: int
    n_answerable: int
    n_unanswerable: int
    coverage: float              # attempted / answerable  (usefulness)
    selective_accuracy: float    # correct / attempted-answerable  (safety@tau)
    selective_quality: float     # mean token_f1 over attempted-answerable (threshold-free)
    abstention_precision: float  # justified abstentions / all abstentions
    hallucination_rate: float    # confident answers on unanswerable / unanswerable
    calibration_utility: float   # mean reward under the matrix (the single summary)
    fabricated_evidence: int | None  # None: not measurable in v1 (no evidence annotations)
    tau: float
    counts: dict[str, int] = field(default_factory=dict)
    per_category: dict[str, float] = field(default_factory=dict)
    per_case: dict[str, float] = field(default_factory=dict)


@dataclass
class CalibrationScorer:
    """Calibration metrics over one pooled set of LoCoMo cases (cat1-5).

    Conforms to the ``Scorer`` protocol (``score`` returns a ``ScoreReport`` whose
    ``aggregate`` is the calibration utility, so it can plug into existing tooling)
    and also exposes ``calibration_report`` with the full policy metric set.
    """

    adapter: SeamLocomoAdapter
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]"
    tau: float = 0.3
    name: str = "locomo_calibration"

    def _run(self, flags) -> list[CaseOutcome]:
        touched = {s: self.adapter._runtime(s) for s in self.cases_by_scope} if flags is not None else {}
        previous = {s: rt._retrieval_flags for s, rt in touched.items()}
        for rt in touched.values():
            rt._retrieval_flags = flags
        outcomes: list[CaseOutcome] = []
        try:
            for scope, cases in self.cases_by_scope.items():
                for case in cases:
                    ans = self.adapter.answer(scope, case.question)
                    outcome, f1, abstained = classify_case(
                        case.gold_answer, ans.generated_answer, tau=self.tau
                    )
                    outcomes.append(CaseOutcome(
                        case_id=case.case_id, category=case.category,
                        answerable=bool(_normalize(case.gold_answer)),
                        abstained=abstained, f1=f1, outcome=outcome,
                        reward=REWARDS[outcome],
                    ))
        finally:
            for s, rt in touched.items():
                rt._retrieval_flags = previous[s]
        return outcomes

    def calibration_report(self, flags=None) -> CalibrationReport:
        outs = self._run(flags)
        n = len(outs)
        answerable = [o for o in outs if o.answerable]
        unanswerable = [o for o in outs if not o.answerable]
        attempted_ans = [o for o in answerable if not o.abstained]
        correct = [o for o in attempted_ans if o.outcome == "correct"]
        abstentions = [o for o in outs if o.abstained]
        justified = [o for o in abstentions if not o.answerable]
        halluc = [o for o in unanswerable if not o.abstained]

        def ratio(a: int, b: int) -> float:
            return a / b if b else 0.0

        counts: dict[str, int] = defaultdict(int)
        for o in outs:
            counts[o.outcome] += 1
        cat_rewards: dict[str, list[int]] = defaultdict(list)
        for o in outs:
            cat_rewards[o.category or "unknown"].append(o.reward)

        return CalibrationReport(
            scorer=self.name,
            n=n,
            n_answerable=len(answerable),
            n_unanswerable=len(unanswerable),
            coverage=ratio(len(attempted_ans), len(answerable)),
            selective_accuracy=ratio(len(correct), len(attempted_ans)),
            selective_quality=(sum(o.f1 for o in attempted_ans) / len(attempted_ans)) if attempted_ans else 0.0,
            abstention_precision=ratio(len(justified), len(abstentions)),
            hallucination_rate=ratio(len(halluc), len(unanswerable)),
            calibration_utility=(sum(o.reward for o in outs) / n) if n else 0.0,
            fabricated_evidence=None,  # not measurable without evidence annotations (v1)
            tau=self.tau,
            counts=dict(counts),
            per_category={c: sum(v) / len(v) for c, v in cat_rewards.items()},
            per_case={o.case_id: float(o.reward) for o in outs},
        )

    def score(self, runtime, flags=None) -> ScoreReport:
        rep = self.calibration_report(flags)
        return ScoreReport(
            scorer=self.name,
            aggregate=rep.calibration_utility,
            n=rep.n,
            per_category=rep.per_category,
            per_case=rep.per_case,
        )


def build_locomo_calibration_scorer(
    dataset_path: str,
    *,
    answerer: str | None = "ollama",
    max_scopes: int = 5,
    split: str | None = DEV,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    tau: float = 0.3,
    question_limit: int | None = None,
    adapter: SeamLocomoAdapter | None = None,
    **adapter_kwargs,
) -> tuple[SeamLocomoAdapter, CalibrationScorer]:
    """Ingest up to ``max_scopes`` conversations and return a pooled calibration
    scorer over their ``split`` (default ``dev``) questions, ALL categories
    (cat5 supplies the unanswerable arm).

    FREE: defaults to the local Ollama answerer (deterministic seed+top_k=1).
    ``split`` defaults to ``dev`` so measurement never touches holdout.

    Loads with ``include_unanswerable=True`` so the cat5 adversarial questions
    (no real answer, only a trap) supply the unanswerable arm; without them the
    calibration metric has no abstention target on real LoCoMo.
    """
    cases = load_locomo_cases(dataset_path, include_unanswerable=True)
    groups = _group_by_scope(cases)
    adapter = adapter or SeamLocomoAdapter(answerer=answerer, **adapter_kwargs)
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]" = OrderedDict()
    for scope, group in list(groups.items())[:max_scopes]:
        dev_cases = _select_split(group, split, salt=salt, ratio=ratio)
        if question_limit is not None:
            dev_cases = dev_cases[:question_limit]
        if not dev_cases:
            continue
        adapter.reset(scope)
        for turn in group[0].conversation:
            adapter.ingest_turn(scope, turn)
        cases_by_scope[scope] = dev_cases
    return adapter, CalibrationScorer(adapter=adapter, cases_by_scope=cases_by_scope, tau=tau)
