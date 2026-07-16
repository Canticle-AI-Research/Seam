from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9_:-]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


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
        idf = {
            term: math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
            for term in set(q_tokens)
        }
        out: dict[str, float] = {}
        for i, doc_id in enumerate(self._doc_ids):
            counts = self._doc_tokens[i]
            dl = self._doc_lens[i]
            score = 0.0
            for term in q_tokens:
                if term not in counts:
                    continue
                f = counts[term]
                num = f * (self.k1 + 1)
                den = f + self.k1 * (1 - self.b + self.b * dl / avgdl)
                score += idf.get(term, 0.0) * (num / den)
            if score > 0:
                out[doc_id] = score
        return out
