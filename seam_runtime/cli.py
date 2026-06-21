from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from .benchmark_baseline_policy import resolve_baseline
from .benchmark_integrity import (
    inspect_benchmark_integrity,
    load_json_payload,
    seal_benchmark_bundle,
    validate_publication_readiness,
    verify_benchmark_bundle as verify_integrity_bundle,
    write_json_payload,
)
from .benchmarks import (
    BENCHMARK_SUITES,
    render_benchmark_diff_pretty,
    render_benchmark_gate_pretty,
    render_benchmark_pretty,
    render_benchmark_verification_pretty,
    write_holdout_benchmark_bundle,
)
from .context_views import CONTEXT_VIEWS, build_context_payload, render_context_pretty
from .dashboard import run_dashboard
from .doctor import build_doctor_report, check_pgvector
from .installer import default_runtime_db_path
from .lossless import (
    LOSSLESS_CODECS,
    LOSSLESS_TRANSFORMS,
    READABLE_GRANULARITIES,
    TOKENIZER_CHOICES,
    benchmark_text_lossless,
    compress_text_readable,
    compress_text_lossless,
    decompress_text_readable,
    decompress_text_lossless,
    query_readable_compressed,
    render_lossless_benchmark_pretty,
)
from .holographic import (
    SURFACE_MODES,
    SURFACE_PAYLOAD_FORMATS,
    context_surface,
    decode_surface,
    encode_surface,
    inspect_surface,
    query_surface,
    verify_surface,
)
from .lx1 import decode as lx1_decode, encode as lx1_encode, token_savings_report
from .agent_memory import render_memory_index, render_memory_records
from .external_memory_benchmarks import (
    benchmark_plan,
    render_external_memory_plan_pretty,
    render_external_memory_report_pretty,
    run_external_memory_benchmarks,
)
from .mirl import IRBatch
from .runtime import SeamRuntime
from .surface_adapters import SurfaceFileAdapter


def _import_run_improvement_cycle():
    """Import ``tools.h2.improvement_loop.run_improvement_cycle`` for ``seam improve``.

    The self-improvement orchestration + apply step live under ``tools/`` (a
    sibling of ``seam_runtime/`` not shipped in the wheel). The ``seam`` console
    script does not put the source-checkout root on ``sys.path``, so add it when
    the file exists (editable/source install). A genuine wheel install has no
    sibling ``tools/`` and this returns None - the caller reports that the
    command needs a source checkout. Mirrors ``doctor._import_streams_verify_all``.
    """
    try:
        from tools.h2.improvement_loop import run_improvement_cycle
        return run_improvement_cycle
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parent.parent
        if (repo_root / "tools" / "h2" / "improvement_loop.py").is_file():
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from tools.h2.improvement_loop import run_improvement_cycle
            return run_improvement_cycle
        return None


def _import_run_paid_validation():
    """Import ``tools.h2.paid_validation.run_paid_validation`` for ``seam improve
    validate``. Same source-checkout fallback as ``_import_run_improvement_cycle``."""
    try:
        from tools.h2.paid_validation import run_paid_validation
        return run_paid_validation
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parent.parent
        if (repo_root / "tools" / "h2" / "paid_validation.py").is_file():
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from tools.h2.paid_validation import run_paid_validation
            return run_paid_validation
        return None


