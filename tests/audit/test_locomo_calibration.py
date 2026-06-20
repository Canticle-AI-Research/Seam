"""CI-safe tests for the LoCoMo calibration scorer (operationalizes
`docs/engineering/09_EPISTEMIC_CALIBRATION.md`). Hermetic: a stub adapter
supplies canned answers, so there is no Ollama, no API, no dataset, no ingest.

The headline test is `test_abstaining_on_everything_is_not_optimal` — it encodes
the policy's central thesis: a model that never hallucinates only because it
never answers is NOT well calibrated.
"""

import json
from collections import OrderedDict

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.types import AdapterAnswer, BenchmarkCase
from benchmarks.external.locomo.calibration_scorer import (
    REWARDS,
    CalibrationScorer,
    classify_case,
    is_abstention,
)


def _write_locomo(tmp_path):
    """Minimal LoCoMo file: one answerable + one adversarial (no `answer`)."""
    data = [{
        "sample_id": "t1",
        "conversation": {"sessions": [
            {"date_time": "2020-01-01", "dialogs": [{"speaker": "A", "text": "hi"}]}
        ]},
        "qa": [
            {"question": "answerable?", "answer": "yes", "category": 1},
            {"question": "adversarial?", "adversarial_answer": "trap", "category": 5,
             "evidence": ["D1:1"]},
        ],
    }]
    p = tmp_path / "mini_locomo.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_loader_default_skips_adversarial(tmp_path):
    cases = load_locomo_cases(_write_locomo(tmp_path))
    assert [c.category for c in cases] == ["1"]            # adversarial dropped
    assert all(c.gold_answer.strip() for c in cases)        # no empty gold


def test_loader_include_unanswerable_admits_adversarial(tmp_path):
    cases = load_locomo_cases(_write_locomo(tmp_path), include_unanswerable=True)
    assert {c.category for c in cases} == {"1", "5"}
    adv = next(c for c in cases if c.category == "5")
    assert adv.gold_answer == ""                            # unanswerable arm
    assert adv.question == "adversarial?"


class _StubAdapter:
    """Minimal adapter: returns a canned generated_answer per question. The
    scorer only calls `.answer()` when `flags is None`, so nothing else is needed."""

    name = "stub"

    def __init__(self, answers_by_question: dict[str, str | None]):
        self._answers = answers_by_question

    def answer(self, scope: str, question: str) -> AdapterAnswer:
        return AdapterAnswer(retrieved_context="", generated_answer=self._answers.get(question))


def _case(qid: str, question: str, gold: str) -> BenchmarkCase:
    cat = "5" if gold == "" else "1"
    return BenchmarkCase(case_id=f"conv-x::{qid}", conversation=(), question=question,
                         gold_answer=gold, category=cat)


def _scorer(rows: list[tuple[str, str, str, str | None]]) -> CalibrationScorer:
    """rows = [(qid, question, gold, generated)]."""
    cases = [_case(qid, q, gold) for qid, q, gold, _ in rows]
    answers = {q: gen for _, q, _, gen in rows}
    adapter = _StubAdapter(answers)
    return CalibrationScorer(adapter=adapter, cases_by_scope=OrderedDict({"conv-x": cases}), tau=0.3)


# --- abstention detection --------------------------------------------------

def test_is_abstention_recognizes_unknown_and_empty():
    assert is_abstention("unknown")
    assert is_abstention("")
    assert is_abstention(None)
    assert is_abstention("I don't know")
    assert is_abstention("Not mentioned.")


def test_is_abstention_rejects_real_answers():
    assert not is_abstention("Paris")
    assert not is_abstention("She plays tennis and paints")
    # contains the word but is a real, long answer -> not an abstention
    assert not is_abstention("the cause of the outage is still unknown to the on-call team")


# --- classify_case mirrors the reward matrix -------------------------------

def test_classify_answerable_correct_wrong_abstain():
    assert classify_case("blue", "blue", tau=0.3)[0] == "correct"
    assert classify_case("blue", "red", tau=0.3)[0] == "wrong"
    assert classify_case("blue", "unknown", tau=0.3)[0] == "abstained_answerable"


