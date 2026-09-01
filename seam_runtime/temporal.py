from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from math import exp

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_PATTERNS = [
    rf"\b({_MONTH})\s+\d{{4}}\b",
    r"\b\d{1,2}\s+" + _MONTH + r"\s+\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b(?:last|this|next)\s+(?:week|month|year)\b",
    r"\b(?:yesterday|today|tomorrow)\b",
    r"\b\d+\s+(?:days?|weeks?|months?|years?)\s+(?:ago|after|before|later)\b",
]
_TEMPORAL_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_RELATIVE_RE = re.compile(
    r"\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
    r"(?P<unit>days?|weeks?|months?|years?)\s+"
    r"(?P<direction>ago|before|after|later)\b",
    re.IGNORECASE,
)
_NAMED_RELATIVE_OFFSETS = {
    "yesterday": -1,
    "today": 0,
    "tomorrow": 1,
    "last week": -7,
    "this week": 0,
    "next week": 7,
    "last month": -30,
    "this month": 0,
    "next month": 30,
    "last year": -365,
    "this year": 0,
    "next year": 365,
}


def detect_temporal_tokens(question: str) -> list[str]:
    return [m.group(0) for m in _TEMPORAL_RE.finditer(question)]


def parse_iso(ts: str | None) -> datetime | None:
    """Parse a supported timestamp into the canonical UTC-naive instant.

    Naive values are interpreted as UTC for compatibility with SEAM's stored
    timestamp contract.  Aware values, including ``Z`` and numeric offsets,
    are converted to UTC before their timezone marker is removed.  Missing and
    invalid values remain distinct from valid instants by returning ``None``.
    """

    if not isinstance(ts, str) or not ts.strip():
        return None
    candidate = ts.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return normalize_datetime(parsed)


def is_missing_timestamp(value: object) -> bool:
    """Return whether ``value`` represents an absent, open interval bound."""

    return value is None or (isinstance(value, str) and not value.strip())


def normalize_datetime(value: datetime) -> datetime:
    """Return ``value`` as the canonical UTC-naive comparison instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_timestamp(value: str | None) -> str | None:
    """Return a fixed-width UTC timestamp key or ``None`` when not parseable."""

    parsed = parse_iso(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="microseconds") + "Z"


def compare_timestamps(left: str | None, right: str | None) -> int | None:
    """Compare two timestamp values under the canonical policy.

    ``None`` means at least one side is missing or invalid, allowing each
    caller to apply its own fail-closed direction without inventing a second
    parser.
    """

    left_key = normalize_timestamp(left)
    right_key = normalize_timestamp(right)
    if left_key is None or right_key is None:
        return None
    return (left_key > right_key) - (left_key < right_key)


def canonical_timestamp_extreme(
    values: Iterable[object],
    *,
    latest: bool,
) -> str | None:
    """Select an earliest/latest valid instant and return its canonical key.

    Missing and invalid values never outrank a valid instant. If every supplied
    value is invalid, no timestamp is established.
    """

    normalized = [
        key
        for value in values
        if (key := normalize_timestamp(str(value) if value is not None else None))
        is not None
    ]
    if not normalized:
        return None
    return (max if latest else min)(normalized)


def register_sqlite_timestamp_functions(connection: sqlite3.Connection) -> None:
    """Install deterministic SQL comparison keys backed by this policy."""

    connection.create_function(
        "seam_timestamp_key",
        1,
        normalize_timestamp,
        deterministic=True,
    )


def parse_temporal_reference(question: str, *, anchor: datetime | None = None) -> datetime | None:
    """Parse one temporal reference from a question.

    Absolute ISO dates do not need an anchor. Relative dates use the supplied
    anchor, typically the first timestamp in the conversation scope.
    """
    tokens = detect_temporal_tokens(question)
    for token in tokens:
        parsed = parse_iso(token)
        if parsed is not None:
            return parsed
    if anchor is None:
        return None

    normalized = question.lower()
    for phrase, days in _NAMED_RELATIVE_OFFSETS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", normalized):
            return anchor + timedelta(days=days)

    match = _RELATIVE_RE.search(question)
    if match is None:
        return None
    count = _parse_count(match.group("count"))
    unit_days = _unit_days(match.group("unit"))
    direction = match.group("direction").lower()
    days = count * unit_days
    if direction in {"ago", "before"}:
        days = -days
    return anchor + timedelta(days=days)


def temporal_distance_score(
    question_date_ref: datetime | None,
    candidate_timestamp: datetime | None,
    decay_constant: float = 30.0,
) -> float:
    if question_date_ref is None or candidate_timestamp is None:
        return 0.0
    if decay_constant <= 0:
        raise ValueError("decay_constant must be positive")
    question_date_ref = normalize_datetime(question_date_ref)
    candidate_timestamp = normalize_datetime(candidate_timestamp)
    delta_days = abs((candidate_timestamp - question_date_ref).total_seconds()) / 86400.0
    return exp(-delta_days / decay_constant)


def _parse_count(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return _NUMBER_WORDS[value.lower()]


def _unit_days(unit: str) -> int:
    normalized = unit.lower().rstrip("s")
    return {
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365,
    }[normalized]
