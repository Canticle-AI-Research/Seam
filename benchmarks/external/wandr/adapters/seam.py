"""SEAM adapter for the zero-network WANDR replay lane.

Endpoints (the WANDR-side adapter contract):

    reset(scope_id)                 -> drop the scope's isolated store
    ingest_row(scope_id, row)       -> persist one submission row with provenance
    ingest_task(scope_id, task)     -> ingest a whole replay task
    retrieve(scope_id, member_key)  -> recover rows for one hierarchy member
    submit(scope_id, task)          -> emit upstream-shaped results JSONL
    counters()                      -> provider/network/cost, asserted zero

Two lanes share this adapter so the ablation is same-code:

``native``      SEAM's canonical retrieval engine (graph legs participate).
``event-only``  the same corpus and budget with graph legs disabled.

Anything that differs between them is therefore attributable to the graph, not
to a second scorer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.external.wandr.types import (
    ReplayCounters,
    WandrRow,
    WandrTask,
    stable_id,
)
from benchmarks.external.wandr.urls import canonical_url

LANES = ("native", "event-only")

class ZeroNetworkViolation(RuntimeError):
    """Raised if the replay lane attempts a live fetch or provider call."""


class SeamWandrAdapter:
    """Replay WANDR submission rows through SEAM memory.

    The adapter never fetches. Every URL in the pinned corpus uses the reserved
    ``.invalid`` TLD, so even an accidental fetch could not resolve; on top of
    that, :meth:`fetch` exists solely to fail loudly.
    """

    name = "seam"

    def __init__(
        self,
        db_root: str | Path,
        *,
        lane: str = "native",
        budget: int = 8000,
        search_top_k: int = 100,
    ) -> None:
        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r}; expected one of {LANES}")
        self.lane = lane
        self.budget = budget
        self.search_top_k = search_top_k
        self._db_root = Path(db_root)
        self._runtimes: dict[str, Any] = {}
        self._counters = ReplayCounters()
        # scope -> member_key -> ordered canonical source ids
        self._provenance: dict[str, dict[str, list[str]]] = {}

    # -- infrastructure -------------------------------------------------

    def namespace(self, scope_id: str) -> str:
        """Isolated namespace per scope, so tasks cannot bleed into each other."""
        return f"wandr:{scope_id}"

    def _runtime(self, scope_id: str):
        if scope_id not in self._runtimes:
            from seam_runtime.models import HashEmbeddingModel
            from seam_runtime.runtime import SeamRuntime

            self._db_root.mkdir(parents=True, exist_ok=True)
            self._runtimes[scope_id] = SeamRuntime(
                self._db_root / f"{scope_id}.db",
                embedding_model=HashEmbeddingModel(),
                allow_pgvector_env=False,
            )
        return self._runtimes[scope_id]

    def counters(self) -> dict[str, Any]:
        return self._counters.as_dict()

    def fetch(self, url: str) -> None:
        """Never valid in this lane."""
        self._counters.network_calls += 1
        raise ZeroNetworkViolation(
            f"replay lane attempted a live fetch of {url!r}; "
            "the WANDR replay corpus is pinned and offline"
        )

    def reset(self, scope_id: str) -> None:
        runtime = self._runtimes.pop(scope_id, None)
        close = getattr(runtime, "close", None)
        if callable(close):
            close()
        db_path = self._db_root / f"{scope_id}.db"
        for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            path.unlink(missing_ok=True)
        self._provenance.pop(scope_id, None)

    # -- ingest ---------------------------------------------------------

    def ingest_row(self, scope_id: str, row: WandrRow) -> str:
        """Persist one row's excerpts as memory, carrying its provenance.

        Returns the canonical source id. Re-ingesting the same
        (member, canonical url) pair is idempotent: WANDR penalises duplicate
        entities, so deduplication belongs at ingest, not at scoring time.
        """
        canonical = canonical_url(row.url)
        source_id = stable_id("source", row.task, canonical)
        member = row.member_key

        seen = self._provenance.setdefault(scope_id, {}).setdefault(member, [])
        if source_id in seen:
            return source_id

        runtime = self._runtime(scope_id)
        text = self._render(row, canonical)
        runtime.ingest_conversation_turn(
            text,
            source_ref=canonical,
            ns=self.namespace(scope_id),
            scope="thread",
            persist=True,
            allow_env_extractor=False,
        )
        seen.append(source_id)
        return source_id

    def _render(self, row: WandrRow, canonical: str) -> str:
        """Render a row into one memory turn.

        Excerpts stay verbatim — upstream requires excerpts be faithful to the
        page — while the member and answer fields supply the queryable framing.
        """
        lines = [f"{key}: {value}" for key, value in sorted(row.item.items())]
        lines.append(f"source: {canonical}")
        lines.extend(str(excerpt) for excerpt in row.excerpts)
        for key, value in sorted(row.answer.items()):
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def ingest_task(self, scope_id: str, task: WandrTask) -> dict[str, Any]:
        ingested = [self.ingest_row(scope_id, row) for row in task.rows]
        unique = sorted(set(ingested))
        return {
            "rows": len(task.rows),
            "unique_sources": len(unique),
            "duplicates_collapsed": len(task.rows) - len(unique),
            "task_id": task.task_id,
        }

    # -- retrieval ------------------------------------------------------

    def retrieve(self, scope_id: str, member_key: str, query: str | None = None):
        """Recover evidence for one hierarchy member through SEAM retrieval.

        Both lanes use the same budget and candidate count; only graph
        participation differs, which is what makes the ablation attributable.
        """
        runtime = self._runtime(scope_id)
        mode = "mix" if self.lane == "native" else "hybrid"
        return runtime.retrieve(
            query or member_key.split("=", 1)[-1],
            scope="thread",
            budget=self.search_top_k,
            include_raw=True,
            ns=self.namespace(scope_id),
            mode=mode,
            include_trace=True,
        )

    def recovered_sources(
        self, scope_id: str, task_name: str, member_key: str
    ) -> list[str]:
        """Canonical source ids SEAM actually surfaced for a member.

        Provenance is read from the RAW record's ``source_ref`` — the value
        SEAM itself persisted at ingest — rather than re-parsed out of the
        rendered text, so this measures stored provenance, not our formatting.
        """
        result = self.retrieve(scope_id, member_key)
        found: list[str] = []
        for candidate in result.candidates:
            ref = (candidate.record.attrs or {}).get("source_ref") or ""
            if not ref:
                continue
            stored_ref = str(ref)
            if stored_ref != canonical_url(stored_ref):
                continue
            source_id = stable_id("source", task_name, stored_ref)
            if source_id not in found:
                found.append(source_id)
        return found

    # -- submission -----------------------------------------------------

    def submit(self, scope_id: str, task: WandrTask) -> list[dict[str, Any]]:
        """Emit upstream-shaped submission rows, deduplicated and canonicalized."""
        emitted: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in task.rows:
            key = (row.member_key, canonical_url(row.url))
            if key in seen:
                continue
            seen.add(key)
            payload = row.to_submission()
            payload["url"] = canonical_url(row.url)
            emitted.append(payload)
        return emitted

    def write_submission(
        self, scope_id: str, task: WandrTask, path: str | Path
    ) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for payload in self.submit(scope_id, task):
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return path

    def close(self) -> None:
        for scope_id in list(self._runtimes):
            runtime = self._runtimes.pop(scope_id)
            close = getattr(runtime, "close", None)
            if callable(close):
                close()
