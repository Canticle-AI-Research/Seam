from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .agent_memory import IngestReport, compact_memory_index, full_memory_records, namespace_ingest_batch, neighbor_timeline, source_hash, stable_document_id
from .benchmarks import diff_benchmark_runs, evaluate_benchmark_gate, run_benchmark_suite, verify_benchmark_bundle
from .dsl import compile_dsl
from .evals import run_retrieval_benchmark
from .mirl import Artifact, IRBatch, Pack, PersistReport, ReconcileReport, RecordKind, SearchResult, TraceGraph, VerifyReport
from .models import EmbeddingModel, default_embedding_model
from .nl import compile_nl
from .pack import pack_record, pack_records
from .reconcile import reconcile_ir
from .retrieval import search_batch
from .storage import SQLiteStore
from .symbols import export_symbol_markdown, propose_symbols
from .transpile import transpile_python
from .vector_adapters import PgVectorAdapter, SQLiteVectorAdapter, VectorAdapter
from .verify import verify_ir


LOGGER = logging.getLogger(__name__)


class SeamRuntime:
    def __init__(
        self,
        store_path: str | Path = "seam.db",
        embedding_model: EmbeddingModel | None = None,
        vector_adapter: VectorAdapter | None = None,
        pgvector_dsn: str | None = None,
    ) -> None:
        self.store = SQLiteStore(store_path)
        self.embedding_model = embedding_model or default_embedding_model()
        resolved_dsn = pgvector_dsn or os.environ.get("SEAM_PGVECTOR_DSN")
        if vector_adapter is not None:
            self.vector_adapter = vector_adapter
        elif resolved_dsn:
            self.vector_adapter = PgVectorAdapter(resolved_dsn, self.embedding_model)
        else:
            self.vector_adapter = SQLiteVectorAdapter(str(store_path), self.embedding_model)
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

    def __enter__(self) -> "SeamRuntime":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def compile_nl(self, raw_text: str, source_ref: str = "local://input", ns: str = "local.default", scope: str = "thread") -> IRBatch:
        return compile_nl(raw_text, source_ref=source_ref, ns=ns, scope=scope)

    def compile_dsl(self, dsl_text: str, ns: str = "local.default", scope: str = "project") -> IRBatch:
        return compile_dsl(dsl_text, ns=ns, scope=scope)

    def ingest_text(
        self,
        text: str,
        source_ref: str = "local://input",
        ns: str = "local.default",
        scope: str = "thread",
        persist: bool = True,
    ) -> IngestReport:
        document_id = stable_document_id(source_ref, text)
        batch = namespace_ingest_batch(self.compile_nl(text, source_ref=source_ref, ns=ns, scope=scope), document_id)
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
        return persist_report

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
        # Substream isolation: when ``ns`` is given, confine BOTH the candidate
        # load and the vector top-K to that namespace so a shared store/vector
        # pool cannot leak another namespace's records. ns=None reproduces the
        # prior global behavior exactly.
        batch = self.store.load_ir(ns=ns, scope=scope)
        vector_scores = self.vector_adapter.search(query, limit=max(budget * 3, 10), namespace=ns)
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
    ) -> IngestReport:
        # Unified compiler (HISTORY#311): conversation turns and plain memories
        # share one faithful pipeline. `ingest_conversation_turn` is kept as the
        # benchmark/agent entry point but delegates to compile_nl.
        document_id = stable_document_id(source_ref, text)
        batch = namespace_ingest_batch(
            compile_nl(text, source_ref=source_ref, ns=ns, scope=scope),
            document_id,
        )
        stored_ids: list[str] = []
        if persist:
            stored_ids = self.persist_ir(batch).stored_ids
            self.store.mark_document_superseded_by_source_ref(
                source_ref, except_document_id=document_id
            )
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
                "indexable_count": len([
                    r for r in batch.records
                    if r.kind in {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL, RecordKind.RAW}
                ]),
            },
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

    def reindex_vectors(self, record_ids: list[str] | None = None) -> dict[str, object]:
        batch = self.store.load_ir(ids=record_ids) if record_ids else self.store.load_ir()
        stale = []
        inspector = getattr(self.vector_adapter, "stale_records", None)
        if inspector is not None:
            stale = inspector(batch.records)
        self.vector_adapter.index_records(batch.records)
        return {
            "indexed_ids": [record.id for record in batch.records],
            "model": self.embedding_model.name,
            "adapter": getattr(self.vector_adapter, "name", "unknown"),
            "stale_before": stale,
        }