def _parse_candidate_flags(flags_json: str):
    """Parse a ``--flags`` JSON object into a RetrievalFlags, rejecting unknown
    fields and ill-typed values (same coercion as the #289 apply step)."""
    from .retrieval import RetrievalFlags, coerce_flag_value, retrieval_flag_field_types

    data = json.loads(flags_json)
    if not isinstance(data, dict):
        raise ValueError("--flags must be a JSON object of RetrievalFlags fields")
    known = retrieval_flag_field_types()
    values = {}
    for key, raw in data.items():
        if key not in known:
            raise ValueError(f"unknown retrieval flag {key!r} (known: {sorted(known)})")
        coerced = coerce_flag_value(key, raw)
        if coerced is None:
            raise ValueError(f"invalid value for retrieval flag {key!r}: {raw!r}")
        values[key] = coerced
    return RetrievalFlags(**values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SEAM v1 memory compiler/runtime")
    parser.add_argument("--db", default=default_runtime_db_path(), help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Store raw text from a file or stdin")
    ingest_parser.add_argument("source")
    ingest_parser.add_argument("--persist", action="store_true", help="Persist compiled memory records and index them")
    ingest_parser.add_argument("--source-ref")
    ingest_parser.add_argument("--ns", default="local.default")
    ingest_parser.add_argument("--scope", default="thread")
    ingest_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    lossless_compress_parser = subparsers.add_parser("lossless-compress", aliases=["compress-doc"], help="Losslessly compress a document into SEAM machine text")
    lossless_compress_parser.add_argument("source")
    lossless_compress_parser.add_argument("--codec", choices=["auto", *LOSSLESS_CODECS], default="auto")
    lossless_compress_parser.add_argument("--transform", choices=["auto", *LOSSLESS_TRANSFORMS], default="auto")
    lossless_compress_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
    lossless_compress_parser.add_argument("--output")
    lossless_compress_parser.add_argument("--format", choices=["machine", "json"], default="machine")

    readable_compress_parser = subparsers.add_parser(
        "readable-compress",
        aliases=["compress-readable"],
        help="Compress text into directly readable SEAM-RC/1 machine language",
    )
    readable_compress_parser.add_argument("source")
    readable_compress_parser.add_argument("--source-ref")
    readable_compress_parser.add_argument("--granularity", choices=READABLE_GRANULARITIES, default="auto")
    readable_compress_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
    readable_compress_parser.add_argument("--output")
    readable_compress_parser.add_argument("--format", choices=["machine", "json"], default="machine")

    readable_query_parser = subparsers.add_parser(
        "readable-query",
        aliases=["query-compressed"],
        help="Ask a SEAM-RC/1 compressed document directly without rebuilding the source",
    )
    readable_query_parser.add_argument("source")
    readable_query_parser.add_argument("query")
    readable_query_parser.add_argument("--limit", type=int, default=5)
    readable_query_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    readable_rebuild_parser = subparsers.add_parser("readable-rebuild", help="Verify and rebuild exact text from SEAM-RC/1")
    readable_rebuild_parser.add_argument("source")
    readable_rebuild_parser.add_argument("--output")

    surface_parser = subparsers.add_parser("surface", help="Read and write SEAM-HS/1 holographic memory surfaces")
    surface_subparsers = surface_parser.add_subparsers(dest="surface_command", required=True)
    surface_compile_parser = surface_subparsers.add_parser("compile", help="Compile source text to MIRL and write a SEAM-HS/1 surface")
    surface_compile_parser.add_argument("source")
    surface_compile_parser.add_argument("--output", required=True)
    surface_compile_parser.add_argument("--mode", choices=SURFACE_MODES, default="rgb24")
    surface_compile_parser.add_argument("--source-ref")
    surface_compile_parser.add_argument("--ns", default="local.default")
    surface_compile_parser.add_argument("--scope", default="thread")
    surface_compile_parser.add_argument("--persist", action="store_true", help="Also persist compiled MIRL records into SQLite")
    surface_compile_parser.add_argument("--store", action="store_true", help="Record the generated surface in the SQLite surface library")
    surface_compile_parser.add_argument("--artifact-dir", help="Directory for redundant stored surface copies")
    surface_compile_parser.add_argument("--no-copy", action="store_true", help="Store metadata against the output path without creating a redundant copy")
    surface_compile_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_encode_parser = surface_subparsers.add_parser("encode", help="Write MIRL/RC/LX bytes into a lossless PNG surface")
    surface_encode_parser.add_argument("source")
    surface_encode_parser.add_argument("--output", required=True)
    surface_encode_parser.add_argument("--mode", choices=SURFACE_MODES, default="rgb24")
    surface_encode_parser.add_argument("--payload-format", choices=SURFACE_PAYLOAD_FORMATS, default="auto")
    surface_encode_parser.add_argument("--source-ref")
    surface_encode_parser.add_argument("--store", action="store_true", help="Record the generated surface in the SQLite surface library")
    surface_encode_parser.add_argument("--artifact-dir", help="Directory for redundant stored surface copies")
    surface_encode_parser.add_argument("--no-copy", action="store_true", help="Store metadata against the output path without creating a redundant copy")
    surface_encode_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_decode_parser = surface_subparsers.add_parser("decode", help="Restore the exact payload bytes from a SEAM-HS/1 PNG surface")
    surface_decode_parser.add_argument("source")
    surface_decode_parser.add_argument("--output")
    surface_decode_parser.add_argument("--format", choices=["payload", "json"], default="payload")
    surface_verify_parser = surface_subparsers.add_parser("verify", help="Verify SEAM-HS/1 envelope and payload hash")
    surface_verify_parser.add_argument("source")
    surface_verify_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_query_parser = surface_subparsers.add_parser("query", help="Query embedded MIRL or SEAM-RC/1 directly from a surface")
    surface_query_parser.add_argument("source")
    surface_query_parser.add_argument("query")
    surface_query_parser.add_argument("--limit", type=int, default=5)
    surface_query_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_search_parser = surface_subparsers.add_parser("search", help="Rank embedded MIRL or SEAM-RC/1 hits directly from a surface")
    surface_search_parser.add_argument("source")
    surface_search_parser.add_argument("query")
    surface_search_parser.add_argument("--limit", type=int, default=5)
    surface_search_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_context_parser = surface_subparsers.add_parser("context", help="Build context directly from a SEAM-HS/1 surface")
    surface_context_parser.add_argument("source")
    surface_context_parser.add_argument("--query", required=True)
    surface_context_parser.add_argument("--budget", type=int, default=1200)
    surface_context_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_import_parser = surface_subparsers.add_parser("import", help="Persist embedded MIRL or machine artifact metadata into SQLite")
    surface_import_parser.add_argument("source")
    surface_import_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_store_parser = surface_subparsers.add_parser("store", help="Record an existing SEAM-HS/1 surface in the SQLite surface library")
    surface_store_parser.add_argument("source")
    surface_store_parser.add_argument("--source-ref")
    surface_store_parser.add_argument("--source-sha256")
    surface_store_parser.add_argument("--artifact-dir", help="Directory for redundant stored surface copies")
    surface_store_parser.add_argument("--no-copy", action="store_true", help="Store metadata against the source path without creating a redundant copy")
    surface_store_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_list_parser = surface_subparsers.add_parser("list", help="List stored SEAM-HS/1 surface library entries")
    surface_list_parser.add_argument("--limit", type=int, default=20)
    surface_list_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_show_parser = surface_subparsers.add_parser("show", help="Show one stored SEAM-HS/1 surface library entry")
    surface_show_parser.add_argument("surface_ref")
    surface_show_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    surface_repair_parser = surface_subparsers.add_parser("repair", help="Verify or restore a stored SEAM-HS/1 redundant surface copy")
    surface_repair_parser.add_argument("surface_ref")
    surface_repair_parser.add_argument("--source", help="Override repair source path")
    surface_repair_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    lossless_decompress_parser = subparsers.add_parser("lossless-decompress", aliases=["decompress-doc"], help="Restore a SEAM lossless document back to exact text")
    lossless_decompress_parser.add_argument("source")
    lossless_decompress_parser.add_argument("--output")

    lossless_benchmark_parser = subparsers.add_parser("lossless-benchmark", aliases=["benchmark-doc"], help="Benchmark lossless document compression and roundtrip recovery")
    lossless_benchmark_parser.add_argument("source")
    lossless_benchmark_parser.add_argument("--codec", choices=["auto", *LOSSLESS_CODECS], default="auto")
    lossless_benchmark_parser.add_argument("--transform", choices=["auto", *LOSSLESS_TRANSFORMS], default="auto")
    lossless_benchmark_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
    lossless_benchmark_parser.add_argument("--min-savings", type=float, default=0.30)
    lossless_benchmark_parser.add_argument("--compressed-output")
    lossless_benchmark_parser.add_argument("--roundtrip-output")
    lossless_benchmark_parser.add_argument("--log-output")
    lossless_benchmark_parser.add_argument("--show-machine", action="store_true")
    lossless_benchmark_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    demo_parser = subparsers.add_parser("demo", help="Run operator-facing SEAM demos")
    demo_subparsers = demo_parser.add_subparsers(dest="demo_command", required=True)
    demo_lossless_parser = demo_subparsers.add_parser("lossless", help="Compress or rebuild a lossless SEAM-LX document demo")
    demo_lossless_parser.add_argument("source")
    demo_lossless_parser.add_argument("output")
    demo_lossless_parser.add_argument("--rebuild", action="store_true", help="Treat the source as machine text and rebuild the original document")
    demo_lossless_parser.add_argument("--codec", choices=["auto", *LOSSLESS_CODECS], default="auto")
    demo_lossless_parser.add_argument("--transform", choices=["auto", *LOSSLESS_TRANSFORMS], default="auto")
    demo_lossless_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
    demo_lossless_parser.add_argument("--min-savings", type=float, default=0.30)
    demo_lossless_parser.add_argument("--show-machine", action="store_true")
    demo_lossless_parser.add_argument("--log-output")
    demo_lossless_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    
    benchmark_parser = subparsers.add_parser("benchmark", help="Run or inspect SEAM glassbox benchmark suites")
    benchmark_subparsers = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run_parser = benchmark_subparsers.add_parser("run", help="Run benchmark suites")
    benchmark_run_parser.add_argument("suite", nargs="?", choices=["all", *BENCHMARK_SUITES], default="all")
    benchmark_run_parser.add_argument("--tokenizer", choices=TOKENIZER_CHOICES, default="auto")
    benchmark_run_parser.add_argument("--min-savings", type=float, default=0.30)
    benchmark_run_parser.add_argument("--persist", action="store_true")
    benchmark_run_parser.add_argument("--output")
    benchmark_run_parser.add_argument("--holdout", action="store_true", help="Run publish-only holdout fixtures from benchmarks/fixtures/holdout")
    benchmark_run_parser.add_argument("--confirm-holdout", action="store_true", help="Confirm intentional publish-only holdout execution")
    benchmark_run_parser.add_argument("--holdout-output-dir", help="Directory for default holdout result bundles")
    benchmark_run_parser.add_argument("--include-machine-text", action="store_true")
    benchmark_run_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    benchmark_show_parser = benchmark_subparsers.add_parser("show", help="Show a persisted benchmark run")
    benchmark_show_parser.add_argument("run_id", nargs="?", default="latest")
    benchmark_show_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    benchmark_verify_parser = benchmark_subparsers.add_parser("verify", help="Verify a benchmark bundle hash and case hashes")
    benchmark_verify_parser.add_argument("bundle")
    benchmark_verify_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    benchmark_diff_parser = benchmark_subparsers.add_parser("diff", help="Compare two benchmark bundles or persisted run ids")
    benchmark_diff_parser.add_argument("run_a")
    benchmark_diff_parser.add_argument("run_b")
    benchmark_diff_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    benchmark_gate_parser = benchmark_subparsers.add_parser("gate", help="Evaluate benchmark bundle pass/fail and baseline regression gates")
    benchmark_gate_parser.add_argument("bundle")
    benchmark_gate_parser.add_argument("--baseline", help="Baseline bundle path or persisted run id for regression gating")
    benchmark_gate_parser.add_argument("--policy", help="JSON gate policy file")
    benchmark_gate_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    compile_nl_parser = subparsers.add_parser("compile-nl", aliases=["remember"], help="Compile natural language into MIRL and persist (use --no-persist to skip storing)")
    compile_nl_parser.add_argument("text")
    compile_nl_parser.add_argument("--source-ref", default="local://input")
    compile_nl_parser.add_argument("--no-persist", dest="persist", action="store_false", default=True)
    _add_rag_sync_args(compile_nl_parser)

    compile_dsl_parser = subparsers.add_parser("compile-dsl", help="Compile SEAM DSL into MIRL and persist (use --no-persist to skip storing)")
    compile_dsl_parser.add_argument("file")
    compile_dsl_parser.add_argument("--no-persist", dest="persist", action="store_false", default=True)
    _add_rag_sync_args(compile_dsl_parser)

    verify_parser = subparsers.add_parser("verify", help="Verify MIRL from a text file")
    verify_parser.add_argument("file")

    persist_parser = subparsers.add_parser("persist", help="Persist MIRL from a text file")
    persist_parser.add_argument("file")
    _add_rag_sync_args(persist_parser)

    search_parser = subparsers.add_parser("search", help="Combined search over persisted MIRL")
    search_parser.add_argument("query")
    search_parser.add_argument("--scope")
    search_parser.add_argument("--budget", type=int, default=5)

    plan_parser = subparsers.add_parser("plan", aliases=["hybrid-plan"], help="Plan a retrieval run")
    plan_parser.add_argument("query")
    _add_retrieval_common_args(plan_parser, include_backend=False)

    retrieve_parser = subparsers.add_parser("retrieve", aliases=["hybrid-search"], help="Run retrieval and rank results")
    retrieve_parser.add_argument("query")
    _add_retrieval_common_args(retrieve_parser)

    memory_parser = subparsers.add_parser("memory", help="Progressive-disclosure SEAM memory tools")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_search_parser = memory_subparsers.add_parser("search", help="Return compact memory index results")
    memory_search_parser.add_argument("query")
    memory_search_parser.add_argument("--scope")
    memory_search_parser.add_argument("--budget", type=int, default=5)
    memory_search_parser.add_argument("--format", choices=["pretty", "json", "ids"], default="pretty")
    memory_get_parser = memory_subparsers.add_parser("get", help="Return full selected MIRL records")
    memory_get_parser.add_argument("record_ids")
    memory_get_parser.add_argument("--timeline", action="store_true")
    memory_get_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    improve_parser = subparsers.add_parser("improve", help="Self-improvement loop over retrieval-flag levers")
    improve_subparsers = improve_parser.add_subparsers(dest="improve_command", required=True)
    improve_cycle_parser = improve_subparsers.add_parser(
        "cycle",
        help="Run one improvement cycle: evaluate levers against free scorers, propose the best non-regressing gain, optionally auto-apply with revert-on-regression",
    )
    improve_cycle_parser.add_argument("--db", default=argparse.SUPPRESS, help="SQLite database path (may also be given before the subcommand)")
    improve_cycle_parser.add_argument("--auto-approve", action="store_true", help="Approve + apply the proposal and auto-revert if it regresses post-apply (default: propose only)")
    improve_cycle_parser.add_argument("--probe-sample", type=int, default=50, help="Self-probe sample size from the local corpus (default 50; 0 disables the self-probe scorer)")
    improve_cycle_parser.add_argument("--probe-budget", type=int, default=20, help="Fixed eval budget for the self-probe scorer (default 20)")
    improve_cycle_parser.add_argument("--locomo-dataset", default=None, help="Optional free LoCoMo context_recall scorer from this dataset path (source checkout only)")
    improve_cycle_parser.add_argument("--locomo-scopes", type=int, default=5, help="Number of LoCoMo conversations pooled into the dev gate (default 5; multi-conversation so proposals generalize)")
    improve_cycle_parser.add_argument("--locomo-split", choices=["dev", "holdout", "all"], default="dev", help="Which split to score (default dev; the loop must NOT tune on holdout)")
    improve_cycle_parser.add_argument("--locomo-questions", type=int, default=None, help="Cap dev questions per LoCoMo conversation")
    improve_cycle_parser.add_argument("--locomo-answerer", choices=["none", "ollama"], default="none", help="LoCoMo scorer kind: 'none' = free context_recall (default); 'ollama' = free answer-quality (token_f1 via local Ollama), the dilution-sensitive scorer that lets the loop tune the search_top_k/context_budget profile. Profile tuning also requires --probe-sample 0 (self-probe is not profile-safe).")
    improve_cycle_parser.add_argument("--answerer-model", default="qwen2.5:3b", help="Ollama model for the answer-quality scorer (default qwen2.5:3b); endpoint via SEAM_BENCH_OLLAMA_URL")
    improve_validate_parser = improve_subparsers.add_parser(
        "validate",
        help="PAID holdout validation: judge the applied flag state (or --flags) against the stock baseline with a paid answerer + LLM judge. Dry-run cost estimate by default; spends ONLY with --confirm-paid",
    )
    improve_validate_parser.add_argument("--db", default=argparse.SUPPRESS, help="SQLite database path (may also be given before the subcommand)")
    improve_validate_parser.add_argument("--locomo-dataset", required=True, help="LoCoMo dataset path (source checkout only)")
    improve_validate_parser.add_argument("--locomo-scopes", type=int, default=5, help="Number of conversations pooled into the validation (default 5)")
    improve_validate_parser.add_argument("--locomo-questions", type=int, default=None, help="Cap questions per conversation (bounds spend)")
    improve_validate_parser.add_argument("--split", choices=["dev", "holdout", "all"], default="holdout", help="Split to validate on (default holdout - the cases the loop never tuned on)")
    improve_validate_parser.add_argument("--answerer", choices=["openai", "claude"], default="openai", help="Paid answerer that generates from retrieved context (default openai)")
    improve_validate_parser.add_argument("--answerer-model", default=None, help="Answerer model override")
    improve_validate_parser.add_argument("--judge", choices=["openai", "claude"], default="openai", help="Paid LLM judge (default openai)")
    improve_validate_parser.add_argument("--judge-model", default=None, help="Judge model override")
    improve_validate_parser.add_argument("--flags", default=None, help="Explicit candidate flags as a JSON object (default: the loop's persisted applied state)")
    improve_validate_parser.add_argument("--noise-margin", type=float, default=None, help="Judged-score noise margin for the verdict (default 0.02)")
    improve_validate_parser.add_argument("--confirm-paid", action="store_true", help="REQUIRED to spend: without it the command prints the call-count estimate and makes zero API calls")

    mcp_parser = subparsers.add_parser("mcp", help="Run SEAM agent integration bridges")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_subparsers.add_parser("stdio", help="Serve a standards-compliant MCP JSON-RPC server over stdio")
    mcp_subparsers.add_parser("serve", help="Serve the legacy JSON-lines bridge over stdio")

    compare_parser = subparsers.add_parser("compare", aliases=["hybrid-compare"], help="Compare basic search with retrieval ranking")
    compare_parser.add_argument("query")
    _add_retrieval_common_args(compare_parser)

    index_parser = subparsers.add_parser("index", aliases=["rag-sync"], help="Sync persisted records into the active vector indexes")
    index_parser.add_argument("--record-ids", default="")
    index_parser.add_argument("--scope")
    index_parser.add_argument("--namespace")
    index_parser.add_argument("--format", choices=["pretty", "json", "ids"], default="pretty")
    index_parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
    index_parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
    index_parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")

    context_parser = subparsers.add_parser("context", aliases=["rag-search"], help="Retrieve context for generation")
    context_parser.add_argument("query")
    context_parser.add_argument("--scope")
    context_parser.add_argument("--budget", type=int, default=5)
    context_parser.add_argument("--pack-budget", type=int, default=512)
    context_parser.add_argument("--lens", default="rag")
    context_parser.add_argument("--mode", choices=["context", "narrative", "exact"], default="context")
    context_parser.add_argument("--view", choices=CONTEXT_VIEWS, default="pack")
    context_parser.add_argument("--format", choices=["pretty", "json", "ids"], default="pretty")
    context_parser.add_argument("--trace", action="store_true")
    context_parser.add_argument("--retrieval-mode", choices=["vector", "graph", "hybrid", "mix"], default="hybrid")
    context_parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
    context_parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
    context_parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")

    shell_parser = subparsers.add_parser(
        "shell",
        aliases=["chat"],
        help="Start an interactive SEAM memory shell",
    )
    shell_parser.add_argument(
        "--once",
        action="append",
        default=[],
        help="Run one shell command non-interactively and exit; may be repeated",
    )
    shell_parser.add_argument("--budget", type=int, default=5)
    shell_parser.add_argument("--pack-budget", type=int, default=512)
    shell_parser.add_argument("--retrieval-mode", choices=["vector", "graph", "hybrid", "mix"], default="mix")

    dashboard_parser = subparsers.add_parser("dashboard", help="Launch the runtime-connected terminal dashboard")
    dashboard_parser.add_argument("--snapshot", action="store_true", help="Render one dashboard frame and exit")
    dashboard_parser.add_argument("--run", dest="dashboard_commands", action="append", default=[], help="Run a dashboard command non-interactively")
    dashboard_parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal between renders")
    dashboard_parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
    dashboard_parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
    dashboard_parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")

    serve_parser = subparsers.add_parser("serve", help="Run the SEAM REST API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.add_argument("--workers", type=int, default=1)

    webui_parser = subparsers.add_parser(
        "webui",
        aliases=["dashboard-web"],
        help="Serve the SEAM browser dashboard (UI + REST API on one server) and open it",
    )
    webui_parser.add_argument("--host", default="127.0.0.1")
    webui_parser.add_argument("--port", type=int, default=8765)
    webui_parser.add_argument("--reload", action="store_true")
    webui_parser.add_argument("--workers", type=int, default=1)
    webui_parser.add_argument(
        "--no-open", dest="open_browser", action="store_false", default=True,
        help="Do not open a browser window automatically",
    )

    pack_parser = subparsers.add_parser("pack", help="Build a pack from persisted record ids")
    pack_parser.add_argument("record_ids")
    pack_parser.add_argument("--lens", default="general")
    pack_parser.add_argument("--budget", type=int, default=512)
    pack_parser.add_argument("--mode", choices=["exact", "context", "narrative"], default="context")
    pack_parser.add_argument("--no-persist", dest="persist", action="store_false", default=True)

    decompile_parser = subparsers.add_parser("decompile", help="Decompile persisted record ids")
    decompile_parser.add_argument("record_ids")
    decompile_parser.add_argument("--mode", default="expanded")

    trace_parser = subparsers.add_parser("trace", help="Trace provenance for a persisted object id")
    trace_parser.add_argument("obj_id")

    reconcile_parser = subparsers.add_parser("reconcile", help="Reconcile claims and emit relation/state updates")
    reconcile_parser.add_argument("--record-ids", default="")

    transpile_parser = subparsers.add_parser("transpile", help="Transpile MIRL workflows to Python")
    transpile_parser.add_argument("record_ids")
    transpile_parser.add_argument("--target", default="python")

    reindex_parser = subparsers.add_parser("reindex", help="Rebuild vector index entries")
    reindex_parser.add_argument("--record-ids", default="")

    promote_symbols_parser = subparsers.add_parser("promote-symbols", help="Propose and persist machine-only symbols")
    promote_symbols_parser.add_argument("--record-ids", default="")
    promote_symbols_parser.add_argument("--min-frequency", type=int, default=2)

    export_symbols_parser = subparsers.add_parser("export-symbols", help="Export symbol nursery markdown for audit/safety")
    export_symbols_parser.add_argument("--namespace")
    export_symbols_parser.add_argument("--output")

    doctor_parser = subparsers.add_parser("doctor", help="Check SEAM install health and run a lightweight smoke test")
    doctor_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    lx1_encode_parser = subparsers.add_parser("lx1-encode", help="Encode MIRL records to LX/1 compact AI-readable notation")
    lx1_encode_parser.add_argument("source", help="MIRL text file or - for stdin")
    lx1_encode_parser.add_argument("--output", help="Write output to file instead of stdout")
    lx1_encode_parser.add_argument("--ns", default="local.default")
    lx1_encode_parser.add_argument("--scope", default="project")

    lx1_decode_parser = subparsers.add_parser("lx1-decode", help="Decode LX/1 compact notation back to MIRL records")
    lx1_decode_parser.add_argument("source", help="LX/1 file or - for stdin")
    lx1_decode_parser.add_argument("--output", help="Write MIRL text to file instead of stdout")
    lx1_decode_parser.add_argument("--persist", action="store_true", help="Persist decoded records to the database")

    lx1_benchmark_parser = subparsers.add_parser("lx1-benchmark", help="Show token savings of LX/1 notation vs verbose MIRL")
    lx1_benchmark_parser.add_argument("source", help="MIRL text file or - for stdin")
    lx1_benchmark_parser.add_argument("--ns", default="local.default")
    lx1_benchmark_parser.add_argument("--scope", default="project")
    lx1_benchmark_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    bench_parser = subparsers.add_parser("bench", help="External memory benchmark registry and runner")
    bench_subparsers = bench_parser.add_subparsers(dest="bench_command", required=True)
    bench_external_parser = bench_subparsers.add_parser(
        "external",
        help="Run or plan external memory benchmarks (LoCoMo, MemBench, etc.)",
    )
    bench_external_parser.add_argument("target", nargs="?", choices=["locomo", "longmemeval", "beam"], help="Run a specific external benchmark")
    bench_external_parser.add_argument("--scope", default="required", help="required, all, or a single benchmark id")
    bench_external_parser.add_argument("--plan", action="store_true", help="Print the configured/missing runner plan and exit 0")
    bench_external_parser.add_argument("--strict", action="store_true", help="Fail when required runners are NOT_CONFIGURED")
    bench_external_parser.add_argument("--output", help="Write JSON to this path")
    bench_external_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    bench_external_parser.add_argument("--timeout-seconds", type=int, default=3600)
    bench_external_parser.add_argument("--quickstart", choices=["locomo"], help="Run a bundled quickstart benchmark (locomo: 60s synthetic fixture)")
    bench_external_parser.add_argument("--adapter", choices=["seam", "mem0", "zep"], default="seam", help="Memory system under test")
    bench_external_parser.add_argument("--judge", choices=["none", "stub", "claude", "openai"], default=None, help="LLM judge in addition to string-match scoring")
    bench_external_parser.add_argument("--judge-model", default=None, help="Override the default judge model id")
    bench_external_parser.add_argument("--dataset-path", help="Local dataset path for locomo, longmemeval, or beam")
    bench_external_parser.add_argument("--dry-run", action="store_true", help="Validate external benchmark inputs without full execution")
    bench_external_parser.add_argument("--track", choices=["1m", "10m"], default="1m", help="BEAM track")
    bench_external_parser.add_argument("--limit", type=int, default=None, help="Limit external benchmark cases where supported")
    bench_external_parser.add_argument("--workers", type=int, default=1, help="Parallel case workers where supported")

    bench_seal_parser = bench_subparsers.add_parser("seal", help="Seal a benchmark result as a BIL bundle")
    bench_seal_parser.add_argument("result", help="Benchmark result JSON path")
    bench_seal_parser.add_argument("--level", choices=["BIL-1", "BIL-2"], default="BIL-2")
    bench_seal_parser.add_argument("--output", required=True, help="Write sealed bundle JSON to this path")
    bench_seal_parser.add_argument("--allow-stub-seal", action="store_true", help="Allow sealing a result with a stub judge above BIL-0")
    bench_seal_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    bench_verify_parser = bench_subparsers.add_parser("verify", help="Verify a sealed benchmark BIL bundle")
    bench_verify_parser.add_argument("bundle", help="Benchmark bundle JSON path")
    bench_verify_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    bench_inspect_parser = bench_subparsers.add_parser("inspect", help="Inspect benchmark integrity/BIL status")
    bench_inspect_parser.add_argument("payload", help="Benchmark result or bundle JSON path")
    bench_inspect_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    bench_publish_parser = bench_subparsers.add_parser(
        "publish",
        help="Gate a benchmark result for competitive publication (non-stub judge + BIL-2 verify)",
    )
    bench_publish_parser.add_argument("result", help="Benchmark result JSON path")
    bench_publish_parser.add_argument("--bundle", help="Pre-sealed BIL-2 bundle JSON path; default seals BIL-2 in memory")
    bench_publish_parser.add_argument("--dataset", default="", help="Dataset name (else read from result.dataset)")
    bench_publish_parser.add_argument("--fixture-hash", default="", help="Fixture hash (else read from result)")
    bench_publish_parser.add_argument("--git-sha", default="", help="Git SHA (else auto-detected from the repo)")
    bench_publish_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")

    subparsers.add_parser("stats", help="Run retrieval benchmark summary")
    return parser


def run_cli(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in {"lossless-compress", "compress-doc"}:
        text = _read_text_source(args.source)
        artifact = compress_text_lossless(text, codec=args.codec, transform=args.transform, tokenizer=args.tokenizer)
        if args.output:
            _write_text_output(args.output, artifact.machine_text)
        if args.format == "json":
            print(json.dumps(artifact.to_dict(include_machine_text=True), indent=2))
            return
        _print_text(artifact.machine_text)
        return
    if args.command in {"readable-compress", "compress-readable"}:
        text = _read_text_source(args.source)
        artifact = compress_text_readable(
            text,
            source_ref=args.source_ref or args.source,
            granularity=args.granularity,
            tokenizer=args.tokenizer,
        )
        if args.output:
            _write_text_output(args.output, artifact.machine_text)
        if args.format == "json":
            print(json.dumps(artifact.to_dict(include_machine_text=True), indent=2))
            return
        _print_text(artifact.machine_text)
        return
    if args.command in {"readable-query", "query-compressed"}:
        machine_text = _read_text_source(args.source)
        result = query_readable_compressed(machine_text, args.query, limit=args.limit)
        payload = result.to_dict()
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return
        _print_text(_render_readable_query_pretty(payload))
        return
    if args.command == "readable-rebuild":
        text = decompress_text_readable(_read_text_source(args.source))
        if args.output:
            _write_text_output(args.output, text)
            print(args.output)
            return
        _print_text(text)
        return
    if args.command == "surface":
        if args.surface_command == "encode":
            payload = Path(args.source).read_bytes() if args.source != "-" else sys.stdin.buffer.read()
            source_ref = args.source_ref or args.source
            artifact = encode_surface(
                payload,
                output_path=Path(args.output),
                mode=args.mode,
                payload_format=args.payload_format,
                source_ref=source_ref,
            )
            output_payload = artifact.to_dict()
            if args.store:
                runtime = SeamRuntime(args.db)
                output_payload["library"] = _store_surface_library_entry(
                    runtime,
                    output_payload,
                    source_ref=source_ref,
                    source_sha256=_sha256_file(args.source),
                    stored_by="surface encode",
                    artifact_dir=args.artifact_dir,
                    copy_artifact=not args.no_copy,
                )
            if args.format == "json":
                print(json.dumps(output_payload, indent=2))
                return
            _print_text(_render_surface_artifact_pretty(output_payload))
            return
        if args.surface_command == "decode":
            runtime = SeamRuntime(args.db) if not Path(args.source).exists() else None
            payload = decode_surface(_resolve_surface_path(args.source, runtime))
            if args.output:
                Path(args.output).write_bytes(payload.payload)
                print(args.output)
                return
            if args.format == "json":
                print(json.dumps(payload.to_dict(include_payload=True), indent=2))
                return
            buffer = getattr(sys.stdout, "buffer", None)
            if buffer is None:
                print(payload.text)
            else:
                buffer.write(payload.payload)
                buffer.write(b"\n")
            return
        if args.surface_command == "verify":
            runtime = SeamRuntime(args.db) if not Path(args.source).exists() else None
            result = verify_surface(_resolve_surface_path(args.source, runtime)).to_dict()
            if args.format == "json":
                print(json.dumps(result, indent=2))
                return
            _print_text(_render_surface_verify_pretty(result))
            return
        if args.surface_command in {"query", "search"}:
            runtime = SeamRuntime(args.db) if not Path(args.source).exists() else None
            result = query_surface(_resolve_surface_path(args.source, runtime), args.query, limit=args.limit).to_dict()
            if args.format == "json":
                print(json.dumps(result, indent=2))
                return
            _print_text(_render_surface_query_pretty(result))
            return
        if args.surface_command == "context":
            runtime = SeamRuntime(args.db) if not Path(args.source).exists() else None
            payload = context_surface(_resolve_surface_path(args.source, runtime), query=args.query, budget=args.budget)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            _print_text(_render_surface_context_pretty(payload))
            return
        if args.surface_command == "store":
            runtime = SeamRuntime(args.db)
            artifact = inspect_surface(Path(args.source))
            row = _store_surface_library_entry(
                runtime,
                artifact,
                source_ref=args.source_ref or str(artifact.get("source_ref", "")),
                source_sha256=args.source_sha256,
                stored_by="surface store",
                artifact_dir=args.artifact_dir,
                copy_artifact=not args.no_copy,
            )
            if args.format == "json":
                print(json.dumps(row, indent=2))
                return
            _print_text(_render_surface_library_entry_pretty(row))
            return
        if args.surface_command == "list":
            runtime = SeamRuntime(args.db)
            rows = runtime.store.list_surface_artifacts(limit=args.limit)
            if args.format == "json":
                print(json.dumps({"surfaces": rows}, indent=2))
                return
            _print_text(_render_surface_library_list_pretty(rows))
            return
        if args.surface_command == "show":
            runtime = SeamRuntime(args.db)
            row = runtime.store.read_surface_artifact(args.surface_ref)
            if args.format == "json":
                print(json.dumps(row, indent=2))
                return
            _print_text(_render_surface_library_entry_pretty(row))
            return
        if args.surface_command == "repair":
            runtime = SeamRuntime(args.db)
            result = _repair_surface_library_entry(runtime, args.surface_ref, source_override=args.source)
            if args.format == "json":
                print(json.dumps(result, indent=2))
                return
            _print_text(_render_surface_repair_pretty(result))
            return
    if args.command in {"lossless-decompress", "decompress-doc"}:
        machine_text = _read_text_source(args.source)
        text = decompress_text_lossless(machine_text)
        if args.output:
            _write_text_output(args.output, text)
            print(args.output)
            return
        _print_text(text)
        return
    if args.command in {"lossless-benchmark", "benchmark-doc"}:
        text = _read_text_source(args.source)
        result = benchmark_text_lossless(
            text,
            codec=args.codec,
            transform=args.transform,
            min_token_savings=args.min_savings,
            tokenizer=args.tokenizer,
        )
        if args.compressed_output:
            _write_text_output(args.compressed_output, result.artifact.machine_text)
        if args.roundtrip_output:
            _write_text_output(args.roundtrip_output, result.roundtrip_text)
        payload = result.to_dict(include_machine_text=args.show_machine)
        if args.log_output:
            _write_text_output(args.log_output, json.dumps(payload, indent=2))
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return
        print(render_lossless_benchmark_pretty(payload))
        return
    if args.command == "demo" and args.demo_command == "lossless":
        if args.rebuild:
            rebuilt_text = decompress_text_lossless(_read_text_source(args.source))
            _write_text_output(args.output, rebuilt_text)
            payload = {
                "mode": "rebuild",
                "source": args.source,
                "output": args.output,
                "status": "PASS",
                "sha256": hashlib.sha256(rebuilt_text.encode("utf-8")).hexdigest(),
                "output_bytes": len(rebuilt_text.encode("utf-8")),
                "integrity": "verified against embedded SEAM-LX/1 hash",
            }
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(_render_lossless_demo_result(payload))
            return

        text = _read_text_source(args.source)
        result = benchmark_text_lossless(
            text,
            codec=args.codec,
            transform=args.transform,
            min_token_savings=args.min_savings,
            tokenizer=args.tokenizer,
        )
        _write_text_output(args.output, result.artifact.machine_text)
        payload = result.to_dict(include_machine_text=args.show_machine)
        payload["mode"] = "compress"
        payload["source"] = args.source
        payload["output"] = args.output
        if args.log_output:
            payload["log_output"] = args.log_output
            _write_text_output(args.log_output, json.dumps(payload, indent=2))
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return
        print(_render_lossless_demo_result(payload))
        return

    if args.command == "lx1-encode":
        batch = IRBatch.from_text(_read_text_source(args.source))
        compact = lx1_encode(batch, ns=args.ns, scope=args.scope)
        if args.output:
            _write_text_output(args.output, compact)
        else:
            print(compact)
        return
    if args.command == "lx1-decode":
        compact = _read_text_source(args.source)
        batch = lx1_decode(compact)
        mirl_text = batch.to_text()
        if args.output:
            _write_text_output(args.output, mirl_text)
        else:
            print(mirl_text)
        if args.persist:
            runtime = SeamRuntime(args.db)
            runtime.persist_ir(batch)
        return
    if args.command == "lx1-benchmark":
        mirl_text = _read_text_source(args.source)
        batch = IRBatch.from_text(mirl_text)
        compact = lx1_encode(batch, ns=args.ns, scope=args.scope)
        report = token_savings_report(mirl_text, compact)
        if args.format == "json":
            print(json.dumps(report, indent=2))
            return
        print(_render_lx1_benchmark_pretty(report))
        return

    if args.command == "serve":
        from .server import run_server

        run_server(host=args.host, port=args.port, db=args.db, reload=args.reload, workers=args.workers)
        return

    if args.command in ("webui", "dashboard-web"):
        from .server import run_server, webui_dir

        if webui_dir() is None:
            print(
                "SEAM dashboard assets not found (expected seam_runtime/webui/dashboard.html).",
                file=sys.stderr,
            )
            return
        url = f"http://{args.host}:{args.port}/"
        if getattr(args, "open_browser", True):
            import threading
            import webbrowser

            # Open the browser shortly after uvicorn starts accepting connections.
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"SEAM dashboard: {url}  (Ctrl-C to stop)")
        run_server(host=args.host, port=args.port, db=args.db, reload=args.reload, workers=args.workers)
        return

    if args.command == "bench" and args.bench_command == "external":
        if args.target:
            cmd: list[str]
            if args.target == "locomo":
                cmd = [sys.executable, "-m", "benchmarks.external.locomo.run"]
                if args.dataset_path:
                    cmd.extend(["--dataset-path", args.dataset_path])
                else:
                    raise SystemExit("locomo requires --dataset-path for explicit benchmark runs")
                if args.adapter:
                    cmd.extend(["--adapter", args.adapter])
                if args.limit is not None:
                    cmd.extend(["--limit", str(args.limit)])
                if args.workers is not None:
                    cmd.extend(["--workers", str(args.workers)])
            elif args.target == "longmemeval":
                if not args.dataset_path:
                    raise SystemExit("longmemeval requires --dataset-path")
                cmd = [sys.executable, "-m", "benchmarks.external.longmemeval.run", "--dataset-path", args.dataset_path]
                if args.adapter:
                    cmd.extend(["--adapter", args.adapter])
                if args.limit is not None:
                    cmd.extend(["--limit", str(args.limit)])
                if args.workers is not None:
                    cmd.extend(["--workers", str(args.workers)])
            elif args.target == "beam":
                if not args.dataset_path:
                    raise SystemExit("beam requires --dataset-path")
                cmd = [
                    sys.executable, "-m", "benchmarks.external.beam.run",
                    "--track", args.track, "--dataset-path", args.dataset_path,
                ]
                if args.adapter:
                    cmd.extend(["--adapter", args.adapter])
                if args.limit is not None:
                    cmd.extend(["--limit", str(args.limit)])
                if args.workers is not None:
                    cmd.extend(["--workers", str(args.workers)])
            else:
                raise SystemExit(f"Unknown external benchmark target: {args.target!r}")
            if args.dry_run:
                cmd.append("--dry-run")
            if args.output:
                cmd.extend(["--output", args.output])
            if args.judge:
                cmd.extend(["--judge", args.judge])
            if args.judge_model:
                cmd.extend(["--judge-model", args.judge_model])
            result = subprocess.run(cmd, check=False)
            raise SystemExit(result.returncode)
        if args.quickstart:
            if args.quickstart == "locomo":
                cmd = [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart"]
                if args.output:
                    cmd.extend(["--output", args.output])
                if args.adapter:
                    cmd.extend(["--adapter", args.adapter])
                if args.judge:
                    cmd.extend(["--judge", args.judge])
                if args.judge_model:
                    cmd.extend(["--judge-model", args.judge_model])
                if args.workers is not None:
                    cmd.extend(["--workers", str(args.workers)])
                result = subprocess.run(cmd, check=False)
                raise SystemExit(result.returncode)
            raise SystemExit(f"Unknown quickstart target: {args.quickstart!r}")
        if args.plan:
            payload = benchmark_plan(scope=args.scope)
            text = json.dumps(payload, indent=2) if args.format == "json" else render_external_memory_plan_pretty(payload)
            exit_code = 0
        else:
            payload = run_external_memory_benchmarks(scope=args.scope, strict=args.strict, timeout_seconds=args.timeout_seconds)
            text = json.dumps(payload, indent=2) if args.format == "json" else render_external_memory_report_pretty(payload)
            exit_code = 1 if payload.get("status") == "FAIL" else 0
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(text)
        raise SystemExit(exit_code)

    if args.command == "bench" and args.bench_command == "seal":
        result_payload = load_json_payload(args.result)
        try:
            bundle = seal_benchmark_bundle(
                result_payload, level=args.level,
                allow_stub_seal=getattr(args, "allow_stub_seal", False),
            )
        except ValueError as exc:
            raise SystemExit(str(exc))
        write_json_payload(args.output, bundle)
        report = inspect_benchmark_integrity(bundle)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(_render_bil_integrity_pretty(report))
        return

    if args.command == "bench" and args.bench_command == "verify":
        bundle = load_json_payload(args.bundle)
        report = verify_integrity_bundle(bundle)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(_render_bil_integrity_pretty({"status": report["status"], "bil": report["bil"], "verification": report}))
        raise SystemExit(0 if report.get("status") == "PASS" else 1)

    if args.command == "bench" and args.bench_command == "inspect":
        payload = load_json_payload(args.payload)
        report = inspect_benchmark_integrity(payload)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(_render_bil_integrity_pretty(report))
        raise SystemExit(0 if report.get("status") == "PASS" else 1)

    if args.command == "bench" and args.bench_command == "publish":
        result_payload = load_json_payload(args.result)
        if args.bundle:
            bundle = load_json_payload(args.bundle)
        else:
            # Seal in memory only to produce a verifiable BIL-2 bundle for the
            # readiness check. allow_stub_seal here does NOT weaken the gate:
            # validate_publication_readiness still refuses stub judges below.
            bundle = seal_benchmark_bundle(result_payload, level="BIL-2", allow_stub_seal=True)
        bil_verification = verify_integrity_bundle(bundle)
        dataset = args.dataset or str((result_payload.get("dataset") or {}).get("name") or "")
        fixture_hash = (
            args.fixture_hash
            or str(result_payload.get("fixture_hash") or "")
            or str((result_payload.get("dataset") or {}).get("fixture_hash") or "")
        )
        git_sha = args.git_sha or _current_git_sha()
        readiness = validate_publication_readiness(
            result_payload,
            git_sha=git_sha,
            fixture_hash=fixture_hash,
            dataset_name=dataset,
            bil_verification=bil_verification,
        )
        if args.format == "json":
            print(json.dumps({"readiness": readiness, "bil_verification": bil_verification}, indent=2, sort_keys=True))
        else:
            print(_render_publication_readiness_pretty(readiness))
        raise SystemExit(0 if readiness.get("ready") else 1)

    runtime = SeamRuntime(args.db)

    if args.command == "ingest":
        text = _read_text_source(args.source)
        if args.persist:
            report = runtime.ingest_text(text, source_ref=args.source_ref or args.source, ns=args.ns, scope=args.scope, persist=True)
            if args.format == "json":
                print(json.dumps(report.to_dict(), indent=2))
                return
            print(_render_ingest_report(report.to_dict()))
            return
        print(runtime.compile_nl(text, source_ref=args.source_ref or args.source, ns=args.ns, scope=args.scope).to_text())
        return
    if args.command == "surface" and args.surface_command == "compile":
        text = _read_text_source(args.source)
        source_ref = args.source_ref or args.source
        batch = runtime.compile_nl(text, source_ref=source_ref, ns=args.ns, scope=args.scope)
        artifact = encode_surface(
            batch.to_text().encode("utf-8"),
            output_path=Path(args.output),
            mode=args.mode,
            payload_format="MIRL",
            source_ref=source_ref,
        )
        report: dict[str, object] = {
            "surface": artifact.to_dict(),
            "payload_format": "MIRL",
            "record_count": len(batch.records),
            "source_ref": source_ref,
            "stored_ids": [],
        }
        if args.store:
            report["library"] = _store_surface_library_entry(
                runtime,
                artifact.to_dict(),
                source_ref=source_ref,
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                stored_by="surface compile",
                artifact_dir=args.artifact_dir,
                copy_artifact=not args.no_copy,
            )
        if args.persist:
            persist_report = runtime.persist_ir(batch).to_dict()
            report["stored_ids"] = persist_report.get("stored_ids", [])
            report["persist"] = persist_report
        if args.format == "json":
            print(json.dumps(report, indent=2))
            return
        _print_text(_render_surface_compile_pretty(report))
        return
    if args.command == "surface" and args.surface_command == "import":
        surface_path = _resolve_surface_path(args.source, runtime)
        payload = decode_surface(surface_path)
        if payload.payload_format == "MIRL":
            report = runtime.persist_ir(IRBatch.from_text(payload.text)).to_dict()
            report["surface"] = payload.to_dict()
        else:
            artifact_id = runtime.store.write_machine_artifact(
                source_type="surface.import",
                source_id=args.source,
                artifact=payload.to_dict(include_payload=True),
                roundtrip_ok=True,
                metadata={"family": "surface", "payload_format": payload.payload_format},
            )
            report = {"artifact_id": artifact_id, "surface": payload.to_dict()}
        try:
            report["library"] = runtime.store.update_surface_import_status(args.source, "imported")
        except KeyError:
            pass
        if args.format == "json":
            print(json.dumps(report, indent=2))
            return
        _print_text(_render_surface_import_pretty(report))
        return
    if args.command in {"compile-nl", "remember"}:
        batch = runtime.compile_nl(args.text, source_ref=args.source_ref)
        if args.persist or args.sync_index:
            runtime.persist_ir(batch)
            if args.sync_index:
                orchestrator = _build_retrieval_orchestrator(runtime, args)
                orchestrator.sync_persistent_indexes(record_ids=[record.id for record in batch.records])
        if args.persist:
            print(f"Encoded {len(batch.records)} records → stored in {args.db}")
        else:
            print(batch.to_text())
        return
    if args.command == "compile-dsl":
        batch = runtime.compile_dsl(Path(args.file).read_text(encoding="utf-8"))
        if args.persist or args.sync_index:
            runtime.persist_ir(batch)
            if args.sync_index:
                orchestrator = _build_retrieval_orchestrator(runtime, args)
                orchestrator.sync_persistent_indexes(record_ids=[record.id for record in batch.records])
        if args.persist:
            print(f"Encoded {len(batch.records)} records → stored in {args.db}")
        else:
            print(batch.to_text())
        return
    if args.command == "verify":
        batch = IRBatch.from_text(Path(args.file).read_text(encoding="utf-8"))
        print(json.dumps(runtime.verify_ir(batch).to_dict(), indent=2))
        return
    if args.command == "persist":
        batch = IRBatch.from_text(Path(args.file).read_text(encoding="utf-8"))
        report = runtime.persist_ir(batch).to_dict()
        if args.sync_index:
            orchestrator = _build_retrieval_orchestrator(runtime, args)
            report["index"] = orchestrator.sync_persistent_indexes(record_ids=[record["id"] for record in batch.to_json()])
        print(json.dumps(report, indent=2))
        return
    if args.command == "search":
        print(json.dumps(runtime.search_ir(args.query, scope=args.scope, budget=args.budget).to_dict(), indent=2))
        return
    if args.command in {"plan", "hybrid-plan"}:
        orchestrator = _build_retrieval_orchestrator(runtime, args)
        plan = orchestrator.plan(args.query, scope=args.scope, budget=args.budget, mode=args.mode)
        _print_retrieval_output(plan.to_dict(), output_format=args.format, renderer=_render_plan_pretty)
        return
    if args.command in {"retrieve", "hybrid-search"}:
        orchestrator = _build_retrieval_orchestrator(runtime, args)
        result = orchestrator.search(args.query, scope=args.scope, budget=args.budget, include_trace=args.trace, mode=args.mode)
        _print_retrieval_output(result.to_dict(), output_format=args.format, renderer=_render_search_pretty)
        return
    if args.command == "memory":
        if args.memory_command == "search":
            payload = runtime.memory_search(args.query, scope=args.scope, budget=args.budget)
            _print_retrieval_output(payload, output_format=args.format, renderer=render_memory_index)
            return
        if args.memory_command == "get":
            payload = runtime.memory_get(_split_ids(args.record_ids), include_timeline=args.timeline)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(render_memory_records(payload))
            return
    if args.command == "improve" and args.improve_command == "cycle":
        run_cycle = _import_run_improvement_cycle()
        if run_cycle is None:
            print(json.dumps({"error": "seam improve cycle requires a source checkout (tools/ is not shipped in the wheel)"}, indent=2))
            return
        from .self_improve import SelfProbeScorer, generate_probes

        scorers = []
        if args.probe_sample > 0:
            probes = generate_probes(runtime, sample=args.probe_sample)
            scorers.append(SelfProbeScorer(probes, budget=args.probe_budget))
        adapter = None
        if args.locomo_dataset:
            import tempfile

            # One pooled scorer over the dev split of N conversations: the
            # multi-conversation gate, so an accepted lever generalizes and the
            # loop never tunes on holdout. The answerer choice selects the metric:
            # 'none' = free context_recall (cannot tune the profile - a bigger
            # budget games recall); 'ollama' = free answer-quality (token_f1), the
            # dilution-sensitive profile_safe scorer that CAN tune search_top_k/
            # context_budget to the configured answerer.
            if args.locomo_answerer == "ollama":
                from benchmarks.external.locomo.answer_quality_scorer import (
                    build_locomo_answer_quality_scorer,
                )

                adapter, locomo_scorer = build_locomo_answer_quality_scorer(
                    args.locomo_dataset,
                    max_scopes=args.locomo_scopes,
                    split=args.locomo_split,
                    question_limit=args.locomo_questions,
                    answerer_model=args.answerer_model,
                    db_path=tempfile.mkdtemp(),
                    keep_db=True,
                )
            else:
                from benchmarks.external.locomo.recall_scorer import build_locomo_dev_scorer

                adapter, locomo_scorer = build_locomo_dev_scorer(
                    args.locomo_dataset,
                    max_scopes=args.locomo_scopes,
                    split=args.locomo_split,
                    question_limit=args.locomo_questions,
                    db_path=tempfile.mkdtemp(),
                    keep_db=True,
                )
            scorers.append(locomo_scorer)
        if not scorers:
            print(json.dumps({"error": "no scorers: set --probe-sample > 0 or pass --locomo-dataset"}, indent=2))
            return
        try:
            report = run_cycle(runtime, runtime.store, scorers, auto_approve=args.auto_approve)
        finally:
            if adapter is not None:
                adapter.close()
        print(json.dumps(report, indent=2))
        return
    if args.command == "improve" and args.improve_command == "validate":
        run_validation = _import_run_paid_validation()
        if run_validation is None:
            print(json.dumps({"error": "seam improve validate requires a source checkout (tools/ is not shipped in the wheel)"}, indent=2))
            return
        from benchmarks.external.locomo.judged_scorer import (
            build_locomo_holdout_scorer,
            estimate_locomo_paid_validation,
        )
        from tools.h2.paid_validation import DEFAULT_JUDGED_NOISE_MARGIN

        split = None if args.split == "all" else args.split
        candidate_flags = None
        if args.flags is not None:
            try:
                candidate_flags = _parse_candidate_flags(args.flags)
            except (ValueError, json.JSONDecodeError) as exc:
                print(json.dumps({"error": f"invalid --flags: {exc}"}, indent=2))
                return
        if not args.confirm_paid:
            # Dry run: count what the validation would cost. No conversation is
            # ingested and no API client is constructed on this path.
            estimate = estimate_locomo_paid_validation(
                args.locomo_dataset,
                max_scopes=args.locomo_scopes,
                split=split,
                question_limit=args.locomo_questions,
            )
            estimate["dry_run"] = True
            estimate["note"] = (
                "no API calls were made; re-run with --confirm-paid to execute "
                "(one answerer call + up to one judge call per case per pass)"
            )
            print(json.dumps(estimate, indent=2))
            return
        import tempfile

        adapter, scorer = build_locomo_holdout_scorer(
            args.locomo_dataset,
            max_scopes=args.locomo_scopes,
            split=split,
            question_limit=args.locomo_questions,
            answerer=args.answerer,
            answerer_model=args.answerer_model,
            judge=args.judge,
            judge_model=args.judge_model,
            db_path=tempfile.mkdtemp(),
            keep_db=True,
        )
        try:
            report = run_validation(
                scorer,
                runtime.store,
                candidate_flags=candidate_flags,
                noise_margin=args.noise_margin if args.noise_margin is not None else DEFAULT_JUDGED_NOISE_MARGIN,
            )
        finally:
            adapter.close()
        print(json.dumps(report, indent=2))
        return
    if args.command == "mcp" and args.mcp_command == "stdio":
        from .mcp_protocol import run_mcp_server

        run_mcp_server(runtime)
        return
    if args.command == "mcp" and args.mcp_command == "serve":
        from .mcp import run_stdio_bridge

        run_stdio_bridge(runtime)
        return
    if args.command in {"compare", "hybrid-compare"}:
        orchestrator = _build_retrieval_orchestrator(runtime, args)
        search_result = runtime.search_ir(args.query, scope=args.scope, budget=args.budget).to_dict()
        retrieved = orchestrator.search(args.query, scope=args.scope, budget=args.budget, include_trace=args.trace, mode=args.mode).to_dict()
        _print_retrieval_output({"search": search_result, "retrieve": retrieved}, output_format=args.format, renderer=_render_compare_pretty)
        return
    if args.command in {"index", "rag-sync"}:
        orchestrator = _build_retrieval_orchestrator(runtime, args)
        payload = orchestrator.sync_persistent_indexes(
            record_ids=_split_ids(args.record_ids) if args.record_ids else None,
            scope=args.scope,
            namespace=args.namespace,
        )
        _print_retrieval_output(payload, output_format=args.format, renderer=_render_rag_sync_pretty)
        return
    if args.command in {"context", "rag-search"}:
        orchestrator = _build_retrieval_orchestrator(runtime, args)
        payload = build_context_payload(
            orchestrator.rag(
                args.query,
                scope=args.scope,
                budget=args.budget,
                pack_budget=args.pack_budget,
                lens=args.lens,
                mode=args.mode,
                include_trace=args.trace,
                retrieval_mode=args.retrieval_mode,
            ).to_dict(),
            view=args.view,
        )
        _print_retrieval_output(payload, output_format=args.format, renderer=render_context_pretty)
        return
    if args.command in {"shell", "chat"}:
        _run_agent_shell(
            runtime,
            once=args.once,
            budget=args.budget,
            pack_budget=args.pack_budget,
            retrieval_mode=args.retrieval_mode,
        )
        return
    if args.command == "dashboard":
        run_dashboard(
            runtime,
            vector_backend=args.vector_backend,
            vector_path=args.vector_path,
            vector_collection=args.vector_collection,
            snapshot=args.snapshot,
            commands=args.dashboard_commands,
            no_clear=args.no_clear,
        )
        return
    if args.command == "pack":
        print(json.dumps(runtime.pack_ir(record_ids=_split_ids(args.record_ids), lens=args.lens, budget=args.budget, mode=args.mode, persist=args.persist).to_dict(), indent=2))
        return
    if args.command == "decompile":
        print(runtime.decompile_ir(record_ids=_split_ids(args.record_ids), mode=args.mode))
        return
    if args.command == "trace":
        print(json.dumps(runtime.trace(args.obj_id).to_dict(), indent=2))
        return
    if args.command == "reconcile":
        record_ids = _split_ids(args.record_ids) if args.record_ids else None
        print(json.dumps(runtime.reconcile_ir(record_ids=record_ids).to_dict(), indent=2))
        return
    if args.command == "transpile":
        print(json.dumps(runtime.transpile_ir(record_ids=_split_ids(args.record_ids), target=args.target).to_dict(), indent=2))
        return
    if args.command == "reindex":
        record_ids = _split_ids(args.record_ids) if args.record_ids else None
        print(json.dumps(runtime.reindex_vectors(record_ids=record_ids), indent=2))
        return
    if args.command == "promote-symbols":
        record_ids = _split_ids(args.record_ids) if args.record_ids else None
        print(json.dumps(runtime.promote_symbols(record_ids=record_ids, min_frequency=args.min_frequency).to_dict(), indent=2))
        return
    if args.command == "export-symbols":
        print(runtime.export_symbols(namespace=args.namespace, output_path=args.output))
        return
    if args.command == "doctor":
        payload = _build_doctor_report()
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return
        print(_render_doctor_report(payload))
        return
    if args.command == "benchmark":
        if args.benchmark_command == "run":
            if args.holdout and not args.confirm_holdout:
                _confirm_holdout_run()
            payload = runtime.run_benchmark_suite(
                suite=args.suite,
                tokenizer=args.tokenizer,
                min_token_savings=args.min_savings,
                persist=args.persist,
                include_machine_text=args.include_machine_text,
                bundle_path=args.output,
                holdout=args.holdout,
            )
            holdout_output = None
            if args.holdout and args.output is None:
                holdout_output = write_holdout_benchmark_bundle(payload, args.holdout_output_dir)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(render_benchmark_pretty(payload))
            if holdout_output is not None:
                print(f"\nHoldout bundle: {holdout_output}")
            return
        if args.benchmark_command == "show":
            if args.run_id == "latest":
                runs = runtime.list_benchmark_runs(limit=1)
                if not runs:
                    raise SystemExit("No benchmark runs have been persisted yet.")
                run_id = str(runs[0]["run_id"])
            else:
                run_id = args.run_id
            payload = runtime.read_benchmark_run(run_id)
            if not payload:
                raise SystemExit(f"Benchmark run not found: {run_id}")
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(render_benchmark_pretty(payload))
            return
        if args.benchmark_command == "verify":
            payload = runtime.verify_benchmark_bundle(args.bundle)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(render_benchmark_verification_pretty(payload))
            return
        if args.benchmark_command == "diff":
            run_a = _resolve_benchmark_ref(runtime, args.run_a)
            run_b = _resolve_benchmark_ref(runtime, args.run_b)
            payload = runtime.diff_benchmark_runs(run_a, run_b)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
                return
            print(render_benchmark_diff_pretty(payload))
            return
        if args.benchmark_command == "gate":
            bundle = _resolve_benchmark_ref(runtime, args.bundle)
            if args.baseline:
                baseline = _resolve_benchmark_ref(runtime, args.baseline)
            else:
                current_run = Path(bundle) if isinstance(bundle, str) and Path(bundle).exists() else None
                policy_result = resolve_baseline(current_run=current_run)
                baseline = policy_result
                if baseline is None and args.format != "json":
                    print("note: no baseline found — first-run gate, skipping regression check")
            payload = runtime.evaluate_benchmark_gate(bundle, baseline=baseline, policy=args.policy)
            if args.format == "json":
                print(json.dumps(payload, indent=2))
            else:
                print(render_benchmark_gate_pretty(payload))
            if payload.get("status") != "PASS":
                raise SystemExit(1)
            return

        print(json.dumps(runtime.run_retrieval_benchmark(), indent=2))


def _split_ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _run_agent_shell(
    runtime: SeamRuntime,
    *,
    once: list[str] | None = None,
    budget: int = 5,
    pack_budget: int = 512,
    retrieval_mode: str = "mix",
) -> None:
    commands = list(once or [])
    if commands:
        for command in commands:
            response = _handle_shell_command(
                runtime,
                command,
                budget=budget,
                pack_budget=pack_budget,
                retrieval_mode=retrieval_mode,
            )
            if response is not None:
                print(response)
        return

    print("SEAM shell. Type /help for commands, /exit to quit.")
    while True:
        try:
            raw = input("seam> ")
        except EOFError:
            print()
            return
        response = _handle_shell_command(
            runtime,
            raw,
            budget=budget,
            pack_budget=pack_budget,
            retrieval_mode=retrieval_mode,
        )
        if response == "__exit__":
            return
        if response:
            print(response)


def _handle_shell_command(
    runtime: SeamRuntime,
    raw: str,
    *,
    budget: int,
    pack_budget: int,
    retrieval_mode: str,
) -> str | None:
    text = raw.strip()
    if not text:
        return None
    if text in {"/exit", "/quit", "exit", "quit"}:
        return "__exit__"
    if text in {"/help", "?"}:
        return "\n".join(
            [
                "SEAM shell commands:",
                "  /remember <text>  compile and persist memory",
                "  /search <query>   search compact memory records",
                "  /context <query>  build prompt-ready context",
                "  /stats            show store stats",
                "  /doctor           run install/runtime smoke checks",
                "  /exit             quit",
                "Natural text without a slash runs /context.",
            ]
        )

    command, _, argument = text.partition(" ")
    if command == "/remember":
        if not argument.strip():
            return "Usage: /remember <text>"
        batch = runtime.compile_nl(argument.strip(), source_ref="shell://remember")
        report = runtime.persist_ir(batch).to_dict()
        stored = report.get("stored_ids", [])
        return f"remembered {len(stored)} records: {', '.join(stored[:6])}"

    if command == "/search":
        query = argument.strip()
        if not query:
            return "Usage: /search <query>"
        payload = runtime.memory_search(query, budget=budget)
        return render_memory_index(payload)

    if command == "/context" or not text.startswith("/"):
        query = argument.strip() if command == "/context" else text
        if not query:
            return "Usage: /context <query>"
        from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
        orchestrator = RetrievalOrchestrator(runtime)
        rag_payload = orchestrator.rag(
            query,
            budget=budget,
            mode=retrieval_mode,
            include_trace=False,
        ).to_dict()
        if isinstance(rag_payload.get("pack"), dict):
            rag_payload["pack"]["budget"] = pack_budget
        payload = build_context_payload(rag_payload, view="prompt")
        return render_context_pretty(payload)

    if command == "/stats":
        stats = runtime.store.get_stats()
        return "\n".join(f"{key}: {value}" for key, value in sorted(stats.items()))

    if command == "/doctor":
        return _render_doctor_report(_build_doctor_report())

    return f"Unknown shell command: {command}. Type /help."


def _confirm_holdout_run() -> None:
    message = (
        "Holdout benchmark runs are publish-only and should not be used for routine tuning. "
        "Type RUN HOLDOUT to continue: "
    )
    if not sys.stdin.isatty():
        raise SystemExit("Holdout benchmark requires --confirm-holdout in non-interactive shells.")
    try:
        response = input(message).strip()
    except EOFError as exc:
        raise SystemExit("Holdout benchmark requires --confirm-holdout in non-interactive shells.") from exc
    if response != "RUN HOLDOUT":
        raise SystemExit("Holdout benchmark cancelled.")


def _resolve_benchmark_ref(runtime: SeamRuntime, value: str) -> str | dict[str, object]:
    if value == "latest":
        runs = runtime.list_benchmark_runs(limit=1)
        if not runs:
            raise SystemExit("No benchmark runs have been persisted yet.")
        value = str(runs[0]["run_id"])
    path = Path(value)
    if path.exists():
        return value
    try:
        payload = runtime.read_benchmark_run(value)
    except KeyError:
        raise SystemExit(f"Benchmark bundle or persisted run not found: {value}")
    return payload


def _read_text_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_bytes().decode("utf-8", errors="replace")


def _sha256_file(source: str) -> str | None:
    if source == "-":
        return None
    path = Path(source)
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_surface_path(surface_ref: str, runtime: SeamRuntime | None = None, db_path: str | None = None) -> Path:
    path = Path(surface_ref)
    if path.exists():
        return path
    if runtime is None:
        runtime = SeamRuntime(db_path or "seam.db")
    return Path(str(runtime.store.read_surface_artifact(surface_ref)["artifact_path"]))


def _store_surface_library_entry(
    runtime: SeamRuntime,
    artifact: dict[str, object],
    *,
    source_ref: str | None,
    source_sha256: str | None,
    stored_by: str,
    artifact_dir: str | None = None,
    copy_artifact: bool = True,
    import_status: str = "not_imported",
) -> dict[str, object]:
    artifact_payload = dict(artifact)
    metadata: dict[str, object] = {"stored_by": stored_by}
    if copy_artifact:
        redundant = SurfaceFileAdapter(artifact_dir).store_copy(
            str(artifact_payload["path"]),
            str(artifact_payload.get("surface_sha256") or ""),
        )
        metadata["redundant_copy"] = redundant.to_dict()
        artifact_payload["original_path"] = artifact_payload.get("path")
        artifact_payload["path"] = redundant.artifact_path
        artifact_payload["surface_sha256"] = redundant.surface_sha256
    return runtime.store.write_surface_artifact(
        artifact_payload,
        source_ref=source_ref,
        source_sha256=source_sha256,
        verification_status="PASS",
        import_status=import_status,
        metadata=metadata,
    )


def _repair_surface_library_entry(runtime: SeamRuntime, surface_ref: str, source_override: str | None = None) -> dict[str, object]:
    row = runtime.store.read_surface_artifact(surface_ref)
    source_path = source_override or _surface_repair_source(row)
    repair = SurfaceFileAdapter(Path(str(row["artifact_path"])).parent).repair_copy(
        str(row["artifact_path"]),
        surface_sha256=str(row["surface_sha256"]),
        source_path=source_path,
    )
    verification_status = "PASS" if repair.status == "PASS" else "FAIL"
    query_status = str(row["query_status"]) if repair.status == "PASS" else "unavailable"
    updated = runtime.store.update_surface_artifact_state(
        surface_ref,
        artifact_path=repair.artifact_path,
        verification_status=verification_status,
        query_status=query_status,
        metadata={"last_repair": repair.to_dict()},
    )
    return {"repair": repair.to_dict(), "surface": updated}


def _surface_repair_source(row: dict[str, object]) -> str | None:
    metadata = row.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    redundant = metadata.get("redundant_copy")
    if isinstance(redundant, dict) and redundant.get("source_path"):
        return str(redundant["source_path"])
    artifact = metadata.get("artifact")
    if isinstance(artifact, dict) and artifact.get("original_path"):
        return str(artifact["original_path"])
    return None


def _write_text_output(target: str, text: str) -> None:
    if target == "-":
        _print_text(text)
        return
    Path(target).write_bytes(text.encode("utf-8"))


def _print_text(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        print(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.write(b"\n")


def _render_lossless_demo_result(payload: dict[str, object]) -> str:
    if payload.get("mode") == "rebuild":
        return "\n".join(
            [
                "Demo: REBUILD PASS",
                f"Source machine text: {payload.get('source')}",
                f"Rebuilt output: {payload.get('output')}",
                f"Rebuilt bytes: {payload.get('output_bytes')}",
                f"SHA256: {payload.get('sha256')}",
                f"Integrity: {payload.get('integrity')}",
            ]
        )

    lines = [
        f"Demo: {'PASS' if payload.get('passed') else 'FAIL'}",
        f"Source document: {payload.get('source')}",
        f"Compressed output: {payload.get('output')}",
    ]
    if payload.get("log_output"):
        lines.append(f"Log output: {payload.get('log_output')}")
    lines.extend(["", render_lossless_benchmark_pretty(payload)])
    return "\n".join(lines)


def _render_readable_query_pretty(payload: dict[str, object]) -> str:
    lines = [
        "Readable query results",
        f"Source: {payload.get('source_ref')}",
        f"SHA256: {payload.get('sha256')}",
        f"Query: {payload.get('query')}",
    ]
    hits = payload.get("hits", [])
    if not hits:
        lines.append("No direct compressed-language hits.")
        return "\n".join(lines)
    for index, hit in enumerate(hits, start=1):
        reasons = ", ".join(str(reason) for reason in hit.get("reasons", []))
        span = ""
        if hit.get("start") is not None and hit.get("end") is not None:
            span = f" span={hit.get('start')}..{hit.get('end')}"
        lines.append(
            f"{index}. {hit.get('record_type')} {hit.get('record_id')} score={hit.get('score')}{span}"
        )
        if reasons:
            lines.append(f"   reasons={reasons}")
        lines.append(f"   {str(hit.get('text', '')).rstrip()}")
    return "\n".join(lines)


def _render_surface_artifact_pretty(payload: dict[str, object]) -> str:
    lines = [
        "Holographic surface written",
        f"Path: {payload.get('path')}",
        f"Mode: {payload.get('mode')}",
        f"Payload: {payload.get('payload_format')} {payload.get('payload_bytes')} bytes",
        f"SHA256: {payload.get('payload_sha256')}",
        f"Surface: {payload.get('width')}x{payload.get('height')} {payload.get('surface_bytes')} bytes",
    ]
    library = payload.get("library")
    if isinstance(library, dict):
        lines.append(f"Library id: {library.get('surface_id')}")
    return "\n".join(lines)


def _render_surface_compile_pretty(payload: dict[str, object]) -> str:
    surface = payload.get("surface", {})
    surface_payload = surface if isinstance(surface, dict) else {}
    stored_ids = payload.get("stored_ids", [])
    lines = [
        "Holographic surface compiled",
        f"Source: {payload.get('source_ref')}",
        f"Path: {surface_payload.get('path')}",
        f"Mode: {surface_payload.get('mode')}",
        f"Payload: MIRL {surface_payload.get('payload_bytes')} bytes",
        f"Records: {payload.get('record_count')}",
        f"SHA256: {surface_payload.get('payload_sha256')}",
        f"Stored ids: {', '.join(str(item) for item in stored_ids) if stored_ids else '(not persisted)'}",
    ]
    library = payload.get("library")
    if isinstance(library, dict):
        lines.append(f"Library id: {library.get('surface_id')}")
    return "\n".join(lines)


def _render_surface_verify_pretty(payload: dict[str, object]) -> str:
    lines = [
        f"Holographic surface verify: {payload.get('status')}",
        f"Path: {payload.get('path')}",
        f"Mode: {payload.get('mode')}",
        f"Payload: {payload.get('payload_format')} {payload.get('payload_bytes')} bytes",
        f"SHA256: {payload.get('payload_sha256')}",
    ]
    errors = payload.get("errors", [])
    if errors:
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def _render_surface_query_pretty(payload: dict[str, object]) -> str:
    lines = [
        "Holographic surface query",
        f"Source: {payload.get('source_path')}",
        f"Payload: {payload.get('payload_format')}",
        f"Query: {payload.get('query')}",
    ]
    hits = payload.get("hits", [])
    if not hits:
        lines.append("No direct surface hits.")
        return "\n".join(lines)
    for index, hit in enumerate(hits, start=1):
        lines.append(f"{index}. {hit.get('record_type')} {hit.get('record_id')} score={hit.get('score')}")
        reasons = ", ".join(str(reason) for reason in hit.get("reasons", []))
        if reasons:
            lines.append(f"   reasons={reasons}")
        lines.append(f"   {str(hit.get('text', '')).rstrip()}")
    return "\n".join(lines)


def _render_surface_context_pretty(payload: dict[str, object]) -> str:
    context = payload.get("context", {})
    lines = [
        "Holographic surface context",
        f"Source: {payload.get('source_path')}",
        f"Payload: {payload.get('payload_format')}",
        f"Query: {payload.get('query')}",
    ]
    if isinstance(context, dict) and "payload" in context:
        lines.append(json.dumps(context["payload"], indent=2))
    elif isinstance(context, dict) and "snippets" in context:
        lines.extend(str(snippet) for snippet in context.get("snippets", []))
    else:
        lines.append(json.dumps(context, indent=2))
    return "\n".join(lines)


def _render_surface_import_pretty(payload: dict[str, object]) -> str:
    surface = payload.get("surface", {})
    lines = [
        "Holographic surface import complete",
        f"Payload: {surface.get('payload_format') if isinstance(surface, dict) else '(unknown)'}",
    ]
    if "stored_ids" in payload:
        lines.append(f"Stored ids: {', '.join(str(item) for item in payload.get('stored_ids', []))}")
    if "artifact_id" in payload:
        lines.append(f"Artifact id: {payload.get('artifact_id')}")
    library = payload.get("library")
    if isinstance(library, dict):
        lines.append(f"Library id: {library.get('surface_id')}")
        lines.append(f"Import status: {library.get('import_status')}")
    return "\n".join(lines)


def _render_surface_library_entry_pretty(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "Holographic surface library entry",
            f"ID: {payload.get('surface_id')}",
            f"Path: {payload.get('artifact_path')}",
            f"Mode: {payload.get('mode')}",
            f"Payload: {payload.get('payload_format')} {payload.get('payload_bytes')} bytes",
            f"Payload SHA256: {payload.get('payload_sha256')}",
            f"Surface SHA256: {payload.get('surface_sha256')}",
            f"Verification: {payload.get('verification_status')}",
            f"Query: {payload.get('query_status')}",
            f"Import: {payload.get('import_status')}",
            f"Source: {payload.get('source_ref') or '(none)'}",
        ]
    )


def _render_surface_library_list_pretty(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "No stored holographic surfaces."
    lines = ["Holographic surface library"]
    for row in rows:
        lines.append(
            f"- {row.get('surface_id')} {row.get('payload_format')} {row.get('mode')} "
            f"{row.get('verification_status')} {row.get('query_status')} {row.get('artifact_path')}"
        )
    return "\n".join(lines)


def _render_surface_repair_pretty(payload: dict[str, object]) -> str:
    repair = payload.get("repair", {})
    surface = payload.get("surface", {})
    repair_payload = repair if isinstance(repair, dict) else {}
    surface_payload = surface if isinstance(surface, dict) else {}
    lines = [
        "Holographic surface repair",
        f"ID: {surface_payload.get('surface_id')}",
        f"Status: {repair_payload.get('status')}",
        f"Action: {repair_payload.get('action')}",
        f"Path: {repair_payload.get('artifact_path')}",
        f"Source: {repair_payload.get('source_path') or '(none)'}",
        f"Verification: {surface_payload.get('verification_status')}",
        f"Query: {surface_payload.get('query_status')}",
    ]
    errors = repair_payload.get("errors", [])
    if errors:
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def _render_ingest_report(payload: dict[str, object]) -> str:
    document = payload.get("document", {})
    stored_ids = payload.get("stored_ids", [])
    return "\n".join(
        [
            f"Ingested: {document.get('source_ref')}",
            f"Document: {document.get('document_id')}",
            f"Bytes: {document.get('byte_count')}",
            f"Chunks: {document.get('chunk_count')}",
            f"Extraction: {document.get('extraction_status')}",
            f"Index: {document.get('indexed_status')}",
            f"Stored ids: {', '.join(stored_ids) if stored_ids else '(none)'}",
        ]
    )


_build_doctor_report = build_doctor_report  # backwards-compatible alias for callers in this module
_check_pgvector = check_pgvector  # backwards-compatible alias


def _render_doctor_report(payload: dict[str, object]) -> str:
    dependency_lines = [
        f"- {name}: {'installed' if installed else 'missing'}"
        for name, installed in payload.get("dependencies", {}).items()
    ]
    pgvector = payload.get("pgvector", {})
    if pgvector.get("configured"):
        pg_line = f"PgVector: {'reachable' if pgvector.get('reachable') else 'configured but unreachable'}"
        if not pgvector.get("reachable") and pgvector.get("error"):
            pg_line += f" ({pgvector['error']})"
    else:
        pg_line = "PgVector: not configured (set SEAM_PGVECTOR_DSN to enable)"
    gate = payload.get("commit_gate", {}) or {}
    gate_status = gate.get("status", "unknown")
    if gate_status == "PASS":
        commit_gate_line = f"Commit gate: PASS ({gate.get('mode')})"
    elif gate_status == "not-installed":
        commit_gate_line = f"Commit gate: not installed (run {gate.get('install_cmd')})"
    elif gate_status == "drift":
        commit_gate_line = f"Commit gate: drift ({gate.get('mode')}; run {gate.get('install_cmd')})"
    elif gate_status == "not-a-git-repo":
        commit_gate_line = "Commit gate: skipped (not a git repo)"
    elif gate_status == "source-missing":
        commit_gate_line = f"Commit gate: source missing ({gate.get('source')})"
    else:
        commit_gate_line = f"Commit gate: {gate_status}"
    streams = payload.get("streams", {}) or {}
    streams_status = streams.get("status", "unknown")
    if streams_status == "PASS":
        streams_line = "Streams: PASS"
    elif streams_status == "FAIL":
        errs = streams.get("errors", []) or []
        first = errs[0] if errs else ""
        streams_line = f"Streams: FAIL ({len(errs)} issue(s); first: {first})"
    elif streams_status == "unavailable":
        streams_line = f"Streams: unavailable ({streams.get('error','?')})"
    else:
        streams_line = f"Streams: {streams_status}"
    stashes = payload.get("stashes", {}) or {}
    stashes_status = stashes.get("status", "unknown")
    if stashes_status == "clean":
        stashes_line = "Stashes: none"
    elif stashes_status == "advisory":
        entries = stashes.get("stashes", []) or []
        ages = [s.get("age_days") for s in entries if isinstance(s.get("age_days"), int)]
        oldest = max(ages) if ages else 0
        stashes_line = (
            f"Stashes: {stashes.get('count', len(entries))} present (oldest {oldest}d) — "
            "review abandoned WIP (git stash list)"
        )
    elif stashes_status == "not-a-git-repo":
        stashes_line = "Stashes: skipped (not a git repo)"
    else:
        stashes_line = f"Stashes: {stashes_status}"
    return "\n".join(
        [
            f"SEAM doctor: {payload.get('status')}",
            f"Python: {payload.get('python')}",
            f"DB mode: {payload.get('db_mode')}",
            f"Default DB: {payload.get('default_db_path')}",
            f"Compile smoke: {payload.get('smoke_compile', {}).get('status')} ({payload.get('smoke_compile', {}).get('record_count')} records)",
            (
                "Lossless smoke: "
                f"{payload.get('lossless', {}).get('status')} "
                f"({payload.get('lossless', {}).get('token_savings_ratio')} savings, "
                f"estimator={payload.get('lossless', {}).get('token_estimator')})"
            ),
            pg_line,
            commit_gate_line,
            streams_line,
            stashes_line,
            (
                "Required deps: OK"
                if not payload.get("missing_required_dependencies")
                else f"Required deps: missing ({', '.join(payload.get('missing_required_dependencies', []))})"
            ),
            "Dependencies:",
            *dependency_lines,
        ]
    )


def _add_retrieval_common_args(parser: argparse.ArgumentParser, include_backend: bool = True) -> None:
    parser.add_argument("--scope")
    parser.add_argument("--budget", type=int, default=5)
    parser.add_argument("--mode", choices=["vector", "graph", "hybrid", "mix"], default="hybrid")
    parser.add_argument("--format", choices=["pretty", "json", "ids"], default="pretty")
    parser.add_argument("--trace", action="store_true")
    if include_backend:
        parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
        parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
        parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")


def _add_rag_sync_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--index", "--rag-sync", dest="sync_index", action="store_true")
    parser.add_argument("--vector-backend", "--semantic-backend", dest="vector_backend", choices=["seam", "chroma"], default="seam")
    parser.add_argument("--vector-path", "--chroma-path", dest="vector_path", default=".seam_chroma")
    parser.add_argument("--vector-collection", "--chroma-collection", dest="vector_collection", default="seam_hybrid")


def _build_retrieval_orchestrator(runtime: SeamRuntime, args: argparse.Namespace):
    from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
    return RetrievalOrchestrator(
        runtime,
        semantic_backend=getattr(args, "vector_backend", "seam"),
        chroma_path=getattr(args, "vector_path", ".seam_chroma"),
        chroma_collection=getattr(args, "vector_collection", "seam_hybrid"),
    )


def _print_retrieval_output(payload: dict[str, object], output_format: str, renderer) -> None:
    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return
    if output_format == "ids":
        print(_render_ids(payload))
        return
    print(renderer(payload))


def _render_plan_pretty(payload: dict[str, object]) -> str:
    filters = payload.get("filters", {})
    legs = payload.get("legs", [])
    active_filters = [f"{key}={value}" for key, value in filters.items() if value not in (None, [], "")]
    lines = [
        f"Intent: {payload.get('intent')}",
        f"Query: {payload.get('query')}",
        f"Normalized: {payload.get('normalized_query') or '(none)'}",
        f"Filters: {', '.join(active_filters) if active_filters else '(none)'}",
        "Legs:",
    ]
    for leg in legs:
        lines.append(f"- {leg['name']} (limit={leg['limit']}): {leg['rationale']}")
    return "\n".join(lines)


def _render_search_pretty(payload: dict[str, object]) -> str:
    lines = [
        f"Intent: {payload.get('intent')}",
        f"Query: {payload.get('query')}",
        f"Normalized: {payload.get('normalized_query') or '(none)'}",
        "Candidates:",
    ]
    candidates = payload.get("candidates", [])
    if not candidates:
        lines.append("(none)")
    for index, candidate in enumerate(candidates, start=1):
        record = candidate["record"]
        source_text = ", ".join(f"{name}={score:.2f}" for name, score in candidate.get("sources", {}).items())
        lines.append(f"{index}. {record['id']} [{record['kind']}] score={candidate['score']:.3f} sources={source_text or '(none)'}")
        signal = _record_signal(record)
        if signal:
            lines.append(f"   {signal}")
    if payload.get("trace"):
        lines.append("Trace: included")
    return "\n".join(lines)


def _render_compare_pretty(payload: dict[str, object]) -> str:
    base_search = payload.get("search", {})
    retrieval = payload.get("retrieve", {})
    search_ids = ", ".join(candidate["record"]["id"] for candidate in base_search.get("candidates", [])) or "(none)"
    retrieval_ids = ", ".join(candidate["record"]["id"] for candidate in retrieval.get("candidates", [])) or "(none)"
    return "\n".join(
        [
            f"Query: {retrieval.get('query') or base_search.get('query')}",
            f"Search: {search_ids}",
            f"Retrieve: {retrieval_ids}",
            f"Retrieval intent: {retrieval.get('intent')}",
            "Use --format json for full scores and trace payloads.",
        ]
    )


def _render_rag_sync_pretty(payload: dict[str, object]) -> str:
    sqlite_ids = payload.get("sqlite_indexed", [])
    return "\n".join(
        [
            f"Backend: {payload.get('backend')}",
            f"SQLite indexed: {len(sqlite_ids)}",
            f"Chroma indexed: {payload.get('chroma_indexed', 0)}",
            f"Record ids: {', '.join(payload.get('record_ids', [])) or '(none)'}",
        ]
    )


def _render_ids(payload: dict[str, object]) -> str:
    if "search" in payload and "retrieve" in payload:
        search_ids = " ".join(candidate["record"]["id"] for candidate in payload["search"].get("candidates", []))
        retrieval_ids = " ".join(candidate["record"]["id"] for candidate in payload["retrieve"].get("candidates", []))
        return f"search: {search_ids}\nretrieve: {retrieval_ids}".strip()
    if "records" in payload:
        return "\n".join(payload.get("candidate_ids", []))
    if "candidates" in payload:
        return "\n".join(candidate["record"]["id"] for candidate in payload.get("candidates", []))
    if "candidate_ids" in payload:
        return "\n".join(payload.get("candidate_ids", []))
    if "results" in payload:
        return "\n".join(str(item.get("id")) for item in payload.get("results", []))
    if "legs" in payload:
        return "\n".join(leg["name"] for leg in payload.get("legs", []))
    if "record_ids" in payload:
        return "\n".join(payload.get("record_ids", []))
    return ""


def _render_lx1_benchmark_pretty(report: dict[str, object]) -> str:
    return "\n".join([
        "LX/1 notation benchmark",
        f"Original MIRL tokens : {report.get('original_tokens')}",
        f"LX/1 compact tokens  : {report.get('compact_tokens')}",
        f"Token savings        : {float(report.get('token_savings_ratio', 0)):.1%}",
        f"Intelligence/token   : {float(report.get('intelligence_per_token_gain', 0)):.2f}x",
        f"Original chars       : {report.get('original_chars')}",
        f"LX/1 chars           : {report.get('compact_chars')}",
        f"Char savings         : {float(report.get('char_savings_ratio', 0)):.1%}",
    ])


def _render_bil_integrity_pretty(report: dict[str, object]) -> str:
    bil = report.get("bil") if isinstance(report.get("bil"), dict) else {}
    verification = report.get("verification") if isinstance(report.get("verification"), dict) else None
    lines = [
        f"SEAM benchmark integrity: {report.get('status')}",
        f"BIL: {bil.get('level')}",
        f"Sealed: {bil.get('sealed')}",
    ]
    if bil.get("result_hash"):
        lines.append(f"Result hash: {bil.get('result_hash')}")
    if bil.get("input_manifest_hash"):
        lines.append(f"Input manifest hash: {bil.get('input_manifest_hash')}")
    if verification:
        failed = [check for check in verification.get("checks", []) if check.get("status") != "PASS"]
        lines.append(f"Verification checks: {len(verification.get('checks', [])) - len(failed)}/{len(verification.get('checks', []))} passed")
        for check in failed[:10]:
            lines.append(f"- {check.get('id')}: {check.get('message')}")
    return "\n".join(lines)


def _current_git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _render_publication_readiness_pretty(report: dict[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        f"Publication readiness: {'READY' if report.get('ready') else 'BLOCKED'}",
        f"Checks: {summary.get('passed', 0)} passed, {summary.get('warned', 0)} warned, {summary.get('failed', 0)} failed",
    ]
    for check in report.get("checks", []) if isinstance(report.get("checks"), list) else []:
        if check.get("status") != "PASS":
            lines.append(f"- [{check.get('status')}] {check.get('id')}: {check.get('message')}")
    blocked_by = report.get("publication_blocked_by") or []
    if blocked_by:
        lines.append(f"Blocked by: {', '.join(blocked_by)}")
    return "\n".join(lines)


def _record_signal(record: dict[str, object]) -> str:
    attrs = record.get("attrs", {})
    if "predicate" in attrs or "object" in attrs:
        return f"{attrs.get('subject', '')} {attrs.get('predicate', '')} {attrs.get('object', '')}".strip()
    if "target" in attrs:
        return f"target={attrs.get('target')}"
    return ""
