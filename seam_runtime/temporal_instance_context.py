"""Temporal-instance context projection for the Mem0-harness facade lane.

Motivation (HISTORY#424/#426): SEAM's cat2 temporal score on mem0's unmodified
harness is 71.96% vs mem0's published 92.0%, and the dominant measured failure
is WRONG-INSTANCE date selection — the harness answerer, given 200 ranked raw
turns, repeatedly reports the date of a different (often the most recent)
occurrence of the queried activity instead of the queried instance's date.
SEAM's native ``temporal/1`` answer directive fixes exactly this on the native
lane but cannot reach the harness lane: the harness owns answer generation and
the facade constructs its adapter with ``answerer=None``.

This module is the retrieval-side counterpart, following the proven
``event_count_context`` pattern (HISTORY#416): for temporal questions it builds
a bounded, disposable ``SEAM-TEMPORAL/1`` projection that organizes the
retrieved raw turns into a date -> observations index (session date parsed from
the ``[Speaker YYYY-MM-DD]`` prefix the facade emits), so the downstream
answerer can line the queried event up with the date it was OBSERVED, and is
explicitly told that a turn's bracketed date is when the speaker said it — with
"yesterday"/"last week" wording meaning the event happened before that date.

Deliberately self-contained: no import from ``event_count_context`` (that
module has in-flight concurrent edits) and no ``RetrievalFlags`` field yet —
the facade enables it from the ``SEAM_TEMPORAL_CONTEXT_POLICY`` environment
variable while the lever is validated (productization into core flags follows
a measured win, per the productize-to-core policy). Default is OFF and the
off path is byte-identical: callers get ``None`` and change nothing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

POLICY_OFF = "off"
POLICY_V1 = "temporal-instance/1"

_TEMPORAL_QUERY = re.compile(
    r"\b(when did|when was|what (?:date|day|time|year|month)|"
    r"on (?:what|which) (?:date|day)|how long (?:ago|did|has|было)?|"
    r"how (?:many|much) (?:days|weeks|months|years)|what day did)\b",
    re.IGNORECASE,
)

# The facade renders raw turns as "[Speaker YYYY-MM-DD] text".
_SPEAKER_DATE = re.compile(r"^\[([^\]]+?)\s+(\d{4}-\d{2}-\d{2})\]\s*(.*)$", re.DOTALL)

# Words that mean the event PRECEDED the session date; surfaced per-row so the
# answerer resolves them instead of echoing the session date.
_RELATIVE_MARKER = re.compile(
    r"\b(yesterday|last (?:night|week|month|year|friday|saturday|sunday|monday|"
    r"tuesday|wednesday|thursday)|a few days ago|the other day|this morning|"
    r"earlier th(?:is|at) (?:week|month|year)|recently|just got back|"
    r"over the weekend)\b",
    re.IGNORECASE,
)


def is_temporal_question(query: str) -> bool:
    return bool(_TEMPORAL_QUERY.search(query or ""))


@dataclass(frozen=True)
class TemporalEvidence:
    """One retrieved raw-turn memory as the facade serves it."""

    record_id: str
    text: str
    score: float
    original_rank: int


@dataclass(frozen=True)
class _DateRow:
    session_date: str
    speaker: str
    snippet: str
    relative_marker: str | None
    evidence: TemporalEvidence


@dataclass(frozen=True)
class TemporalProjection:
    query: str
    rows: tuple[_DateRow, ...]
    undated: tuple[TemporalEvidence, ...] = field(default=())

    @property
    def projection_id(self) -> str:
        digest = hashlib.sha256(
            "|".join([self.query, *[r.evidence.record_id for r in self.rows]]).encode()
        ).hexdigest()[:16]
        return f"seam-temporal-1-{digest}"

    def render(self, *, max_dates: int = 24, max_rows_per_date: int = 3,
               max_text_chars: int = 140) -> str:
        by_date: dict[str, list[_DateRow]] = {}
        for row in self.rows:
            by_date.setdefault(row.session_date, []).append(row)
        lines = [
            "SEAM-TEMPORAL/1 date index (disposable projection; raw memories follow).",
            "Each retrieved memory is stamped [Speaker YYYY-MM-DD] = the SESSION date",
            "the speaker said it. Words like 'yesterday'/'last week' mean the event",
            "happened BEFORE that session date - resolve them against it. To answer a",
            "'when' question: find the session whose text describes the QUERIED event",
            "(same activity, same details), not a similar event from another date, and",
            "prefer the earliest session that reports it as already done.",
            "",
        ]
        for date in sorted(by_date)[:max_dates]:
            rows = by_date[date][:max_rows_per_date]
            lines.append(f"{date}:")
            for row in rows:
                snippet = row.snippet[:max_text_chars]
                marker = f" [relative: {row.relative_marker}]" if row.relative_marker else ""
                lines.append(f"  - ({row.speaker}) {snippet}{marker}")
        return "\n".join(lines)


def build_temporal_context_projection(
    query: str,
    evidence: list[TemporalEvidence],
    *,
    policy: str = POLICY_OFF,
) -> TemporalProjection | None:
    """Projection for a temporal question, or None (the byte-identical off path).

    None when: policy is off/unknown, the query is not temporal, or fewer than
    two distinct session dates were parsed (a single date cannot be
    wrong-instance-confused, and the projection would only spend context).
    """

    if policy != POLICY_V1 or not is_temporal_question(query) or not evidence:
        return None
    rows: list[_DateRow] = []
    undated: list[TemporalEvidence] = []
    for item in evidence:
        match = _SPEAKER_DATE.match(item.text or "")
        if not match:
            undated.append(item)
            continue
        speaker, date, body = match.group(1), match.group(2), match.group(3)
        marker = _RELATIVE_MARKER.search(body)
        rows.append(
            _DateRow(
                session_date=date,
                speaker=speaker,
                snippet=" ".join(body.split()),
                relative_marker=marker.group(0).lower() if marker else None,
                evidence=item,
            )
        )
    if len({r.session_date for r in rows}) < 2:
        return None
    return TemporalProjection(query=query, rows=tuple(rows), undated=tuple(undated))