def test_classify_unanswerable_abstain_vs_hallucinate():
    assert classify_case("", "unknown", tau=0.3)[0] == "justified_abstention"
    assert classify_case("", "self-care is important", tau=0.3)[0] == "hallucination"


def test_reward_matrix_ordering_is_the_contract():
    # fabrication/hallucination << wrong < unnecessary-abstention < correct == justified
    assert REWARDS["hallucination"] < REWARDS["wrong"] < REWARDS["abstained_answerable"] < 0
    assert REWARDS["correct"] == REWARDS["justified_abstention"] > 0


# --- full metric math on a hand-built set ----------------------------------

def test_calibration_report_metric_math():
    rep = _scorer([
        ("q0", "capital of france?", "paris", "paris"),          # correct  +2
        ("q1", "favorite color?", "blue", "red"),                # wrong    -3
        ("q2", "what sport?", "tennis", "unknown"),              # abst-ans -1
        ("q3", "adversarial A", "", "unknown"),                  # justified +2
        ("q4", "adversarial B", "", "self-care is important"),  # halluc   -4
    ]).calibration_report()

    assert rep.n == 5 and rep.n_answerable == 3 and rep.n_unanswerable == 2
    assert rep.coverage == 2 / 3            # 2 of 3 answerable attempted
    assert rep.selective_accuracy == 0.5    # 1 correct of 2 attempted
    assert rep.selective_quality == 0.5     # mean f1 (1.0 + 0.0)/2
    assert rep.abstention_precision == 0.5  # 1 justified of 2 abstentions
    assert rep.hallucination_rate == 0.5    # 1 hallucination of 2 unanswerable
    assert rep.calibration_utility == (2 - 3 - 1 + 2 - 4) / 5  # -0.8
    assert rep.fabricated_evidence is None
    assert rep.counts == {"correct": 1, "wrong": 1, "abstained_answerable": 1,
                          "justified_abstention": 1, "hallucination": 1}


# --- the policy's central thesis -------------------------------------------

def test_abstaining_on_everything_is_not_optimal():
    """A model that abstains on every question has hallucination_rate 0 and is
    safe — but it is NOT well calibrated: coverage collapses to 0 and its utility
    is far below a calibrated model. This is why abstention is not unconditionally
    rewarded (09_EPISTEMIC_CALIBRATION.md)."""
    rows = [
        ("q0", "q0", "paris", None), ("q1", "q1", "blue", None), ("q2", "q2", "tennis", None),
        ("q3", "q3", "", None), ("q4", "q4", "", None),
    ]
    abstain_all = _scorer([(i, q, g, "unknown") for i, q, g, _ in rows]).calibration_report()
    perfect = _scorer([
        ("q0", "q0", "paris", "paris"), ("q1", "q1", "blue", "blue"), ("q2", "q2", "tennis", "tennis"),
        ("q3", "q3", "", "unknown"), ("q4", "q4", "", "unknown"),
    ]).calibration_report()

    # safe but useless
    assert abstain_all.hallucination_rate == 0.0
    assert abstain_all.coverage == 0.0
    # and decisively worse than the calibrated model
    assert abstain_all.calibration_utility < perfect.calibration_utility
    assert perfect.coverage == 1.0 and perfect.calibration_utility == 2.0


def test_reckless_confidence_is_punished_on_unanswerable():
    """Answering every adversarial (unanswerable) question confidently tanks the
    score via the hallucination penalty, even if some answerable guesses land."""
    rep = _scorer([
        ("q0", "q0", "paris", "paris"),                 # correct  +2
        ("q1", "q1", "", "a plausible lie"),            # halluc   -4
        ("q2", "q2", "", "another confident guess"),    # halluc   -4
    ]).calibration_report()
    assert rep.hallucination_rate == 1.0
    assert rep.calibration_utility < 0


def test_score_protocol_returns_scorereport():
    """Conforms to the Scorer protocol: aggregate == calibration utility."""
    scorer = _scorer([("q0", "q0", "paris", "paris"), ("q1", "q1", "", "unknown")])
    report = scorer.score(runtime=None, flags=None)
    assert report.scorer == "locomo_calibration"
    assert report.n == 2
    assert report.aggregate == 2.0  # (+2 correct, +2 justified) / 2
