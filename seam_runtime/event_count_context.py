"""Query-time context projection for distinct-event and distinct-item counts.

The retrieval layer often finds every required turn for a count question while
the downstream answerer still counts repeated mentions, future plans, or nearby
events.  This module provides a deterministic, provenance-preserving projection
over retrieved RAW memories.  It does not generate an answer or mutate durable
truth: it reorders evidence for the disposable answer context and renders an
explicit machine-readable counting contract.

The policy is versioned and default-off.  ``off`` returns no projection, so
callers preserve their byte-for-byte baseline behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Sequence

EVENT_COUNT_POLICY_OFF = "off"
EVENT_COUNT_DISTINCT_V1 = "event-count/distinct/1"
EVENT_COUNT_POLICIES = frozenset(
    {EVENT_COUNT_POLICY_OFF, EVENT_COUNT_DISTINCT_V1}
)

_COUNT_QUESTION_RE = re.compile(
    r"\b(?:how many(?:\s+times)?|number of)\b",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(
    r"^\[(?P<speaker>[^\]\d]+?)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2}|[^\]]+)\]\s*(?P<body>.*)$",
    re.DOTALL,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_NEGATED_RE = re.compile(
    r"\b(?:did not|didn't|does not|doesn't|has not|hasn't|have not|haven't|"
    r"never|no longer|not yet|without)\b",
    re.IGNORECASE,
)
_PLANNED_RE = re.compile(
    r"\b(?:plan(?:s|ned|ning)?|hope(?:s|d)? to|want(?:s|ed)? to|"
    r"going to|will|would like to|next (?:week|month|year|time|weekend)|"
    r"upcoming|looking forward to|intend(?:s|ed)? to|might|could)\b",
    re.IGNORECASE,
)
_OBSERVED_RE = re.compile(
    r"\b(?:attended|bought|completed|did|finished|found|got|had|has|have|"
    r"injured|joined|made|met|moved|owned|owns|participated|received|"
    r"resumed|saw|took|visited|went|won|wrote)\b",
    re.IGNORECASE,
)
_REFERENCE_LEAD_RE = re.compile(
    r"^(?:that|this|those|these|it|they|the same|the event|the trip|"
    r"the tournament|the show|the game)\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[.!?;])\s+|\s+(?:although|but|however|while)\s+",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "did",
        "do",
        "does",
        "for",
        "had",
        "has",
        "have",
        "her",
        "his",
        "how",
        "in",
        "is",
        "it",
        "many",
        "of",
        "on",
        "or",
        "the",
        "their",
        "them",
        "they",
        "times",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "with",
    }
)
_IRREGULAR_STEMS = {
    "bought": "buy",
    "did": "do",
    "found": "find",
    "got": "get",
    "had": "have",
    "made": "make",
    "met": "meet",
    "owned": "own",
    "saw": "see",
    "taken": "take",
    "took": "take",
    "went": "go",
    "won": "win",
    "wrote": "write",
    "written": "write",
}
_STATE_PRIORITY = {
    "observed": 4,
    "mixed": 3,
    "mentioned": 3,
    "reference-only": 2,
    "planned": 1,
    "negated": 0,
}


@dataclass(frozen=True)
class CountEvidence:
    """One retrieved memory with stable provenance and original rank."""

    record_id: str
    text: str
    score: float = 0.0
    created_at: str = ""
    original_rank: int = 0


@dataclass(frozen=True)
class RankedCountEvidence:
    """Evidence annotated for the disposable count context."""

    evidence: CountEvidence
    state: str
    speaker: str
    timestamp: str
    overlap: int
    group_id: str
    rank_score: float


@dataclass(frozen=True)
class CountContextProjection:
    """A deterministic SEAM-COUNT/1 view over retrieved memories."""

    policy: str
    question: str
    ranked: tuple[RankedCountEvidence, ...]

    @property
    def projection_id(self) -> str:
        material = "\x1f".join(
            (self.policy, self.question, *(row.evidence.record_id for row in self.ranked))
        )
        return f"seam-count:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"

    def render(self, *, max_rows: int = 48, max_text_chars: int = 500) -> str:
        """Render an injection-resistant, line-oriented machine context.

        Candidate text is JSON encoded on each line, so newlines and strings
        resembling SEAM control records remain data rather than new directives.
        """

        rendered = self.ranked[: max(0, max_rows)]
        text_limit = max(0, max_text_chars)
        rows = [
            (
                "SEAM-COUNT/1|operation=distinct-occurrence-or-item-count|"
                f"candidate_count={len(self.ranked)}|"
                f"rendered_candidate_count={len(rendered)}|"
                f"truncated={str(len(rendered) < len(self.ranked)).lower()}"
            ),
            (
                "METHOD|Count distinct qualifying occurrences or items, not message "
                "mentions. Merge rows that describe the same occurrence or item. "
                "Do not count planned, hypothetical, negated, or reference-only rows "
                "unless another observed row establishes the occurrence or item. "
                "A mixed row contains multiple relevant clauses and requires "
                "clause-level inspection. "
                "Preserve separate rows only when the evidence supports separate "
                "occurrences or items."
            ),
        ]
        for index, row in enumerate(rendered, 1):
            payload = {
                "group": row.group_id,
                "overlap": row.overlap,
                "raw_id": row.evidence.record_id,
                "speaker": row.speaker,
                "state": row.state,
                "text": _one_line(row.evidence.text)[:text_limit],
                "timestamp": row.timestamp or row.evidence.created_at,
            }
            rows.append(
                f"CANDIDATE|{index}|"
                + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
        return "\n".join(rows)


def is_count_question(question: str) -> bool:
    """Return whether ``question`` requests a distinct count."""

    return bool(_COUNT_QUESTION_RE.search(question or ""))


def build_count_context_projection(
    question: str,
    evidence: Sequence[CountEvidence],
    *,
    policy: str = EVENT_COUNT_POLICY_OFF,
) -> CountContextProjection | None:
    """Build a ranked count projection, or ``None`` when policy does not apply."""

    if policy not in EVENT_COUNT_POLICIES:
        raise ValueError(f"unknown event count policy {policy!r}")
    if policy == EVENT_COUNT_POLICY_OFF or not is_count_question(question) or not evidence:
        return None

    question_terms = _content_terms(question)
    question_action_terms = question_terms & set(_IRREGULAR_STEMS.values()) | (
        question_terms
        & {
            "attend",
            "buy",
            "complete",
            "do",
            "enter",
            "finish",
            "find",
            "get",
            "go",
            "have",
            "injure",
            "join",
            "make",
            "meet",
            "move",
            "own",
            "participate",
            "receive",
            "resume",
            "see",
            "take",
            "visit",
            "win",
            "write",
        }
    )
    ranked: list[RankedCountEvidence] = []
    for fallback_rank, item in enumerate(evidence, 1):
        speaker, timestamp, body = _split_memory(item.text)
        state = _evidence_state(
            body,
            question_terms=question_terms,
            question_action_terms=question_action_terms,
        )
        memory_terms = _content_terms(f"{speaker} {body}")
        overlap = len(question_terms & memory_terms)
        speaker_match = len(question_terms & _content_terms(speaker))
        original_rank = item.original_rank or fallback_rank
        rank_score = (
            overlap * 10.0
            + speaker_match * 8.0
            + _STATE_PRIORITY[state] * 2.0
            + float(item.score)
            - original_rank * 0.0001
        )
        group_material = "\x1f".join(
            (speaker.lower(), timestamp, " ".join(sorted(memory_terms)))
        )
        group_id = hashlib.sha256(group_material.encode("utf-8")).hexdigest()[:12]
        ranked.append(
            RankedCountEvidence(
                evidence=item,
                state=state,
                speaker=speaker,
                timestamp=timestamp,
                overlap=overlap,
                group_id=group_id,
                rank_score=rank_score,
            )
        )

    ranked.sort(
        key=lambda row: (
            -row.rank_score,
            row.evidence.original_rank or 10**9,
            row.evidence.record_id,
        )
    )
    return CountContextProjection(
        policy=policy,
        question=question,
        ranked=tuple(ranked),
    )


def _split_memory(text: str) -> tuple[str, str, str]:
    match = _HEADER_RE.match(_one_line(text))
    if not match:
        return "", "", _one_line(text)
    return (
        match.group("speaker").strip(),
        match.group("date").strip(),
        match.group("body").strip(),
    )


def _evidence_state(
    body: str,
    *,
    question_terms: set[str] | None = None,
    question_action_terms: set[str] | None = None,
) -> str:
    relevant = _relevant_clauses(
        body,
        question_terms=question_terms or set(),
        question_action_terms=question_action_terms or set(),
    )
    if not relevant:
        return "mentioned"
    states = {_clause_state(clause) for clause in relevant}
    if len(states) > 1:
        return "mixed"
    return next(iter(states), "mentioned")


def _clause_state(body: str) -> str:
    if _NEGATED_RE.search(body):
        return "negated"
    if _PLANNED_RE.search(body):
        return "planned"
    if _REFERENCE_LEAD_RE.search(body) and not _OBSERVED_RE.search(body):
        return "reference-only"
    if _OBSERVED_RE.search(body):
        return "observed"
    return "mentioned"


def _relevant_clauses(
    body: str,
    *,
    question_terms: set[str],
    question_action_terms: set[str],
) -> list[str]:
    clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(body) if part.strip()]
    if len(clauses) <= 1 or not question_terms:
        return clauses or [body]

    scored: list[tuple[int, str]] = []
    for clause in clauses:
        terms = _content_terms(clause)
        action_overlap = len(terms & question_action_terms)
        overlap = len(terms & question_terms)
        scored.append((action_overlap * 100 + overlap, clause))
    best = max(score for score, _ in scored)
    return [clause for score, clause in scored if score == best] if best > 0 else []


def _content_terms(text: str) -> set[str]:
    return {
        stem
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and (stem := _stem(token)) not in _STOPWORDS
    }


def _stem(token: str) -> str:
    if token in _IRREGULAR_STEMS:
        return _IRREGULAR_STEMS[token]
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _one_line(text: str) -> str:
    return " ".join((text or "").split())
