from __future__ import annotations

import json
import logging
import os
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
    SearchResult,
    TraceGraph,
    VerifyReport,
)
from .models import EmbeddingModel, default_embedding_model
from .nl import compile_nl
from .pack import pack_record, pack_records
from .reconcile import reconcile_ir
from .retrieval import search_batch
from .storage import SQLiteStore
from .symbols import export_symbol_markdown, propose_symbols
from .transpile import transpile_python
from .vector import VECTOR_TEXT_VERSION
from .vector_adapters import (
    PgVectorAdapter,
    SQLiteVectorAdapter,
    VectorAdapter,
    search_vector_adapter,
)
from .verify import verify_ir

LOGGER = logging.getLogger(__name__)


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
        return verify_ir(ir_batch)

    def normalize_ir(self, ir_batch: IRBatch) -> IRBatch:
        return IRBatch(sorted(ir_batch.records, key=lambda record: record.id))

    def persist_ir(self, ir_batch: IRBatch) -> PersistReport:
        report = self.verify_ir(ir_batch)
        if not report.valid:
            raise ValueError(json.dumps(report.to_dict(), indent=2))
        normalized = self.normalize_ir(ir_batch)
        touched_ids = [record.id for record in normalized.records]
        previous = self.store.load_ir(ids=touched_ids) if touched_ids else IRBatch([])
        persist_report = self.store.persist_ir(normalized)
        try:
            self.vector_adapter.index_records(normalized.records)
        except Exception as exc:
            try:
                self.store.delete_ir(touched_ids, include_vectors=True)
                if previous.records:
                    self.store.persist_ir(previous)
                    self.vector_adapter.index_records(previous.records)
            except Exception as rollback_exc:
                touched_preview = ", ".join(touched_ids[:20])
                if len(touched_ids) > 20:
                    touched_preview += f", ... ({len(touched_ids)} total)"
                LOGGER.exception(
                    "Vector indexing failed and SQLite rollback failed for record ids: %s",
                    touched_preview,
                )
                rollback_exc.add_note(f"Original vector indexing error: {exc!r}")
                raise RuntimeError(
                    "Vector indexing failed and SQLite rollback failed; "
                    f"manual recovery may be required for record ids: {touched_preview}"
                ) from rollback_exc
            raise RuntimeError("Vector indexing failed; rolled back SQLite record write") from exc
        self.project_node_vectors()
        return persist_report

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
    ) -> dict[str, object]:
        return self.store.plan_scoped_delete(
            tenant_id=tenant_id,
            namespace=namespace,
            scope=scope,
            record_ids=record_ids,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def apply_scoped_delete(
        self,
        *,
        tenant_id: str,
        operation_id: str,
        actor: str,
        interrupt_after_intent: bool = False,
    ) -> dict[str, object]:
        return self.store.apply_scoped_delete(
            tenant_id=tenant_id,
            operation_id=operation_id,
            actor=actor,
            interrupt_after_intent=interrupt_after_intent,
            delete_derived_records=self._delete_derived_records,
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
                return {"model_name": model_name, "embedded": 0, "failed": 0}
            # The same node text under a different ns/scope is the same point in
            # vector space, so a boundary-only move must reuse the stored vector
            # rather than pay to embed it again.
            reusable = self.store.reusable_node_vectors(
                model_name, [str(entry["source_hash"]) for entry in pending]
            )
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

    def _retrieval_flags_cached(self):
        """Resolve effective retrieval flags once and cache for this runtime.

        Layers defaults < persisted applied-state < env (see
        ``load_retrieval_flags``); caching keeps scoring stable across queries
        for the process lifetime.
        """
        flags = getattr(self, "_retrieval_flags", None)
        if flags is None:
            from .retrieval import load_retrieval_flags

            flags = load_retrieval_flags(self.store)
            self._retrieval_flags = flags
        return flags

    def search_ir(self, query: str, lens: str = "general", scope: str | None = None, budget: int = 5, include_raw: bool = False, temporal_window = None, temporal_reference = None, ns: str | None = None, flags = None) -> SearchResult:
        from .bm25 import BM25Index
        from .mirl import iter_textual_fields

        # An explicit ``flags`` overrides the per-runtime cache: the self-improvement
        # proposer passes a candidate RetrievalFlags to ablate one lever deterministically
        # without mutating env or the cached runtime state.
        flags = flags if flags is not None else self._retrieval_flags_cached()
        # Retrieval-depth override (HISTORY#320): flags.search_top_k (env
        # SEAM_RETRIEVAL_TOP_K) raises the candidate count past the call-site
        # `budget` when set. The benchmark default of 20 was starving recall;
        # deeper retrieval is a measured paid-judge win (0.40->0.52). None = use
        # the caller's `budget` unchanged.
        budget = flags.search_top_k if getattr(flags, "search_top_k", None) else budget
        # Substream isolation: confine both the candidate load and vector top-K
        # to the requested namespace/scope boundary. Omitted filters reproduce
        # the prior global behavior exactly.
        batch = self.store.load_ir(ns=ns, scope=scope)
        vector_scores = search_vector_adapter(
            self.vector_adapter,
            query,
            limit=max(budget * 3, 10),
            namespace=ns,
            scope=scope,
        )
        namespace = batch.records[0].ns if batch.records else None
        bm25 = None
        if include_raw or flags.bm25_all_kinds:
            bm25 = BM25Index()
            for record in batch.records:
                if record.kind == RecordKind.RAW:
                    content = record.attrs.get("content")
                    text = content if isinstance(content, str) and content else ""
                elif flags.bm25_all_kinds:
                    text = " ".join(iter_textual_fields(record))
                else:
                    text = ""
                if text:
                    bm25.add(record.id, text)
        return search_batch(batch, query=query, scope=scope, limit=max(1, budget), vector_scores=vector_scores, namespace=namespace, include_raw=include_raw, bm25_index=bm25, temporal_window=temporal_window, temporal_reference=temporal_reference, flags=flags)

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
            self.store.persist_ir(IRBatch([pack_mirl]))
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
        batch = self.store.load_ir(ids=record_ids) if record_ids else self.store.load_ir()
        report = reconcile_ir(batch)
        if report.added_records:
            self.store.persist_ir(IRBatch(report.added_records))
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
        batch = self.store.load_ir(ids=record_ids) if record_ids else self.store.load_ir()
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
        batch = self.store.load_ir(ids=record_ids, ns=ns, scope=scope) if (record_ids or ns or scope) else self.store.load_ir()
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
