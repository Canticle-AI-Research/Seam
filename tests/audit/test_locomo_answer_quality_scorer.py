"""CI-safe (model-free) tests for the free LoCoMo answer-quality scorer.

The scorer needs a generating answerer at runtime (local Ollama), which CI has
no access to, so these use a fake adapter that records the char budget seen
during each answer() call. They lock the two contracts that matter for Strand B:

* ``profile_safe`` is True (the loop may tune the profile against it);
* the candidate's ``context_budget`` is applied to the adapter's ``self.budget``
  char trim for the pass and restored after - the adapter trims with its own
  budget, not ``flags.context_budget``, so without this the knob would be inert.
"""

from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

from benchmarks.external.common.types import AdapterAnswer
from benchmarks.external.locomo.answer_quality_scorer import PooledLocomoAnswerQualityScorer
from seam_runtime.retrieval import RetrievalFlags


class _FakeRuntime:
    def __init__(self):
        self._retrieval_flags = None
        self.store = object()


class _FakeAdapter:
    """Minimal stand-in: records ``self.budget`` at each answer() so the test can
    assert the scorer applied the candidate's context_budget during the pass."""

    def __init__(self, answers: dict[str, str], start_budget: int = 2000):
        self.budget = start_budget
        self._answers = answers
        self._rt = _FakeRuntime()
        self.budgets_seen: list[int] = []

    def _runtime(self, scope):
        return self._rt

    def answer(self, scope, question):
        self.budgets_seen.append(self.budget)
        return AdapterAnswer(retrieved_context="ctx", generated_answer=self._answers[question])


def _one_case(question="who", gold="alice paris", category="1"):
    return OrderedDict(
        {"conv-1": [SimpleNamespace(case_id="conv-1::q0", question=question, gold_answer=gold, category=category)]}
    )


def test_answer_quality_scorer_is_profile_safe():
    scorer = PooledLocomoAnswerQualityScorer(adapter=_FakeAdapter({}), cases_by_scope=OrderedDict())
    assert scorer.profile_safe is True
    assert scorer.name == "locomo_answer_quality"


def test_applies_context_budget_to_adapter_and_restores():
    adapter = _FakeAdapter({"who": "alice paris"}, start_budget=2000)
    scorer = PooledLocomoAnswerQualityScorer(adapter=adapter, cases_by_scope=_one_case())

    report = scorer.score(None, flags=RetrievalFlags(search_top_k=300, context_budget=60000))

    # the adapter char budget DURING the pass was the candidate's context_budget
    assert adapter.budgets_seen == [60000]
    # ...and was restored afterwards
    assert adapter.budget == 2000
    # exact-match generated answer -> token_f1 == 1.0
    assert report.aggregate == 1.0
    assert report.per_category == {"1": 1.0}
    # the candidate flags reached the runtime via the override and were restored
    assert adapter._rt._retrieval_flags is None


def test_context_budget_none_leaves_adapter_budget_unchanged():
    adapter = _FakeAdapter({"who": "bob"}, start_budget=2000)
    scorer = PooledLocomoAnswerQualityScorer(adapter=adapter, cases_by_scope=_one_case(gold="alice"))

    report = scorer.score(None, flags=RetrievalFlags())  # context_budget None

    assert adapter.budgets_seen == [2000]  # unchanged
    assert adapter.budget == 2000
    assert report.aggregate == 0.0  # "bob" vs "alice" -> no token overlap
