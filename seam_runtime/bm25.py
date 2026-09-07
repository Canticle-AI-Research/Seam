from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9_:-]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _inverse_document_frequencies(
    n: int, df: Counter[str], q_tokens: list[str]
) -> dict[str, float]:
    return {
        term: math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
        for term in set(q_tokens)
    }


def _score_document(
    counts: Counter[str], dl: int, *, q_tokens: list[str], avgdl: float,
    idf: dict[str, float], k1: float, b: float,
) -> float:
    """Shared formula, including query multiplicity and float operation order."""
    score = 0.0
    for term in q_tokens:
        if term not in counts:
            continue
        f = counts[term]
        num = f * (k1 + 1)
        den = f + k1 * (1 - b + b * dl / avgdl)
        score += idf.get(term, 0.0) * (num / den)
    return score


class BM25Query:
    """Exact corpus statistics for one query, without retained documents.

    ``add`` observes every tokenized document, including noncandidate/status
    excluded records. Only query-term document frequencies survive each call.
    After accumulation, ``score`` rescans individual texts using the same
    formula as ``BM25Index``. Full-corpus normalization needs a separate pass.
    """

    def __init__(self, query: str, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._q_tokens = _tokens(query)
        self._terms = set(self._q_tokens)
        self._df: Counter[str] = Counter()
        self._n = 0
        self._total_length = 0
        self._idf: dict[str, float] | None = None

    def add(self, text: str) -> None:
        tokens = _tokens(text)
        if not tokens:
            return
        self._n += 1
        self._total_length += len(tokens)
        for term in self._terms.intersection(tokens):
            self._df[term] += 1
        self._idf = None

    def score(self, text: str) -> float:
        if not self._n or not self._q_tokens:
            return 0.0
        tokens = _tokens(text)
        if self._idf is None:
            self._idf = _inverse_document_frequencies(
                self._n, self._df, self._q_tokens
            )
        return _score_document(
            Counter(tokens), len(tokens), q_tokens=self._q_tokens,
            avgdl=self._total_length / self._n, idf=self._idf,
            k1=self.k1, b=self.b,
        )


class BM25Index:
    """Per-corpus BM25 over plain text documents.

    Cheap to construct (one pass over the corpus). Designed to be built
    per-scope at search time; do not persist. Constants are the standard
    BM25 defaults (k1=1.5, b=0.75) — do not retune in this fix.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_lens: list[int] = []
        self._doc_tokens: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._doc_ids: list[str] = []

    def add(self, doc_id: str, text: str) -> None:
        toks = _tokens(text)
        if not toks:
            return
        counts = Counter(toks)
        self._doc_ids.append(doc_id)
        self._doc_tokens.append(counts)
        self._doc_lens.append(len(toks))
        for term in counts.keys():
            self._df[term] += 1

    def score(self, query: str) -> dict[str, float]:
        if not self._doc_lens:
            return {}
        n = len(self._doc_lens)
        avgdl = sum(self._doc_lens) / n
        q_tokens = _tokens(query)
        if not q_tokens:
            return {}
        idf = _inverse_document_frequencies(n, self._df, q_tokens)
        out: dict[str, float] = {}
        for i, doc_id in enumerate(self._doc_ids):
            counts = self._doc_tokens[i]
            dl = self._doc_lens[i]
            score = _score_document(
                counts, dl, q_tokens=q_tokens, avgdl=avgdl, idf=idf,
                k1=self.k1, b=self.b,
            )
            if score > 0:
                out[doc_id] = score
        return out
