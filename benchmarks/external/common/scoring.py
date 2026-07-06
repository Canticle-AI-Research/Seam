from __future__ import annotations

import re
import string
from collections import Counter


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = "".join(ch for ch in text if ch not in string.punctuation)
    return " ".join(text.split())


def exact_match(pred: str, gold: str) -> float:
    return 1.0 if _normalize(pred) == _normalize(gold) else 0.0


def token_f1(pred: str, gold: str) -> float:
    pred_tokens = _normalize(pred).split()
    gold_tokens = _normalize(gold).split()
    if not pred_tokens or not gold_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def context_recall(retrieved: str, gold: str) -> float:
    """1.0 if every token of the gold answer appears in the retrieved context."""
    retrieved_tokens = set(_normalize(retrieved).split())
    gold_tokens = _normalize(gold).split()
    if not gold_tokens:
        return 1.0
    hits = sum(1 for tok in gold_tokens if tok in retrieved_tokens)
    return hits / len(gold_tokens)


def aggregate_judge_scores(verdicts: list) -> dict:
    seen = [v for v in verdicts if v is not None]
    if not seen:
        return {"judge_score_mean": None, "judge_count": 0}
    def _score(v):
        return v.score if hasattr(v, "score") else v["score"]

    def _verdict(v):
        return v.verdict if hasattr(v, "verdict") else v["verdict"]
    result = {
        "judge_score_mean": sum(_score(v) for v in seen) / len(seen),
        "judge_count": len(seen),
        "correct_count": sum(1 for v in seen if _verdict(v) == "correct"),
        "partial_count": sum(1 for v in seen if _verdict(v) == "partial"),
        "incorrect_count": sum(1 for v in seen if _verdict(v) == "incorrect"),
    }
    abstain = sum(1 for v in seen if _verdict(v) == "abstain")
    if abstain > 0:
        result["abstain_count"] = abstain
    return result
