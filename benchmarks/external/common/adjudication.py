"""Versioned local adjudication overlays for benchmark score reports.

Raw benchmark results are never rewritten.  An overlay supplies explicit,
auditable per-case score corrections and produces a separately named score
view.  Private case text is neither required nor accepted by this schema; only
case id, category, corrected score, and a short disposition are loaded.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from seam_runtime.self_improve import ScoreReport

ADJUDICATION_SCHEMA = "seam-adjudication/1"


@dataclass(frozen=True)
class AdjudicatedCase:
    case_id: str
    category: str
    score: float
    disposition: str


@dataclass(frozen=True)
class AdjudicationOverlay:
    version: str
    cases: Mapping[str, AdjudicatedCase]


def load_adjudication_overlay(path: str | Path) -> AdjudicationOverlay:
    """Load and fail closed on a minimal, versioned adjudication JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != ADJUDICATION_SCHEMA:
        raise ValueError(f"expected adjudication schema {ADJUDICATION_SCHEMA!r}")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("adjudication version must be a non-empty string")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("adjudication cases must be a list")

    cases: dict[str, AdjudicatedCase] = {}
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("each adjudication case must be an object")
        case_id = raw.get("case_id")
        category = raw.get("category")
        score = raw.get("score")
        disposition = raw.get("disposition")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("adjudication case_id must be a non-empty string")
        if case_id in cases:
            raise ValueError(f"duplicate adjudication case_id {case_id!r}")
        if not isinstance(category, str) or not category:
            raise ValueError(f"adjudication category missing for {case_id!r}")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise ValueError(f"adjudication score must be within [0, 1] for {case_id!r}")
        if not isinstance(disposition, str) or not disposition:
            raise ValueError(f"adjudication disposition missing for {case_id!r}")
        cases[case_id] = AdjudicatedCase(
            case_id=case_id,
            category=category,
            score=float(score),
            disposition=disposition,
        )
    return AdjudicationOverlay(version=version, cases=cases)


class AdjudicatedScorer:
    """Wrap a scorer and expose a separate corrected score view.

    The wrapped scorer still performs the raw measurement.  Only listed case
    ids are replaced; every other score stays byte-for-byte equivalent.  The
    most recent raw report remains available as ``last_raw_report`` so callers
    can report both views without obscuring the benchmark result.
    """

    def __init__(
        self,
        inner,
        overlay: AdjudicationOverlay,
        *,
        category_by_case: Mapping[str, str] | None = None,
    ) -> None:
        self.inner = inner
        self.overlay = overlay
        self.category_by_case = dict(category_by_case or {})
        self.name = f"{inner.name}:adjudicated:{overlay.version}"
        self.profile_safe = bool(getattr(inner, "profile_safe", False))
        self.answer_policy_safe = bool(getattr(inner, "answer_policy_safe", False))
        self.last_raw_report: ScoreReport | None = None
        self.last_views: dict[str, ScoreReport] = {}

    def score(self, runtime, flags=None) -> ScoreReport:
        raw = self.inner.score(runtime, flags=flags)
        self.last_raw_report = raw
        per_case = dict(raw.per_case)
        unmatched = sorted(set(self.overlay.cases) - set(per_case))
        if unmatched:
            raise ValueError(
                f"adjudication overlay references unknown case ids: {unmatched!r}"
            )
        for case_id, case in self.overlay.cases.items():
            expected_category = self.category_by_case.get(case_id)
            if expected_category is not None and expected_category != case.category:
                raise ValueError(
                    f"adjudication category mismatch for {case_id!r}: "
                    f"overlay={case.category!r}, scorer={expected_category!r}"
                )
            per_case[case_id] = case.score

        category_values: dict[str, list[float]] = defaultdict(list)
        for case_id, value in per_case.items():
            overlay_case = self.overlay.cases.get(case_id)
            category = (
                overlay_case.category
                if overlay_case is not None
                else self.category_by_case.get(case_id, "unknown")
            )
            category_values[category].append(float(value))
        n = len(per_case)
        corrected = ScoreReport(
            scorer=self.name,
            aggregate=sum(per_case.values()) / n if n else 0.0,
            n=n,
            per_category={
                category: sum(values) / len(values)
                for category, values in category_values.items()
            },
            per_case=per_case,
        )
        self.last_views = {"raw": raw, "adjudicated": corrected}
        return corrected
