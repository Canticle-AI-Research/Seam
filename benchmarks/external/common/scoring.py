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
    """1.0 if every token of the gold answer appears in the retrieved context.

    NOTE: this is a crude gold-token-overlap proxy. It false-positives on
    generic tokens (dates, bare numbers, yes/no, common single words) that
    appear in a long context for unrelated reasons, so it must NOT be trusted
    alone to attribute a wrong answer to the retriever vs. the answerer. Use
    ``evidence_status`` for that attribution. Preserved unchanged for backward
    compatibility of the recorded numeric field."""
    retrieved_tokens = set(_normalize(retrieved).split())
    gold_tokens = _normalize(gold).split()
    if not gold_tokens:
        return 1.0
    hits = sum(1 for tok in gold_tokens if tok in retrieved_tokens)
    return hits / len(gold_tokens)


# --- Conservative evidence attribution (measurement integrity) -----------------
#
# The crude ``context_recall`` overlap mislabels correct "unknown" refusals as
# answerer failures (documented cases: a date gold "19 October 2023" scoring
# 0.67 because "october"/"2023" appear elsewhere; a "Yes" gold scoring 1.0 as a
# pure false positive). ``evidence_status`` is the conservative replacement used
# to attribute a non-correct verdict to the retriever, the answerer, or neither.
# Bump ``EVIDENCE_CLASSIFIER_VERSION`` whenever the rule changes so recorded runs
# stay comparable.
EVIDENCE_CLASSIFIER_VERSION = "evidence/1"

# Month names + short forms: a bare date token is not distinctive evidence.
_MONTHS = frozenset(
    "january february march april may june july august september october "
    "november december jan feb mar apr jun jul aug sep sept oct nov dec".split()
)
# Answer fillers that carry no locateable content of their own.
_GENERIC_ANSWER_TOKENS = frozenset({"yes", "no", "none", "unknown", "na", "nan", "unclear", "nil"})


def _is_generic_token(tok: str) -> bool:
    """A token whose appearance in a long context is not, by itself, evidence:
    month names, bare numbers/years, and yes/no/unknown fillers."""
    if tok in _MONTHS or tok in _GENERIC_ANSWER_TOKENS:
        return True
    if tok.isdigit():
        return True
    return False


def content_tokens(text: str) -> list[str]:
    """Distinctive (non-generic) normalized tokens of ``text``. These are the
    tokens whose presence in the retrieved context is real evidence, as opposed
    to the coincidental generic-token overlap that inflates ``context_recall``."""
    return [t for t in _normalize(text).split() if not _is_generic_token(t)]


def is_open_domain_category(category) -> bool:
    """LoCoMo cat3 = open-domain / world-knowledge QA. Its gold answer may
    legitimately require outside knowledge that is NOT written in the dialogue,
    so gold-token-in-context overlap is not a valid retrieval signal for it."""
    return str(category).strip().lower() in {"3", "cat3"}


def _segments(text: str) -> list[str]:
    """Split packed context into co-occurrence units. LoCoMo's packed context is
    one conversational turn per line (``[Speaker time] utterance``), so a line is
    a turn. Falls back to the whole text as one segment when it is unstructured
    (no newlines), which safely degrades to plain whole-context membership."""
    segs = [s for s in text.split("\n") if s.strip()]
    return segs or ([text] if text.strip() else [])


def evidence_status(retrieved: str, gold: str, category=None) -> tuple[str, str]:
    """Conservative retrieval-evidence attribution for a gold answer.

    Returns ``(status, rationale)``. Unlike ``context_recall`` (a float), this
    does not treat coincidental generic-token overlap as evidence, and it
    refuses to attribute open-domain (cat3) answers to retrieval at all.

    A multi-token gold is only ``present`` when its distinctive tokens
    **co-occur within a single turn** — words that merely appear scattered
    across unrelated turns are NOT evidence that the answer was retrievable, so
    they fall to ``uncertain``. A lone distinctive token is likewise too weak.

    Statuses:
      - ``present``     strong: distinctive gold tokens co-occur in one turn.
      - ``absent``      no distinctive gold token is anywhere in the context.
      - ``uncertain``   partial / generic-only / scattered / single-weak overlap.
      - ``open_domain`` cat3: not a retrieval-vs-answerer question.
    """
    if is_open_domain_category(category):
        return (
            "open_domain",
            "cat3 open-domain/world-knowledge: gold-token overlap is not a retrieval signal",
        )
    gold_set = set(content_tokens(gold))
    if not gold_set:
        return (
            "uncertain",
            "gold has no distinctive content tokens (dates/numbers/yes-no only); overlap not decisive",
        )
    ctx_all = set(_normalize(retrieved).split())
    present = gold_set & ctx_all
    coverage = len(present) / len(gold_set)
    if coverage == 0.0:
        return ("absent", "no distinctive gold token found in context")
    if len(gold_set) == 1:
        return (
            "uncertain",
            "single distinctive gold token present; too weak to confirm evidence",
        )
    if coverage < 1.0:
        return ("uncertain", f"partial gold-token coverage {len(present)}/{len(gold_set)}")
    # Full coverage: require co-occurrence in one turn, else it is scattered.
    for seg in _segments(retrieved):
        if gold_set <= set(_normalize(seg).split()):
            return ("present", f"all {len(gold_set)} distinctive gold tokens co-occur in one turn")
    return (
        "uncertain",
        f"all {len(gold_set)} distinctive gold tokens present but scattered across turns; not co-located",
    )


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
