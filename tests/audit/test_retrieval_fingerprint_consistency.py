"""Track S S5: a candidate set and its fingerprint attest one committed state.

The exit-gate clause: *a concurrent ingest cannot produce a candidate set or
fingerprint assembled from mutually inconsistent database states.*

`HISTORY#528` recorded why the connection-count clause is not enough on its
own. Routing the eleven ``store._connect()`` sites through a pool satisfies
"opens no new physical connections" while every leg still reads its own
implicit transaction, so the tear survives. These cases therefore stop the
request *between legs*, commit a real ingest from another thread, and let it
finish -- the exact interleaving that produced a mixed-state fingerprint.

``candidate_set_sha256`` is the reason this matters beyond ranking: it is
recorded as evidence that a decision was made over a specific pool. A digest
covering records that never coexisted attests a pool that never existed.
"""

from __future__ import annotations

import threading

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.retrieval_orchestrator import adapters as adapter_module
from seam_runtime.retrieval_orchestrator.adapters import SQLiteIRAdapter
from seam_runtime.retrieval_orchestrator.types import (
    QueryFilters,
    QueryIntent,
    RetrievalPlan,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter

# Every record carries IDENTICAL text; only the id differs. Varying the text
# per record makes this fixture silently useless: under the 64-dimension signed
# hash embedding a distinguishing word can collide destructively with the query
# term, score the record at or below zero, and drop it from the semantic leg --
# so a torn read would produce no visible difference and the test would pass
# against a broken implementation.
_TEXT = "a note about compilers"


def _record(record_id: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:test"]},
        attrs={"subject": "ent:test", "predicate": "notes", "object": _TEXT},
    )


def _runtime(path) -> SeamRuntime:
    model = HashEmbeddingModel()
    return SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=SQLiteVectorAdapter(str(path), model),
        allow_pgvector_env=False,
    )


def _seed(runtime: SeamRuntime, prefix: str, count: int) -> list[str]:
    records = [_record(f"clm:{prefix}-{index}") for index in range(count)]
    runtime.persist_ir(IRBatch(records))
    return [record.id for record in records]


def _ingest_from_another_thread(path, prefix: str, count: int) -> None:
    """Commit an ingest in a context that holds no snapshot of its own."""

    error: list[BaseException] = []

    def worker() -> None:
        try:
            writer = _runtime(path)
            try:
                _seed(writer, prefix, count)
            finally:
                writer.close()
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=120)
    assert not thread.is_alive(), "the concurrent ingest never finished"
    assert not error, f"the concurrent ingest failed: {error[0]!r}"


def test_ingest_between_legs_cannot_enter_the_candidate_set(tmp_path) -> None:
    """Records committed after the request began must appear in no leg."""

    path = tmp_path / "interleaved.db"
    runtime = _runtime(path)
    try:
        _seed(runtime, "seed", 6)

        # Stop the request after its first SQL leg, exactly where an
        # unsnapshotted request would begin reading a newer state.
        original_search = adapter_module.SQLiteIRAdapter.search
        fired = threading.Event()

        def interleaving_search(self, plan, limit):
            hits = original_search(self, plan, limit)
            if not fired.is_set():
                fired.set()
                _ingest_from_another_thread(path, "late", 4)
            return hits

        adapter_module.SQLiteIRAdapter.search = interleaving_search
        try:
            orchestrator = runtime._retrieval_orchestrator_cached()
            result = orchestrator.search("compilers", budget=20, mode="mix")
        finally:
            adapter_module.SQLiteIRAdapter.search = original_search

        assert fired.is_set(), "the fixture never interleaved an ingest"

        returned = {candidate.record.id for candidate in result.candidates}
        leaked = {record_id for record_id in returned if "late" in record_id}
        assert not leaked, f"a mid-request commit entered the candidate set: {leaked}"
        assert returned, "the fixture produced no candidates at all"

        # The ingest really did land -- the isolation is the snapshot, not a
        # failed write.
        after = {record.id for record in runtime.store.load_ir(ns="work", scope="thread").records}
        assert any("late" in record_id for record_id in after)
    finally:
        runtime.close()


