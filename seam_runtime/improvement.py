"""H2 slice 5: validation + workflow for ``improvement_proposal`` rows.

This module is the operator gate for H2 ranking-policy and protocol
proposals. It NEVER writes to ``AGENTS.md``, ``REPO_LEDGER.md``, or
``PROJECT_STATUS.md``; the only side effects are SQLite reads/writes
through ``SQLiteStore`` and (optionally) reading a holdout-split
manifest produced by ``tools/h2/holdout_split.py``.

The flow:

1. A proposer (human or tool) calls ``validate_proposal`` with the
   evidence (event_ids and/or case_ids) and an optional
   ``SplitAssignment``. The validator flags the proposal as a holdout
   violation if any cited ``case_id`` falls in the holdout pool.
2. The store writes the proposal with the violation flag. Slice 4's
   manifest is the source of truth; proposals that cite holdout cases
   are persisted so the audit trail is preserved but require explicit
   operator action to approve.
3. Operators flip status through ``SQLiteStore.record_proposal_decision``;
   prior decisions stay in place so reversals (approve -> reject) are
   captured, not erased.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from tools.h2.holdout_split import SplitAssignment


def _import_holdout_case_ids():
    """Import ``tools.h2.holdout_split.holdout_case_ids`` for the holdout gate.

    ``tools/`` is a sibling of ``seam_runtime/`` intentionally not shipped in
    the wheel (see ``cli._import_run_improvement_cycle``), so a genuine
    PyPI/uvx install falls back to ``None`` here instead of crashing on
    import; ``validate_proposal`` then reports that the holdout check needs a
    source checkout rather than raising ``ModuleNotFoundError`` at import time.
    """
    try:
        from tools.h2.holdout_split import holdout_case_ids
        return holdout_case_ids
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parent.parent
        if (repo_root / "tools" / "h2" / "holdout_split.py").is_file():
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from tools.h2.holdout_split import holdout_case_ids
            return holdout_case_ids
        return None


VALID_KINDS = (
    "ranking_weight",
    "decomposer_threshold",
    "stale_filter",
    "schema_change",
    "other",
)

VALID_STATUSES = ("pending", "approved", "rejected", "superseded")


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of ``validate_proposal``.

    ``holdout_violation`` is the canonical flag that gets persisted on the
    proposal row. ``holdout_case_ids`` lists the specific case_ids that
    triggered it (useful for the operator to see in ``seam improvement
    show``). ``warnings`` is a free-text list of non-blocking concerns.
    """

    holdout_violation: bool
    holdout_case_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_proposal(
    *,
    kind: str,
    summary: str,
    evidence_case_ids: Iterable[str] | None = None,
    holdout_assignment: SplitAssignment | None = None,
) -> ValidationReport:
    """Compute the validation report for a proposed change.

    Holdout check is the load-bearing gate: a proposal whose cited
    ``case_ids`` overlap the holdout pool is flagged. Approval is still
    possible through the operator workflow, but the violation must travel
    with the proposal record so reviewers see it.

    Non-fatal warnings are returned for missing rationale, unknown kind,
    and empty evidence; they do not block writing the proposal.
    """
    warnings: list[str] = []

    if kind not in VALID_KINDS:
        warnings.append(
            f"kind {kind!r} is not in the conventional set {VALID_KINDS!r}; using 'other' is fine for novel categories"
        )
    if not summary.strip():
        warnings.append("summary is empty")

    holdout_hits: list[str] = []
    if holdout_assignment is not None and evidence_case_ids is not None:
        case_id_list = [c for c in evidence_case_ids if c]
        if not case_id_list:
            warnings.append("no evidence case_ids supplied; holdout check is a no-op")
        else:
            holdout_case_ids = _import_holdout_case_ids()
            if holdout_case_ids is None:
                raise RuntimeError(
                    "Holdout-split checking requires a source checkout: "
                    "tools/h2/holdout_split.py is not shipped in the wheel"
                )
            holdout_set = set(holdout_case_ids(holdout_assignment))
            holdout_hits = sorted(set(case_id_list) & holdout_set)
            unknown = [c for c in case_id_list if c not in holdout_assignment.assignments]
            if unknown:
                warnings.append(
                    f"evidence case_ids not in holdout manifest: {sorted(unknown)!r} (assignment is incomplete)"
                )

    return ValidationReport(
        holdout_violation=bool(holdout_hits),
        holdout_case_ids=holdout_hits,
        warnings=warnings,
    )


def proposal_blocks_promotion(proposal: dict) -> bool:
    """Return True if this proposal would prevent ranking-policy promotion.

    Slice 5 gate: a promotion ships only when the latest decision is
    ``approved`` AND ``holdout_violation`` is False. Everything else
    (pending, rejected, superseded, or violation flag set) blocks.
    """
    if proposal.get("holdout_violation"):
        return True
    return proposal.get("latest_status") != "approved"
