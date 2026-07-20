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
from dataclasses import dataclass, replace
from typing import Sequence

EVENT_COUNT_POLICY_OFF = "off"
EVENT_COUNT_DISTINCT_V1 = "event-count/distinct/1"
EVENT_COUNT_DISTINCT_V2 = "event-count/distinct/2"
EVENT_COUNT_POLICIES = frozenset(
    {EVENT_COUNT_POLICY_OFF, EVENT_COUNT_DISTINCT_V1, EVENT_COUNT_DISTINCT_V2}
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
_ITEM_OBJECT_RE = re.compile(
    r"\bhow many\s+(?!times\b)(?P<object>.+?)\s+"
    r"(?:has|have|had|did|does|do|was|were|is|are)\b",
    re.IGNORECASE,
)
_PLAN_INTENT_RE = re.compile(
    r"\b(?:plan(?:s|ned|ning)?|intend(?:s|ed)?|schedule(?:d)?|"
    r"down for|can't wait|cannot wait|let's|should join|pick a date|"
    r"does \w+day sound good|gonna|going to|next (?:week|month|year))\b",
    re.IGNORECASE,
)
_MENTION_INTENT_RE = re.compile(r"\bmention(?:s|ed|ing)?\b", re.IGNORECASE)
_JOINT_PLAN_RE = re.compile(
    r"\b(?:with you|our|we|together|join you|does \w+day sound good)\b",
    re.IGNORECASE,
)
_ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
_ACTION_ALIASES = {
    "attend": {"attend", "go"},
    "buy": {"buy", "get", "purchase"},
    "find": {"discover", "find"},
    "injure": {"hurt", "injure", "sprain"},
    "make": {"make", "reach"},
    "mention": {"mention", "say", "tell"},
    "own": {"have", "own"},
    "participate": {"compete", "enter", "final", "join", "participate", "try", "win"},
    "plan": {"arrange", "plan", "schedule"},
    "reject": {"decline", "reject", "turn"},
    "receive": {"get", "receive", "send", "write"},
    "take": {"bring", "take", "walk"},
    "walk": {"bring", "take", "walk"},
    "win": {"get", "win"},
    "write": {"complete", "finish", "start", "wrap", "write"},
}
_V2_GENERIC_TERMS = frozenset(
    {
        "again",
        "another",
        "ever",
        "many",
        "more",
        "new",
        "number",
        "some",
        "time",
        "together",
    }
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
    eligible: bool = False
    eligibility_reason: str = "unclassified"
    ordinal: int = 0


@dataclass(frozen=True)
class CountContextProjection:
    """A deterministic, versioned SEAM-COUNT view over retrieved memories."""

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

        if self.policy == EVENT_COUNT_DISTINCT_V2:
            return self._render_v2(max_rows=max_rows, max_text_chars=max_text_chars)

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

    def _render_v2(self, *, max_rows: int, max_text_chars: int) -> str:
        """Render bounded same-event groups with explicit RAW-id provenance."""

        groups = _ordered_groups(self.ranked)
        row_limit = max(0, max_rows)
        rendered: list[tuple[str, list[RankedCountEvidence], int]] = []
        remaining = row_limit
        for group_id, members in groups:
            if remaining <= 0:
                break
            visible = members[:remaining]
            rendered.append((group_id, visible, len(members)))
            remaining -= len(visible)
        text_limit = max(0, max_text_chars)
        direct_match_groups = sum(
            any(row.eligible for row in rows) for _, rows in groups
        )
        ordinal_hint = max((row.ordinal for row in self.ranked), default=0)
        count_unit = (
            "occurrence"
            if re.search(r"\bhow many\s+times\b", self.question, re.IGNORECASE)
            else "item-or-event"
        )
        rendered_member_count = sum(len(members) for _, members, _ in rendered)
        truncated = (
            rendered_member_count < len(self.ranked)
            or len(rendered) < len(groups)
        )
        rows = [
            (
                "SEAM-COUNT/2|operation=explicit-same-event-grouping|"
                f"count_unit={count_unit}|candidate_count={len(self.ranked)}|"
                f"event_group_count={len(groups)}|"
                f"direct_match_group_count={direct_match_groups}|"
                f"ordinal_hint_max={ordinal_hint}|rendered_group_count={len(rendered)}|"
                f"rendered_member_count={rendered_member_count}|"
                f"truncated={str(truncated).lower()}"
            ),
            (
                "METHOD|Determine which GROUP records qualify from the question "
                "and MEMBER evidence, then count qualifying GROUP records, not "
                "MEMBER records. "
                "All members of one group describe the same occurrence or item. "
                "direct_match and ordinal_hint_max are prioritization hints, not "
                "an answer or durable truth. Inspect MEMBER text when a group is "
                "mixed or supporting dialogue establishes identity. "
                "Plans count only when the question asks about plans; mentions count "
                "only when the question asks about mentions."
            ),
        ]
        for group_index, (group_id, members, total_member_count) in enumerate(
            rendered, 1
        ):
            eligible_members = [row for row in members if row.eligible]
            representative = max(
                eligible_members or members,
                key=lambda row: (
                    row.overlap,
                    row.rank_score,
                    -row.evidence.original_rank,
                ),
            )
            payload = {
                "direct_match": bool(eligible_members),
                "group": group_id,
                "member_count": total_member_count,
                "members_truncated": len(members) < total_member_count,
                "ordinal": max((row.ordinal for row in members), default=0),
                "raw_ids": [row.evidence.record_id for row in members],
                "reason": (
                    representative.eligibility_reason
                    if eligible_members
                    else "support-or-distractor"
                ),
                "representative": _one_line(representative.evidence.text)[:text_limit],
                "speakers": sorted({row.speaker for row in members if row.speaker}),
                "states": sorted({row.state for row in members}),
                "timestamps": sorted(
                    {
                        row.timestamp or row.evidence.created_at
                        for row in members
                        if row.timestamp or row.evidence.created_at
                    }
                ),
            }
            rows.append(
                f"GROUP|{group_index}|"
                + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            for member_index, member in enumerate(members, 1):
                member_payload = {
                    "direct_match": member.eligible,
                    "raw_id": member.evidence.record_id,
                    "speaker": member.speaker,
                    "state": member.state,
                    "text": _one_line(member.evidence.text)[:text_limit],
                    "timestamp": member.timestamp or member.evidence.created_at,
                }
                rows.append(
                    f"MEMBER|{group_index}.{member_index}|"
                    + json.dumps(
                        member_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
        return "\n".join(rows)


@dataclass(frozen=True)
class _CountIntent:
    mode: str
    count_unit: str
    subject_speakers: frozenset[str]
    action_terms: frozenset[str]
    action_aliases: frozenset[str]
    object_terms: frozenset[str]
    object_phrase: tuple[str, ...]


@dataclass(frozen=True)
class _RowFeatures:
    eligible: bool
    reason: str
    ordinal: int
    support: bool
    anchor_terms: frozenset[str]


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
    if policy == EVENT_COUNT_DISTINCT_V2:
        ranked = _group_v2_rows(question, ranked)
    return CountContextProjection(
        policy=policy,
        question=question,
        ranked=tuple(ranked),
    )


def _group_v2_rows(
    question: str,
    ranked: list[RankedCountEvidence],
) -> list[RankedCountEvidence]:
    intent = _count_intent(question, ranked)
    features = {
        row.evidence.record_id: _v2_row_features(row, intent)
        for row in ranked
    }
    chronology = sorted(
        ranked,
        key=lambda row: (
            row.timestamp or row.evidence.created_at or "9999",
            row.evidence.original_rank or 10**9,
            row.evidence.record_id,
        ),
    )
    groups: list[list[RankedCountEvidence]] = []
    group_features: list[list[_RowFeatures]] = []
    assignments: dict[str, str] = {}

    for row in chronology:
        feature = features[row.evidence.record_id]
        match_index: int | None = None
        for index, members in enumerate(groups):
            if _same_v2_event(
                row,
                feature,
                members,
                group_features[index],
                intent,
            ):
                match_index = index
                break
        if match_index is None:
            match_index = len(groups)
            groups.append([])
            group_features.append([])
        groups[match_index].append(row)
        group_features[match_index].append(feature)

    for members, member_features in zip(groups, group_features, strict=True):
        material = "\x1f".join(
            [
                intent.count_unit,
                *(sorted(row.evidence.record_id for row in members)),
            ]
        )
        group_id = f"event:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12]}"
        for row, feature in zip(members, member_features, strict=True):
            assignments[row.evidence.record_id] = group_id

    return [
        replace(
            row,
            group_id=assignments[row.evidence.record_id],
            eligible=features[row.evidence.record_id].eligible,
            eligibility_reason=features[row.evidence.record_id].reason,
            ordinal=features[row.evidence.record_id].ordinal,
        )
        for row in ranked
    ]


def _same_v2_event(
    row: RankedCountEvidence,
    feature: _RowFeatures,
    members: list[RankedCountEvidence],
    member_features: list[_RowFeatures],
    intent: _CountIntent,
) -> bool:
    """Return only high-confidence deterministic same-event matches."""

    timestamp = row.timestamp or row.evidence.created_at
    ordinal = feature.ordinal
    for member, other in zip(members, member_features, strict=True):
        other_timestamp = member.timestamp or member.evidence.created_at
        same_timestamp = bool(timestamp and timestamp == other_timestamp)
        same_speaker = _normalize_name(row.speaker) == _normalize_name(member.speaker)
        both_relevant = feature.support and other.support

        # Same-session dialogue and repeated descriptions are the dominant v1
        # overcount. For an occurrence-count question, keep different speakers'
        # separate planning/mention acts distinct; for item/event counts, merge
        # supporting dialogue that names the same object on the same date.
        if same_timestamp and both_relevant:
            if intent.count_unit == "item-or-event" or same_speaker:
                return True

        # An explicit ordinal is a stable item identity across follow-up turns.
        if (
            intent.count_unit == "item-or-event"
            and ordinal
            and ordinal == other.ordinal
            and both_relevant
        ):
            return True

        # Near-identical distinctive anchors are safe across timestamps. Require
        # at least two non-query terms so generic "the tournament" references do
        # not collapse genuinely separate events.
        shared = feature.anchor_terms & other.anchor_terms
        union = feature.anchor_terms | other.anchor_terms
        if (
            same_speaker
            and len(shared) >= 2
            and union
            and len(shared) / len(union) >= 0.72
        ):
            return True
    return False


def _ordered_groups(
    ranked: Sequence[RankedCountEvidence],
) -> list[tuple[str, list[RankedCountEvidence]]]:
    groups: dict[str, list[RankedCountEvidence]] = {}
    order: list[str] = []
    for row in ranked:
        if row.group_id not in groups:
            groups[row.group_id] = []
            order.append(row.group_id)
        groups[row.group_id].append(row)
    order_index = {group_id: index for index, group_id in enumerate(order)}
    order.sort(
        key=lambda group_id: (
            -int(any(row.eligible for row in groups[group_id])),
            -max(row.rank_score for row in groups[group_id]),
            order_index[group_id],
        )
    )
    return [(group_id, groups[group_id]) for group_id in order]


def _count_intent(
    question: str,
    ranked: Sequence[RankedCountEvidence],
) -> _CountIntent:
    question_terms = _content_terms_v2(question)
    question_tokens = tuple(
        _normalize_name(_stem_v2(token))
        for token in _TOKEN_RE.findall(question.lower())
    )
    speakers = {
        speaker
        for row in ranked
        if (speaker := _normalize_name(row.speaker))
        and any(_names_match(speaker, token) for token in question_tokens)
    }
    mode = (
        "planned"
        if _PLAN_INTENT_RE.search(question)
        else "mentioned"
        if _MENTION_INTENT_RE.search(question)
        else "observed"
    )
    count_unit = (
        "occurrence"
        if re.search(r"\bhow many\s+times\b", question, re.IGNORECASE)
        else "item-or-event"
    )

    action_terms = {
        canonical
        for canonical, aliases in _ACTION_ALIASES.items()
        if canonical in question_terms or aliases & question_terms
    }
    if mode == "planned":
        action_terms.add("plan")
    if mode == "mentioned":
        action_terms.add("mention")
    aliases = {
        alias
        for action in action_terms
        for alias in _ACTION_ALIASES.get(action, {action})
    } | action_terms

    phrase_match = _ITEM_OBJECT_RE.search(question)
    object_phrase = (
        tuple(
            stem
            for token in _TOKEN_RE.findall(phrase_match.group("object").lower())
            if (stem := _stem_v2(token)) not in _STOPWORDS
        )
        if phrase_match
        else ()
    )
    subject_terms = {
        token
        for speaker in speakers
        for token in _TOKEN_RE.findall(speaker)
    }
    object_terms = set(object_phrase) or (
        question_terms
        - subject_terms
        - aliases
        - _V2_GENERIC_TERMS
        - {"plan", "mention"}
    )
    return _CountIntent(
        mode=mode,
        count_unit=count_unit,
        subject_speakers=frozenset(speakers),
        action_terms=frozenset(action_terms),
        action_aliases=frozenset(aliases),
        object_terms=frozenset(object_terms),
        object_phrase=object_phrase,
    )


def _v2_row_features(
    row: RankedCountEvidence,
    intent: _CountIntent,
) -> _RowFeatures:
    _, _, body = _split_memory(row.evidence.text)
    clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(body) if part.strip()]
    clauses = clauses or [body]
    scored: list[tuple[int, str, set[str]]] = []
    for clause in clauses:
        terms = _content_terms_v2(clause)
        object_overlap = len(terms & intent.object_terms)
        action_overlap = len(terms & intent.action_aliases)
        scored.append((object_overlap * 100 + action_overlap * 10, clause, terms))
    _, selected, selected_terms = max(scored, key=lambda item: item[0])

    speaker = _normalize_name(row.speaker)
    subject_match = (
        not intent.subject_speakers
        or speaker in intent.subject_speakers
        or bool(_content_terms_v2(selected) & set(intent.subject_speakers))
    )
    object_overlap = selected_terms & intent.object_terms
    required_object_overlap = 1 if len(intent.object_terms) < 3 else 2
    object_match = bool(object_overlap) and len(object_overlap) >= required_object_overlap
    if intent.object_phrase and len(intent.object_phrase) > 1:
        clause_tokens = tuple(
            _stem_v2(token) for token in _TOKEN_RE.findall(selected.lower())
        )
        phrase_match = _contains_subsequence(clause_tokens, intent.object_phrase)
        # Strong action/object evidence may use a pronoun or synonym in place of
        # one phrase token, so the exact phrase is a preference rather than the
        # only admissible path.
        object_match = phrase_match or (
            object_match and bool(selected_terms & intent.action_aliases)
        )

    if intent.mode == "planned":
        action_match = bool(_PLAN_INTENT_RE.search(selected))
    elif intent.mode == "mentioned":
        action_match = bool(selected_terms & (intent.action_aliases | {"win"}))
    else:
        action_match = bool(selected_terms & intent.action_aliases)

    # Negation excludes only the selected target-bearing clause. This avoids
    # treating an actually received rejection letter as nonexistent merely
    # because a later sentence says the submission "didn't work out."
    if intent.mode == "planned" and len(intent.subject_speakers) > 1:
        named_subjects = {
            subject
            for subject in intent.subject_speakers
            if subject in _normalize_name(selected)
        }
        joint_match = len(named_subjects) > 1 or bool(_JOINT_PLAN_RE.search(selected))
        action_match = action_match and joint_match

    target_negated = _target_is_negated(selected, intent.action_aliases)
    eligible = (
        subject_match
        and object_match
        and action_match
        and not target_negated
    )
    support = subject_match and object_match
    ordinal = (
        max(
            (
                _ORDINAL_WORDS.get(token, 0)
                for token in _TOKEN_RE.findall(selected.lower())
            ),
            default=0,
        )
        if support
        else 0
    )
    reason = (
        f"{intent.mode}-target-match"
        if eligible
        else "target-negated"
        if target_negated and support
        else "support-only"
        if support
        else "distractor"
    )
    anchors = (
        selected_terms
        - set(intent.object_terms)
        - set(intent.action_aliases)
        - _V2_GENERIC_TERMS
        - _STOPWORDS
    )
    return _RowFeatures(
        eligible=eligible,
        reason=reason,
        ordinal=ordinal,
        support=support,
        anchor_terms=frozenset(anchors),
    )


def _target_is_negated(clause: str, action_aliases: frozenset[str]) -> bool:
    if not _NEGATED_RE.search(clause):
        return False
    tokens = [_stem_v2(token) for token in _TOKEN_RE.findall(clause.lower())]
    negation_indexes = {
        index
        for index, token in enumerate(tokens)
        if token in {"didn't", "doesn't", "hasn't", "haven't", "never", "not", "without"}
    }
    return any(
        action_index > negation_index
        and action_index - negation_index <= 3
        and token in action_aliases
        for negation_index in negation_indexes
        for action_index, token in enumerate(tokens)
    )


def _contains_subsequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[index : index + width] == needle for index in range(len(haystack) - width + 1))


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _names_match(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    for index in range(len(longer)):
        if longer[:index] + longer[index + 1 :] == shorter:
            return True
    return False


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


def _content_terms_v2(text: str) -> set[str]:
    return {
        stem
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and (stem := _stem_v2(token)) not in _STOPWORDS
    }


def _stem_v2(token: str) -> str:
    corrected = {
        "attended": "attend",
        "attending": "attend",
        "games": "game",
        "hiking": "hike",
        "injured": "injure",
        "injuring": "injure",
        "letters": "letter",
        "mentioned": "mention",
        "mentioning": "mention",
        "participated": "participate",
        "participating": "participate",
        "planned": "plan",
        "planning": "plan",
        "recieved": "receive",
        "received": "receive",
        "screenplays": "screenplay",
        "shows": "show",
        "tournaments": "tournament",
        "trails": "trail",
        "turtles": "turtle",
        "winning": "win",
        "wins": "win",
        "written": "write",
        **_IRREGULAR_STEMS,
    }.get(token)
    if corrected:
        return corrected
    if len(token) > 5 and token.endswith("ing"):
        stem = token[:-3]
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


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
