"""H2 slice 4: deterministic dev/holdout split for benchmark case_ids.

The retrieval_event substrate is now writable both live (slice 2 hook) and
from history (slice 3 backfill). Before any ranking-policy tuning consumes
those rows, we need a stable dev/holdout partition of the underlying cases
so that "tune on the full 1542-case set, then claim improvement on the same
1542-case set" stops being structurally possible.

This module is the partition primitive: given a salt and a dev ratio, every
``case_id`` hashes deterministically into ``dev`` or ``holdout``. The result
is materialised as a JSON manifest the operator commits to the repo, so the
split is part of git history and cannot be silently changed.

Workflow:

1. First run produces the manifest from the source dataset's case_ids::

       python -m tools.h2.holdout_split \\
           --source quickstart \\
           --manifest benchmarks/external/locomo/holdout_assignment.json

   Default salt is ``seam-locomo-v1`` and default ratio is ``0.8`` (80% dev,
   20% holdout). Override with ``--salt`` / ``--ratio``.

2. Re-running with the same manifest is idempotent for existing case_ids
   and appends any new ones with the same salt/ratio.

3. Changing ``--salt`` or ``--ratio`` when a manifest already exists is
   rejected unless ``--rewrite`` is also passed. The manifest carries the
   active salt and ratio in its body so consumers can audit them.

4. Downstream code consumes the manifest with ``load_manifest(path)`` and
   ``dev_case_ids(...)`` / ``holdout_case_ids(...)`` / ``is_holdout(...)``.

Slice 5 (``seam improvement review``) is the consumer that will block
ranking-policy proposals whose tuning touched holdout case_ids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from benchmarks.external.common.dataset import load_locomo_cases, load_quickstart_cases
from benchmarks.external.common.types import BenchmarkCase

DEV = "dev"
HOLDOUT = "holdout"
_VALID_SPLITS = (DEV, HOLDOUT)

DEFAULT_SALT = "seam-locomo-v1"
DEFAULT_RATIO = 0.8

MANIFEST_SCHEMA = "seam-holdout-split/v1"


@dataclass(frozen=True)
class SplitAssignment:
    """Manifest payload: the salt+ratio that produced the split plus the
    per-case_id assignment table. ``assignments`` is ``{case_id: 'dev' | 'holdout'}``."""

    salt: str
    ratio: float
    dataset_source: str
    assignments: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.ratio < 1.0:
            raise ValueError(f"ratio must be in (0.0, 1.0), got {self.ratio!r}")
        bad = {v for v in self.assignments.values() if v not in _VALID_SPLITS}
        if bad:
            raise ValueError(f"invalid split labels: {sorted(bad)!r}")


def assign_one(case_id: str, *, salt: str, ratio: float) -> str:
    """Deterministic bucket for a single case_id. Returns ``"dev"`` or ``"holdout"``.

    The hash is sha256 over ``salt + ":" + case_id`` reduced to a uniform
    bucket in ``[0, 1)``. Same salt + same case_id => same bucket forever.
    """
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio must be in (0.0, 1.0), got {ratio!r}")
    digest = hashlib.sha256(f"{salt}:{case_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0x100000000  # uniform in [0.0, 1.0)
    return DEV if bucket < ratio else HOLDOUT


def compute_assignments(
    case_ids: Iterable[str], *, salt: str, ratio: float
) -> dict[str, str]:
    """Compute the full split table for a fresh set of case_ids."""
    return {cid: assign_one(cid, salt=salt, ratio=ratio) for cid in case_ids}


def dev_case_ids(assignment: SplitAssignment) -> list[str]:
    return sorted(cid for cid, split in assignment.assignments.items() if split == DEV)


def holdout_case_ids(assignment: SplitAssignment) -> list[str]:
    return sorted(cid for cid, split in assignment.assignments.items() if split == HOLDOUT)


def is_holdout(assignment: SplitAssignment, case_id: str) -> bool:
    return assignment.assignments.get(case_id) == HOLDOUT


def load_manifest(path: str | Path) -> SplitAssignment:
    """Read an existing manifest. Raises if file is missing or malformed."""
    path = Path(path)
    blob = json.loads(path.read_text(encoding="utf-8"))
    if blob.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(
            f"unexpected manifest schema {blob.get('schema')!r}, expected {MANIFEST_SCHEMA!r}"
        )
    return SplitAssignment(
        salt=blob["salt"],
        ratio=float(blob["ratio"]),
        dataset_source=blob["dataset_source"],
        assignments=dict(blob.get("assignments") or {}),
    )


def save_manifest(path: str | Path, assignment: SplitAssignment) -> None:
    """Write the manifest with sorted assignments for stable diffs."""
    path = Path(path)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "salt": assignment.salt,
        "ratio": assignment.ratio,
        "dataset_source": assignment.dataset_source,
        "assignments": dict(sorted(assignment.assignments.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class UpdateReport:
    """What changed when ``update_manifest`` ran."""

    manifest_path: Path
    added: list[str]
    existing: list[str]
    dev_count: int
    holdout_count: int
    salt_changed: bool
    ratio_changed: bool


def _load_source_cases(source: str | Path) -> list[BenchmarkCase]:
    """Resolve --source: the literal string 'quickstart' uses the bundled fixture."""
    if isinstance(source, str) and source.lower() == "quickstart":
        return load_quickstart_cases()
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"source dataset not found: {path}")
    return load_locomo_cases(path)


def update_manifest(
    *,
    manifest_path: str | Path,
    source: str | Path,
    salt: str = DEFAULT_SALT,
    ratio: float = DEFAULT_RATIO,
    rewrite: bool = False,
) -> tuple[SplitAssignment, UpdateReport]:
    """Idempotent assign: read existing manifest, add new case_ids, write back.

    Raises ``ValueError`` if ``salt`` or ``ratio`` differ from the existing
    manifest and ``rewrite=False``; the caller must opt in by passing
    ``rewrite=True``. When ``rewrite=True``, every assignment is recomputed
    from scratch under the new salt/ratio (a deliberate, audit-worthy event).
    """
    manifest_path = Path(manifest_path)
    cases = _load_source_cases(source)
    case_ids = [c.case_id for c in cases]
    source_label = source if isinstance(source, str) else str(source)

    if manifest_path.exists():
        existing = load_manifest(manifest_path)
        salt_changed = existing.salt != salt
        ratio_changed = existing.ratio != ratio
        if (salt_changed or ratio_changed) and not rewrite:
            raise ValueError(
                "manifest already exists with different salt/ratio; pass rewrite=True "
                f"to recompute. existing salt={existing.salt!r} ratio={existing.ratio!r}; "
                f"requested salt={salt!r} ratio={ratio!r}"
            )

        if rewrite and (salt_changed or ratio_changed):
            new_assignments = compute_assignments(case_ids, salt=salt, ratio=ratio)
            added = sorted(case_ids)
            existing_kept: list[str] = []
        else:
            new_assignments = dict(existing.assignments)
            added = []
            existing_kept = []
            for cid in case_ids:
                if cid in new_assignments:
                    existing_kept.append(cid)
                else:
                    new_assignments[cid] = assign_one(cid, salt=salt, ratio=ratio)
                    added.append(cid)
            added.sort()
            existing_kept.sort()

        assignment = SplitAssignment(
            salt=salt,
            ratio=ratio,
            dataset_source=source_label,
            assignments=new_assignments,
        )
    else:
        salt_changed = False
        ratio_changed = False
        new_assignments = compute_assignments(case_ids, salt=salt, ratio=ratio)
        assignment = SplitAssignment(
            salt=salt,
            ratio=ratio,
            dataset_source=source_label,
            assignments=new_assignments,
        )
        added = sorted(case_ids)
        existing_kept = []

    save_manifest(manifest_path, assignment)
    report = UpdateReport(
        manifest_path=manifest_path,
        added=added,
        existing=existing_kept,
        dev_count=len(dev_case_ids(assignment)),
        holdout_count=len(holdout_case_ids(assignment)),
        salt_changed=salt_changed,
        ratio_changed=ratio_changed,
    )
    return assignment, report


def _format_report(report: UpdateReport) -> str:
    parts = [
        f"manifest={report.manifest_path}",
        f"dev={report.dev_count}",
        f"holdout={report.holdout_count}",
        f"added={len(report.added)}",
        f"unchanged={len(report.existing)}",
    ]
    if report.salt_changed:
        parts.append("salt_changed=True")
    if report.ratio_changed:
        parts.append("ratio_changed=True")
    return " | ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tools.h2.holdout_split",
        description=(
            "Deterministic dev/holdout split for benchmark case_ids. "
            "Idempotent: re-running with the same salt/ratio assigns new "
            "case_ids and leaves existing ones untouched."
        ),
    )
    p.add_argument(
        "--source",
        required=True,
        help="Source dataset. 'quickstart' for the bundled fixture, otherwise a LoCoMo JSON path.",
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="Path to the split manifest JSON. Created if missing.",
    )
    p.add_argument(
        "--salt",
        default=DEFAULT_SALT,
        help=f"Hash salt. Default: {DEFAULT_SALT!r}.",
    )
    p.add_argument(
        "--ratio",
        type=float,
        default=DEFAULT_RATIO,
        help=f"Dev fraction in (0.0, 1.0). Default: {DEFAULT_RATIO}.",
    )
    p.add_argument(
        "--rewrite",
        action="store_true",
        help=(
            "Allow recomputing every assignment when salt or ratio changes. "
            "Without this flag, a salt/ratio change against an existing manifest "
            "is rejected."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, report = update_manifest(
        manifest_path=args.manifest,
        source=args.source,
        salt=args.salt,
        ratio=args.ratio,
        rewrite=args.rewrite,
    )
    print(_format_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
