"""Hash-pinned replay corpus loading. No live fetch, ever.

The corpus is checked in under ``benchmarks/fixtures/wandr/`` and pinned by
SHA-256 in ``MANIFEST.json``. Loading verifies the pin, so a corpus edit is a
deliberate, visible act rather than silent drift underneath a published number.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks.external.wandr.types import KeySpec, WandrRow, WandrTask
from benchmarks.external.wandr.urls import canonical_url

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "wandr"
MANIFEST_NAME = "MANIFEST.json"


class CorpusIntegrityError(RuntimeError):
    """A pinned corpus file does not match its recorded digest."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"replay corpus manifest missing: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def available_tasks(root: Path | None = None) -> tuple[str, ...]:
    manifest = _load_manifest(root or FIXTURE_ROOT)
    return tuple(sorted(manifest.get("tasks", {})))


def load_task(name: str, root: Path | None = None, verify: bool = True) -> WandrTask:
    """Load one pinned replay task.

    ``verify`` defaults to True; the digest check is the mechanism that makes
    "fixed corpus" an enforced property instead of a claim.
    """
    root = root or FIXTURE_ROOT
    manifest = _load_manifest(root)
    tasks = manifest.get("tasks", {})
    if name not in tasks:
        raise KeyError(
            f"unknown replay task {name!r}; available: {', '.join(sorted(tasks))}"
        )

    spec = tasks[name]
    corpus_path = root / spec["file"]
    if not corpus_path.exists():
        raise FileNotFoundError(f"replay corpus missing: {corpus_path}")

    if verify:
        actual = sha256_file(corpus_path)
        expected = spec.get("sha256")
        if actual != expected:
            raise CorpusIntegrityError(
                f"{corpus_path.name} digest {actual} != pinned {expected}; "
                "the corpus changed. Re-pin deliberately if intended."
            )

    rows: list[WandrRow] = []
    for line_no, line in enumerate(
        corpus_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(WandrRow.from_dict(name, json.loads(line)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{corpus_path.name}:{line_no}: {exc}") from exc

    hierarchy = tuple(
        KeySpec(name=level["name"], required=int(level["required"]))
        for level in spec["key_hierarchy"]
    )
    return WandrTask(name=name, key_hierarchy=hierarchy, rows=tuple(rows))


def validate_hierarchy(task: WandrTask) -> list[str]:
    """Check a task against its own key hierarchy.

    Returns human-readable violations. Upstream treats ``required`` as a soft
    floor ("more is usually better"), so falling short is reported, not raised —
    the replay lane measures SEAM, not corpus authorship.
    """
    problems: list[str] = []
    if not task.key_hierarchy:
        return ["task declares no key hierarchy"]

    member_spec = task.key_hierarchy[0]
    members = task.member_keys()
    if len(members) < member_spec.required:
        problems.append(
            f"{member_spec.name}: {len(members)} members < required "
            f"{member_spec.required}"
        )

    if len(task.key_hierarchy) > 1:
        url_spec = task.key_hierarchy[1]
        for member in members:
            urls = {
                canonical_url(row.url)
                for row in task.rows
                if row.member_key == member
            }
            if len(urls) < url_spec.required:
                problems.append(
                    f"{member}: {len(urls)} {url_spec.name}(s) < required "
                    f"{url_spec.required}"
                )

    for row in task.rows:
        if not row.excerpts:
            problems.append(f"{row.member_key} @ {row.url}: no excerpts")

    return problems
