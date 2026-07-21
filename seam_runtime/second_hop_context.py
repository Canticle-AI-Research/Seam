"""Second-hop (entity-bridge) retrieval expansion for the Mem0-harness facade.

Motivation (HISTORY#429 miss autopsy): under the matched gpt-4o contract, the
dominant residual failure on mem0's harness is NOT answer-side — only 8 of 63
misses had the gold text anywhere in the retrieved top-200. ~30 misses are
abstentions/naming failures where the answering turn exists in the store but
the question's wording doesn't resemble it (the #419/#420 "second hop": the
question asks about Tim's favorite composer, the evidence turn says he plays
Star Wars tunes on the piano). One embedding query cannot make that jump.

Mechanism (pseudo-relevance feedback, entity-flavored): take the primary
ranked results, mine their raw texts for BRIDGE TERMS — quoted titles,
mid-sentence capitalized entity spans, frequent content bigrams — that do not
already appear in the query, then run a small number of secondary searches for
those terms and splice their novel results into a reserved TAIL of the result
list. Primary ranking for the head of the list is untouched, so the
displacement risk that killed earlier format changes (#369 lesson) is bounded
to the reserved tail slots.

This module is pure logic (term extraction + splice plan) so it tests
hermetically; the facade owns the actual secondary ``search_ir`` calls.
Enablement is facade-scoped via ``SEAM_SECOND_HOP_POLICY=entity-bridge/1``
(default OFF, off path byte-identical). No RetrievalFlags field yet — core
productization follows a measured win, and retrieval.py has in-flight
concurrent edits.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

POLICY_OFF = "off"
POLICY_V1 = "entity-bridge/1"

# Slots at the tail of the result list that secondary-hop results may occupy.
DEFAULT_RESERVE_SLOTS = 40
# Primary results mined for bridge terms.
DEFAULT_MINE_TOP = 30
# Maximum secondary searches per query.
DEFAULT_MAX_BRIDGE_QUERIES = 3

_SPEAKER_PREFIX = re.compile(r"^\[[^\]]*\]\s*")
_QUOTED = re.compile(r"[\"“‘']([A-Z][^\"”’']{2,60})[\"”’']")
# Capitalized span NOT at sentence start: preceded by a lowercase word.
_MIDSENTENCE_CAPS = re.compile(
    r"(?<=[a-z,;] )((?:[A-Z][\w'&.-]+ ?){1,4})(?![a-z])"
)
_WORD = re.compile(r"[A-Za-z][\w'-]+")

_STOP = frozenset(
    "the a an and or but of in on at to for with from by about as is are was "
    "were be been being have has had do does did will would can could should "
    "may might i you he she it we they my your his her its our their this "
    "that these those what which who when where why how not no yes so very "
    "just also too really said says like".split()
)


@dataclass(frozen=True)
class BridgePlan:
    """Secondary queries to run and how many tail slots they may fill."""

    queries: tuple[str, ...]
    reserve_slots: int


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2]


def extract_bridge_terms(
    query: str,
    primary_texts: list[str],
    *,
    mine_top: int = DEFAULT_MINE_TOP,
    max_terms: int = DEFAULT_MAX_BRIDGE_QUERIES,
) -> list[str]:
    """Salient entity/title terms from the primary results, absent from the query.

    Ranked by frequency across distinct results; quoted titles outrank plain
    capitalized spans at equal frequency (titles are the strongest bridge —
    "Star Wars", "The Alchemist"-class evidence).
    """

    query_words = set(_content_words(query))
    counts: Counter[str] = Counter()
    quoted_bonus: set[str] = set()
    for text in primary_texts[:mine_top]:
        body = _SPEAKER_PREFIX.sub("", text or "")
        seen_here: set[str] = set()
        for match in _QUOTED.finditer(body):
            term = match.group(1).strip()
            key = term.lower()
            if key not in seen_here:
                counts[term] += 1
                quoted_bonus.add(term)
                seen_here.add(key)
        for match in _MIDSENTENCE_CAPS.finditer(body):
            term = match.group(1).strip()
            words = set(_content_words(term))
            if not words or words <= query_words:
                continue
            key = term.lower()
            if key not in seen_here:
                counts[term] += 1
                seen_here.add(key)
    ranked = sorted(
        counts.items(),
        key=lambda kv: (kv[1], kv[0] in quoted_bonus, -len(kv[0])),
        reverse=True,
    )
    out: list[str] = []
    seen: set[str] = set()
    for term, _ in ranked:
        key = term.lower()
        if key in seen or key in query_words:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


def build_bridge_plan(
    query: str,
    primary_texts: list[str],
    *,
    policy: str = POLICY_OFF,
    reserve_slots: int = DEFAULT_RESERVE_SLOTS,
) -> BridgePlan | None:
    """Plan of secondary searches, or None (the byte-identical off path)."""

    if policy != POLICY_V1 or not primary_texts:
        return None
    terms = extract_bridge_terms(query, primary_texts)
    if not terms:
        return None
    return BridgePlan(queries=tuple(terms), reserve_slots=reserve_slots)


def splice_results(
    primary: list[dict],
    secondary: list[dict],
    *,
    limit: int,
    reserve_slots: int,
) -> list[dict]:
    """Merge: primary head untouched; novel secondary results fill a reserved
    tail, scored below the retained primary minimum so any downstream
    score-descending re-sort keeps the primary head intact."""

    if not secondary:
        return primary
    head_len = max(0, min(len(primary), limit) - reserve_slots)
    head = primary[:head_len]
    seen = {str(item.get("id")) for item in primary}
    seen.discard("None")
    floor = min(
        (float(item.get("score", 0.0)) for item in primary[: limit or None]),
        default=0.0,
    )
    novel: list[dict] = []
    for index, item in enumerate(secondary):
        rid = str(item.get("id"))
        if rid in seen:
            continue
        seen.add(rid)
        spliced = dict(item)
        spliced["score"] = floor - 1e-4 * (index + 1)
        novel.append(spliced)
    tail_budget = max(0, limit - head_len)
    tail: list[dict] = novel[:tail_budget]
    # Backfill remaining tail room with the displaced primary results.
    for item in primary[head_len:]:
        if len(head) + len(tail) >= limit:
            break
        tail.append(item)
    merged = head + tail
    merged.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return merged[:limit]
