from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .agent_memory import (
    IngestReport,
    compact_memory_index,
    full_memory_records,
    namespace_ingest_batch,
    neighbor_timeline,
    source_hash,
    stable_document_id,
)
from .benchmarks import diff_benchmark_runs, evaluate_benchmark_gate, run_benchmark_suite, verify_benchmark_bundle
from .context_assembly import ContextCandidate, ContextPack, assemble_context
from .dsl import compile_dsl
from .evals import run_retrieval_benchmark
from .lifecycle import BatchIngestItem
from .mirl import (
    Artifact,
    IRBatch,
    MIRLRecord,
    Pack,
    PersistReport,
    ReconcileReport,
    RecordKind,
    SearchCandidate,
    SearchResult,
    Status,
    TraceGraph,
    VerifyReport,
)
from .models import EmbeddingModel, default_embedding_model
from .nl import compile_nl
from .pack import pack_record, pack_records
from .reconcile import reconcile_ir
from .storage import SQLiteStore
from .symbols import export_symbol_markdown, propose_symbols
from .transpile import transpile_python
from .vector import INDEXABLE_KINDS, VECTOR_TEXT_VERSION
from .vector_adapters import (
    PgVectorAdapter,
    SQLiteVectorAdapter,
    VectorAdapter,
)
from .verify import verify_ir

LOGGER = logging.getLogger(__name__)

_RUNTIME_PERSIST_LOCKS_GUARD = threading.Lock()
_RUNTIME_PERSIST_LOCKS: dict[str, "_RuntimePersistLock"] = {}
_PERSIST_LOCK_TIMEOUT_SECONDS = 60.0


class _RuntimePersistLock:
    """Reentrant in-process lock backed by one cross-process file lock."""

    def __init__(self, file_identity: str | None) -> None:
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._file_handle = None
        self._lock_path: Path | None = None
        if file_identity is not None:
            digest = hashlib.sha256(file_identity.encode("utf-8")).hexdigest()
            store_path = Path(file_identity)
            self._lock_path = (
                store_path.parent / f".seam-runtime-{digest[:16]}.lock"
            )

    def __enter__(self) -> "_RuntimePersistLock":
        self._thread_lock.acquire()
        try:
            if self._depth == 0:
                self._acquire_process_lock()
            self._depth += 1
            return self
        except Exception:
            self._thread_lock.release()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        try:
            self._depth -= 1
            if self._depth == 0:
                self._release_process_lock()
        finally:
            self._thread_lock.release()

    def _acquire_process_lock(self) -> None:
        if self._lock_path is None:
            return
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+b")
        deadline = time.monotonic() + _PERSIST_LOCK_TIMEOUT_SECONDS
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "timed out acquiring the runtime persistence lock"
                            ) from None
                        time.sleep(0.05)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(
                            handle.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "timed out acquiring the runtime persistence lock"
                            ) from None
                        time.sleep(0.05)
        except Exception:
            handle.close()
            raise
        self._file_handle = handle

    def _release_process_lock(self) -> None:
        handle = self._file_handle
        self._file_handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _runtime_persist_lock(
    store_path: str | Path,
    *,
    memory_identity: int,
) -> _RuntimePersistLock:
    """Share one write+projection critical section per local canonical store."""

    raw_path = str(store_path)
    key = (
        f":memory:{memory_identity}"
        if raw_path == ":memory:"
        else str(Path(raw_path).expanduser().resolve())
    )
    with _RUNTIME_PERSIST_LOCKS_GUARD:
        lock = _RUNTIME_PERSIST_LOCKS.get(key)
        if lock is None:
            lock = _RuntimePersistLock(None if raw_path == ":memory:" else key)
            _RUNTIME_PERSIST_LOCKS[key] = lock
        return lock


