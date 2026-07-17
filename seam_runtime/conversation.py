"""Versioned semantic-conversation adaptation for answer generation.

The retrieval layer returns evidence.  This module turns that evidence into a
query-specific, directly readable SEAM conversation view before an answerer
sees it.  It deliberately does not generate an answer, call a model, or alter
stored truth: the output remains a disposable PACK-like projection with the
original evidence text preserved line-for-line.

``conversation/1`` closes the first measured cat1 gap: an answerer must scan
the complete evidence set, resolve aliases/coreferences, validate requested
counts/dimensions, and only then synthesize.  ``conversation/2`` keeps the v1
projection byte-identical but detects more enumeration-shaped questions and
issues a stricter exhaustive set-completion contract.  ``conversation/3``
keeps v2's scan and detection but constrains the OUTPUT to the bare answer
(one comma-separated line for sets, no narration); this regressed (the defect
was over-generation, not format).  ``conversation/4`` keeps v2's scan but
replaces its completeness pressure with a cardinality constraint: include every
directly-responsive item, exclude merely-adjacent ones — targeting the measured
over-generation that judge/1 penalizes.
``inference/high-confidence/1`` separately licenses ordinary world-knowledge
inference for questions whose answer is not stated verbatim, while retaining
ambiguity-aware abstention.  ``inference/high-confidence/2`` adds two cheap
measured fixes on top of v1: it forbids abstaining when the context clearly
supports one answer, and requires enumerate-then-count for cardinality
questions.  ``inference/high-confidence/3`` builds on v2 and licenses
open-domain world-knowledge NAMING: when retrieved clues uniquely identify a
well-known real-world entity (person, place, work, product, game), it names the
entity instead of describing it or abstaining, with an ambiguity guard for
clues that fit several entities — targeting the champion's dominant cat3
open-domain miss shape.  ``temporal/1`` separately requires resolving
relative time expressions against per-message timestamps before answering;
``temporal/2`` adds instance disambiguation (enumerate every dated candidate,
then pick by tense and time reference).  ``exact-answer/1`` is an orthogonal
answer-output contract: a single-pass draft-then-verify directive that composes
on top of the collection policies (champion base ``conversation/2``) and, after
the draft, adds dropped set items, prunes anything the question did not ask for
(a post-draft precision pass, unlike ``conversation/4`` which pruned at
collection time and lost recall), and anchors the answer to the specific
person/event/date the question refers to.  All policies are opt-in and versioned
so the improvement loop can measure, promote, or revert them without changing
the locked baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

CONVERSATION_ADAPTER_OFF = "off"
CONVERSATION_ADAPTER_V1 = "conversation/1"
CONVERSATION_ADAPTER_V2 = "conversation/2"
CONVERSATION_ADAPTER_V3 = "conversation/3"
CONVERSATION_ADAPTER_V4 = "conversation/4"
CONVERSATION_ADAPTERS = frozenset(
    {
        CONVERSATION_ADAPTER_OFF,
        CONVERSATION_ADAPTER_V1,
        CONVERSATION_ADAPTER_V2,
        CONVERSATION_ADAPTER_V3,
        CONVERSATION_ADAPTER_V4,
    }
)

# Conversation adapters that use the wider v2 enumeration-shape detection.
_WIDE_SET_DETECTION = frozenset(
    {CONVERSATION_ADAPTER_V2, CONVERSATION_ADAPTER_V3, CONVERSATION_ADAPTER_V4}
)

INFERENCE_CONTEXT_ONLY = "context-only"
INFERENCE_HIGH_CONFIDENCE_V1 = "inference/high-confidence/1"
INFERENCE_HIGH_CONFIDENCE_V2 = "inference/high-confidence/2"
INFERENCE_HIGH_CONFIDENCE_V3 = "inference/high-confidence/3"
INFERENCE_POLICIES = frozenset(
    {
        INFERENCE_CONTEXT_ONLY,
        INFERENCE_HIGH_CONFIDENCE_V1,
        INFERENCE_HIGH_CONFIDENCE_V2,
        INFERENCE_HIGH_CONFIDENCE_V3,
    }
)

TEMPORAL_POLICY_OFF = "off"
TEMPORAL_GROUNDING_V1 = "temporal/1"
TEMPORAL_GROUNDING_V2 = "temporal/2"
TEMPORAL_POLICIES = frozenset(
    {TEMPORAL_POLICY_OFF, TEMPORAL_GROUNDING_V1, TEMPORAL_GROUNDING_V2}
)

ANSWER_CONTRACT_OFF = "off"
EXACT_ANSWER_CONTRACT_V1 = "exact-answer/1"
ANSWER_CONTRACTS = frozenset({ANSWER_CONTRACT_OFF, EXACT_ANSWER_CONTRACT_V1})


class ConversationIntent(str, Enum):
    DIRECT = "direct"
    SET_COMPLETION = "set-completion"
    INFERENCE = "inference"


_SET_PATTERNS = (
    re.compile(r"\b(?:all|both|each|every)\b", re.IGNORECASE),
    re.compile(r"\bhow many\b", re.IGNORECASE),
    re.compile(r"\b(?:list|enumerate|name)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:which|what)\b.{0,48}\b(?:activities|books|emotions|events|"
        r"exercises|facts|games|hobbies|items|names|people|places|reasons|"
        r"sports|things|types|ways)\b",
        re.IGNORECASE,
    ),
)
_INFERENCE_PATTERNS = (
    re.compile(r"\b(?:infer|imply|likely|probably|suggests?)\b", re.IGNORECASE),
    re.compile(r"\bwhat (?:kind|type) of\b", re.IGNORECASE),
    re.compile(r"\bbased on (?:this|that|the conversation|what)\b", re.IGNORECASE),
    re.compile(r"\b(?:might|could) (?:be|have|mean|suggest)\b", re.IGNORECASE),
)
# conversation/2 widens set detection with question SHAPES rather than a longer
# noun list: perfect-tense experience questions ("what has X painted", "which
# countries have they visited") inherently ask for every occurrence, and a
# possessive/of-plural head noun ("names of John's children", "Melanie's pets'
# names") asks for a complete set.  A single-fact question that matches is
# harmless: the complete supported set is one item.
_SET_PATTERNS_V2 = _SET_PATTERNS + (
    re.compile(r"\b(?:what|which|who|where)\b[^?]{0,60}\bha(?:s|ve)\b", re.IGNORECASE),
    re.compile(r"\b(?:names?|kinds?|types?|breeds?) of\b", re.IGNORECASE),
    re.compile(
        r"\b(?:which|what)\b.{0,48}\b(?:areas|artists|bands|children|cities|"
        r"countries|dogs|foods|friends|goals|injuries|jobs|languages|movies|"
        r"paintings|pets|plans|skills|songs|states|titles|trips)\b",
        re.IGNORECASE,
    ),
)


def classify_conversation_intent(
    question: str,
    *,
    adapter_version: str = CONVERSATION_ADAPTER_V1,
) -> ConversationIntent:
    """Classify the answer operation from question text without benchmark labels.

    Set-completion takes precedence because a question may contain inferential
    language while still requiring a complete multi-item answer.  The rules are
    intentionally conservative; direct questions still receive the adapter's
    evidence-wide scan when a conversation adapter is enabled.  ``off`` and
    ``conversation/1`` share the v1 patterns so v1 behavior stays byte-stable;
    ``conversation/2`` adds the wider v2 set patterns.
    """

    if adapter_version not in CONVERSATION_ADAPTERS:
        raise ValueError(f"unknown conversation adapter {adapter_version!r}")
    set_patterns = (
        _SET_PATTERNS_V2 if adapter_version in _WIDE_SET_DETECTION else _SET_PATTERNS
    )
    text = question.strip()
    if any(pattern.search(text) for pattern in set_patterns):
        return ConversationIntent.SET_COMPLETION
    if any(pattern.search(text) for pattern in _INFERENCE_PATTERNS):
        return ConversationIntent.INFERENCE
    return ConversationIntent.DIRECT


def _evidence_lines(context: str) -> list[str]:
    """Return stable, exact-text evidence units with exact duplicates removed."""

    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in context.splitlines():
        if not raw_line.strip() or raw_line in seen:
            continue
        seen.add(raw_line)
        lines.append(raw_line)
    return lines


@dataclass(frozen=True)
class ConversationView:
    version: str
    intent: ConversationIntent
    question: str
    evidence: tuple[str, ...]

    def render(self) -> str:
        """Render a directly readable, provenance-preserving SEAM-CONV view."""

        view_version = self.version.rsplit("/", 1)[-1]
        header = (
            f"SEAM-CONV/{view_version}|intent={self.intent.value}|"
            f"evidence_count={len(self.evidence)}"
        )
        rows = [header, f"QUESTION|{self.question.strip()}"]
        rows.extend(f"EVIDENCE|{index}|{text}" for index, text in enumerate(self.evidence, 1))
        return "\n".join(rows)


def adapt_conversation_context(
    question: str,
    context: str,
    *,
    version: str = CONVERSATION_ADAPTER_OFF,
) -> tuple[str, ConversationIntent]:
    """Return ``(adapted_context, intent)`` for a versioned adapter policy.

    ``off`` is byte-identical.  ``conversation/1`` and ``conversation/2``
    preserve every non-empty evidence line, remove only exact duplicates, and
    add stable ids so an answerer can reason over a complete evidence set
    without confusing the projection for durable truth; v2 differs from v1
    only in intent detection and the strictness of the method directive.
    """

    if version not in CONVERSATION_ADAPTERS:
        raise ValueError(f"unknown conversation adapter {version!r}")
    intent = classify_conversation_intent(
        question,
        adapter_version=version if version != CONVERSATION_ADAPTER_OFF else CONVERSATION_ADAPTER_V1,
    )
    if version == CONVERSATION_ADAPTER_OFF:
        return context, intent
    view = ConversationView(
        version=version,
        intent=intent,
        question=question,
        evidence=tuple(_evidence_lines(context)),
    )
    return view.render(), intent


def answer_method_directive(
    intent: ConversationIntent,
    *,
    conversation_adapter: str = CONVERSATION_ADAPTER_OFF,
    inference_policy: str = INFERENCE_CONTEXT_ONLY,
    temporal_policy: str = TEMPORAL_POLICY_OFF,
    answer_contract: str = ANSWER_CONTRACT_OFF,
) -> str:
    """Build the bounded reasoning contract placed before the answer context."""

    if conversation_adapter not in CONVERSATION_ADAPTERS:
        raise ValueError(f"unknown conversation adapter {conversation_adapter!r}")
    if inference_policy not in INFERENCE_POLICIES:
        raise ValueError(f"unknown inference policy {inference_policy!r}")
    if temporal_policy not in TEMPORAL_POLICIES:
        raise ValueError(f"unknown temporal policy {temporal_policy!r}")
    if answer_contract not in ANSWER_CONTRACTS:
        raise ValueError(f"unknown answer contract {answer_contract!r}")

    if conversation_adapter == CONVERSATION_ADAPTER_OFF:
        method = "Use the retrieved context as evidence."
    else:
        method = (
            "Scan every EVIDENCE row before answering. Collect all candidate facts "
            "across turns, resolve aliases and pronouns, preserve temporal scope, "
            "deduplicate equivalent facts, and validate requested counts or dimensions "
            "before synthesizing the answer."
        )

    if (
        conversation_adapter == CONVERSATION_ADAPTER_V1
        and intent == ConversationIntent.SET_COMPLETION
    ):
        method += " Return the complete supported set; do not stop after the first match."
    elif (
        conversation_adapter in (CONVERSATION_ADAPTER_V2, CONVERSATION_ADAPTER_V3)
        and intent == ConversationIntent.SET_COMPLETION
    ):
        method += (
            " This question asks for a complete set. Sweep every EVIDENCE row and "
            "collect each distinct supported item; related items are often mentioned "
            "in separate turns far apart, so do not stop after the first rows that "
            "mention the topic. Before answering, re-check the evidence for items "
            "your draft answer is missing. An answer that omits a supported item is "
            "incomplete; return the full deduplicated set."
        )
    elif (
        conversation_adapter == CONVERSATION_ADAPTER_V4
        and intent == ConversationIntent.SET_COMPLETION
    ):
        # v4 = cardinality constraint. v2's completeness pressure ("return the
        # full set; an omitted item is incomplete") drove OVER-generation: the
        # answerer padded sets with adjacent/related items and judge/1's extra-
        # detail penalty scored those as partials (2026-07-15 record: over-
        # generation, not format, was the defect; v3's terse fix regressed).
        # v4 keeps the exhaustive scan but balances recall with precision.
        method += (
            " This question asks for a set. Sweep every EVIDENCE row and include "
            "each item that DIRECTLY answers the specific question asked; such items "
            "are often in separate turns far apart, so do not stop after the first "
            "match. But match the question's scope exactly: do NOT add items that are "
            "merely related, adjacent, or mentioned nearby without themselves "
            "answering the question. Answer with precisely the responsive items — "
            "neither omitting a responsive one nor padding the set with extra ones."
        )

    if conversation_adapter == CONVERSATION_ADAPTER_V3:
        # v3's fix for the measured v2 regression mode: the exhaustive SCAN is
        # kept, but the OUTPUT is constrained to the bare answer. List-formatted
        # / narrated answers were judged correct at 14% vs 67% overall on the
        # 2026-07-14 record even when they contained the complete gold.
        method += (
            " Output contract: after reasoning, state only the answer itself. "
            "For a set, give every supported item on one line, separated by "
            "commas, with no numbering, no headers, and no per-item commentary. "
            "Never restate the question, never narrate where evidence came "
            "from, and never append additional context beyond what was asked."
        )

    if temporal_policy in (TEMPORAL_GROUNDING_V1, TEMPORAL_GROUNDING_V2):
        method += (
            " Each context line's bracketed prefix is the timestamp of that message, "
            "and speakers describe events relative to it. Resolve relative time "
            "expressions such as 'yesterday', 'last Friday', 'last week', 'last year', "
            "or 'a few months ago' into the absolute date or period they denote using "
            "that message's timestamp. When asked when something happened, give the "
            "resolved event time, not the time of the message that mentions it; when "
            "asked how long something took or how much time passed, compute the "
            "duration from the resolved event times."
        )
    if temporal_policy == TEMPORAL_GROUNDING_V2:
        # v2 adds instance disambiguation: the dominant surviving temporal
        # failure on the 2026-07-14 record was picking the WRONG dated mention
        # of a similar recurring event, not failing to resolve a date.
        method += (
            " If several dated mentions could match the question, first list each "
            "candidate event with its resolved date, then choose deliberately: for "
            "past-tense questions pick the instance consistent with the question's "
            "time reference; for future or planning questions pick the earliest "
            "planned occurrence. Never default to the first or most prominent "
            "mention."
        )

    if inference_policy in (
        INFERENCE_HIGH_CONFIDENCE_V1,
        INFERENCE_HIGH_CONFIDENCE_V2,
        INFERENCE_HIGH_CONFIDENCE_V3,
    ):
        method += (
            " You may combine the evidence with stable, widely known world knowledge only "
            "when it supports one high-confidence interpretation. If multiple plausible "
            "interpretations remain, answer 'unknown' rather than guess."
        )
    else:
        method += " Do not add facts that are not supported by the context."

    if inference_policy in (INFERENCE_HIGH_CONFIDENCE_V2, INFERENCE_HIGH_CONFIDENCE_V3):
        # v2 attacks the two cheapest measured misses (2026-07-15 scan): 4 cases
        # answered 'unknown' though a single supported answer was present, and 3
        # 'how many' questions that under-counted. 'unknown' stays available for
        # genuinely-absent evidence; this only forbids abstaining when a clear
        # single answer exists, and requires enumerate-then-count for cardinality.
        method += (
            " Do not answer 'unknown' when the context clearly supports one specific "
            "answer; reserve 'unknown' for questions the evidence genuinely does not "
            "address. For a 'how many' or 'how much' question, first list every "
            "distinct qualifying item or occurrence found in the evidence, then report "
            "the count of that list rather than estimating."
        )

    if inference_policy == INFERENCE_HIGH_CONFIDENCE_V3:
        # v3 = open-domain world-knowledge NAMING, built on v2. Targets the
        # champion's dominant cat3 miss shape (2026-07-17 scan of the #390 record,
        # HISTORY#412 follow-up): the answerer DESCRIBES or abstains ('Unknown')
        # when the retrieved clues uniquely identify a well-known real-world named
        # entity. Measured examples it should convert: context says Tim plays Star
        # Wars piano tunes -> name the composer 'John Williams'; a national park
        # described by its features -> name it; a card game described by its rules
        # -> name it. v2's high-confidence + no-abstention rules still apply; this
        # extends them to NAMING the specific entity, with an explicit ambiguity
        # guard so it does not confidently guess when clues fit several entities.
        method += (
            " When the retrieved context describes a specific real-world named entity "
            "— a person, place, creative work, product, team, or game — through "
            "distinctive attributes or clues, and stable widely-known world knowledge "
            "identifies exactly one well-known entity matching those clues, NAME that "
            "entity rather than only describing it or answering 'unknown'. If the clues "
            "could plausibly fit more than one well-known entity, do not guess — name "
            "none and answer with what the context supports."
        )

    if answer_contract == EXACT_ANSWER_CONTRACT_V1:
        # exact-answer/1 = a structural draft-then-verify pass that composes on
        # TOP of the collection policies above. It attacks three miss buckets the
        # 2026-07-16 record mining isolated: (a) supported set items dropped from
        # the draft (recall), (b) judge-docked partials that carried the full gold
        # but padded extras (precision — a POST-draft prune), and (c) cases
        # answered from a similar-but-wrong instance (episode anchoring).
        #
        # MEASURED LOSER — TESTED AND PARKED (HISTORY#412, record
        # 20260717-132158). On the 344 holdout with conversation/2 + hc/2 +
        # temporal/1 + broad it scored 0.7471, BELOW both champions (#390 0.7689,
        # #405 0.7762); every category regressed vs #390, including cat3
        # -0.048. Root cause overturns the design premise: the PRECISION prune is
        # backwards for judge/1 — the judge REWARDS the fuller answer because it
        # is likelier to contain the gold, so pruning "extras" deletes gold (e.g.
        # gold "filmmaker" pruned from "screenwriter and filmmaker"), the same
        # over-terse failure mode that sank conversation/3. Kept default-off for
        # provenance; do NOT enable. The cat3 lesson is the opposite lever:
        # completeness + open-domain world-knowledge licensing, not pruning.
        set_clause = ""
        if intent == ConversationIntent.SET_COMPLETION:
            set_clause = (
                " Coverage: this question asks for a set, so re-scan every part of the "
                "retrieved context and ADD any qualifying item your draft left out — "
                "supported items are frequently stated in separate turns far apart."
            )
        method += (
            " Before giving your final answer, verify your draft against the retrieved "
            "context in one pass." + set_clause + " Precision: REMOVE anything in your "
            "draft that the question did not ask for — extra facts, adjacent details, "
            "restated question text, or explanation — and keep only the exact "
            "information requested. Anchoring: confirm every part of the answer comes "
            "from the specific person, event, and time the question refers to, not a "
            "similar-looking but different one elsewhere in the context; when the "
            "question fixes a date or occasion, use only evidence matching it. Then "
            "output only the corrected answer."
        )
    return method