def test_fingerprint_matches_a_state_that_actually_existed(tmp_path) -> None:
    """The digest must equal the one a quiet request over that state produces."""

    path = tmp_path / "fingerprint.db"
    runtime = _runtime(path)
    try:
        _seed(runtime, "seed", 6)

        orchestrator = runtime._retrieval_orchestrator_cached()
        quiet = orchestrator.decide("compilers", budget=5, mode="mix")

        original_search = adapter_module.SQLiteIRAdapter.search
        fired = threading.Event()

        def interleaving_search(self, plan, limit):
            hits = original_search(self, plan, limit)
            if not fired.is_set():
                fired.set()
                _ingest_from_another_thread(path, "late", 4)
            return hits

        adapter_module.SQLiteIRAdapter.search = interleaving_search
        try:
            interleaved = orchestrator.decide("compilers", budget=5, mode="mix")
        finally:
            adapter_module.SQLiteIRAdapter.search = original_search

        assert fired.is_set(), "the fixture never interleaved an ingest"
        assert interleaved.candidate_set_sha256 == quiet.candidate_set_sha256, (
            "the fingerprint attests a candidate pool assembled from more than "
            "one database state"
        )
    finally:
        runtime.close()


def test_a_request_started_after_the_ingest_sees_it(tmp_path) -> None:
    """The snapshot isolates one request; it does not freeze the store."""

    path = tmp_path / "later.db"
    runtime = _runtime(path)
    try:
        _seed(runtime, "seed", 4)
        orchestrator = runtime._retrieval_orchestrator_cached()
        first = orchestrator.decide("compilers", budget=20, mode="mix")

        _ingest_from_another_thread(path, "late", 4)

        second = orchestrator.decide("compilers", budget=20, mode="mix")
        assert second.candidate_set_sha256 != first.candidate_set_sha256

        returned = {
            candidate.record.id
            for candidate in (*second.selected, *second.rejected)
        }
        assert any("late" in record_id for record_id in returned), (
            "a request opened after the commit still could not see it"
        )
    finally:
        runtime.close()


def test_repeated_quiet_requests_are_bit_identical(tmp_path) -> None:
    """Holding a snapshot must not perturb the digest across runs."""

    path = tmp_path / "stable.db"
    runtime = _runtime(path)
    try:
        _seed(runtime, "seed", 8)
        orchestrator = runtime._retrieval_orchestrator_cached()
        digests = {
            orchestrator.decide("compilers", budget=5, mode="mix").candidate_set_sha256
            for _ in range(4)
        }
        assert len(digests) == 1, digests
    finally:
        runtime.close()


def test_sql_truncation_ties_ignore_mutable_update_timestamps(tmp_path) -> None:
    """Metadata-only rewrites cannot change equal-score candidate membership."""

    path = tmp_path / "sql-tiebreak.db"
    runtime = _runtime(path)
    try:
        records = [_record(f"clm:{suffix}") for suffix in ("a", "b", "c", "z")]
        runtime.persist_ir(IRBatch(records))
        plan = RetrievalPlan(
            query="compilers",
            normalized_query="compilers",
            intent=QueryIntent.HYBRID,
            filters=QueryFilters(namespace="work", scope="thread"),
            legs=[],
        )
        adapter = SQLiteIRAdapter(runtime.store)
        before = [hit.record.id for hit in adapter.search(plan, limit=2)]

        rewritten = _record("clm:z")
        rewritten.updated_at = "2999-01-01T00:00:00+00:00"
        runtime.persist_ir(IRBatch([rewritten]))
        after = [hit.record.id for hit in adapter.search(plan, limit=2)]

        assert before == ["clm:a", "clm:b"]
        assert after == before
    finally:
        runtime.close()
