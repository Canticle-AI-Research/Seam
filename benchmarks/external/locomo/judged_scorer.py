"""PAID judged LoCoMo scorer: the operator-gated holdout validation tier.

Implements the same ``seam_runtime.self_improve.Scorer`` protocol as the free
recall scorer, but measures ANSWER QUALITY rather than retrieval overlap: the
adapter's paid answerer generates an answer from the retrieved context and a
paid LLM judge scores it against the gold answer. The aggregate is
``judge_score_mean`` (correct=1.0 / partial=0.5 / incorrect=0.0), the same
metric as the HISTORY#279 paid 100-case slice (0.44 -> 0.57).

HARD OPERATOR GATE: every ``score()`` pass makes paid API calls (one answerer
call plus up to one judge call per case). This scorer must NEVER be added to
the always-on improvement loop's scorer list or auto-run by any agent; the
only entry point is ``seam improve validate`` behind ``--confirm-paid``. Use
``estimate_locomo_paid_validation`` for the zero-cost dry-run estimate (it
loads and counts cases without ingesting anything or constructing a client).

Defaults to the HOLDOUT split: validation measures generalization on cases the
dev-tuned loop has never seen (the loop tunes on dev ONLY; HISTORY#297).
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.judge import Judge, JudgeVerdict, build_judge
from benchmarks.external.common.types import BenchmarkCase
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from benchmarks.external.locomo.recall_scorer import _group_by_scope, _select_split
from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import ScoreReport
from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, HOLDOUT

# Answerers the adapter can actually generate with (seam.py _generate_answer).
GENERATING_ANSWERERS = ("openai", "claude")

# One validation = baseline pass + candidate pass.
VALIDATION_PASSES = 2


@dataclass
class JudgedLocomoScorer:
    """Pooled ``judge_score_mean`` over the questions of multiple conversations,
    under whatever flags are passed to ``score`` (baseline when ``flags is
    None``). Same flag-override/restore discipline as the free pooled scorer.

    Cost shape per ``score()`` pass: one answerer call per case, plus one judge
    call per case whose generated answer is non-empty (an empty/missing answer
    is scored 0.0 directly - certain-incorrect, no judge spend). A transient
    judge failure is retried ``judge_retries`` times, then raised: a partially
    judged pass would silently skew the baseline-vs-candidate pairing.

    ``last_run`` holds the most recent pass's verdict counts / call counts so
    the validation report can show what the spend bought.
    """

    adapter: SeamLocomoAdapter
    judge: Judge
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]"
    name: str = "locomo_judged"
    judge_retries: int = 1
    last_run: dict = field(default_factory=dict)

    def score(self, runtime, flags=None) -> ScoreReport:
        runtimes = {scope: self.adapter._runtime(scope) for scope in self.cases_by_scope}
        previous = {scope: rt._retrieval_flags for scope, rt in runtimes.items()}
        applied = flags if flags is not None else (
            load_retrieval_flags(next(iter(runtimes.values())).store) if runtimes else None
        )
        for rt in runtimes.values():
            rt._retrieval_flags = applied
        # The adapter trims context with self.budget, NOT flags.context_budget,
        # so apply the candidate's context_budget to the char trim for the pass
        # (restored in finally). Without this a 'broad' candidate gets the wider
        # candidate pool but the SAME trimmed context = a confounded judged A/B
        # (mirrors PooledLocomoAnswerQualityScorer, the free counterpart).
        prev_budget = self.adapter.budget
        if applied is not None and applied.context_budget is not None:
            self.adapter.budget = applied.context_budget
        per_case: dict[str, float] = {}
        category_values: dict[str, list[float]] = defaultdict(list)
        verdict_counts: dict[str, int] = defaultdict(int)
        judge_calls = 0
        judge_retries_used = 0
        empty_answers = 0
        try:
            for scope, cases in self.cases_by_scope.items():
                for case in cases:
                    answer = self.adapter.answer(scope, case.question)
                    pred = (answer.generated_answer or "").strip()
                    if not pred:
                        # No generated answer = certain incorrect; skip the judge
                        # call rather than pay to confirm it.
                        empty_answers += 1
                        verdict_counts["incorrect"] += 1
                        value = 0.0
                    else:
                        verdict, retries = self._judge_with_retry(case, pred)
                        judge_calls += 1 + retries
                        judge_retries_used += retries
                        verdict_counts[verdict.verdict] += 1
                        value = verdict.score
                    per_case[case.case_id] = value
                    category_values[case.category or "unknown"].append(value)
        finally:
            for scope, rt in runtimes.items():
                rt._retrieval_flags = previous[scope]
            self.adapter.budget = prev_budget
        self.last_run = {
            "verdict_counts": dict(verdict_counts),
            "judge_calls": judge_calls,
            "judge_retries": judge_retries_used,
            "empty_answers": empty_answers,
        }
        n = len(per_case)
        aggregate = sum(per_case.values()) / n if n else 0.0
        per_category = {cat: sum(v) / len(v) for cat, v in category_values.items()}
        return ScoreReport(
            scorer=self.name, aggregate=aggregate, n=n,
            per_category=per_category, per_case=per_case,
        )

    def _judge_with_retry(self, case: BenchmarkCase, pred: str) -> tuple[JudgeVerdict, int]:
        last_exc: Exception | None = None
        for attempt in range(self.judge_retries + 1):
            try:
                verdict = self.judge.score(
                    question=case.question, gold=case.gold_answer, pred=pred
                )
                return verdict, attempt
            except Exception as exc:  # judge transport/parse failure
                last_exc = exc
        raise RuntimeError(
            f"judge failed for case {case.case_id!r} after "
            f"{self.judge_retries + 1} attempts: {last_exc}"
        ) from last_exc


def build_locomo_holdout_scorer(
    dataset_path: str,
    *,
    max_scopes: int = 5,
    split: str | None = HOLDOUT,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    question_limit: int | None = None,
    answerer: str = "openai",
    answerer_model: str | None = None,
    judge: str = "openai",
    judge_model: str | None = None,
    judge_instance: Judge | None = None,
    adapter: SeamLocomoAdapter | None = None,
    judge_retries: int = 1,
    **adapter_kwargs,
) -> tuple[SeamLocomoAdapter, JudgedLocomoScorer]:
    """Ingest up to ``max_scopes`` conversations and return ONE pooled PAID
    judged scorer over their ``split`` (default ``holdout``) questions.

    Argument validation happens BEFORE the dataset is read or any client is
    constructed, so a misconfigured call fails without side effects. The
    answerer must be a generating one (``answerer=None`` would judge an empty
    string for every case = paying the judge to measure nothing); the judge
    must resolve to a real Judge (``none`` is the free tier's job).
    ``judge_instance``/``adapter`` injection exists for tests.
    """
    if adapter is None and answerer not in GENERATING_ANSWERERS:
        raise ValueError(
            f"judged scorer requires a generating answerer {GENERATING_ANSWERERS}, "
            f"got {answerer!r}"
        )
    judge_obj = judge_instance or build_judge(judge, judge_model)
    if judge_obj is None:
        raise ValueError(
            "judged scorer requires a real judge (got 'none'); "
            "use the free recall scorer for judge-less measurement"
        )
    cases = load_locomo_cases(dataset_path)
    groups = _group_by_scope(cases)
    adapter = adapter or SeamLocomoAdapter(
        answerer=answerer, answerer_model=answerer_model, **adapter_kwargs
    )
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]" = OrderedDict()
    for scope, group in list(groups.items())[:max_scopes]:
        split_cases = _select_split(group, split, salt=salt, ratio=ratio)
        if question_limit is not None:
            split_cases = split_cases[:question_limit]
        if not split_cases:
            continue
        adapter.reset(scope)
        for turn in group[0].conversation:
            adapter.ingest_turn(scope, turn)
        cases_by_scope[scope] = split_cases
    return adapter, JudgedLocomoScorer(
        adapter=adapter, judge=judge_obj,
        cases_by_scope=cases_by_scope, judge_retries=judge_retries,
    )


def estimate_locomo_paid_validation(
    dataset_path: str,
    *,
    max_scopes: int = 5,
    split: str | None = HOLDOUT,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    question_limit: int | None = None,
    passes: int = VALIDATION_PASSES,
) -> dict:
    """Zero-cost dry-run estimate for a paid validation: counts the cases the
    judged scorer would run WITHOUT ingesting a conversation, constructing an
    API client, or making any call. ``*_max`` because empty generated answers
    skip their judge call at run time."""
    cases = load_locomo_cases(dataset_path)
    groups = _group_by_scope(cases)
    scopes = 0
    n = 0
    for _scope, group in list(groups.items())[:max_scopes]:
        split_cases = _select_split(group, split, salt=salt, ratio=ratio)
        if question_limit is not None:
            split_cases = split_cases[:question_limit]
        if not split_cases:
            continue
        scopes += 1
        n += len(split_cases)
    return {
        "split": split or "all",
        "scopes": scopes,
        "cases": n,
        "passes": passes,
        "answerer_calls_max": passes * n,
        "judge_calls_max": passes * n,
        "total_paid_calls_max": 2 * passes * n,
    }
