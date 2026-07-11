"""Versioned semantic-conversation adaptation for answer generation.

The retrieval layer returns evidence.  This module turns that evidence into a
query-specific, directly readable SEAM conversation view before an answerer
sees it.  It deliberately does not generate an answer, call a model, or alter
stored truth: the output remains a disposable PACK-like projection with the
original evidence text preserved line-for-line.

``conversation/1`` closes the first measured cat1 gap: an answerer must scan
the complete evidence set, resolve aliases/coreferences, validate requested
counts/dimensions, and only then synthesize.  ``inference/high-confidence/1``
separately licenses ordinary world-knowledge inference for questions whose
answer is not stated verbatim, while retaining ambiguity-aware abstention.
Both policies are opt-in and versioned so the improvement loop can measure,
promote, or revert them without changing the locked baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

CONVERSATION_ADAPTER_OFF = "off"
CONVERSATION_ADAPTER_V1 = "conversation/1"
CONVERSATION_ADAPTERS = frozenset({CONVERSATION_ADAPTER_OFF, CONVERSATION_ADAPTER_V1})

INFERENCE_CONTEXT_ONLY = "context-only"
INFERENCE_HIGH_CONFIDENCE_V1 = "inference/high-confidence/1"
INFERENCE_POLICIES = frozenset({INFERENCE_CONTEXT_ONLY, INFERENCE_HIGH_CONFIDENCE_V1})


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


def classify_conversation_intent(question: str) -> ConversationIntent:
    """Classify the answer operation from question text without benchmark labels.

    Set-completion takes precedence because a question may contain inferential
    language while still requiring a complete multi-item answer.  The rules are
    intentionally conservative; direct questions still receive the adapter's
    evidence-wide scan when ``conversation/1`` is enabled.
    """

    text = question.strip()
    if any(pattern.search(text) for pattern in _SET_PATTERNS):
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

        header = (
            f"SEAM-CONV/1|intent={self.intent.value}|"
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

    ``off`` is byte-identical.  ``conversation/1`` preserves every non-empty
    evidence line, removes only exact duplicates, and adds stable ids so an
    answerer can reason over a complete evidence set without confusing the
    projection for durable truth.
    """

    if version not in CONVERSATION_ADAPTERS:
        raise ValueError(f"unknown conversation adapter {version!r}")
    intent = classify_conversation_intent(question)
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
) -> str:
    """Build the bounded reasoning contract placed before the answer context."""

    if conversation_adapter not in CONVERSATION_ADAPTERS:
        raise ValueError(f"unknown conversation adapter {conversation_adapter!r}")
    if inference_policy not in INFERENCE_POLICIES:
        raise ValueError(f"unknown inference policy {inference_policy!r}")

    if conversation_adapter == CONVERSATION_ADAPTER_OFF:
        method = "Use the retrieved context as evidence."
    else:
        method = (
            "Scan every EVIDENCE row before answering. Collect all candidate facts "
            "across turns, resolve aliases and pronouns, preserve temporal scope, "
            "deduplicate equivalent facts, and validate requested counts or dimensions "
            "before synthesizing the answer."
        )

    if intent == ConversationIntent.SET_COMPLETION:
        method += " Return the complete supported set; do not stop after the first match."

    if inference_policy == INFERENCE_HIGH_CONFIDENCE_V1:
        method += (
            " You may combine the evidence with stable, widely known world knowledge only "
            "when it supports one high-confidence interpretation. If multiple plausible "
            "interpretations remain, answer 'unknown' rather than guess."
        )
    else:
        method += " Do not add facts that are not supported by the context."
    return method
