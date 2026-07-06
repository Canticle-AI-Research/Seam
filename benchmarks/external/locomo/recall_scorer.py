"""Free LoCoMo string-match scorer for the H2 self-improvement loop.

Implements the ``seam_runtime.self_improve.Scorer`` protocol on top of the real
LoCoMo adapter, so the proposer optimizes the *actual* benchmark metric
(``common.scoring.context_recall``) rather than a lookalike proxy. It is FREE:
``--answerer none --judge none`` semantics - no judge, no API, no paid call.

Fidelity: it drives the adapter's full ``answer()`` path (retrieval + evidence
closure + char-budget trim), exactly as ``runner.run_benchmark_grouped`` does,
and scores ``context_recall(retrieved_context, gold_answer)``. To evaluate a
candidate lever set it overrides the adapter runtime's cached
``_retrieval_flags`` for the duration of the scoring pass (restored after), so
``search_ir`` retrieves under the candidate flags without env mutation or
re-ingest. The conversation is ingested ONCE at construction; ``score`` only
re-runs retrieval, so a full lever sweep is cheap.

Anti-gaming note: ``context_recall`` rises with the char budget / search_top_k,
but those are FIXED on the adapter for the scorer's lifetime; the proposer's
levers only re-rank within that fixed budget, so it cannot game the score by
enlarging the context.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Sequence

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.scoring import context_recall
from benchmarks.external.common.types import BenchmarkCase
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.retrieval import load_retrieval_flags
from seam_runtime.self_improve import ScoreReport
from tools.h2.holdout_split import DEFAULT_RATIO, DEFAULT_SALT, DEV, assign_one


def scope_for(case_id: str) -> str:
    """LoCoMo case_id -> conversation scope (``conv-26::q0`` -> ``conv-26``)."""
    return case_id.split("::", 1)[0]


def _select_split(
    cases: Sequence[BenchmarkCase], split: str | None, *, salt: str, ratio: float
) -> list[BenchmarkCase]:
    """Filter cases to the dev/holdout ``split`` via the deterministic
    ``assign_one`` hash (same salt+ratio => same partition forever). ``split``
    None keeps every case. The self-improvement loop tunes on ``dev`` ONLY;
    ``holdout`` is reserved for publish-time audits and must never feed the gate."""
    if split is None:
        return list(cases)
    return [c for c in cases if assign_one(c.case_id, salt=salt, ratio=ratio) == split]


@dataclass
class LocomoRecallScorer:
    """Mean ``context_recall`` over one conversation's questions, under whatever
    flags are passed to ``score`` (baseline when ``flags is None``)."""

    adapter: SeamLocomoAdapter
    scope: str
    cases: Sequence[BenchmarkCase]
    name: str = "locomo_recall"

    def score(self, runtime, flags=None) -> ScoreReport:
        rt = self.adapter._runtime(self.scope)
        previous = rt._retrieval_flags
        rt._retrieval_flags = flags if flags is not None else load_retrieval_flags(rt.store)
        per_case: dict[str, float] = {}
        category_values: dict[str, list[float]] = defaultdict(list)
        try:
            for case in self.cases:
                answer = self.adapter.answer(self.scope, case.question)
                recall = context_recall(answer.retrieved_context, case.gold_answer)
                per_case[case.case_id] = recall
                category_values[case.category or "unknown"].append(recall)
        finally:
            rt._retrieval_flags = previous
        n = len(self.cases)
        aggregate = sum(per_case.values()) / n if n else 0.0
        per_category = {cat: sum(v) / len(v) for cat, v in category_values.items()}
        return ScoreReport(
            scorer=self.name,
            aggregate=aggregate,
            n=n,
            per_category=per_category,
            per_case=per_case,
        )


@dataclass
class PooledLocomoRecallScorer:
    """Mean ``context_recall`` pooled over the dev questions of MULTIPLE
    conversations. One aggregate + per-category recall across a diverse dev set
    is a more generalizable signal than a single conversation (the #292 caveat:
    a one-conversation win may not hold elsewhere). Each question is answered via
    its own conversation's runtime; the candidate flags are applied to every
    touched runtime for the scoring pass and restored after."""

    adapter: SeamLocomoAdapter
    cases_by_scope: "OrderedDict[str, list[BenchmarkCase]]"
    name: str = "locomo_recall"

    def score(self, runtime, flags=None) -> ScoreReport:
        runtimes = {scope: self.adapter._runtime(scope) for scope in self.cases_by_scope}
        previous = {scope: rt._retrieval_flags for scope, rt in runtimes.items()}
        for rt in runtimes.values():
            rt._retrieval_flags = flags if flags is not None else load_retrieval_flags(rt.store)
        per_case: dict[str, float] = {}
        category_values: dict[str, list[float]] = defaultdict(list)
        try:
            for scope, cases in self.cases_by_scope.items():
                for case in cases:
                    answer = self.adapter.answer(scope, case.question)
                    recall = context_recall(answer.retrieved_context, case.gold_answer)
                    per_case[case.case_id] = recall
                    category_values[case.category or "unknown"].append(recall)
        finally:
            for scope, rt in runtimes.items():
                rt._retrieval_flags = previous[scope]
        n = len(per_case)
        aggregate = sum(per_case.values()) / n if n else 0.0
        per_category = {cat: sum(v) / len(v) for cat, v in category_values.items()}
        return ScoreReport(
            scorer=self.name, aggregate=aggregate, n=n,
            per_category=per_category, per_case=per_case,
        )


def build_locomo_dev_scorer(
    dataset_path: str,
    *,
    max_scopes: int = 5,
    split: str | None = DEV,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    question_limit: int | None = None,
    adapter: SeamLocomoAdapter | None = None,
    **adapter_kwargs,
) -> tuple[SeamLocomoAdapter, "PooledLocomoRecallScorer"]:
    """Ingest up to ``max_scopes`` conversations and return ONE pooled scorer over
    their ``split`` (default ``dev``) questions - the multi-conversation dev gate.

    FREE (answerer=None). ``split`` defaults to ``dev`` so the loop never tunes on
    holdout. A scope contributing zero dev questions is skipped (not ingested-then-empty).
    """
    cases = load_locomo_cases(dataset_path)
    groups = _group_by_scope(cases)
    adapter = adapter or SeamLocomoAdapter(answerer=None, **adapter_kwargs)
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
    return adapter, PooledLocomoRecallScorer(adapter=adapter, cases_by_scope=cases_by_scope)


def _group_by_scope(cases: Sequence[BenchmarkCase]) -> "OrderedDict[str, list[BenchmarkCase]]":
    groups: "OrderedDict[str, list[BenchmarkCase]]" = OrderedDict()
    for case in cases:
        groups.setdefault(scope_for(case.case_id), []).append(case)
    return groups


def build_locomo_recall_scorers(
    dataset_path: str,
    *,
    max_scopes: int = 1,
    question_limit: int | None = None,
    adapter: SeamLocomoAdapter | None = None,
    **adapter_kwargs,
) -> tuple[SeamLocomoAdapter, list[LocomoRecallScorer]]:
    """Load the dataset, ingest up to ``max_scopes`` conversations once each, and
    return one ``LocomoRecallScorer`` per scope. FREE - no answerer/judge.

    Pass the conversation through the adapter exactly as the benchmark runner
    does (reset -> ingest each turn). ``question_limit`` caps the questions per
    scope (for a faster inner-loop signal).
    """
    cases = load_locomo_cases(dataset_path)
    groups = _group_by_scope(cases)
    # answerer=None -> retrieval only, no generation (free, no judge/API).
    adapter = adapter or SeamLocomoAdapter(answerer=None, **adapter_kwargs)
    scorers: list[LocomoRecallScorer] = []
    for scope, group in list(groups.items())[:max_scopes]:
        adapter.reset(scope)
        for turn in group[0].conversation:
            adapter.ingest_turn(scope, turn)
        questions = list(group[:question_limit]) if question_limit else list(group)
        scorers.append(LocomoRecallScorer(adapter=adapter, scope=scope, cases=questions))
    return adapter, scorers
