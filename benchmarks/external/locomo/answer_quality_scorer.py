"""Free LoCoMo ANSWER-QUALITY scorer for the H2 self-improvement loop.

Implements the ``seam_runtime.self_improve.Scorer`` protocol, scoring the
generated answer's ``token_f1`` against the gold answer using a FREE local
Ollama answerer - no judge, no API, no paid call. It is the dilution-sensitive
counterpart to ``LocomoRecallScorer``:

* ``context_recall`` (the recall scorer) RISES monotonically with a bigger
  search_top_k / context budget - more retrieved text mechanically contains more
  gold tokens - so it cannot safely tune those knobs (it would always pick the
  widest budget). The self-probe scorer has the same hazard (more candidates ->
  trivially higher record-in-set recall).
* ``token_f1`` of a GENERATED answer FALLS when the context is over-broad for the
  answerer: too much context dilutes a weak model and the answer degrades
  (validated free - a weak qwen-3b answerer scored token_f1 0.34 at the compact
  profile vs 0.03 at broad). So this scorer is ``profile_safe`` - the loop may
  propose the answerer-aware profile knobs against it, and it tunes the knee to
  whatever answerer is configured (compact for a weak local model, broad for a
  capable one).

Cost: FREE but NOT free of a model - it requires a reachable local Ollama
endpoint (``SEAM_BENCH_OLLAMA_URL``, default :11434). The always-on self-probe
loop needs no model; this scorer is opt-in for the operator who wants to
loop-tune the retrieval profile to their answerer.

Adapter note: the LoCoMo adapter trims the assembled context with its own
``self.budget`` char limit, NOT ``flags.context_budget`` (which the core
``runtime.pack_ir`` honors but the adapter's evidence-context path does not). So
to A/B the context_budget knob honestly this scorer applies the candidate flags'
``context_budget`` to the adapter's ``budget`` for the scoring pass (restored
after), in addition to setting ``search_top_k`` via the per-runtime flag override
that ``search_ir`` honors.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.scoring import token_f1
from benchmarks.external.common.types import BenchmarkCase
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from benchmarks.external.locomo.recall_scorer import _group_by_scope, _select_split
from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import ScoreReport
from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, DEV


@dataclass
class PooledLocomoAnswerQualityScorer:
    """Mean generated-answer ``token_f1`` pooled over the dev questions of
    MULTIPLE conversations, under whatever flags are passed to ``score``.

    ``profile_safe`` is True: this metric is dilution-sensitive, so the loop may
    propose the search_top_k/context_budget profile knobs against it. The adapter
    must be built with a generating answerer (``answerer="ollama"``)."""

    adapter: SeamLocomoAdapter
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]"
    name: str = "locomo_answer_quality"
    profile_safe: bool = True

    def score(self, runtime, flags=None) -> ScoreReport:
        runtimes = {scope: self.adapter._runtime(scope) for scope in self.cases_by_scope}
        previous = {scope: rt._retrieval_flags for scope, rt in runtimes.items()}
        applied = flags if flags is not None else load_retrieval_flags(
            next(iter(runtimes.values())).store
        ) if runtimes else None
        for rt in runtimes.values():
            rt._retrieval_flags = applied
        # The adapter trims context with self.budget, not flags.context_budget,
        # so apply the candidate's context_budget to the char trim for the pass.
        prev_budget = self.adapter.budget
        if applied is not None and applied.context_budget is not None:
            self.adapter.budget = applied.context_budget
        per_case: dict[str, float] = {}
        category_values: dict[str, list[float]] = defaultdict(list)
        try:
            for scope, cases in self.cases_by_scope.items():
                for case in cases:
                    answer = self.adapter.answer(scope, case.question)
                    f1 = token_f1(answer.generated_answer or "", case.gold_answer)
                    per_case[case.case_id] = f1
                    category_values[case.category or "unknown"].append(f1)
        finally:
            for scope, rt in runtimes.items():
                rt._retrieval_flags = previous[scope]
            self.adapter.budget = prev_budget
        n = len(per_case)
        aggregate = sum(per_case.values()) / n if n else 0.0
        per_category = {cat: sum(v) / len(v) for cat, v in category_values.items()}
        return ScoreReport(
            scorer=self.name, aggregate=aggregate, n=n,
            per_category=per_category, per_case=per_case,
        )


def build_locomo_answer_quality_scorer(
    dataset_path: str,
    *,
    max_scopes: int = 5,
    split: str | None = DEV,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    question_limit: int | None = None,
    answerer: str = "ollama",
    answerer_model: str = "qwen2.5:3b",
    adapter: SeamLocomoAdapter | None = None,
    **adapter_kwargs,
) -> tuple[SeamLocomoAdapter, "PooledLocomoAnswerQualityScorer"]:
    """Ingest up to ``max_scopes`` conversations and return ONE pooled
    answer-quality scorer over their ``split`` (default ``dev``) questions.

    The adapter is built with a generating answerer (default local Ollama
    ``qwen2.5:3b``), so this requires a reachable ``SEAM_BENCH_OLLAMA_URL``. The
    loop never tunes on holdout: ``split`` defaults to ``dev``.
    """
    cases = load_locomo_cases(dataset_path)
    groups = _group_by_scope(cases)
    adapter = adapter or SeamLocomoAdapter(
        answerer=answerer, answerer_model=answerer_model, **adapter_kwargs
    )
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
    return adapter, PooledLocomoAnswerQualityScorer(adapter=adapter, cases_by_scope=cases_by_scope)