class SeamRuntime:
    def __init__(
        self,
        store_path: str | Path = "seam.db",
        embedding_model: EmbeddingModel | None = None,
        vector_adapter: VectorAdapter | None = None,
        pgvector_dsn: str | None = None,
        pgvector_table: str | None = None,
        allow_pgvector_env: bool = True,
    ) -> None:
        self.store = SQLiteStore(store_path)
        self._persist_projection_lock = _runtime_persist_lock(
            self.store.path,
            memory_identity=id(self.store),
        )
        self.embedding_model = embedding_model or default_embedding_model()
        resolved_dsn = pgvector_dsn or (
            os.environ.get("SEAM_PGVECTOR_DSN")
            if allow_pgvector_env
            else None
        )
        resolved_table = pgvector_table or os.environ.get("SEAM_PGVECTOR_TABLE") or "seam_vector_index"
        if vector_adapter is not None:
            self.vector_adapter = vector_adapter
        elif resolved_dsn:
            self.vector_adapter = PgVectorAdapter(resolved_dsn, self.embedding_model, table_name=resolved_table)
        else:
            self.vector_adapter = SQLiteVectorAdapter(self.store.path, self.embedding_model)
        self._derived_delete_hooks: list[
            Callable[[list[str]], None]
        ] = []
        # Retrieval flags are resolved once per runtime (defaults < persisted
        # applied-state < env) and cached so scoring stays stable for the life
        # of the process; an `improvement apply` mid-run does not change results
        # under a live runtime, which keeps a benchmark run reproducible. A new
        # runtime (the benchmark path opens one per run) picks up applied state.
        self._retrieval_flags = None
        self._retrieval_orchestrator = None
        # Converge any derived indexing a previous process committed but never
        # completed. Normally a single indexed lookup against an empty table:
        # the steady state is that nothing is owed.
        self.replay_vector_outbox()

    def close(self) -> None:
        """Close the underlying SQLite store connection pool.

        Transient runtimes opened against a temp database must be closed before
        that database is deleted; on Windows an open SQLite handle locks the file
        and tempdir cleanup fails with ``PermissionError``/WinError 32. Idempotent.
        The vector adapters open connections per-operation (``with closing(...)``)
        so they hold no handle at rest; only the store pool needs closing.
        """
        store = getattr(self, "store", None)
        close = getattr(store, "close", None)
        if callable(close):
            close()

    def check_ready(self) -> None:
        """Raise when either persistence layer cannot serve a trivial read."""
        self.store.check_ready()
        vector_check = getattr(self.vector_adapter, "check_ready", None)
        if callable(vector_check):
            vector_check()

    def register_derived_delete_hook(
        self, hook: Callable[[list[str]], None]
    ) -> None:
        """Register one configured derived index for lifecycle cleanup."""

        if not callable(hook):
            raise TypeError("derived delete hook must be callable")
        if hook not in self._derived_delete_hooks:
            self._derived_delete_hooks.append(hook)

    def _delete_derived_records(self, record_ids: tuple[str, ...]) -> None:
        ids = list(record_ids)
        if not isinstance(self.vector_adapter, SQLiteVectorAdapter):
            vector_delete = getattr(self.vector_adapter, "delete_records", None)
            if not callable(vector_delete):
                raise RuntimeError(
                    "configured vector adapter cannot delete derived records"
                )
            vector_delete(ids)
        for hook in tuple(self._derived_delete_hooks):
            hook(ids)

    def __enter__(self) -> "SeamRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _resolve_agent_id(agent_id: str | None) -> str | None:
        resolved = (agent_id or os.environ.get("SEAM_AGENT") or "").strip()
        return resolved or None

    def compile_nl(
        self,
        raw_text: str,
        source_ref: str = "local://input",
        ns: str = "local.default",
        scope: str = "thread",
        agent_id: str | None = None,
        *,
        extractor=None,
        speaker: str | None = None,
        source_timestamp: str | None = None,
        derived_fact_policy: str | None = None,
        allow_env_extractor: bool = True,
        id_salt: str | None = None,
    ) -> IRBatch:
        batch = compile_nl(
            raw_text,
            source_ref=source_ref,
            ns=ns,
            scope=scope,
            extractor=extractor,
            speaker=speaker,
            source_timestamp=source_timestamp,
            derived_fact_policy=derived_fact_policy,
            allow_env_extractor=allow_env_extractor,
            id_salt=id_salt,
        )
        resolved_agent = self._resolve_agent_id(agent_id)
        if resolved_agent:
            for record in batch.records:
                record.ext["agent_id"] = resolved_agent
                if record.kind == RecordKind.PROV:
                    compiler_agent = record.attrs.get("agent")
                    if compiler_agent and compiler_agent != resolved_agent:
                        record.ext["compiler_agent"] = compiler_agent
                    record.attrs["agent"] = resolved_agent
        return batch

    def compile_dsl(self, dsl_text: str, ns: str = "local.default", scope: str = "project") -> IRBatch:
        return compile_dsl(dsl_text, ns=ns, scope=scope)

    def ingest_text(
        self,
        text: str,
        source_ref: str = "local://input",
        ns: str = "local.default",
        scope: str = "thread",
        persist: bool = True,
        agent_id: str | None = None,
    ) -> IngestReport:
        resolved_agent = self._resolve_agent_id(agent_id)
        document_id = stable_document_id(source_ref, text)
        batch = namespace_ingest_batch(
            self.compile_nl(text, source_ref=source_ref, ns=ns, scope=scope, agent_id=resolved_agent),
            document_id,
        )
        stored_ids: list[str] = []
        if persist:
            stored_ids = self.persist_ir(batch).stored_ids
            # Mark previous versions of this source as superseded.
            self.store.mark_document_superseded_by_source_ref(source_ref, except_document_id=document_id)
        document = self.store.upsert_document_status(
            document_id=document_id,
            ns=ns,
            scope=scope,
            source_ref=source_ref,
            source_hash=source_hash(text),
            byte_count=len(text.encode("utf-8")),
            chunk_count=max(1, len(batch.kind(RecordKind.SPAN))),
            extraction_status="compiled",
            indexed_status="indexed" if persist else "not_indexed",
            metadata={
                "record_count": len(batch.records),
                "indexable_count": len([record for record in batch.records if record.kind in {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL}]),
                "agent_id": resolved_agent,
            },
        )
        return IngestReport(document=document, stored_ids=stored_ids)

    def verify_ir(self, ir_batch: IRBatch) -> VerifyReport:
        batch_ids = {record.id for record in ir_batch.records}
        candidate_ids = sorted(
            {
                reference_id
                for record in ir_batch.records
                for reference_id in (
                    *record.prov,
                    *record.evidence,
                    *(
                        record.attrs.get("refs", [])
                        if record.kind is RecordKind.PACK
                        and record.attrs.get("mode") == "exact"
                        and isinstance(record.attrs.get("refs"), list)
                        else []
                    ),
                )
                if isinstance(reference_id, str) and reference_id not in batch_ids
            }
        )
        known_record_kinds: dict[str, RecordKind] = {}
        known_records: dict[str, MIRLRecord] = {}
        for offset in range(0, len(candidate_ids), 500):
            chunk = candidate_ids[offset : offset + 500]
            loaded = self.store.load_ir(ids=chunk).records
            known_records.update({record.id: record for record in loaded})
            known_record_kinds.update(
                {record.id: record.kind for record in loaded}
            )
        return verify_ir(
            ir_batch,
            known_record_kinds=known_record_kinds,
            known_records=known_records,
        )

    def normalize_ir(self, ir_batch: IRBatch) -> IRBatch:
        return IRBatch(sorted(ir_batch.records, key=lambda record: record.id))

    def persist_ir(
        self,
        ir_batch: IRBatch,
        *,
        reject_existing_ids: bool = False,
    ) -> PersistReport:
        """Persist one write and its vector compensation as one runtime section.

        SQLite protects each canonical transaction, while a configured vector
        adapter may commit after it. Serializing the complete write/index/
        compensate sequence per local store prevents a failed writer from
        restoring over a later successful writer in the same process.
        """

        with self._persist_projection_lock:
            return self._persist_ir_locked(
                ir_batch,
                reject_existing_ids=reject_existing_ids,
            )

    def _persist_ir_locked(
        self,
        ir_batch: IRBatch,
        *,
        reject_existing_ids: bool = False,
    ) -> PersistReport:
        """Validate and persist MIRL, then refresh vector and node projections.

        This is a strict write path: invalid MIRL raises before storage, and
        every successful call indexes indexable records and projects graph-node
        vectors. Read-only callers must not use it as a permissive parser.
        """

        report = self.verify_ir(ir_batch)
        if not report.valid:
            raise ValueError(json.dumps(report.to_dict(), indent=2))
        normalized = self.normalize_ir(ir_batch)
        touched_ids = [record.id for record in normalized.records]
        previous = self.store.load_ir(ids=touched_ids) if touched_ids else IRBatch([])
        previous_vector_rows = self.store.snapshot_vector_rows(touched_ids)
        previous_public_memory_handle_rows = (
            self.store.snapshot_public_memory_handle_rows(touched_ids)
        )
        persist_report = self.store.persist_ir(
            normalized,
            _preserve_node_vectors=True,
            # The intent to index commits with the records themselves, so a
            # crash before indexing leaves durable evidence that it is owed.
            _enqueue_vector_outbox=True,
            _reject_existing_ids=reject_existing_ids,
        )
        persisted = self.store.load_ir(ids=persist_report.stored_ids)
        vector_error_type: str | None = None
        canonical_restore_error_type: str | None = None
        adapter_restore_error_type: str | None = None
        try:
            # Index the canonical payloads that actually committed. Entity
            # reconciliation may omit an incoming duplicate and remap the
            # references on surviving records, so the caller's batch is not a
            # reliable description of the durable projection boundary.
            self.vector_adapter.index_records(persisted.records)
        except Exception as exc:
            vector_error_type = type(exc).__name__
            try:
                self.store.restore_ir_after_failed_projection(
                    previous,
                    touched_ids,
                    previous_vector_rows=previous_vector_rows,
                    previous_public_memory_handle_rows=(
                        previous_public_memory_handle_rows
                    ),
                )
            except Exception as rollback_exc:
                canonical_restore_error_type = type(rollback_exc).__name__
            if (
                canonical_restore_error_type is None
                and not bool(
                    getattr(self.vector_adapter, "index_records_atomic", False)
                )
            ):
                try:
                    self._restore_external_vector_projection(previous, touched_ids)
                except Exception as rollback_exc:
                    adapter_restore_error_type = type(rollback_exc).__name__
            if (
                canonical_restore_error_type is None
                and adapter_restore_error_type is None
            ):
                # Restore succeeded, so canonical and derived state are both
                # back to what they were and nothing is owed. Retiring the
                # intents here is what keeps a failed write an exact no-op
                # rather than something that accumulates permanent queue rows.
                self._acknowledge_vector_outbox(persist_report)
            else:
                # Restore did not complete. The intents are the durable record
                # that this slice may be unindexed, so they stay pending and
                # replay reconciles them on the next reopen.
                self._note_vector_outbox_failure(persist_report, vector_error_type)
        if canonical_restore_error_type is not None:
            LOGGER.error(
                "Vector indexing failed and canonical restore failed "
                "(record_count=%d, vector_error_type=%s, "
                "restore_error_type=%s)",
                len(touched_ids),
                vector_error_type,
                canonical_restore_error_type,
            )
            raise RuntimeError(
                "Vector indexing failed and canonical restore failed; "
                "manual recovery may be required"
            )
        if adapter_restore_error_type is not None:
            LOGGER.error(
                "Vector indexing failed and external vector restore failed "
                "(record_count=%d, vector_error_type=%s, "
                "restore_error_type=%s)",
                len(touched_ids),
                vector_error_type,
                adapter_restore_error_type,
            )
            raise RuntimeError(
                "Vector indexing failed and external vector restore failed; "
                "manual recovery may be required"
            )
        if vector_error_type is not None:
            LOGGER.warning(
                "Vector indexing failed; canonical and vector writes restored "
                "(record_count=%d, vector_error_type=%s)",
                len(touched_ids),
                vector_error_type,
            )
            raise RuntimeError(
                "Vector indexing failed; canonical and vector writes were restored"
            )
        # The derived index is durably updated, so the intents are settled.
        # Acknowledging only here -- never on the failure paths above -- is what
        # makes an unacknowledged intent mean exactly "this may be unindexed".
        self._acknowledge_vector_outbox(persist_report)
        self.project_node_vectors()
        return persist_report

    def _acknowledge_vector_outbox(self, persist_report: PersistReport) -> None:
        entry_ids = list(getattr(persist_report, "outbox_entry_ids", ()) or ())
        if not entry_ids:
            return
        try:
            self.store.acknowledge_vector_outbox(entry_ids)
        except Exception:
            # A failed acknowledgement is safe: the intent stays pending and
            # replay re-indexes idempotently. Failing the write here would
            # instead report a successful, durable persist as an error.
            LOGGER.warning(
                "Could not acknowledge vector outbox intents (count=%d)",
                len(entry_ids),
                exc_info=True,
            )

    def _note_vector_outbox_failure(
        self, persist_report: PersistReport, error_type: str
    ) -> None:
        entry_ids = list(getattr(persist_report, "outbox_entry_ids", ()) or ())
        if not entry_ids:
            return
        try:
            self.store.record_vector_outbox_failure(entry_ids, error_type=error_type)
        except Exception:
            LOGGER.warning(
                "Could not record vector outbox failure (count=%d)",
                len(entry_ids),
                exc_info=True,
            )

    def replay_vector_outbox(self, *, batch_size: int = 200) -> dict[str, int]:
        """Re-apply vector index intents that were never acknowledged.

        Called on reopen so that a process that died between the canonical
        commit and the derived index converges. Re-indexing is a content-hash
        no-op when the backend already has the record, so replaying an intent
        whose work in fact completed costs nothing and changes nothing --
        which is what makes duplicate replay harmless.

        Returns a count summary; it never raises, because a vector backend that
        is still unreachable must not make the runtime unconstructible. The
        intents simply stay pending for the next attempt.
        """

        summary = {"pending": 0, "reindexed": 0, "acknowledged": 0, "failed": 0}
        try:
            entries = self.store.pending_vector_outbox()
        except Exception:
            LOGGER.warning("Could not read the vector outbox", exc_info=True)
            return summary
        if not entries:
            return summary
        summary["pending"] = len(entries)

        for start in range(0, len(entries), max(1, int(batch_size))):
            chunk = entries[start : start + max(1, int(batch_size))]
            entry_ids = [int(entry["entry_id"]) for entry in chunk]
            record_ids = sorted({str(entry["record_id"]) for entry in chunk})
            try:
                batch = self.store.load_ir(ids=record_ids)
                # Records the intent named but canonical no longer holds were
                # rolled back or deleted after the intent was written. There is
                # nothing to index, so the intent is settled rather than stuck.
                live_records = [
                    record
                    for record in batch.records
                    if record.status is not Status.DELETED_SOFT
                ]
                if live_records:
                    self.vector_adapter.index_records(live_records)
                    summary["reindexed"] += len(live_records)
                self.store.acknowledge_vector_outbox(entry_ids)
                summary["acknowledged"] += len(entry_ids)
            except Exception as exc:
                summary["failed"] += len(entry_ids)
                LOGGER.warning(
                    "Vector outbox replay failed (count=%d, error_type=%s)",
                    len(entry_ids),
                    type(exc).__name__,
                )
                try:
                    self.store.record_vector_outbox_failure(
                        entry_ids, error_type=type(exc).__name__
                    )
                except Exception:  # pragma: no cover - bookkeeping only
                    LOGGER.warning(
                        "Could not record vector outbox failure", exc_info=True
                    )
        return summary

    def _restore_external_vector_projection(
        self,
        previous: IRBatch,
        touched_ids: list[str],
    ) -> None:
        """Compensate a partially applied non-SQLite vector write.

        External adapters do not share SQLite's transaction. Their common
        protocol does, however, provide delete plus canonical reindex. Clear
        the complete touched slice first, then rebuild only the records that
        existed before the failed write. If either operation fails, the caller
        reports an explicit manual-recovery boundary without exposing IDs.
        S5's durable outbox remains the crash-recovery solution across process
        loss; this closes same-process partial adapter mutation.
        """

        ordered_ids = sorted(set(touched_ids))
        if not ordered_ids:
            return
        self.vector_adapter.delete_records(ordered_ids)
        if previous.records:
            self.vector_adapter.index_records(previous.records)

    @staticmethod
    def _semantic_seed_env(name: str, *, default: float) -> float:
        """Read a numeric seeding knob, treating an unusable value as unset.

        A malformed knob must not take a graph query down; falling back to the
        default keeps retrieval available and leaves the misconfiguration visible
        in the returned seed count.
        """
        raw = str(os.environ.get(name) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            LOGGER.warning("%s is not numeric (%r); using %s", name, raw, default)
            return default

    def knowledge_graph(
        self,
        *,
        query: str | None = None,
        semantic_seeds: int | None = None,
        min_seed_score: float | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        """Query the knowledge graph with lexical *and* semantic node seeding.

        Lexical seeding structurally cannot reach a node whose label shares no
        tokens with the query, which is the paraphrase failure expressed in graph
        form. Embedding the query here — rather than inside ``knowledge_graph`` —
        keeps the graph layer provider-free and deterministic under test.

        DEFAULT OFF, pending measurement. On a weak embedder every node scores
        near-identically, so a permissive floor turns semantic seeding into noise
        injection that can cost precision instead of buying recall. Enable with
        ``SEAM_GRAPH_SEMANTIC_SEEDS`` (count) and tune ``SEAM_GRAPH_SEMANTIC_MIN_SCORE``
        so an A/B measures the lever rather than the default.

        Seeding failures degrade to lexical-only rather than failing the query: a
        semantic seed is an additional way in, never a precondition.
        """
        flags = self._retrieval_flags_cached()
        if semantic_seeds is None:
            semantic_seeds = int(flags.graph_semantic_seeds)
        if min_seed_score is None:
            min_seed_score = float(flags.graph_semantic_min_score)
        seed_ids: list[str] = []
        text = (query or "").strip()
        if text and semantic_seeds > 0:
            model = self.embedding_model
            model_name = getattr(model, "name", "") or model.__class__.__name__
            try:
                ranked = self.store.search_node_vectors(
                    model.embed(text),
                    model_name,
                    ns=kwargs.get("namespace"),  # type: ignore[arg-type]
                    scope=kwargs.get("scope"),  # type: ignore[arg-type]
                    limit=semantic_seeds,
                    min_score=min_seed_score,
                )
                seed_ids = [node_id for node_id, _ in ranked]
            except Exception:
                LOGGER.exception("Semantic node seeding failed; falling back to lexical seeds")
        return self.store.knowledge_graph(query=query, semantic_seed_ids=seed_ids, **kwargs)

    def rebuild_graph_products(
        self,
        *,
        namespace: str,
        scope: str,
        max_facts: int = 10_000,
        min_observation_episodes: int = 2,
        max_sentences_per_product: int = 64,
    ) -> dict[str, object]:
        """Derive a new G4 snapshot from current, trust-gated graph facts."""

        with self._persist_projection_lock:
            return self.store.rebuild_graph_products(
                namespace=namespace,
                scope=scope,
                max_facts=max_facts,
                min_observation_episodes=min_observation_episodes,
                max_sentences_per_product=max_sentences_per_product,
            )

    def graph_products(
        self,
        *,
        namespace: str,
        scope: str,
        kinds: list[str] | None = None,
        subject_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Read the latest complete G4 snapshot for one tenant boundary."""

        return self.store.graph_products(
            namespace=namespace,
            scope=scope,
            kinds=kinds,
            subject_id=subject_id,
            limit=limit,
        )

    def graph_product_history(
        self,
        *,
        namespace: str,
        scope: str,
        stable_key: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Read immutable content versions for one derived graph product."""

        return self.store.graph_product_history(
            namespace=namespace,
            scope=scope,
            stable_key=stable_key,
            limit=limit,
        )

    def assemble_context(
        self,
        *,
        task: str,
        namespace: str,
        scope: str,
        as_of: str,
        token_budget: int,
        fact_reserve_tokens: int = 0,
        max_candidates: int = 10_000,
        candidates: list[ContextCandidate] | None = None,
    ) -> ContextPack:
        """Assemble a deterministic, exact-backtrace G5 context PACK."""

        resolved = (
            candidates
            if candidates is not None
            else self.store.context_candidates(
                namespace=namespace,
                scope=scope,
                max_candidates=max_candidates,
            )
        )
        return assemble_context(
            resolved,
            task=task,
            namespace=namespace,
            scope=scope,
            as_of=as_of,
            token_budget=token_budget,
            fact_reserve_tokens=fact_reserve_tokens,
        )

    def plan_scoped_delete(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        record_ids: list[str],
        idempotency_key: str,
        actor: str,
        idempotency_context: str | None = None,
        record_generations: dict[str, str] | None = None,
    ) -> dict[str, object]:
        with self._persist_projection_lock:
            return self.store.plan_scoped_delete(
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                record_ids=record_ids,
                idempotency_key=idempotency_key,
                actor=actor,
                idempotency_context=idempotency_context,
                record_generations=record_generations,
            )

    def register_public_memory_handles(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        handles: dict[str, tuple[str, str]],
    ) -> None:
        """Serialize recall capability publication with write compensation."""

        with self._persist_projection_lock:
            self.store.register_public_memory_handles(
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                handles=handles,
            )

    def apply_scoped_delete(
        self,
        *,
        tenant_id: str,
        operation_id: str,
        actor: str,
        interrupt_after_intent: bool = False,
        require_current_incarnation: bool = False,
    ) -> dict[str, object]:
        with self._persist_projection_lock:
            return self.store.apply_scoped_delete(
                tenant_id=tenant_id,
                operation_id=operation_id,
                actor=actor,
                interrupt_after_intent=interrupt_after_intent,
                delete_derived_records=self._delete_derived_records,
                require_current_incarnation=require_current_incarnation,
            )

    def batch_ingest(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        items: list[BatchIngestItem],
        idempotency_key: str,
        actor: str,
        interrupt_after_items: int | None = None,
    ) -> dict[str, object]:
        operation = self.store.plan_batch_ingest(
            tenant_id=tenant_id,
            namespace=namespace,
            scope=scope,
            items=items,
            idempotency_key=idempotency_key,
            actor=actor,
        )
        return self._apply_batch_ingest(
            str(operation["operation_id"]),
            tenant_id=tenant_id,
            actor=actor,
            interrupt_after_items=interrupt_after_items,
        )

    def resume_lifecycle_operation(
        self, operation_id: str, *, tenant_id: str, actor: str
    ) -> dict[str, object]:
        operation = self.store.lifecycle_operation(
            tenant_id=tenant_id, operation_id=operation_id
        )
        if operation["kind"] == "scoped_delete":
            return self.apply_scoped_delete(
                tenant_id=tenant_id,
                operation_id=operation_id,
                actor=actor,
            )
        if operation["kind"] == "batch_ingest":
            return self._apply_batch_ingest(
                operation_id, tenant_id=tenant_id, actor=actor
            )
        raise ValueError("unknown lifecycle operation kind")

    def _apply_batch_ingest(
        self,
        operation_id: str,
        *,
        tenant_id: str,
        actor: str,
        interrupt_after_items: int | None = None,
    ) -> dict[str, object]:
        operation = self.store.begin_batch_ingest(
            tenant_id=tenant_id, operation_id=operation_id, actor=actor
        )
        if operation["state"] == "applied":
            return operation
        completed = set(
            self.store.completed_batch_indexes(
                tenant_id=tenant_id, operation_id=operation_id
            )
        )
        applied_this_call = 0
        items = self.store.lifecycle_batch_items(
            tenant_id=tenant_id, operation_id=operation_id
        )
        for index, item in enumerate(items):
            if index in completed:
                continue
            report = self.ingest_text(
                item.text,
                source_ref=item.source_ref,
                ns=str(operation["namespace"]),
                scope=str(operation["scope"]),
                agent_id=actor,
            )
            self.store.record_batch_item(
                tenant_id=tenant_id,
                operation_id=operation_id,
                item_index=index,
                stored_ids=report.stored_ids,
                actor=actor,
            )
            applied_this_call += 1
            if (
                interrupt_after_items is not None
                and applied_this_call >= interrupt_after_items
            ):
                return self.store.lifecycle_operation(
                    tenant_id=tenant_id, operation_id=operation_id
                )
        return self.store.complete_batch_ingest(
            tenant_id=tenant_id, operation_id=operation_id, actor=actor
        )

    def apply_reasoning_promotion(
        self, *, proposal_id: str, applied_by: str
    ) -> dict[str, object]:
        """Explicitly persist one reviewed R5 assertion; never auto-applied."""

        with self._persist_projection_lock:
            result = self.store.apply_reasoning_promotion(
                proposal_id=proposal_id, applied_by=applied_by
            )
            record = MIRLRecord.from_dict(result["record"])  # type: ignore[arg-type]
            try:
                self.vector_adapter.index_records([record])
                vector_indexed = True
            except Exception:
                # Canonical MIRL + application audit committed atomically before
                # this derived external index. Do not erase reviewed truth merely
                # because a rebuildable vector backend is temporarily unavailable.
                LOGGER.exception(
                    "Applied reasoning promotion but vector indexing is pending"
                )
                vector_indexed = False
            self.project_node_vectors()
            return {**result, "vector_indexed": vector_indexed}

    def reverse_reasoning_promotion(
        self, *, proposal_id: str, reversed_by: str, reason: str
    ) -> dict[str, object]:
        """Audit reversal and append a canonical supersession relation."""

        with self._persist_projection_lock:
            result = self.store.reverse_reasoning_promotion(
                proposal_id=proposal_id,
                reversed_by=reversed_by,
                reason=reason,
            )
            record = MIRLRecord.from_dict(  # type: ignore[arg-type]
                result["superseding_record"]
            )
            try:
                self.vector_adapter.index_records([record])
                vector_indexed = True
            except Exception:
                LOGGER.exception(
                    "Reversed reasoning promotion but vector indexing is pending"
                )
                vector_indexed = False
            self.project_node_vectors()
            return {**result, "vector_indexed": vector_indexed}

    def project_node_vectors(self, *, limit: int | None = None) -> dict[str, object]:
        with self._persist_projection_lock:
            return self._project_node_vectors_locked(limit=limit)

    def _project_node_vectors_locked(
        self, *, limit: int | None = None
    ) -> dict[str, object]:
        """Embed graph nodes whose derived vector is missing, stale, or legacy.

        This runs after record indexing rather than inside it because a node
        vector is a *derived* projection: losing one costs a later recompute, not
        correctness. So a failure here deliberately does NOT roll back a good
        ingest. The affected nodes simply stay pending and are picked up by the
        next ingest or an explicit reindex, which makes the projection
        self-healing instead of turning a transient embedding error into data loss.
        """
        model = self.embedding_model
        model_name = getattr(model, "name", "") or model.__class__.__name__
        try:
            pending = self.store.pending_node_vectors(model_name, limit=limit)
            if not pending:
                self.store.cleanup_orphan_node_vectors()
                return {"model_name": model_name, "embedded": 0, "failed": 0}
            # The same node text under a different ns/scope is the same point in
            # vector space, so a boundary-only move must reuse the stored vector
            # rather than pay to embed it again. Read reusable hashes before
            # orphan cleanup because a boundary move can replace a synthetic
            # node id while preserving its exact semantic text.
            reusable = self.store.reusable_node_vectors(
                model_name, [str(entry["source_hash"]) for entry in pending]
            )
            self.store.cleanup_orphan_node_vectors()
            embedded: list[dict[str, object]] = []
            failed = 0
            for entry in pending:
                vector = reusable.get(str(entry["source_hash"]))
                if vector is None:
                    try:
                        vector = model.embed(str(entry["source_text"]))
                    except Exception:
                        # One unembeddable node must not strand the rest of the batch.
                        failed += 1
                        continue
                embedded.append({**entry, "vector": vector})
            written = self.store.store_node_vectors(model_name, embedded)
        except Exception:
            LOGGER.exception("Graph node vector projection failed; nodes remain pending")
            return {"model_name": model_name, "embedded": 0, "failed": 0, "error": True}
        return {"model_name": model_name, "embedded": written, "failed": failed}

    def refresh_retrieval_flags(self):
        """Drop the cached flags and re-resolve them from store plus env.

        The cache below is deliberately process-lifetime, so a long-lived
        surface (REST, MCP, TUI) does NOT observe an applied-state change made
        after it started. That is a stability guarantee, not an oversight:
        scoring must not shift underneath an in-flight session. This method is
        the explicit, auditable way to adopt new applied state -- call it after
        `upsert_retrieval_flag_state`/`replace_retrieval_flag_state` when the
        running process should pick the change up.
        """

        self._retrieval_flags = None
        return self._retrieval_flags_cached()

    def _retrieval_flags_cached(self):
        """Resolve effective retrieval flags once and cache for this runtime.

        Layers defaults < persisted applied-state < env (see
        ``load_retrieval_flags``); caching keeps scoring stable across queries
        for the process lifetime. Use `refresh_retrieval_flags()` to adopt
        applied-state changes explicitly.
        """
        flags = getattr(self, "_retrieval_flags", None)
        if flags is None:
            from .retrieval import load_retrieval_flags

            flags = load_retrieval_flags(self.store)
            self._retrieval_flags = flags
        return flags

    def _retrieval_orchestrator_cached(self):
        """Return the one canonical retrieval engine for this runtime."""

        orchestrator = self._retrieval_orchestrator
        if orchestrator is None:
            from .retrieval_orchestrator import RetrievalOrchestrator

            orchestrator = RetrievalOrchestrator(self)
            self._retrieval_orchestrator = orchestrator
        return orchestrator

    def retrieve(
        self,
        query: str,
        lens: str = "general",
        scope: str | None = None,
        budget: int = 5,
        include_raw: bool = False,
        temporal_window=None,
        temporal_reference=None,
        ns: str | None = None,
        flags=None,
        *,
        mode: str = "mix",
        graph_hops: int = 1,
        semantic_graph_seeding: bool | None = None,
        graph_at: str | None = None,
        graph_include_history: bool = False,
        include_trace: bool = False,
        ranking_policy: str = "reciprocal-rank-fusion/2",
    ):
        """Search through SEAM's canonical SQL/vector/graph retrieval engine."""

        resolved_flags = flags if flags is not None else self._retrieval_flags_cached()
        if semantic_graph_seeding is None:
            semantic_graph_seeding = bool(resolved_flags.graph_semantic_seeds)
        return self._retrieval_orchestrator_cached().search(
            query=query,
            scope=scope,
            budget=budget,
            include_trace=include_trace,
            mode=mode,
            namespace=ns,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
            lens=lens,
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            flags=resolved_flags,
            ranking_policy=ranking_policy,
        )

    def search_ir(
        self,
        query: str,
        lens: str = "general",
        scope: str | None = None,
        budget: int = 5,
        include_raw: bool = False,
        temporal_window=None,
        temporal_reference=None,
        ns: str | None = None,
        flags=None,
        include_trace: bool = False,
        ranking_policy: str = "legacy-weighted/1",
    ) -> SearchResult:
        """Compatibility result shape over the canonical retrieval engine.

        ``search_ir`` remains as the longstanding local API, but it no longer
        executes a second scoring pipeline. Every runtime surface now receives
        candidates from ``RetrievalOrchestrator`` through ``retrieve``.

        ``ranking_policy`` is an explicit pass-through so this compatibility
        shape can no longer *silently* rank differently from ``retrieve()``.
        The default stays ``legacy-weighted/1`` deliberately: it is the
        versioned behavioral control that every recorded LoCoMo/mem0 arm was
        measured under, and promoting the surface default to
        ``reciprocal-rank-fusion/2`` is an S9-gated measurement change, not an
        S8 refactor. Given the same policy, this method returns exactly the
        ``retrieve()`` ranking, narrowed to the compatibility record kinds.
        """

        resolved_flags = flags if flags is not None else self._retrieval_flags_cached()
        result_budget = (
            int(resolved_flags.search_top_k)
            if resolved_flags.search_top_k
            else budget
        )
        compatibility_kinds = {
            RecordKind.CLM,
            RecordKind.STA,
            RecordKind.EVT,
            RecordKind.REL,
        }
        if include_raw:
            compatibility_kinds.add(RecordKind.RAW)
        result = self.retrieve(
            query=query,
            lens=lens,
            scope=scope,
            budget=max(1, result_budget),
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            ns=ns,
            flags=resolved_flags,
            mode="mix",
            ranking_policy=ranking_policy,
            include_trace=include_trace,
        )
        compatible_ranked = [
            candidate
            for candidate in result.candidates
            if candidate.record.kind in compatibility_kinds
        ][: max(1, result_budget)]
        evidence_ids = sorted(
            {
                evidence_id
                for candidate in compatible_ranked
                for evidence_id in candidate.record.evidence
            }
        )
        evidence_by_id = (
            self.store.load_ir(ids=evidence_ids, ns=ns, scope=scope).by_id()
            if evidence_ids
            else {}
        )
        candidates = [
            SearchCandidate(
                record=candidate.record,
                score=candidate.score,
                reasons=list(candidate.reasons),
                evidence=[
                    evidence_by_id[evidence_id]
                    for evidence_id in candidate.record.evidence
                    if evidence_id in evidence_by_id
                ],
            )
            for candidate in compatible_ranked
        ]
        return SearchResult(
            query=result.normalized_query or query,
            candidates=candidates,
            trace=result.trace,
        )

    def ingest_conversation_turn(
        self,
        text: str,
        source_ref: str = "local://input",
        ns: str = "local.default",
        scope: str = "thread",
        persist: bool = True,
        agent_id: str | None = None,
        *,
        extractor=None,
        speaker: str | None = None,
        source_timestamp: str | None = None,
        derived_fact_policy: str | None = None,
        allow_env_extractor: bool = True,
    ) -> IngestReport:
        # Unified compiler (HISTORY#311): conversation turns and plain memories
        # share one faithful pipeline. `ingest_conversation_turn` is kept as the
        # benchmark/agent entry point but delegates to compile_nl.
        resolved_agent = self._resolve_agent_id(agent_id)
        document_id = stable_document_id(source_ref, text)
        batch = namespace_ingest_batch(
            self.compile_nl(
                text,
                source_ref=source_ref,
                ns=ns,
                scope=scope,
                agent_id=resolved_agent,
                extractor=extractor,
                speaker=speaker,
                source_timestamp=source_timestamp,
                derived_fact_policy=derived_fact_policy,
                allow_env_extractor=allow_env_extractor,
            ),
            document_id,
        )
        stored_ids: list[str] = []
        if persist:
            stored_ids = self.persist_ir(batch).stored_ids
            self.store.mark_document_superseded_by_source_ref(
                source_ref, except_document_id=document_id
            )
        metadata: dict[str, object] = {
            "record_count": len(batch.records),
            "indexable_count": len([
                r for r in batch.records
                if r.kind in {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL, RecordKind.RAW}
            ]),
            "agent_id": resolved_agent,
        }
        if derived_fact_policy:
            rich_claims = [
                record
                for record in batch.records
                if record.kind == RecordKind.CLM
                and record.ext.get("derived_fact_policy") == derived_fact_policy
            ]
            metadata["derived_fact_policy"] = derived_fact_policy
            metadata["derived_fact_count"] = len(rich_claims)
            fingerprints = {
                str(record.ext.get("derived_fact_config_fingerprint"))
                for record in rich_claims
                if record.ext.get("derived_fact_config_fingerprint")
            }
            if len(fingerprints) == 1:
                metadata["derived_fact_config_fingerprint"] = fingerprints.pop()
        document = self.store.upsert_document_status(
            document_id=document_id,
            ns=ns,
            scope=scope,
            source_ref=source_ref,
            source_hash=source_hash(text),
            byte_count=len(text.encode("utf-8")),
            chunk_count=max(1, len(batch.kind(RecordKind.SPAN))),
            extraction_status="compiled",
            indexed_status="indexed" if persist else "not_indexed",
            metadata=metadata,
        )
        return IngestReport(document=document, stored_ids=stored_ids)

    def memory_search(self, query: str, scope: str | None = None, budget: int = 5) -> dict[str, object]:
        result = self.search_ir(query, scope=scope, budget=budget)
        scores = {candidate.record.id: candidate.score for candidate in result.candidates}
        return compact_memory_index([candidate.record for candidate in result.candidates], query=query, scores=scores)

    def memory_get(self, record_ids: list[str], include_timeline: bool = False) -> dict[str, object]:
        batch = self.store.load_ir(ids=record_ids)
        payload = full_memory_records(batch.records)
        if include_timeline:
            needed_ids = set(record_ids)
            for record in batch.records:
                needed_ids.update(record.prov)
                needed_ids.update(record.evidence)
                for key in ("src", "dst", "target", "raw_id", "subject"):
                    value = record.attrs.get(key)
                    if isinstance(value, str):
                        needed_ids.add(value)
                obj = record.attrs.get("object")
                if isinstance(obj, str):
                    needed_ids.add(obj)
            timeline_batch = self.store.load_ir(ids=list(needed_ids))
            payload["context"] = neighbor_timeline(timeline_batch, record_ids)
        return payload

    def pack_ir(
        self,
        record_ids: list[str] | None = None,
        lens: str = "general",
        budget: int | None = None,
        profile: str = "default",
        mode: str = "context",
        persist: bool = False,
    ) -> Pack:
        if persist:
            with self._persist_projection_lock:
                return self._pack_ir_locked(
                    record_ids=record_ids,
                    lens=lens,
                    budget=budget,
                    profile=profile,
                    mode=mode,
                    persist=True,
                )
        return self._pack_ir_locked(
            record_ids=record_ids,
            lens=lens,
            budget=budget,
            profile=profile,
            mode=mode,
            persist=False,
        )

    def _pack_ir_locked(
        self,
        *,
        record_ids: list[str] | None,
        lens: str,
        budget: int | None,
        profile: str,
        mode: str,
        persist: bool,
    ) -> Pack:
        # Honor the answerer-aware retrieval profile's context_budget when the
        # caller does not pass an explicit budget (None). No profile set ->
        # context_budget is None -> falls back to the prior 512 default, so
        # callers that relied on the default are byte-identical (no regression).
        if budget is None:
            cb = getattr(self._retrieval_flags_cached(), "context_budget", None)
            budget = cb if cb else 512
        batch = self.store.load_ir(ids=record_ids) if record_ids else self.store.load_ir()
        namespace = batch.records[0].ns if batch.records else None
        pack = pack_records(batch.records, lens=lens, budget=budget, mode=mode, profile=profile, namespace=namespace)
        pack_mirl = pack_record(pack, ns=batch.records[0].ns if batch.records else "local.default", scope=batch.records[0].scope if batch.records else "project")
        if mode == "exact":
            report = self.verify_ir(IRBatch(batch.records + [pack_mirl]))
            if not report.valid:
                raise ValueError(json.dumps(report.to_dict(), indent=2))
        if persist:
            self.persist_ir(IRBatch([pack_mirl]))
        return pack

    def decompile_ir(self, record_ids: list[str], mode: str = "expanded") -> str:
        batch = self.store.load_ir(ids=record_ids)
        claims = [record for record in batch.records if record.kind == RecordKind.CLM]
        states = [record for record in batch.records if record.kind == RecordKind.STA]
        if states:
            fields = states[0].attrs.get("fields", {})
            body = "; ".join(f"{key}={value}" for key, value in fields.items())
        elif claims:
            body = "; ".join(f"{record.attrs.get('subject')} {record.attrs.get('predicate')} {record.attrs.get('object')}" for record in claims)
        else:
            body = "No MIRL records available."
        return body if mode == "minimal" else f"MIRL summary: {body}"

    def trace(self, obj_id: str) -> TraceGraph:
        return self.store.trace(obj_id)

    def reconcile_ir(self, record_ids: list[str] | None = None) -> ReconcileReport:
        with self._persist_projection_lock:
            batch = (
                self.store.load_ir(ids=record_ids)
                if record_ids
                else self.store.load_ir()
            )
            report = reconcile_ir(batch)
            if report.added_records:
                self.persist_ir(IRBatch(report.added_records))
            return report

    def transpile_ir(self, record_ids: list[str], target: str = "python") -> Artifact:
        batch = self.store.load_ir(ids=record_ids)
        if target != "python":
            raise NotImplementedError(f"Unsupported target: {target}")
        return transpile_python(batch.records)

    def suggest_symbols(self, record_ids: list[str] | None = None) -> IRBatch:
        batch = self.store.load_ir(ids=record_ids) if record_ids else self.store.load_ir()
        return IRBatch(propose_symbols(batch))

    def promote_symbols(self, record_ids: list[str] | None = None, min_frequency: int = 2) -> PersistReport:
        with self._persist_projection_lock:
            batch = (
                self.store.load_ir(ids=record_ids)
                if record_ids
                else self.store.load_ir()
            )
            symbols = IRBatch(propose_symbols(batch, min_frequency=min_frequency))
            if not symbols.records:
                return PersistReport(stored_ids=[], store_path=self.store.path)
            return self.persist_ir(symbols)

    def export_symbols(self, namespace: str | None = None, output_path: str | Path | None = None) -> str:
        batch = self.store.load_ir(ns=namespace)
        markdown = export_symbol_markdown(batch.records, namespace=namespace)
        if output_path is not None:
            Path(output_path).write_text(markdown, encoding="utf-8")
        return markdown

    def run_retrieval_benchmark(self) -> dict[str, object]:
        return run_retrieval_benchmark(embedding_model=self.embedding_model)

    def run_benchmark_suite(
        self,
        suite: str = "all",
        tokenizer: str = "auto",
        min_token_savings: float = 0.30,
        persist: bool = False,
        include_machine_text: bool = False,
        bundle_path: str | Path | None = None,
        holdout: bool = False,
    ) -> dict[str, object]:
        return run_benchmark_suite(
            self,
            suite=suite,
            tokenizer=tokenizer,
            min_token_savings=min_token_savings,
            persist=persist,
            include_machine_text=include_machine_text,
            bundle_path=bundle_path,
            holdout=holdout,
        )

    def verify_benchmark_bundle(self, bundle: str | Path | dict[str, object]) -> dict[str, object]:
        return verify_benchmark_bundle(bundle)

    def diff_benchmark_runs(self, run_a: str | Path | dict[str, object], run_b: str | Path | dict[str, object]) -> dict[str, object]:
        return diff_benchmark_runs(run_a, run_b)

    def evaluate_benchmark_gate(
        self,
        bundle: str | Path | dict[str, object],
        baseline: str | Path | dict[str, object] | None = None,
        policy: str | Path | dict[str, object] | None = None,
    ) -> dict[str, object]:
        return evaluate_benchmark_gate(bundle, baseline=baseline, policy=policy)

    def read_benchmark_run(self, run_id: str) -> dict[str, object]:
        return self.store.read_benchmark_run(run_id)

    def list_benchmark_runs(self, limit: int = 10) -> list[dict[str, object]]:
        return self.store.list_benchmark_runs(limit=limit)

    def reindex_vectors(
        self,
        record_ids: list[str] | None = None,
        *,
        ns: str | None = None,
        scope: str | None = None,
        boundary_only: bool = False,
    ) -> dict[str, object]:
        # Loading canonical rows and publishing their derived vectors are one
        # projection critical section. Otherwise a manual reindex can observe a
        # transient write that is subsequently compensated and republish it.
        with self._persist_projection_lock:
            return self._reindex_vectors_locked(
                record_ids,
                ns=ns,
                scope=scope,
                boundary_only=boundary_only,
            )

    def _reindex_vectors_locked(
        self,
        record_ids: list[str] | None = None,
        *,
        ns: str | None = None,
        scope: str | None = None,
        boundary_only: bool = False,
    ) -> dict[str, object]:
        batch = (
            self.store.load_ir(ids=record_ids, ns=ns, scope=scope)
            if (record_ids or ns or scope)
            else self.store.load_ir()
        )
        syncer = None
        if boundary_only:
            syncer = getattr(self.vector_adapter, "sync_boundaries", None)
            if not callable(syncer):
                adapter_name = getattr(self.vector_adapter, "name", "unknown")
                raise NotImplementedError(
                    "Unsupported boundary-only reindex for vector adapter: "
                    f"{adapter_name}"
                )
        stale = []
        inspector = getattr(self.vector_adapter, "stale_records", None)
        if inspector is not None:
            stale = inspector(batch.records)
        if boundary_only:
            sync_result = syncer(batch.records)
            return {
                **sync_result,
                "mode": "boundary_only",
                "record_count": len(batch.records),
                "model": self.embedding_model.name,
                "adapter": getattr(self.vector_adapter, "name", "unknown"),
                "vector_text_version": VECTOR_TEXT_VERSION,
                "stale_before": stale,
            }
        self.vector_adapter.index_records(batch.records)
        return {
            "mode": "full",
            "indexed_ids": [record.id for record in batch.records],
            "model": self.embedding_model.name,
            "adapter": getattr(self.vector_adapter, "name", "unknown"),
            "vector_text_version": VECTOR_TEXT_VERSION,
            "stale_before": stale,
        }

    def verify_vector_divergence(
        self,
        *,
        ns: str | None = None,
        scope: str | None = None,
        vector_adapter: object | None = None,
    ) -> dict[str, object]:
        """Report how a vector backend disagrees with canonical truth.

        Divergence has exactly three shapes, and repair differs for each, so
        they are reported separately rather than as one count:

        ``missing``
            canonical records the backend has no vector for -- the shape a
            crash between commit and indexing produces.
        ``stale``
            vectors whose source text, render version, dimension, or boundary
            no longer matches the canonical record.
        ``orphan``
            vectors with no live canonical record behind them, which stay
            searchable and can surface deleted content.

        ``vector_adapter`` inspects a backend other than the configured one,
        which is how a deployment running SQLite-vector alongside Chroma
        audits both.
        """

        adapter = vector_adapter if vector_adapter is not None else self.vector_adapter
        batch = self.store.load_ir(ns=ns, scope=scope)
        selector = getattr(adapter, "indexable_records", None)
        expected = (
            selector(batch.records)
            if callable(selector)
            else [record for record in batch.records if record.kind in INDEXABLE_KINDS]
        )

        stale: list[dict[str, object]] = []
        missing: list[dict[str, object]] = []
        inspector = getattr(adapter, "stale_records", None)
        supports_stale = callable(inspector)
        if supports_stale:
            for issue in inspector(expected):
                if issue.get("reason") == "missing":
                    missing.append(issue)
                else:
                    stale.append(issue)

        orphans: list[dict[str, object]] = []
        orphan_inspector = getattr(adapter, "orphan_records", None)
        supports_orphan = callable(orphan_inspector)
        if supports_orphan:
            orphans = list(
                orphan_inspector(
                    {record.id for record in expected} if (ns or scope) else None,
                    namespace=ns,
                    scope=scope,
                )
            )

        return {
            "adapter": getattr(adapter, "name", type(adapter).__name__),
            "model": self.embedding_model.name,
            "vector_text_version": VECTOR_TEXT_VERSION,
            "expected_record_count": len(expected),
            "missing": missing,
            "stale": stale,
            "orphan": orphans,
            "diverged": bool(missing or stale or orphans),
            # An adapter that cannot answer one of these is reported as such
            # rather than silently contributing an empty list, so "no
            # divergence" never means "never looked".
            "checks": {
                "missing": supports_stale,
                "stale": supports_stale,
                "orphan": supports_orphan,
            },
        }

    def repair_vector_divergence(
        self,
        *,
        ns: str | None = None,
        scope: str | None = None,
        vector_adapter: object | None = None,
    ) -> dict[str, object]:
        """Detect divergence, repair every shape of it, and re-verify.

        Missing and stale records are re-indexed; orphans are deleted. The
        re-verification is part of the contract: a repair that reports success
        without re-measuring is how divergence silently persists.
        """

        with self._persist_projection_lock:
            adapter = (
                vector_adapter if vector_adapter is not None else self.vector_adapter
            )
            before = self.verify_vector_divergence(
                ns=ns, scope=scope, vector_adapter=adapter
            )

            reindexed_ids = sorted(
                {str(issue["record_id"]) for issue in before["missing"]}
                | {str(issue["record_id"]) for issue in before["stale"]}
            )
            if reindexed_ids:
                batch = self.store.load_ir(ids=reindexed_ids)
                indexer = getattr(adapter, "index_records", None)
                if callable(indexer):
                    indexer(batch.records)
                else:
                    # The Chroma leg adapter syncs rather than indexes.
                    adapter.sync_batch(batch)

            orphan_ids = sorted(
                {str(issue["record_id"]) for issue in before["orphan"]}
            )
            if orphan_ids:
                adapter.delete_records(orphan_ids)

            after = self.verify_vector_divergence(
                ns=ns, scope=scope, vector_adapter=adapter
            )
            return {
                "adapter": before["adapter"],
                "reindexed_ids": reindexed_ids,
                "deleted_orphan_ids": orphan_ids,
                "before": before,
                "after": after,
                "repaired": not after["diverged"],
            }
