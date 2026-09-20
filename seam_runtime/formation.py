"""Pure opt-in formation segmentation with exact source anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass

BASELINE_FORMATION = "baseline"
CONTEXT_SEGMENTS_V1 = "context-segments/1"
FORMATION_POLICIES = {BASELINE_FORMATION, CONTEXT_SEGMENTS_V1}
_ABBREVIATIONS = ("dr.", "mr.", "mrs.", "ms.", "prof.", "e.g.", "i.e.")
_COLON_SPEAKER = re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:")


@dataclass(frozen=True)
class FormationSegment:
    """One verbatim proposition and its half-open source interval."""

    text: str
    start: int
    end: int
    boundary: str
    speaker: str | None
    body_start: int
    quoted: bool
    parent_start: int
    parent_end: int
    parent_body_start: int
    parent_quoted: bool
    context_start: int
    context_end: int
    continuation: bool


def segment_context(
    raw_text: str,
    *,
    max_segment_chars: int,
    content_start: int = 0,
) -> list[FormationSegment]:
    """Split source text at sentence punctuation without changing its text."""

    if (
        isinstance(max_segment_chars, bool)
        or not isinstance(max_segment_chars, int)
        or max_segment_chars <= 0
    ):
        raise ValueError("max_segment_chars must be a positive integer")
    if (
        isinstance(content_start, bool)
        or not isinstance(content_start, int)
        or not 0 <= content_start <= len(raw_text)
    ):
        raise ValueError("content_start must be a valid source offset")
    segments: list[FormationSegment] = []
    quote_states = _quote_states(raw_text)
    line_starts = _line_starts(raw_text)
    start = content_start
    index = content_start
    while index < len(raw_text):
        char = raw_text[index]
        if char == "\n":
            _append_bounded(
                segments,
                raw_text,
                start,
                index,
                boundary="newline",
                max_segment_chars=max_segment_chars,
                quote_states=quote_states,
                line_starts=line_starts,
            )
            start = index + 1
            index += 1
            continue
        if not _is_sentence_boundary(raw_text, index):
            index += 1
            continue
        end = index + 1
        while end < len(raw_text) and raw_text[end] in "!?。！？":
            end += 1
        while end < len(raw_text) and raw_text[end] in ('"', "'", "”", "’"):
            end += 1
        _append_bounded(
            segments,
            raw_text,
            start,
            end,
            boundary="sentence",
            max_segment_chars=max_segment_chars,
            quote_states=quote_states,
            line_starts=line_starts,
        )
        start = end
        index = end
    _append_bounded(
        segments,
        raw_text,
        start,
        len(raw_text),
        boundary="end",
        max_segment_chars=max_segment_chars,
        quote_states=quote_states,
        line_starts=line_starts,
    )
    return segments


def _is_sentence_boundary(raw_text: str, index: int) -> bool:
    char = raw_text[index]
    if char in "。！？":
        return True
    if char not in ".!?":
        return False
    if char == ".":
        if (
            index > 0
            and index + 1 < len(raw_text)
            and raw_text[index - 1].isdigit()
            and raw_text[index + 1].isdigit()
        ):
            return False
        suffix = raw_text[
            max(0, index + 1 - max(map(len, _ABBREVIATIONS))) : index + 1
        ].casefold()
        if any(suffix.endswith(abbreviation) for abbreviation in _ABBREVIATIONS):
            return False
    following = index + 1
    while following < len(raw_text) and raw_text[following] in ('"', "'", "”", "’"):
        following += 1
    return following == len(raw_text) or raw_text[following].isspace()


def _append_bounded(
    segments: list[FormationSegment],
    raw_text: str,
    start: int,
    end: int,
    *,
    boundary: str,
    max_segment_chars: int,
    quote_states: list[bool],
    line_starts: list[int],
) -> None:
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    if start == end:
        return
    parent_start = start
    parent_end = end
    continuation = False
    while end - start > max_segment_chars:
        limit = start + max_segment_chars
        split = next(
            (
                candidate
                for candidate in range(limit, start, -1)
                if raw_text[candidate].isspace()
            ),
            limit,
        )
        hard_boundary = (
            "hard-whitespace" if raw_text[split].isspace() else "hard-character"
        )
        segments.append(
            _segment(
                raw_text,
                start,
                split,
                hard_boundary,
                quote_states,
                line_starts,
                parent_start=parent_start,
                parent_end=parent_end,
                continuation=continuation,
            )
        )
        continuation = True
        start = split
        while start < end and raw_text[start].isspace():
            start += 1
        if start == end:
            return
    segments.append(
        _segment(
            raw_text,
            start,
            end,
            boundary,
            quote_states,
            line_starts,
            parent_start=parent_start,
            parent_end=parent_end,
            continuation=continuation,
        )
    )


def _segment(
    raw_text: str,
    start: int,
    end: int,
    boundary: str,
    quote_states: list[bool],
    line_starts: list[int],
    *,
    parent_start: int,
    parent_end: int,
    continuation: bool,
) -> FormationSegment:
    line_start = line_starts[start]
    speaker_match = _COLON_SPEAKER.match(raw_text, line_start)
    speaker = speaker_match.group(1) if speaker_match is not None else None
    parent_body_start = parent_start
    if speaker_match is not None and parent_start <= speaker_match.end() <= parent_end:
        parent_body_start = speaker_match.end()
        while parent_body_start < parent_end and raw_text[parent_body_start].isspace():
            parent_body_start += 1
    body_start = start
    if speaker_match is not None and start <= speaker_match.end() <= end:
        body_start = speaker_match.end()
        while body_start < end and raw_text[body_start].isspace():
            body_start += 1
    return FormationSegment(
        text=raw_text[start:end],
        start=start,
        end=end,
        boundary=boundary,
        speaker=speaker,
        body_start=body_start,
        quoted=quote_states[body_start],
        parent_start=parent_start,
        parent_end=parent_end,
        parent_body_start=parent_body_start,
        parent_quoted=quote_states[parent_body_start],
        context_start=line_start if speaker_match is not None else parent_start,
        context_end=parent_end,
        continuation=continuation,
    )


def _quote_states(raw_text: str) -> list[bool]:
    states = [False]
    stack: list[str] = []
    for index, char in enumerate(raw_text):
        previous = raw_text[index - 1] if index else ""
        following = raw_text[index + 1] if index + 1 < len(raw_text) else ""
        intra_word_apostrophe = previous.isalnum() and following.isalnum()
        if char == '"' and previous != "\\":
            if stack and stack[-1] == '"':
                stack.pop()
            else:
                stack.append('"')
        elif char == "“":
            stack.append("”")
        elif char == "”" and stack and stack[-1] == "”":
            stack.pop()
        elif char == "‘":
            stack.append("’")
        elif (
            char == "’"
            and not intra_word_apostrophe
            and stack
            and stack[-1] == "’"
        ):
            stack.pop()
        elif char == "'" and not intra_word_apostrophe and not previous.isalnum():
            if stack and stack[-1] == "'":
                stack.pop()
            elif following and not following.isspace():
                stack.append("'")
        elif (
            char == "'"
            and not intra_word_apostrophe
            and stack
            and stack[-1] == "'"
        ):
            stack.pop()
        states.append(bool(stack))
    return states


def _line_starts(raw_text: str) -> list[int]:
    starts: list[int] = []
    current = 0
    for index, char in enumerate(raw_text):
        starts.append(current)
        if char == "\n":
            current = index + 1
    starts.append(current)
    return starts
