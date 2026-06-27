import json
import os
import subprocess
import sys
import tempfile
import time
import asyncio
import unittest
from contextlib import redirect_stdout
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from seam_runtime.retrieval_orchestrator import ChromaSemanticAdapter, QueryIntent, RetrievalOrchestrator
from seam_runtime.retrieval_orchestrator.adapters import SQLiteIRAdapter
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam import SeamRuntime, compile_dsl, compile_nl, decompile_ir, load_ir_lines, pack_ir, render_ir, unpack_pack
from seam_runtime import benchmarks as benchmark_module
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.reconcile import reconcile_ir
from seam_runtime import installer as installer_module
from seam_runtime.cli import run_cli
from seam_runtime.dashboard import DEFAULT_CHAT_MODELS, SeamChatClient, TextualDashboardApp, _write_private_text_file, run_dashboard
from seam_runtime.installer import (
    InstallLayout,
    PATH_MARKER_BEGIN,
    _ensure_posix_shell_profiles,
    _powershell_single_quoted,
    default_runtime_db_path,
    detect_layout,
    install_repo,
    path_in_environment,
    render_posix_shim,
    render_windows_cmd_shim,
    write_shims,
)
from seam_runtime.lossless import (
    benchmark_text_lossless,
    compress_text_lossless,
    compress_text_readable,
    decompress_text_lossless,
    decompress_text_readable,
    query_readable_compressed,
)
from seam_runtime.holographic import (
    decode_surface,
    encode_surface,
    query_surface,
    verify_surface,
)
from seam_runtime.models import (
    HashEmbeddingModel,
    OpenAICompatibleEmbeddingModel,
    SentenceTransformerModel,
    cosine,
    default_embedding_model,
)
from seam_runtime.mcp import dispatch_tool
from seam_runtime.pack import score_pack, unpack_exact_pack
from seam_runtime.symbols import build_symbol_maps, namespace_chain
from seam_runtime.ui.animations import AnimationEngine
from seam_runtime.vector import INDEXABLE_KINDS
from seam_runtime.vector_adapters import PgVectorAdapter
from seam_runtime.verify import verify_ir

try:
    from rich.console import Console
except ImportError:  # pragma: no cover - optional at import time
    Console = None

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - optional server extra
    TestClient = None


TEST_ARTIFACT_DIR = Path("test_seam")


def _claim_ids(text: str) -> list[str]:
    """The CLM ids the compiler emits for ``text``. Compiler record ids are
    content-derived (``clm:<hash>:<n>``), so this matches what persist/search
    will surface — use it instead of hardcoding ids that change with the input."""
    return [record.id for record in compile_nl(text).records if record.kind == RecordKind.CLM]


def _claim_refs(text: str) -> tuple[str, str, str]:
    """``(claim_id, prov_id, span_id)`` for the first claim ``text`` compiles to."""
    batch = compile_nl(text)
    claim = next(record for record in batch.records if record.kind == RecordKind.CLM)
    return claim.id, claim.prov[0], claim.evidence[0]


class SeamTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_ARTIFACT_DIR.mkdir(exist_ok=True)
        self.db_path = TEST_ARTIFACT_DIR / f"test_seam_{uuid4().hex}.db"
        # Default isolation: assume SQLite vector backend unless a test opts in.
        # Operator may export SEAM_PGVECTOR_DSN; that's for adapter-specific tests
        # in tests/audit/, not for SeamTests which exercise the default backend.
        self._pgvector_dsn_backup = os.environ.pop("SEAM_PGVECTOR_DSN", None)

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except PermissionError:
            pass
        if self._pgvector_dsn_backup is not None:
            os.environ["SEAM_PGVECTOR_DSN"] = self._pgvector_dsn_backup

    def test_compile_generates_core_records(self) -> None:
        text = (
            "We want to design a language for AI that permanently remembers things. "
            "It should work for databases, RAG pipelines, and context windows. "
            "The goal is to compress information to the simplest form possible without losing meaning."
        )
        records = compile_nl(text)
        ir = render_ir(records)
        # The floor's core records: one verbatim RAW, a PROV, per-proposition
        # SPAN+CLAIM, and high-confidence entities. NO fabricated project/user.
        self.assertIn("RAW|raw:", ir)
        self.assertIn("PROV|prov:compile:", ir)
        self.assertIn("CLM|clm:", ir)
        self.assertIn("ENT|ent:", ir)
        self.assertNotIn("ent:project:", ir)
        self.assertNotIn("ent:user:", ir)
        # Three sentences -> one verbatim "content" claim each (the floor base);
        # the unified compiler may add grounded conversational enrichment claims
        # on top, so count the content claims specifically.
        claims = [r for r in records.records if r.kind == RecordKind.CLM]
        content_claims = [c for c in claims if c.attrs.get("predicate") == "content"]
        self.assertEqual(len(content_claims), 3)
        self.assertIn("permanently remembers things", content_claims[0].attrs["object"])
        # Every claim subject is a grounded ENT (no fabricated project:SEAM).
        ent_ids = {r.id for r in records.records if r.kind == RecordKind.ENT}
        for c in claims:
            self.assertIn(c.attrs.get("subject"), ent_ids)

    def test_exact_pack_round_trips(self) -> None:
        text = "Build durable AI memory for databases and context windows without losing meaning."
        batch = compile_nl(text)
        pack = pack_ir(batch, lens="design", mode="exact")
        unpacked = unpack_exact_pack(pack)
        self.assertEqual(batch.to_json(), unpacked.to_json())

    def test_context_pack_refs_match_budgeted_entries(self) -> None:
        records = [
            MIRLRecord(
                id=f"clm:{index}",
                kind=RecordKind.CLM,
                attrs={"subject": f"subject:{index}", "predicate": "needs", "object": "memory"},
            )
            for index in range(3)
        ]
        pack = pack_ir(IRBatch(records), budget=60)
        # Dense context entries no longer repeat their own id - it is carried once
        # in refs (refs[i] is the id of entries[i]). refs lists exactly the entries
        # that fit the budget.
        self.assertEqual(pack.refs, pack.payload["refs"])
        self.assertEqual(len(pack.refs), len(pack.payload["entries"]))
        self.assertTrue(pack.refs and set(pack.refs) <= {f"clm:{i}" for i in range(3)})
        self.assertNotIn("id", pack.payload["entries"][0])

    def test_context_pack_resolves_subject_to_label(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("Priya owns the billing service.")
        pack = pack_ir(batch, budget=1_000_000)
        clm = next(e for e in pack.payload["entries"] if e.get("kind") == "CLM")
        subject = str(clm["signal"].get("subject", ""))
        # The claim subject is the entity LABEL (readable), not an opaque ent:... id.
        self.assertNotIn("ent:", subject)
        self.assertNotIn("id", clm)  # dense: no repeated per-entry id

    def test_compile_nl_no_regex_enrichment_by_default(self) -> None:
        # HISTORY#317: the regex enrichment (location/date/went_to/felt) is OFF by
        # default - it mislabeled ~25% of real prose for zero LoCoMo recall benefit.
        # The floor emits ONLY the faithful content claim (+ proper-noun entities);
        # structured triples come from the opt-in grounded extractor.
        import os
        os.environ.pop("SEAM_NL_REGEX_ENRICH", None)
        batch = compile_nl("Bob is allergic to peanuts and shellfish on Monday in Denver.")
        preds = {r.attrs.get("predicate") for r in batch.records if r.kind.value == "CLM"}
        self.assertEqual(preds, {"content"}, f"floor must emit only content claims, got {preds}")
        # ...and the legacy path is recoverable via the flag.
        os.environ["SEAM_NL_REGEX_ENRICH"] = "1"
        try:
            enriched = compile_nl("Bob is allergic to peanuts and shellfish on Monday in Denver.")
            enriched_preds = {r.attrs.get("predicate") for r in enriched.records if r.kind.value == "CLM"}
            self.assertTrue(enriched_preds - {"content"}, "flag should re-enable enrichment claims")
        finally:
            os.environ.pop("SEAM_NL_REGEX_ENRICH", None)

    def test_context_pack_is_content_only(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("Priya owns the billing service.")
        pack = pack_ir(batch, budget=1_000_000)
        kinds = {entry["kind"] for entry in pack.payload["entries"]}
        # A context pack carries only meaning-bearing records (the LLM reasons over
        # these); RAW/PROV/SPAN/ENT are structural and live in the store, not the prompt.
        self.assertTrue(kinds <= {"CLM", "STA", "EVT", "REL"}, kinds)
        self.assertTrue(any(entry["kind"] == "CLM" for entry in pack.payload["entries"]))

    def test_context_pack_factors_prov_evidence_ids_reversibly(self) -> None:
        runtime = SeamRuntime(self.db_path)
        # One document -> all claims share one prov/span hash, so the long hash
        # segment repeats across prov+evidence and the id-alias table fires.
        batch = runtime.compile_nl(
            "Priya owns the billing service. The billing service depends on the payments gateway. "
            "Marcus leads the platform team. Priya reports to Marcus."
        )
        pack = pack_ir(batch, budget=1_000_000)
        idsym = pack.payload.get("idsym", {})
        self.assertTrue(idsym, "expected an id-alias table when prov/evidence hashes repeat")
        # Every alias symbol lives in the reserved `$` namespace (collision-safe: no
        # real id segment starts with `$`).
        self.assertTrue(all(symbol.startswith("$") for symbol in idsym))
        encoded_prov = [value for entry in pack.payload["entries"] for value in entry["prov"]]
        self.assertTrue(any("$" in value for value in encoded_prov), encoded_prov)
        # Reversible: score_pack decodes the aliases back to the full ids, so a
        # faithful pack still earns full prov/evidence retention (traceability holds).
        score = score_pack(pack, batch.records)
        self.assertEqual(score["provenance_retention"], 1.0)
        self.assertEqual(score["evidence_retention"], 1.0)

    def test_verifier_rejects_missing_claim_fields(self) -> None:
        batch = compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
"""
        )
        report = verify_ir(batch)
        self.assertFalse(report.valid)
        codes = {issue.code for issue in report.issues}
        self.assertIn("missing_claim_field", codes)


    def test_runtime_persist_search_trace(self) -> None:
        text = (
            "We want a universal AI memory language for databases, RAG pipelines, and context windows. "
            "It should translate back into natural language without losing meaning."
        )
        claim_id, prov_id, span_id = _claim_refs(text)
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(text))
        result = runtime.search_ir("translator natural language", budget=3)
        self.assertTrue(result.candidates)
        trace = runtime.trace(claim_id)
        node_ids = {node.id for node in trace.nodes}
        self.assertIn(prov_id, node_ids)
        self.assertIn(span_id, node_ids)

    def test_trace_loads_only_reachable_records(self) -> None:
        text = (
            "We want a universal AI memory language for databases, RAG pipelines, and context windows. "
            "It should translate back into natural language without losing meaning."
        )
        claim_id, prov_id, span_id = _claim_refs(text)
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(text))
        with patch.object(runtime.store, "load_ir", side_effect=AssertionError("trace must not load the full DB")):
            trace = runtime.trace(claim_id)
        node_ids = {node.id for node in trace.nodes}
        self.assertIn(prov_id, node_ids)
        self.assertIn(span_id, node_ids)

    def test_store_load_ir_supports_stable_pagination(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = IRBatch(
            [
                MIRLRecord(id="rec:003", kind=RecordKind.ENT, attrs={"label": "three"}),
                MIRLRecord(id="rec:001", kind=RecordKind.ENT, attrs={"label": "one"}),
                MIRLRecord(id="rec:002", kind=RecordKind.ENT, attrs={"label": "two"}),
            ]
        )
        runtime.store.persist_ir(batch)

        first_page = runtime.store.load_ir(limit=2)
        second_page = runtime.store.load_ir(limit=2, offset=2)

        self.assertEqual([record.id for record in first_page.records], ["rec:001", "rec:002"])
        self.assertEqual([record.id for record in second_page.records], ["rec:003"])
        self.assertEqual(runtime.store.load_ir(limit=2, offset=10).records, [])
        with self.assertRaisesRegex(ValueError, "limit must be non-negative"):
            runtime.store.load_ir(limit=-1)

    def test_ir_batch_from_text_reports_malformed_line_number(self) -> None:
        text = '{"not":"mirl"}\nBAD-LINE'

        with self.assertRaisesRegex(ValueError, "MIRL line 1"):
            IRBatch.from_text(text)

    def test_runtime_persist_rolls_back_record_write_when_vector_indexing_fails(self) -> None:
        class FailingVectorAdapter:
            name = "failing-vector"

            def index_records(self, records):
                raise RuntimeError("vector backend unavailable")

            def search(self, query: str, limit: int = 10) -> dict[str, float]:
                return {}

        runtime = SeamRuntime(self.db_path, vector_adapter=FailingVectorAdapter())
        batch = runtime.compile_nl("SEAM should not commit canonical records when required indexing fails.")
        record_ids = [record.id for record in batch.records]
        with self.assertRaisesRegex(RuntimeError, "Vector indexing failed"):
            runtime.persist_ir(batch)
        self.assertEqual(runtime.store.load_ir(ids=record_ids).records, [])

    def test_runtime_persist_rollback_preserves_existing_records_and_vectors(self) -> None:
        class FailingVectorAdapter:
            name = "failing-vector"

            def index_records(self, records):
                raise RuntimeError("vector backend unavailable")

            def search(self, query: str, limit: int = 10) -> dict[str, float]:
                return {}

        runtime = SeamRuntime(self.db_path)
        original = runtime.compile_nl("SEAM keeps indexed records consistent when overwrites fail.")
        runtime.persist_ir(original)
        original_by_id = {record.id: record.to_dict() for record in original.records}
        self.assertGreater(runtime.store.get_stats()["vector_entries"], 0)

        replacement = runtime.compile_nl("Different content should not replace records if indexing fails.")
        runtime.vector_adapter = FailingVectorAdapter()
        with self.assertRaisesRegex(RuntimeError, "Vector indexing failed"):
            runtime.persist_ir(replacement)

        restored = runtime.store.load_ir(ids=[record.id for record in original.records])
        self.assertEqual({record.id: record.to_dict() for record in restored.records}, original_by_id)
        self.assertGreater(runtime.store.get_stats()["vector_entries"], 0)

    def test_runtime_persist_reports_ids_when_sqlite_rollback_fails(self) -> None:
        class FailingVectorAdapter:
            name = "failing-vector"

            def index_records(self, records):
                raise RuntimeError("vector backend unavailable")

            def search(self, query: str, limit: int = 10) -> dict[str, float]:
                return {}

        runtime = SeamRuntime(self.db_path)
        text = "SEAM keeps enough context for manual rollback recovery."
        original = runtime.compile_nl(text)
        runtime.persist_ir(original)
        # Re-persisting the SAME document overwrites its records (compiler ids are
        # content-derived), so the rollback path must restore the PREVIOUS records
        # — and it is that restore we make fail, to reach "manual recovery".
        replacement = runtime.compile_nl(text)
        original_persist_ir = runtime.store.persist_ir
        calls = 0

        def flaky_persist(batch):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("restore unavailable")
            return original_persist_ir(batch)

        runtime.vector_adapter = FailingVectorAdapter()
        runtime.store.persist_ir = flaky_persist  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "manual recovery may be required") as ctx:
            runtime.persist_ir(replacement)
        for record in replacement.records[:2]:
            self.assertIn(record.id, str(ctx.exception))

    @unittest.skipIf(TestClient is None, "fastapi server extra is not installed")
    def test_rest_api_compile_search_context_stats_and_auth(self) -> None:
        from seam_runtime.server import create_app

        runtime = SeamRuntime(self.db_path)
        with patch.dict(os.environ, {"SEAM_API_TOKEN": "test-token"}, clear=False):
            client = TestClient(create_app(runtime))

        self.assertEqual(client.get("/health").json()["status"], "ok")
        self.assertEqual(client.get("/stats").status_code, 401)

        headers = {"Authorization": "Bearer test-token"}
        compile_response = client.post(
            "/compile",
            json={"text": "SEAM stores durable memory for agent retrieval.", "persist": True},
            headers=headers,
        )
        self.assertEqual(compile_response.status_code, 200)
        self.assertTrue(compile_response.json()["records"])
        self.assertTrue(compile_response.json()["persist"]["stored_ids"])

        search_response = client.get("/search", params={"query": "durable memory", "budget": 3}, headers=headers)
        self.assertEqual(search_response.status_code, 200)
        self.assertTrue(search_response.json()["candidates"])

        context_response = client.post("/context", json={"query": "agent retrieval", "budget": 3}, headers=headers)
        self.assertEqual(context_response.status_code, 200)
        self.assertIn("pack", context_response.json())

        stats_response = client.get("/stats", headers=headers)
        self.assertEqual(stats_response.status_code, 200)
        self.assertGreater(stats_response.json()["total_records"], 0)

    @unittest.skipIf(TestClient is None, "fastapi server extra is not installed")
    def test_rest_api_allows_local_webui_cors_preflight(self) -> None:
        from seam_runtime.server import create_app

        runtime = SeamRuntime(self.db_path)
        with patch.dict(os.environ, {"SEAM_API_TOKEN": "test-token"}, clear=False):
            client = TestClient(create_app(runtime))

        response = client.options(
            "/compile",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertIn("POST", response.headers["access-control-allow-methods"])
        self.assertIn("Authorization", response.headers["access-control-allow-headers"])

    @unittest.skipIf(TestClient is None, "fastapi server extra is not installed")
    def test_rest_api_rate_limits_health_and_protected_endpoints(self) -> None:
        from seam_runtime.server import create_app

        runtime = SeamRuntime(self.db_path)
        with patch.dict(os.environ, {"SEAM_API_TOKEN": "test-token", "SEAM_API_RATE_LIMIT_PER_MINUTE": "1"}, clear=False):
            client = TestClient(create_app(runtime))

        first = client.get("/health")
        second = client.get("/health")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

        headers = {"Authorization": "Bearer another-test-token"}
        limited = client.get("/stats", headers=headers)
        self.assertEqual(limited.status_code, 401)

    def test_rate_limiter_purges_inactive_keys_after_window(self) -> None:
        from seam_runtime.server import RateLimiter

        limiter = RateLimiter(limit_per_minute=1)
        with patch("seam_runtime.server.time.monotonic", return_value=0.0):
            self.assertTrue(limiter.check("client-a"))
        with patch("seam_runtime.server.time.monotonic", return_value=61.0):
            self.assertTrue(limiter.check("client-b"))
        self.assertNotIn("client-a", limiter.hits)

    def test_rate_limiter_serializes_concurrent_checks_for_same_key(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from seam_runtime.server import RateLimiter

        class SlowGetDict(dict):
            def get(self, key, default=None):  # type: ignore[no-untyped-def]
                value = super().get(key, default)
                time.sleep(0.01)
                return value

        limiter = RateLimiter(limit_per_minute=1)
        limiter.hits = SlowGetDict({"client-a": []})
        with patch("seam_runtime.server.time.monotonic", return_value=100.0):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: limiter.check("client-a"), range(8)))

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 7)

    @unittest.skipIf(TestClient is None, "fastapi server extra is not installed")
    def test_rest_api_rejects_oversized_post_body_before_handler(self) -> None:
        from seam_runtime.server import create_app

        runtime = SeamRuntime(self.db_path)
        with patch.dict(
            os.environ,
            {"SEAM_API_TOKEN": "test-token", "SEAM_API_MAX_BODY_BYTES": "16"},
            clear=False,
        ):
            client = TestClient(create_app(runtime))
        response = client.post(
            "/compile",
            content=b'{"text":"this body is too large"}',
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)

    def test_remote_token_server_requires_explicit_insecure_override(self) -> None:
        from seam_runtime.server import run_server

        class FakeUvicorn:
            def run(self, *args, **kwargs):
                return None

        with patch.dict(os.environ, {"SEAM_API_TOKEN": "test-token"}, clear=False):
            with patch("seam_runtime.server._require_fastapi", return_value=None):
                with patch("seam_runtime.server._require_uvicorn", return_value=FakeUvicorn()):
                    with self.assertRaisesRegex(RuntimeError, "Refusing to bind authenticated API"):
                        run_server(host="0.0.0.0", db=self.db_path)

    def test_rate_limited_server_rejects_multiple_workers_without_shared_limiter(self) -> None:
        from seam_runtime.server import run_server

        class FakeUvicorn:
            def run(self, *args, **kwargs):
                return None

        with patch.dict(os.environ, {"SEAM_API_RATE_LIMIT_PER_MINUTE": "1"}, clear=False):
            with patch("seam_runtime.server._require_fastapi", return_value=None):
                with patch("seam_runtime.server._require_uvicorn", return_value=FakeUvicorn()):
                    with self.assertRaisesRegex(RuntimeError, "process-local"):
                        run_server(host="127.0.0.1", db=self.db_path, workers=2)

    def test_sqlite_vector_search_streams_rows_without_fetchall(self) -> None:
        from seam_runtime.vector import SQLiteVectorIndex

        class StaticModel:
            name = "test-model"
            dimension = 2

            def embed(self, text: str) -> list[float]:
                return [1.0, 0.0]

        class StreamingRows:
            def __iter__(self):
                return iter(
                    [
                        {"record_id": "rec:1", "vector_json": "[1.0, 0.0]"},
                        {"record_id": "rec:2", "vector_json": "[0.0, 1.0]"},
                    ]
                )

            def fetchall(self):
                raise AssertionError("search must stream vector rows")

        class FakeConnection:
            def execute(self, query, params=()):
                return StreamingRows()

            def close(self):
                return None

        index = SQLiteVectorIndex(str(self.db_path), StaticModel())
        with patch.object(index, "ensure_schema", return_value=None):
            with patch.object(index, "_connect", return_value=FakeConnection()):
                self.assertEqual(index.search("query", limit=1), {"rec:1": 1.0})

    def test_vector_index_reindex_and_search(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("We need a translator back into natural language for memory workflows.")
        claim_id = next(r.id for r in batch.records if r.kind == RecordKind.CLM)
        runtime.store.persist_ir(batch)
        reindex_report = runtime.reindex_vectors()
        self.assertIn(claim_id, reindex_report["indexed_ids"])
        self.assertTrue(reindex_report["stale_before"])
        second_reindex = runtime.reindex_vectors()
        self.assertEqual(second_reindex["stale_before"], [])
        result = runtime.search_ir("translator natural language", budget=3)
        top_ids = [candidate.record.id for candidate in result.candidates]
        self.assertIn(claim_id, top_ids)

    def test_ingest_persists_document_status_and_memory_search_get(self) -> None:
        runtime = SeamRuntime(self.db_path)
        report = runtime.ingest_text(
            "SEAM gives agents persistent local memory with graph and vector retrieval.",
            source_ref="unit://competitive-plan",
            persist=True,
        )
        payload = report.to_dict()
        self.assertEqual(payload["document"]["extraction_status"], "compiled")
        self.assertEqual(payload["document"]["indexed_status"], "indexed")
        self.assertTrue(payload["stored_ids"])

        listed = runtime.store.list_document_status()
        self.assertEqual(listed[0]["source_ref"], "unit://competitive-plan")
        index = runtime.memory_search("persistent local memory", budget=3)
        self.assertTrue(index["results"])
        full = runtime.memory_get([index["results"][0]["id"]], include_timeline=True)
        self.assertTrue(full["records"])
        self.assertIn("context", full)

    def test_retrieval_modes_include_vector_graph_hybrid_mix(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("SEAM stores graph edges and vector embeddings for agent memory retrieval."))
        orchestrator = RetrievalOrchestrator(runtime)
        for mode in ("vector", "graph", "hybrid", "mix"):
            result = orchestrator.search("agent memory retrieval", budget=3, mode=mode, include_trace=True).to_dict()
            self.assertEqual(result["trace"]["plan"]["mode"], mode)
            self.assertTrue(result["trace"]["plan"]["legs"])
        mix_legs = [leg["name"] for leg in orchestrator.plan("agent memory retrieval", mode="mix").to_dict()["legs"]]
        self.assertEqual(mix_legs, ["sql", "vector", "graph"])

    def test_mcp_bridge_dispatches_memory_tools(self) -> None:
        runtime = SeamRuntime(self.db_path)
        ingest = dispatch_tool(
            runtime,
            {
                "tool": "seam_ingest",
                "arguments": {"text": "SEAM MCP exposes persistent memory search.", "source_ref": "unit://mcp"},
            },
        )
        self.assertEqual(ingest["type"], "result")
        search = dispatch_tool(runtime, {"tool": "seam_memory_search", "arguments": {"query": "persistent memory"}})
        self.assertTrue(search["result"]["results"])
        record_id = search["result"]["results"][0]["id"]
        full = dispatch_tool(runtime, {"tool": "seam_memory_get", "arguments": {"ids": [record_id], "timeline": True}})
        self.assertTrue(full["result"]["records"])

        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_ingest", "arguments": {"text": "   "}})
        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_memory_search", "arguments": {"query": " "}})
        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_memory_get", "arguments": {"ids": []}})

    def test_mcp_bridge_imports_without_experimental_retrieval(self) -> None:
        script = r"""
import builtins
import sys

orig = builtins.__import__

def blocked(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith("seam_runtime.retrieval_orchestrator") or name == "experimental":
        raise ImportError("simulated experimental import failure")
    return orig(name, globals, locals, fromlist, level)

builtins.__import__ = blocked
sys.modules.pop("seam_runtime.mcp", None)
import seam_runtime.mcp
print("ok")
"""
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_mcp_bridge_exposes_stats_documents_context_and_doctor_tools(self) -> None:
        runtime = SeamRuntime(self.db_path)
        dispatch_tool(
            runtime,
            {
                "tool": "seam_ingest",
                "arguments": {
                    "text": "SEAM MCP context covers stats and doctor smoke checks for agents.",
                    "source_ref": "unit://mcp-context",
                },
            },
        )

        stats = dispatch_tool(runtime, {"tool": "seam_stats", "arguments": {}})
        self.assertEqual(stats["type"], "result")
        self.assertIn("total_records", stats["result"])
        self.assertGreater(stats["result"]["total_records"], 0)

        documents = dispatch_tool(runtime, {"tool": "seam_documents", "arguments": {"limit": 5}})
        rows = documents["result"]["documents"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["source_ref"], "unit://mcp-context")

        context = dispatch_tool(
            runtime,
            {
                "tool": "seam_context",
                "arguments": {"query": "doctor smoke checks", "budget": 3, "pack_budget": 256},
            },
        )
        self.assertEqual(context["result"]["query"], "doctor smoke checks")
        self.assertIn("pack", context["result"])
        self.assertIn("candidates", context["result"])

        doctor = dispatch_tool(runtime, {"tool": "seam_doctor", "arguments": {}})
        self.assertIn(doctor["result"]["status"], {"PASS", "FAIL"})
        pgvector = doctor["result"].get("pgvector", {})
        # MCP-facing doctor must never leak DSN-shaped error strings.
        self.assertNotIn("error", pgvector)
        self.assertIn("dependencies", doctor["result"])

        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_context", "arguments": {"query": ""}})
        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_context", "arguments": {"query": "doctor", "mode": "loose"}})
        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_context", "arguments": {"query": "doctor", "pack_budget": "big"}})

    def test_mcp_bridge_surface_list_show_and_benchmark_latest_handle_empty_state(self) -> None:
        runtime = SeamRuntime(self.db_path)

        empty_surfaces = dispatch_tool(runtime, {"tool": "seam_surface_list", "arguments": {"limit": 5}})
        self.assertEqual(empty_surfaces["result"]["surfaces"], [])
        self.assertEqual(empty_surfaces["result"]["count"], 0)
        self.assertEqual(empty_surfaces["result"]["limit"], 5)
        self.assertFalse(empty_surfaces["result"]["has_more"])

        # Path-shaped or non-hex refs are rejected by MCP-side validation,
        # tighter than the storage-level lookup which also accepts paths.
        with self.assertRaises(ValueError) as path_ctx:
            dispatch_tool(
                runtime,
                {"tool": "seam_surface_show", "arguments": {"surface_ref": "/etc/passwd"}},
            )
        self.assertIn("hs:", str(path_ctx.exception))

        # Valid hs:<hex> shape but unknown ref returns an actionable KeyError.
        with self.assertRaises(KeyError) as missing_ctx:
            dispatch_tool(
                runtime,
                {"tool": "seam_surface_show", "arguments": {"surface_ref": "hs:00deadbeef"}},
            )
        self.assertIn("seam_surface_list", str(missing_ctx.exception))

        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_surface_show", "arguments": {}})

        empty_benchmarks = dispatch_tool(runtime, {"tool": "seam_benchmark_latest", "arguments": {}})
        self.assertEqual(empty_benchmarks["result"]["runs"], [])
        self.assertEqual(empty_benchmarks["result"]["limit"], 1)
        self.assertFalse(empty_benchmarks["result"]["has_more"])

        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_unknown_tool", "arguments": {}})

    def test_mcp_bridge_ready_line_announces_tool_metadata_with_annotations(self) -> None:
        from seam_runtime.mcp import run_stdio_bridge

        runtime = SeamRuntime(self.db_path)
        output = StringIO()
        run_stdio_bridge(runtime, input_stream=StringIO(""), output_stream=output)

        ready_line = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(ready_line["type"], "ready")
        # Backwards-compatible name->description map stays intact for old clients.
        self.assertIn("seam_surface_query", ready_line["tools"])
        # New structured metadata exposes annotations + input schemas.
        metadata = ready_line["tool_metadata"]
        surface_query_meta = metadata["seam_surface_query"]
        self.assertTrue(surface_query_meta["annotations"]["readOnlyHint"])
        self.assertFalse(surface_query_meta["annotations"]["destructiveHint"])
        self.assertEqual(
            surface_query_meta["input_schema"]["surface_ref"]["pattern"],
            "^hs:[0-9a-f]+$",
        )
        # seam_ingest is the one new tool that writes; readOnlyHint must be False.
        self.assertFalse(metadata["seam_ingest"]["annotations"]["readOnlyHint"])

    def test_mcp_bridge_surface_query_and_decode_use_registered_hs_refs_only(self) -> None:
        source_path = Path(f"mcp_surface_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"mcp_surface_{uuid4().hex}.seam.png")
        artifact_dir = TEST_ARTIFACT_DIR / f"mcp_surfaces_{uuid4().hex}"
        try:
            text = 'MCP surface fixture: "agents query stored holographic surfaces by hs:<id> only."'
            artifact = compress_text_readable(text, source_ref="unit://mcp-surface", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")

            encode_stream = StringIO()
            with redirect_stdout(encode_stream):
                run_cli([
                    "--db", str(self.db_path),
                    "surface", "encode", str(source_path),
                    "--output", str(surface_path),
                    "--store", "--artifact-dir", str(artifact_dir),
                    "--format", "json",
                ])
            surface_id = json.loads(encode_stream.getvalue())["library"]["surface_id"]
            self.assertTrue(surface_id.startswith("hs:"))

            runtime = SeamRuntime(self.db_path)

            query = dispatch_tool(
                runtime,
                {
                    "tool": "seam_surface_query",
                    "arguments": {
                        "surface_ref": surface_id,
                        "query": "agents query stored holographic",
                        "limit": 3,
                    },
                },
            )
            self.assertEqual(query["type"], "result")
            self.assertEqual(query["result"]["query"], "agents query stored holographic")
            self.assertTrue(query["result"]["hits"])

            decoded = dispatch_tool(
                runtime,
                {
                    "tool": "seam_surface_decode",
                    "arguments": {"surface_ref": surface_id, "truncate_text": 32},
                },
            )
            self.assertEqual(decoded["type"], "result")
            self.assertIsNotNone(decoded["result"]["payload_text"])
            self.assertLessEqual(len(decoded["result"]["payload_text"]), 32)
            self.assertTrue(decoded["result"]["payload_text_truncated"])

            metadata_only = dispatch_tool(
                runtime,
                {
                    "tool": "seam_surface_decode",
                    "arguments": {"surface_ref": surface_id, "truncate_text": 0},
                },
            )
            self.assertIsNone(metadata_only["result"]["payload_text"])
            self.assertFalse(metadata_only["result"]["payload_text_truncated"])

            # Path-shaped surface_ref must be rejected by MCP-side validation.
            with self.assertRaises(ValueError) as ctx:
                dispatch_tool(
                    runtime,
                    {
                        "tool": "seam_surface_query",
                        "arguments": {"surface_ref": str(surface_path.resolve()), "query": "x"},
                    },
                )
            self.assertIn("hs:", str(ctx.exception))

            # If the registered surface file is missing, the tool raises an
            # actionable FileNotFoundError pointing at `seam surface repair`.
            surface_path.unlink()
            artifact_path = Path(runtime.store.read_surface_artifact(surface_id)["artifact_path"])
            if artifact_path.exists():
                artifact_path.unlink()
            with self.assertRaises(FileNotFoundError) as repair_ctx:
                dispatch_tool(
                    runtime,
                    {"tool": "seam_surface_query", "arguments": {"surface_ref": surface_id, "query": "x"}},
                )
            self.assertIn("seam surface repair", str(repair_ctx.exception))
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for child in artifact_dir.glob("*"):
                    if child.is_file():
                        child.unlink()
                artifact_dir.rmdir()

    def test_mcp_bridge_surface_verify_and_context_on_registered_surface(self) -> None:
        source_path = Path(f"mcp_verify_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"mcp_verify_surface_{uuid4().hex}.seam.png")
        artifact_dir = TEST_ARTIFACT_DIR / f"mcp_verify_surfaces_{uuid4().hex}"
        try:
            text = "MCP verify fixture: surface integrity checks pass for valid SEAM-HS/1 artifacts."
            artifact = compress_text_readable(text, source_ref="unit://mcp-verify", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")

            encode_stream = StringIO()
            with redirect_stdout(encode_stream):
                run_cli([
                    "--db", str(self.db_path),
                    "surface", "encode", str(source_path),
                    "--output", str(surface_path),
                    "--store", "--artifact-dir", str(artifact_dir),
                    "--format", "json",
                ])
            surface_id = json.loads(encode_stream.getvalue())["library"]["surface_id"]

            runtime = SeamRuntime(self.db_path)

            verify = dispatch_tool(
                runtime,
                {"tool": "seam_surface_verify", "arguments": {"surface_ref": surface_id}},
            )
            self.assertEqual(verify["type"], "result")
            self.assertEqual(verify["result"]["status"], "PASS")

            context = dispatch_tool(
                runtime,
                {
                    "tool": "seam_surface_context",
                    "arguments": {"surface_ref": surface_id, "query": "integrity checks pass", "budget": 256},
                },
            )
            self.assertEqual(context["type"], "result")
            self.assertIn("context", context["result"])
            self.assertIn("source_path", context["result"])

            with self.assertRaises(ValueError):
                dispatch_tool(runtime, {"tool": "seam_surface_context", "arguments": {"surface_ref": surface_id, "query": ""}})
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for child in artifact_dir.glob("*"):
                    if child.is_file():
                        child.unlink()
                artifact_dir.rmdir()

    def test_mcp_bridge_index_status_reports_staleness(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.ingest_text("SEAM index status: first document for vector staleness check.", source_ref="unit://mcp-index-status", persist=True)

        status = dispatch_tool(runtime, {"tool": "seam_index_status", "arguments": {}})
        self.assertEqual(status["type"], "result")
        self.assertGreater(status["result"]["total_records"], 0)
        self.assertGreater(status["result"]["indexable_records"], 0)
        self.assertIn("stale_count", status["result"])
        self.assertIn("stale_records", status["result"])

        with_scope = dispatch_tool(runtime, {"tool": "seam_index_status", "arguments": {"scope": "thread", "limit": 1}})
        self.assertEqual(with_scope["type"], "result")

        with_boundary = dispatch_tool(runtime, {"tool": "seam_index_status", "arguments": {"limit": 1}})
        self.assertEqual(with_boundary["type"], "result")

    def test_mcp_bridge_retrieve_supports_all_four_modes_and_rejects_invalid(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.ingest_text(
            "Retrieval testing: vector-only semantic search returns results. "
            "Graph traversal follows entity relationships. Hybrid combines vector and SQL. "
            "Mix mode uses all three strategies together.",
            source_ref="unit://mcp-retrieve",
            persist=True,
        )

        for mode in ("vector", "graph", "hybrid", "mix"):
            result = dispatch_tool(
                runtime,
                {
                    "tool": "seam_retrieve",
                    "arguments": {"query": "semantic search and retrieval modes", "mode": mode, "budget": 3},
                },
            )
            self.assertEqual(result["type"], "result", f"mode={mode} failed")
            self.assertIn("candidates", result["result"])
            self.assertIn("query", result["result"])

        traced = dispatch_tool(
            runtime,
            {
                "tool": "seam_retrieve",
                "arguments": {"query": "entity relationships", "mode": "mix", "include_trace": True},
            },
        )
        self.assertIn("trace", traced["result"])
        self.assertIsNotNone(traced["result"]["trace"])

        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_retrieve", "arguments": {"query": "test", "mode": "invalid"}})
        with self.assertRaises(ValueError):
            dispatch_tool(runtime, {"tool": "seam_retrieve", "arguments": {"query": ""}})

    def test_mcp_bridge_ready_line_announces_16_tools_with_no_metadata_warnings(self) -> None:
        from seam_runtime.mcp import run_stdio_bridge

        runtime = SeamRuntime(self.db_path)
        from seam_runtime.mcp import TOOL_DESCRIPTIONS, TOOL_METADATA
        keys_desc = set(TOOL_DESCRIPTIONS)
        keys_meta = set(TOOL_METADATA)
        extra_desc = keys_desc - keys_meta
        extra_meta = keys_meta - keys_desc
        if extra_desc or extra_meta:
            self.fail(
                f"TOOL_DESCRIPTIONS/TOOL_METADATA keys mismatch: "
                + (f"desc-only={sorted(extra_desc)}. " if extra_desc else "")
                + (f"meta-only={sorted(extra_meta)}." if extra_meta else "")
            )

        output = StringIO()
        run_stdio_bridge(runtime, input_stream=StringIO(""), output_stream=output)

        ready_line = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(ready_line["type"], "ready")
        self.assertEqual(len(ready_line["tools"]), 16)
        self.assertEqual(len(ready_line["tool_metadata"]), 16)

        for tool_name in ("seam_surface_verify", "seam_surface_context", "seam_index_status", "seam_retrieve"):
            self.assertIn(tool_name, ready_line["tools"], f"{tool_name} missing from ready line")

    def test_mcp_protocol_server_handles_initialize_list_and_call(self) -> None:
        from seam_runtime.mcp_protocol import run_mcp_server

        runtime = SeamRuntime(self.db_path)
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "unit-test", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "seam_stats", "arguments": {}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "seam_memory_search", "arguments": {"query": ""}},
            },
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "missing", "arguments": {}}},
        ]
        output = StringIO()
        run_mcp_server(
            runtime,
            input_stream=StringIO("\n".join(json.dumps(request) for request in requests)),
            output_stream=output,
        )

        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3, 4, 5])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(responses[0]["result"]["capabilities"]["tools"]["listChanged"], False)

        tools = responses[1]["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertIn("seam_context", names)
        self.assertIn("seam_ingest", names)
        context_tool = next(tool for tool in tools if tool["name"] == "seam_context")
        self.assertEqual(context_tool["inputSchema"]["type"], "object")
        self.assertIn("query", context_tool["inputSchema"]["required"])

        call_result = responses[2]["result"]
        self.assertFalse(call_result["isError"])
        self.assertEqual(call_result["content"][0]["type"], "text")
        self.assertIn("total_records", call_result["structuredContent"])

        invalid_args = responses[3]["result"]
        self.assertTrue(invalid_args["isError"])
        self.assertIn("query is required", invalid_args["content"][0]["text"])

        unknown_tool = responses[4]["error"]
        self.assertEqual(unknown_tool["code"], -32602)
        self.assertIn("Unknown SEAM MCP tool", unknown_tool["message"])

    def test_pgvector_bootstrap_uses_private_env_and_compose_service(self) -> None:
        import subprocess

        from seam_runtime.pgvector_bootstrap import ensure_pgvector

        env_path = TEST_ARTIFACT_DIR / f"pgvector_{uuid4().hex}.env"
        env_path.write_text(
            "\n".join(
                [
                    "POSTGRES_DB=seam",
                    "POSTGRES_USER=seam",
                    "POSTGRES_PASSWORD=<local-password>",
                    "SEAM_PGVECTOR_PORT=55432",
                ]
            ),
            encoding="utf-8",
        )
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            if list(command[:3]) == ["docker", "inspect", "-f"]:
                return subprocess.CompletedProcess(command, 0, stdout="healthy\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        tracked_env = ("SEAM_PGVECTOR_DSN", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "SEAM_PGVECTOR_PORT")
        old_env = {key: os.environ.get(key) for key in tracked_env}
        for key in tracked_env:
            os.environ.pop(key, None)
        try:
            with patch("seam_runtime.pgvector_bootstrap.subprocess.run", side_effect=fake_run):
                dsn = ensure_pgvector(Path.cwd(), env_path=str(env_path), stderr=StringIO())
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            env_path.unlink(missing_ok=True)

        self.assertIn("port='55432'", dsn)
        self.assertIn("dbname='seam'", dsn)
        compose_calls = [call for call in calls if call[:2] == ["docker", "compose"]]
        self.assertTrue(compose_calls)
        self.assertIn("--env-file", compose_calls[0])
        self.assertEqual(compose_calls[0][-2:], ["-d", "pgvector"])
        self.assertTrue(any(call[:3] == ["docker", "exec", "seam-pgvector"] and "psql" in call for call in calls),
                        "Expected a docker exec psql call for pgvector boot check")


    def test_symbol_promotion_and_pack_compaction(self) -> None:
        runtime = SeamRuntime(self.db_path)
        # The symbol loop (SEAM spec §23) mines repeated tokens from structured IR.
        # ("memory" recurs across the claim objects -> the core symbol "mem".)
        # The compile_nl FLOOR emits natural-language objects, not the structured
        # tokens this loop is designed for; mining frequent words from arbitrary NL
        # (collision-safe symbol generation) is Track J / §23 follow-up work.
        batch = runtime.compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate stores
  object memory
claim c2:
  subject p1
  predicate recalls
  object memory
"""
        )
        runtime.persist_ir(batch)
        promote = runtime.promote_symbols(min_frequency=2)
        self.assertTrue(promote.stored_ids)
        compact_batch = runtime.store.load_ir()
        expansion_to_symbol, _ = build_symbol_maps(compact_batch.records, namespace="local.default")
        self.assertEqual(expansion_to_symbol.get("memory"), "mem")
        pack = runtime.pack_ir(
            record_ids=[record.id for record in compact_batch.records if record.kind.value in {"CLM", "STA", "SYM"}],
            mode="context",
        )
        self.assertIn("symbols", pack.payload)
        self.assertTrue(pack.payload["symbols"])
        self.assertIn("mem", pack.payload["symbols"])

    def test_symbol_export_and_query_expansion(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate memory_runtime
  object memory_runtime
"""
        )
        runtime.persist_ir(batch)
        runtime.promote_symbols(min_frequency=1)
        exported = runtime.export_symbols()
        self.assertIn("SEAM Symbol Nursery", exported)
        all_records = runtime.store.load_ir().records
        symbol_records = [record for record in all_records if record.kind.value == "SYM"]
        self.assertTrue(symbol_records)
        symbol = symbol_records[0].attrs["symbol"]
        result = runtime.search_ir(symbol, budget=5)
        self.assertTrue(result.candidates)

    def test_namespace_chain_inheritance(self) -> None:
        self.assertEqual(namespace_chain("org.app.user.thread"), ["org", "org.app", "org.app.user", "org.app.user.thread"])

    def test_decompile_and_pack_payload(self) -> None:
        batch = compile_nl("We need a translator back into natural language for AI memory.")
        output = decompile_ir(batch, mode="expanded")
        self.assertIn("MIRL summary", output)
        pack = pack_ir(batch, mode="context")
        payload = unpack_pack(pack)
        self.assertIn("entries", payload)

    def test_cli_text_parser_compat(self) -> None:
        batch = compile_nl("Build durable AI memory for databases.")
        parsed = load_ir_lines(batch.to_text())
        self.assertEqual(len(parsed), len(batch.records))

    def test_default_embedding_model_from_env(self) -> None:
        keys = [
            "SEAM_EMBEDDING_PROVIDER",
            "SEAM_EMBEDDING_MODEL",
            "SEAM_EMBEDDING_BASE_URL",
            "SEAM_EMBEDDING_API_KEY_ENV",
            "SEAM_EMBEDDING_TIMEOUT_S",
            "SEAM_EMBEDDING_DIMENSIONS",
        ]
        snapshot = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["SEAM_EMBEDDING_PROVIDER"] = "openai-compatible"
            os.environ["SEAM_EMBEDDING_MODEL"] = "text-embedding-3-small"
            os.environ["SEAM_EMBEDDING_BASE_URL"] = "https://example.test/v1/embeddings"
            os.environ["SEAM_EMBEDDING_API_KEY_ENV"] = "ALT_OPENAI_KEY"
            os.environ["SEAM_EMBEDDING_TIMEOUT_S"] = "12.5"
            os.environ["SEAM_EMBEDDING_DIMENSIONS"] = "256"
            model = default_embedding_model()
        finally:
            for key, value in snapshot.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIsInstance(model, OpenAICompatibleEmbeddingModel)
        self.assertEqual(model.model, "text-embedding-3-small")
        self.assertEqual(model.base_url, "https://example.test/v1/embeddings")
        self.assertEqual(model.api_key_env, "ALT_OPENAI_KEY")
        self.assertEqual(model.timeout_s, 12.5)
        self.assertEqual(model.dimensions, 256)

    def test_sentence_transformer_lock_prevents_double_load_h7(self) -> None:
        import threading
        import sys
        from unittest.mock import MagicMock

        fake_dims = 128
        # Build a mock SentenceTransformer that records how many times it was called
        fake_st_class = MagicMock()
        fake_st_instance = MagicMock()
        fake_st_instance.encode.return_value.tolist.return_value = [0.0] * (fake_dims - 1) + [1.0]
        type(fake_st_instance).get_sentence_embedding_dimension = MagicMock(return_value=fake_dims)
        fake_st_class.return_value = fake_st_instance

        real_st = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = MagicMock()
        sys.modules["sentence_transformers"].SentenceTransformer = fake_st_class
        try:
            st_model = SentenceTransformerModel(model_name="test-model")
            results: list[list[float]] = []
            errors: list[Exception] = []
            ready = threading.Barrier(4, timeout=5)

            def worker() -> None:
                try:
                    ready.wait()
                    results.append(st_model.embed("hello"))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0, f"unexpected errors: {errors}")
            self.assertEqual(len(results), 4, "all 4 threads should return vectors")
            # SentenceTransformer(...) must be called exactly once
            self.assertEqual(fake_st_class.call_count, 1,
                             f"SentenceTransformer called {fake_st_class.call_count} times, expected 1")
            # All results are the same normalized vector
            for vec in results:
                self.assertEqual(len(vec), fake_dims)
        finally:
            del sys.modules["sentence_transformers"]
            if real_st is not None:
                sys.modules["sentence_transformers"] = real_st

    def test_openai_embedding_retries_transient_errors_h8(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch

        model = OpenAICompatibleEmbeddingModel(
            model="test-model",
            api_key_env="SEAM_TEST_KEY_H8",
            base_url="https://test.example/v1/embeddings",
            dimensions=128,
        )
        response_payload = {"data": [{"embedding": [0.0] * 127 + [1.0]}]}

        def _build_success_response() -> MagicMock:
            resp = MagicMock()
            resp.read.return_value = json.dumps(response_payload).encode("utf-8")
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            return resp

        with patch.dict("os.environ", {"SEAM_TEST_KEY_H8": "fake-key"}):
            # --- succeeds on third attempt after two URLErrors ---
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = [
                    urllib.error.URLError("transient timeout"),
                    urllib.error.URLError("connection reset"),
                    _build_success_response(),
                ]
                result = model.embed("retry test")
                self.assertEqual(len(result), 128)
                self.assertEqual(mock_urlopen.call_count, 3,
                                 f"expected 3 attempts (2 failures + 1 success), got {mock_urlopen.call_count}")

            # --- does NOT retry on HTTP 400 client error ---
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = urllib.error.HTTPError(
                    "https://test.example", 400, "Bad Request", {}, None,
                )
                with self.assertRaises(urllib.error.HTTPError):
                    model.embed("bad request")
                self.assertEqual(mock_urlopen.call_count, 1,
                                 "HTTP 400 should not be retried")

            # --- DOES retry HTTP 429 and 5xx ---
            for status in (429, 502, 503):
                with self.subTest(status=status):
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        mock_urlopen.side_effect = [
                            urllib.error.HTTPError("https://test.example", status, "Server Error", {}, None),
                            _build_success_response(),
                        ]
                        result = model.embed("retryable http")
                        self.assertEqual(len(result), 128)
                        self.assertEqual(mock_urlopen.call_count, 2,
                                         f"HTTP {status} should be retried once then succeed")

            # --- exhausts all retries ---
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = urllib.error.URLError("persistent failure")
                with self.assertRaises(urllib.error.URLError):
                    model.embed("always fails")
                self.assertEqual(mock_urlopen.call_count, 3,
                                 "should exhaust all 3 attempts then raise")

    def test_retrieval_benchmark_uses_gold_fixtures(self) -> None:
        runtime = SeamRuntime(self.db_path)
        benchmark = runtime.run_retrieval_benchmark()
        self.assertGreaterEqual(benchmark["summary"]["fixture_count"], 3)
        self.assertIn("hybrid", benchmark["summary"]["tracks"])
        self.assertTrue(benchmark["summary"]["success_checks"]["exact_packs_reversible"])
        categories = {fixture["category"] for fixture in benchmark["fixtures"]}
        self.assertIn("relation", categories)

    def test_pack_scoring_preserves_traceability_metrics(self) -> None:
        batch = compile_nl("We need a translator back into natural language for AI memory.")
        exact = pack_ir(batch, mode="exact")
        context = pack_ir(batch, mode="context")
        exact_score = score_pack(exact, batch.records)
        context_score = score_pack(context, batch.records)
        self.assertEqual(exact_score["reversibility"], 1.0)
        self.assertGreaterEqual(context_score["traceability"], 0.66)
        self.assertGreater(context_score["overall"], 0.0)

    def test_reconcile_supersedes_when_winner_newer(self) -> None:
        newer = MIRLRecord(
            id="clm:a", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:01Z", conf=0.5,
            attrs={"subject": "X", "predicate": "color", "object": "red"},
        )
        older = MIRLRecord(
            id="clm:b", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.9,
            attrs={"subject": "X", "predicate": "color", "object": "blue"},
        )
        report = reconcile_ir(IRBatch(records=[newer, older]))
        self.assertEqual(len(report.actions), 1)
        self.assertEqual(report.actions[0]["type"], "supersedes")
        self.assertEqual(report.actions[0]["winner"], "clm:a")
        self.assertEqual(report.actions[0]["loser"], "clm:b")

    def test_reconcile_contradicts_when_same_timestamp_different_objects(self) -> None:
        claim_a = MIRLRecord(
            id="clm:c", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.9,
            attrs={"subject": "X", "predicate": "color", "object": "red"},
        )
        claim_b = MIRLRecord(
            id="clm:d", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.5,
            attrs={"subject": "X", "predicate": "color", "object": "blue"},
        )
        report = reconcile_ir(IRBatch(records=[claim_a, claim_b]))
        self.assertEqual(len(report.actions), 1)
        self.assertEqual(report.actions[0]["type"], "contradicts")
        self.assertEqual(report.actions[0]["winner"], "clm:c")
        self.assertEqual(report.actions[0]["loser"], "clm:d")

    def test_reconcile_contradicts_same_timestamp_equal_confidence(self) -> None:
        claim_a = MIRLRecord(
            id="clm:e", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.8,
            attrs={"subject": "X", "predicate": "color", "object": "red"},
        )
        claim_b = MIRLRecord(
            id="clm:f", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.8,
            attrs={"subject": "X", "predicate": "color", "object": "blue"},
        )
        report = reconcile_ir(IRBatch(records=[claim_a, claim_b]))
        self.assertEqual(len(report.actions), 1)
        self.assertEqual(report.actions[0]["type"], "contradicts")

    def test_reconcile_duplicates_when_same_object(self) -> None:
        claim_a = MIRLRecord(
            id="clm:g", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:01Z", conf=0.9,
            attrs={"subject": "X", "predicate": "color", "object": "red"},
        )
        claim_b = MIRLRecord(
            id="clm:h", kind=RecordKind.CLM,
            updated_at="2025-06-01T00:00:00Z", conf=0.5,
            attrs={"subject": "X", "predicate": "color", "object": "red"},
        )
        report = reconcile_ir(IRBatch(records=[claim_a, claim_b]))
        self.assertEqual(len(report.actions), 1)
        self.assertEqual(report.actions[0]["type"], "duplicates")

    def test_retrieval_orchestrator_builds_mixed_plan(self) -> None:
        runtime = SeamRuntime(self.db_path)
        orchestrator = RetrievalOrchestrator(runtime)
        plan = orchestrator.plan("kind:CLM translator natural language", scope="thread", budget=3)
        self.assertEqual(plan.intent, QueryIntent.HYBRID)
        self.assertEqual(plan.filters.kinds, ["CLM"])
        self.assertEqual([leg.name for leg in plan.legs], ["sql", "vector"])
        self.assertEqual(plan.normalized_query, "translator natural language")

    def test_retrieval_orchestrator_merges_sql_and_vector_legs(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("We need a translator back into natural language for memory workflows.")
        runtime.persist_ir(batch)
        claim_id = next(r.id for r in batch.records if r.kind == RecordKind.CLM)
        orchestrator = RetrievalOrchestrator(runtime)
        result = orchestrator.search("kind:CLM translator natural language", budget=3, include_trace=True)
        self.assertTrue(result.candidates)
        translator = next((candidate for candidate in result.candidates if candidate.record.id == claim_id), None)
        self.assertIsNotNone(translator)
        self.assertIn("sql", translator.sources)
        self.assertIsNotNone(result.trace)
        self.assertIn("sql", result.trace["legs"])
        self.assertIn("vector", result.trace["legs"])

    def test_sql_leg_excludes_irrelevant_kind_only_matches(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate translator_for
  object natural_language
claim c2:
  subject p1
  predicate memory_runtime
  object durable_context
"""
        )
        runtime.persist_ir(batch)
        adapter = SQLiteIRAdapter(runtime.store)
        hits = adapter.search(build_plan("kind:CLM translator natural language", budget=5), limit=5)
        hit_ids = [hit.record.id for hit in hits]
        self.assertIn("c1", hit_ids)
        self.assertNotIn("c2", hit_ids)

    def test_sql_leg_returns_exact_structured_match_without_query_terms(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate memory_runtime
  object durable_context
claim c2:
  subject p1
  predicate retrieval_mode
  object vector_search
"""
        )
        runtime.persist_ir(batch)
        adapter = SQLiteIRAdapter(runtime.store)
        hits = adapter.search(build_plan("predicate:memory_runtime subject:p1", budget=5), limit=5)
        self.assertTrue(hits)
        self.assertEqual([hit.record.id for hit in hits], ["c1"])
        self.assertTrue(any(reason == "matched=predicate" for reason in hits[0].reasons))
        self.assertIn("matched=predicate", hits[0].reasons)

    def test_cli_plan_outputs_mixed_intent(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "plan", "kind:CLM translator natural language", "--budget", "3", "--format", "json"])
        payload = stream.getvalue()
        self.assertIn('"intent": "hybrid"', payload)
        self.assertIn('"name": "sql"', payload)
        self.assertIn('"name": "vector"', payload)

    def test_cli_compare_outputs_basic_and_retrieval(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "compare", "translator natural language", "--budget", "3", "--format", "json"])
        payload = stream.getvalue()
        self.assertIn('"search"', payload)
        self.assertIn('"retrieve"', payload)

    def test_cli_retrieve_pretty_output(self) -> None:
        seed = "We need a translator back into natural language for memory workflows."
        claim_id = _claim_ids(seed)[0]
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(seed))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "retrieve", "kind:CLM translator natural language", "--budget", "3"])
        payload = stream.getvalue()
        self.assertIn("Intent: hybrid", payload)
        self.assertIn("Candidates:", payload)
        self.assertIn(claim_id, payload)

    def test_chroma_semantic_adapter_searches_via_fake_client(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("We need a translator back into natural language for memory workflows.")
        runtime.persist_ir(batch)
        claim_id = next(r.id for r in batch.records if r.kind == RecordKind.CLM)
        raw_id = next(r.id for r in batch.records if r.kind == RecordKind.RAW)
        adapter = ChromaSemanticAdapter(runtime.store, runtime.embedding_model, client=FakeChromaClient(), sync_on_search=True)
        plan = build_plan("translator natural language", budget=3)
        hits = adapter.search(plan, limit=3)
        self.assertTrue(hits)
        self.assertIn(hits[0].record.id, {claim_id, raw_id})  # RAW is indexable; chroma indexes all INDEXABLE_KINDS
        self.assertEqual(hits[0].leg, "chroma")

    def test_retrieval_orchestrator_syncs_persistent_indexes(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("We need a translator back into natural language for memory workflows.")
        runtime.persist_ir(batch)
        orchestrator = RetrievalOrchestrator(
            runtime,
            semantic_adapter=ChromaSemanticAdapter(runtime.store, runtime.embedding_model, client=FakeChromaClient()),
            semantic_backend="chroma",
        )
        claim_id = next(r.id for r in batch.records if r.kind == RecordKind.CLM)
        report = orchestrator.sync_persistent_indexes()
        self.assertEqual(report["backend"], "chroma")
        self.assertGreaterEqual(report["chroma_indexed"], 1)
        self.assertIn(claim_id, report["sqlite_indexed"])

    def test_context_pipeline_returns_context_pack(self) -> None:
        runtime = SeamRuntime(self.db_path)
        batch = runtime.compile_nl("We need a translator back into natural language for memory workflows.")
        runtime.persist_ir(batch)
        claim_id = next(r.id for r in batch.records if r.kind == RecordKind.CLM)
        orchestrator = RetrievalOrchestrator(runtime)
        rag = orchestrator.rag("translator natural language", budget=3, pack_budget=2000, include_trace=True)
        self.assertIn(claim_id, rag.candidate_ids)
        self.assertTrue(rag.records)
        self.assertTrue(rag.candidates)
        self.assertEqual(rag.pack["mode"], "context")
        self.assertTrue(rag.pack["payload"]["entries"])
        self.assertIsNotNone(rag.trace)

    def test_cli_rag_search_json_contains_pack(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "context", "translator natural language", "--budget", "3", "--format", "json"])
        payload = stream.getvalue()
        self.assertIn('"pack"', payload)
        self.assertIn('"candidate_ids"', payload)
        self.assertIn('"records"', payload)

    def test_cli_context_prompt_view_outputs_prompt_ready_text(self) -> None:
        seed = "We need a translator back into natural language for memory workflows."
        claim_id = _claim_ids(seed)[0]
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(seed))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "context", "translator natural language", "--budget", "3", "--view", "prompt"])
        payload = stream.getvalue()
        self.assertIn("SEAM retrieved context", payload)
        self.assertIn(f"[1] {claim_id} [CLM]", payload)

    def test_cli_context_evidence_view_json_contains_citations(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(
                ["--db", str(self.db_path), "context", "translator natural language", "--budget", "3", "--view", "evidence", "--format", "json"]
            )
        payload = stream.getvalue()
        self.assertIn('"view": "evidence"', payload)
        self.assertIn('"citation"', payload)

    def test_cli_context_records_view_outputs_exact_record_payloads(self) -> None:
        seed = "We need a translator back into natural language for memory workflows."
        claim_id = _claim_ids(seed)[0]
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(seed))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "context", "translator natural language", "--budget", "3", "--view", "records"])
        payload = stream.getvalue()
        self.assertIn(f'"id": "{claim_id}"', payload)
        self.assertIn('"kind": "CLM"', payload)

    def test_cli_context_summary_view_reports_highlights(self) -> None:
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["--db", str(self.db_path), "context", "translator natural language", "--budget", "3", "--view", "summary"])
        payload = stream.getvalue()
        self.assertIn("Summary:", payload)

    def test_cli_shell_once_remembers_searches_and_contextualizes(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli([
                "--db",
                str(self.db_path),
                "shell",
                "--once",
                "/remember SEAM shell should behave like an agent CLI with persistent memory.",
                "--once",
                "/search agent CLI persistent memory",
                "--once",
                "/context agent CLI",
            ])
        payload = stream.getvalue()
        self.assertIn("remembered", payload)
        self.assertIn("agent CLI", payload)
        self.assertIn("SEAM retrieved context", payload)
        self.assertIn("[1]", payload)

    def test_lossless_codec_roundtrips_exact_text(self) -> None:
        text = "SEAM preserves exact context while compressing token usage for lossless recovery.\n" * 12
        artifact = compress_text_lossless(text)
        restored = decompress_text_lossless(artifact.machine_text)
        self.assertEqual(restored, text)
        self.assertTrue(artifact.machine_text.startswith("SEAM-LX/1"))

    def test_lossless_benchmark_passes_high_savings_demo(self) -> None:
        text = "\n".join(["SEAM preserves exact context while compressing token usage for lossless recovery."] * 60)
        result = benchmark_text_lossless(text, min_token_savings=0.75)
        self.assertTrue(result.roundtrip_match)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.artifact.token_savings_ratio, 0.75)
        self.assertTrue(result.search_log)
        search_statuses = {attempt.status for attempt in result.search_log}
        self.assertIn("improved", search_statuses)
        self.assertTrue(result.stop_reason)

    def test_lossless_benchmark_logs_fluctuations_for_debugging(self) -> None:
        text = "SEAM preserves exact context while compressing token usage for lossless recovery.\n" * 12
        result = benchmark_text_lossless(text, min_token_savings=0.30)
        payload = result.to_dict()
        self.assertIn("search_log", payload)
        self.assertTrue(payload["search_log"])
        statuses = {attempt["status"] for attempt in payload["search_log"]}
        self.assertIn("improved", statuses)
        self.assertTrue(statuses & {"flat", "regressed"},
                        "Expected at least one flat/regressed status")

    def test_lossless_benchmark_respects_requested_tokenizer(self) -> None:
        text = "SEAM preserves exact context while compressing token usage for lossless recovery.\n" * 12
        result = benchmark_text_lossless(text, min_token_savings=0.30, tokenizer="char4_approx")
        self.assertEqual(result.artifact.token_estimator, "char4_approx")

    def test_readable_compression_queries_exact_quote_without_rebuild(self) -> None:
        text = (
            'Project note: "SEAM compression must be directly readable by AI." '
            "The artifact should preserve exact quotes, table cells, numbers, and source spans."
        )
        artifact = compress_text_readable(text, source_ref="unit://readable", tokenizer="char4_approx")
        self.assertTrue(artifact.machine_text.startswith("SEAM-RC/1"))
        self.assertIn("QUOTE|", artifact.machine_text)

        result = query_readable_compressed(artifact.machine_text, '"SEAM compression must be directly readable by AI."')
        self.assertTrue(result.hits)
        self.assertEqual(result.hits[0].record_type, "QUOTE")
        self.assertEqual(result.hits[0].text, '"SEAM compression must be directly readable by AI."')
        self.assertEqual(decompress_text_readable(artifact.machine_text), text)

    def test_cli_readable_compress_and_query_reads_compressed_language(self) -> None:
        source_path = Path(f"readable_source_{uuid4().hex}.txt")
        compressed_path = Path(f"readable_machine_{uuid4().hex}.seamrc")
        try:
            source_text = (
                'Release note: "MIRL is the working compressed document." '
                "SEAM reads the compressed language directly."
            )
            source_path.write_text(source_text, encoding="utf-8")
            with redirect_stdout(StringIO()):
                run_cli(["readable-compress", str(source_path), "--output", str(compressed_path)])
            self.assertTrue(compressed_path.exists())
            self.assertTrue(compressed_path.read_text(encoding="utf-8").startswith("SEAM-RC/1"))

            query_stream = StringIO()
            with redirect_stdout(query_stream):
                run_cli(["readable-query", str(compressed_path), '"MIRL is the working compressed document."'])
            output = query_stream.getvalue()
            self.assertIn("Readable query results", output)
            self.assertIn('"MIRL is the working compressed document."', output)
        finally:
            for path in (source_path, compressed_path):
                if path.exists():
                    path.unlink()

    def test_holographic_surface_rc1_roundtrips_and_queries_directly(self) -> None:
        text = (
            'Surface memory: "SEAM-HS/1 stores readable machine language in pixels." '
            "Direct read does not need OCR, NLP recompilation, or SQLite import."
        )
        artifact = compress_text_readable(text, source_ref="unit://surface", tokenizer="char4_approx")
        surface_path = Path(f"surface_rc1_{uuid4().hex}.seam.png")
        try:
            surface = encode_surface(artifact.machine_text.encode("utf-8"), surface_path, mode="rgb24", payload_format="SEAM-RC/1")
            self.assertEqual(surface.payload_format, "SEAM-RC/1")
            decoded = decode_surface(surface_path)
            self.assertEqual(decoded.payload, artifact.machine_text.encode("utf-8"))
            self.assertTrue(verify_surface(surface_path).ok)

            result = query_surface(surface_path, '"SEAM-HS/1 stores readable machine language in pixels."')
            self.assertTrue(result.hits)
            self.assertEqual(result.hits[0]["record_type"], "QUOTE")
        finally:
            if surface_path.exists():
                surface_path.unlink()

    def test_holographic_surface_rgba32_roundtrips_and_queries_directly(self) -> None:
        text = (
            'Surface density: "RGBA32 stores four exact channel bytes per pixel." '
            "SEAM keeps RGB24 as the default and uses RGBA32 only when explicitly requested."
        )
        artifact = compress_text_readable(text, source_ref="unit://surface-rgba", tokenizer="char4_approx")
        surface_path = Path(f"surface_rgba32_{uuid4().hex}.seam.png")
        try:
            surface = encode_surface(artifact.machine_text.encode("utf-8"), surface_path, mode="rgba32", payload_format="SEAM-RC/1")
            self.assertEqual(surface.mode, "rgba32")
            self.assertEqual(surface.capacity_bytes, surface.width * surface.height * 4)
            decoded = decode_surface(surface_path)
            self.assertEqual(decoded.mode, "rgba32")
            self.assertEqual(decoded.payload, artifact.machine_text.encode("utf-8"))
            self.assertTrue(verify_surface(surface_path).ok)

            result = query_surface(surface_path, '"RGBA32 stores four exact channel bytes per pixel."')
            self.assertTrue(result.hits)
            self.assertEqual(result.hits[0]["record_type"], "QUOTE")
        finally:
            if surface_path.exists():
                surface_path.unlink()

    def test_holographic_surface_rgba64_roundtrips_and_queries_directly(self) -> None:
        text = (
            'Surface density: "RGBA64 stores eight exact channel bytes per pixel." '
            "SEAM uses RGBA64 only when 16-bit channel density is explicitly requested."
        )
        artifact = compress_text_readable(text, source_ref="unit://surface-rgba64", tokenizer="char4_approx")
        surface_path = Path(f"surface_rgba64_{uuid4().hex}.seam.png")
        try:
            surface = encode_surface(artifact.machine_text.encode("utf-8"), surface_path, mode="rgba64", payload_format="SEAM-RC/1")
            self.assertEqual(surface.mode, "rgba64")
            self.assertEqual(surface.capacity_bytes, surface.width * surface.height * 8)
            decoded = decode_surface(surface_path)
            self.assertEqual(decoded.mode, "rgba64")
            self.assertEqual(decoded.payload, artifact.machine_text.encode("utf-8"))
            self.assertTrue(verify_surface(surface_path).ok)

            result = query_surface(surface_path, '"RGBA64 stores eight exact channel bytes per pixel."')
            self.assertTrue(result.hits)
            self.assertEqual(result.hits[0]["record_type"], "QUOTE")
        finally:
            if surface_path.exists():
                surface_path.unlink()

    def test_holographic_surface_rgb_alias_uses_rgb24_adapter(self) -> None:
        text = 'Surface alias: "rgb selects the RGB24 adapter."'
        artifact = compress_text_readable(text, source_ref="unit://surface-rgb-alias", tokenizer="char4_approx")
        surface_path = Path(f"surface_rgb_alias_{uuid4().hex}.seam.png")
        try:
            surface = encode_surface(artifact.machine_text.encode("utf-8"), surface_path, mode="rgb", payload_format="SEAM-RC/1")
            self.assertEqual(surface.mode, "rgb24")
            decoded = decode_surface(surface_path)
            self.assertEqual(decoded.mode, "rgb24")
            self.assertEqual(decoded.payload, artifact.machine_text.encode("utf-8"))
        finally:
            if surface_path.exists():
                surface_path.unlink()

    def test_holographic_surface_mirl_bw1_searches_without_database_import(self) -> None:
        surface_path = Path(f"surface_mirl_{uuid4().hex}.seam.png")
        try:
            mirl_text = compile_dsl(
                """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate holographic_surface
  object direct_read_memory
"""
            ).to_text()
            encode_surface(mirl_text.encode("utf-8"), surface_path, mode="bw1", payload_format="MIRL")
            result = query_surface(surface_path, "holographic_surface direct_read_memory")
            self.assertTrue(result.hits)
            self.assertEqual(result.hits[0]["record_id"], "c1")
        finally:
            if surface_path.exists():
                surface_path.unlink()

    def test_cli_surface_encode_verify_query_and_decode(self) -> None:
        source_path = Path(f"surface_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"surface_cli_{uuid4().hex}.seam.png")
        decoded_path = Path(f"surface_decoded_{uuid4().hex}.seamrc")
        try:
            text = 'CLI note: "surface query reads embedded SEAM-RC/1 directly."'
            artifact = compress_text_readable(text, source_ref="unit://surface-cli", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")
            with redirect_stdout(StringIO()):
                run_cli(["surface", "encode", str(source_path), "--output", str(surface_path), "--mode", "rgb24"])
            self.assertTrue(surface_path.exists())

            verify_stream = StringIO()
            with redirect_stdout(verify_stream):
                run_cli(["surface", "verify", str(surface_path)])
            self.assertIn("PASS", verify_stream.getvalue())

            query_stream = StringIO()
            with redirect_stdout(query_stream):
                run_cli(["surface", "query", str(surface_path), '"surface query reads embedded SEAM-RC/1 directly."'])
            self.assertIn("Holographic surface query", query_stream.getvalue())
            self.assertIn("surface query reads embedded SEAM-RC/1 directly", query_stream.getvalue())

            with redirect_stdout(StringIO()):
                run_cli(["surface", "decode", str(surface_path), "--output", str(decoded_path)])
            self.assertEqual(decoded_path.read_text(encoding="utf-8"), artifact.machine_text)
        finally:
            for path in (source_path, surface_path, decoded_path):
                if path.exists():
                    path.unlink()

    def test_cli_surface_store_list_show_and_query_by_library_id(self) -> None:
        source_path = Path(f"surface_library_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"surface_library_{uuid4().hex}.seam.png")
        artifact_dir = TEST_ARTIFACT_DIR / f"surfaces_{uuid4().hex}"
        try:
            text = 'Library note: "stored surfaces stay directly queryable by id."'
            artifact = compress_text_readable(text, source_ref="unit://surface-library", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")

            encode_stream = StringIO()
            with redirect_stdout(encode_stream):
                run_cli([
                    "--db",
                    str(self.db_path),
                    "surface",
                    "encode",
                    str(source_path),
                    "--output",
                    str(surface_path),
                    "--store",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--format",
                    "json",
                ])
            payload = json.loads(encode_stream.getvalue())
            library = payload["library"]
            surface_id = library["surface_id"]
            self.assertTrue(surface_id.startswith("hs:"))
            self.assertEqual(library["verification_status"], "PASS")
            self.assertEqual(library["query_status"], "direct_queryable")

            list_stream = StringIO()
            with redirect_stdout(list_stream):
                run_cli(["--db", str(self.db_path), "surface", "list", "--format", "json"])
            listed = json.loads(list_stream.getvalue())["surfaces"]
            self.assertEqual([row["surface_id"] for row in listed], [surface_id])

            show_stream = StringIO()
            with redirect_stdout(show_stream):
                run_cli(["--db", str(self.db_path), "surface", "show", surface_id, "--format", "json"])
            shown = json.loads(show_stream.getvalue())
            self.assertNotEqual(shown["artifact_path"], str(surface_path.resolve()))
            self.assertTrue(Path(shown["artifact_path"]).exists())

            surface_path.unlink()

            query_stream = StringIO()
            with redirect_stdout(query_stream):
                run_cli([
                    "--db",
                    str(self.db_path),
                    "surface",
                    "query",
                    surface_id,
                    '"stored surfaces stay directly queryable by id."',
                ])
            self.assertIn("Holographic surface query", query_stream.getvalue())
            self.assertIn("stored surfaces stay directly queryable by id", query_stream.getvalue())
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for child in artifact_dir.glob("*"):
                    if child.is_file():
                        child.unlink()
                artifact_dir.rmdir()

    def test_cli_surface_repair_restores_missing_redundant_copy(self) -> None:
        source_path = Path(f"surface_repair_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"surface_repair_{uuid4().hex}.seam.png")
        artifact_dir = TEST_ARTIFACT_DIR / f"repair_surfaces_{uuid4().hex}"
        try:
            text = 'Repair note: "surface repair rebuilds the redundant copy."'
            artifact = compress_text_readable(text, source_ref="unit://surface-repair", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")

            encode_stream = StringIO()
            with redirect_stdout(encode_stream):
                run_cli([
                    "--db",
                    str(self.db_path),
                    "surface",
                    "encode",
                    str(source_path),
                    "--output",
                    str(surface_path),
                    "--store",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--format",
                    "json",
                ])
            payload = json.loads(encode_stream.getvalue())
            surface_id = payload["library"]["surface_id"]
            stored_path = Path(payload["library"]["artifact_path"])
            self.assertTrue(stored_path.exists())
            stored_path.unlink()
            self.assertFalse(stored_path.exists())

            repair_stream = StringIO()
            with redirect_stdout(repair_stream):
                run_cli(["--db", str(self.db_path), "surface", "repair", surface_id, "--format", "json"])
            repaired = json.loads(repair_stream.getvalue())
            self.assertEqual(repaired["repair"]["status"], "PASS")
            self.assertEqual(repaired["repair"]["action"], "repaired_from_source")
            self.assertTrue(stored_path.exists())
            self.assertEqual(repaired["surface"]["verification_status"], "PASS")

            surface_path.unlink()
            query_stream = StringIO()
            with redirect_stdout(query_stream):
                run_cli(["--db", str(self.db_path), "surface", "query", surface_id, '"surface repair rebuilds the redundant copy."'])
            self.assertIn("surface repair rebuilds the redundant copy", query_stream.getvalue())
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for child in artifact_dir.glob("*"):
                    if child.is_file():
                        child.unlink()
                artifact_dir.rmdir()

    def test_cli_surface_repair_marks_failure_without_source(self) -> None:
        source_path = Path(f"surface_repair_fail_source_{uuid4().hex}.seamrc")
        surface_path = Path(f"surface_repair_fail_{uuid4().hex}.seam.png")
        try:
            text = 'Repair failure note: "missing sources cannot repair."'
            artifact = compress_text_readable(text, source_ref="unit://surface-repair-fail", tokenizer="char4_approx")
            source_path.write_text(artifact.machine_text, encoding="utf-8")

            encode_stream = StringIO()
            with redirect_stdout(encode_stream):
                run_cli([
                    "--db",
                    str(self.db_path),
                    "surface",
                    "encode",
                    str(source_path),
                    "--output",
                    str(surface_path),
                    "--store",
                    "--no-copy",
                    "--format",
                    "json",
                ])
            payload = json.loads(encode_stream.getvalue())
            surface_id = payload["library"]["surface_id"]
            source_path.unlink()
            surface_path.unlink()

            repair_stream = StringIO()
            with redirect_stdout(repair_stream):
                run_cli(["--db", str(self.db_path), "surface", "repair", surface_id, "--format", "json"])
            repaired = json.loads(repair_stream.getvalue())
            self.assertEqual(repaired["repair"]["status"], "FAIL")
            self.assertEqual(repaired["surface"]["verification_status"], "FAIL")
            self.assertEqual(repaired["surface"]["query_status"], "unavailable")
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()

    def test_cli_surface_compile_builds_mirl_surface_without_import(self) -> None:
        source_path = Path(f"surface_compile_source_{uuid4().hex}.txt")
        surface_path = Path(f"surface_compile_{uuid4().hex}.seam.png")
        try:
            source_path.write_text(
                "SEAM should compile automatic holographic memory for behavior and compression.",
                encoding="utf-8",
            )
            stream = StringIO()
            with redirect_stdout(stream):
                run_cli(["surface", "compile", str(source_path), "--output", str(surface_path), "--mode", "rgb24"])
            output = stream.getvalue()
            self.assertIn("Holographic surface compiled", output)
            self.assertTrue(surface_path.exists())

            decoded = decode_surface(surface_path)
            self.assertEqual(decoded.payload_format, "MIRL")
            self.assertEqual(decoded.mode, "rgb24")
            # The floor extracts "SEAM" as a grounded entity (no fabricated project/user).
            self.assertIn("ENT|ent:seam", decoded.text)
            self.assertIn("CLM|clm:", decoded.text)

            result = query_surface(surface_path, "holographic memory")
            self.assertTrue(result.hits)
            self.assertTrue(verify_surface(surface_path).ok)
        finally:
            for path in (source_path, surface_path):
                if path.exists():
                    path.unlink()

    def test_holographic_surface_rejects_jpeg_for_exact_memory(self) -> None:
        jpeg_path = Path(f"surface_lossy_{uuid4().hex}.jpg")
        try:
            jpeg_path.write_bytes(b"\xff\xd8not-a-real-surface")
            result = verify_surface(jpeg_path)
            self.assertFalse(result.ok)
            self.assertTrue(any("JPEG" in error for error in result.errors),
                            "JPEG input should be rejected with a format error")
        finally:
            if jpeg_path.exists():
                jpeg_path.unlink()

    def test_cli_lossless_compress_and_decompress_roundtrip(self) -> None:
        source_path = Path(f"lossless_source_{uuid4().hex}.txt")
        compressed_path = Path(f"lossless_machine_{uuid4().hex}.seamlx")
        try:
            source_text = ("SEAM preserves exact context while compressing token usage for lossless recovery. " * 16).strip()
            source_path.write_text(source_text, encoding="utf-8")
            compress_stream = StringIO()
            with redirect_stdout(compress_stream):
                run_cli(["lossless-compress", str(source_path), "--output", str(compressed_path), "--format", "json"])
            compressed_payload = compress_stream.getvalue()
            self.assertIn('"machine_text"', compressed_payload)
            self.assertTrue(compressed_path.exists())

            decompress_stream = StringIO()
            with redirect_stdout(decompress_stream):
                run_cli(["lossless-decompress", str(compressed_path)])
            restored = decompress_stream.getvalue().strip()
            self.assertEqual(restored, source_text)
        finally:
            if source_path.exists():
                source_path.unlink()
            if compressed_path.exists():
                compressed_path.unlink()

    def test_cli_lossless_benchmark_json_reports_pass(self) -> None:
        source_path = Path(f"lossless_benchmark_{uuid4().hex}.txt")
        try:
            source_text = "\n".join(["SEAM preserves exact context while compressing token usage for lossless recovery."] * 60)
            source_path.write_text(source_text, encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                run_cli(["lossless-benchmark", str(source_path), "--min-savings", "0.75", "--format", "json"])
            payload = stream.getvalue()
            self.assertIn('"passed": true', payload)
            self.assertIn('"roundtrip_match": true', payload)
            self.assertIn('"search_log"', payload)
        finally:
            if source_path.exists():
                source_path.unlink()

    def test_cli_demo_lossless_compress_and_rebuild_roundtrip(self) -> None:
        source_path = Path(f"lossless_demo_source_{uuid4().hex}.txt")
        compressed_path = Path(f"lossless_demo_machine_{uuid4().hex}.seamlx")
        rebuilt_path = Path(f"lossless_demo_rebuilt_{uuid4().hex}.txt")
        log_path = Path(f"lossless_demo_log_{uuid4().hex}.json")
        try:
            source_text = "\n".join(["SEAM preserves exact context while compressing token usage for lossless recovery."] * 60)
            source_path.write_text(source_text, encoding="utf-8")

            compress_stream = StringIO()
            with redirect_stdout(compress_stream):
                run_cli(
                    [
                        "demo",
                        "lossless",
                        str(source_path),
                        str(compressed_path),
                        "--min-savings",
                        "0.75",
                        "--log-output",
                        str(log_path),
                    ]
                )
            self.assertIn("Demo: PASS", compress_stream.getvalue())
            self.assertTrue(compressed_path.exists())
            self.assertTrue(log_path.exists())
            self.assertTrue(compressed_path.read_text(encoding="utf-8").startswith("SEAM-LX/1"))

            rebuild_stream = StringIO()
            with redirect_stdout(rebuild_stream):
                run_cli(["demo", "lossless", str(compressed_path), str(rebuilt_path), "--rebuild"])
            self.assertIn("Demo: REBUILD PASS", rebuild_stream.getvalue())
            self.assertEqual(rebuilt_path.read_text(encoding="utf-8"), source_text)
        finally:
            for path in (source_path, compressed_path, rebuilt_path, log_path):
                if path.exists():
                    path.unlink()

    def test_runtime_benchmark_suite_persists_and_verifies_bundle(self) -> None:
        runtime = SeamRuntime(self.db_path)
        bundle_path = Path(f"benchmark_bundle_{uuid4().hex}.json")
        try:
            report = runtime.run_benchmark_suite(suite="all", persist=True, bundle_path=bundle_path)
            self.assertEqual(report["summary"]["status"], "PASS")
            self.assertEqual(report["summary"]["family_count"], 8)
            self.assertTrue(bundle_path.exists())

            runs = runtime.list_benchmark_runs(limit=1)
            self.assertTrue(runs)
            self.assertEqual(runs[0]["run_id"], report["manifest"]["run_id"])

            loaded = runtime.read_benchmark_run(report["manifest"]["run_id"])
            self.assertEqual(loaded["bundle_hash"], report["bundle_hash"])

            verification = runtime.verify_benchmark_bundle(bundle_path)
            self.assertEqual(verification["status"], "PASS")
            self.assertTrue(verification["bundle_hash_ok"])
        finally:
            if bundle_path.exists():
                bundle_path.unlink()

    def test_runtime_benchmark_temp_databases_are_cleaned_up(self) -> None:
        temp_root = Path(tempfile.gettempdir())
        patterns = ("seam-bench-long-*.db*", "seam-bench-agent-*.db*")
        for pattern in patterns:
            for path in temp_root.glob(pattern):
                path.unlink(missing_ok=True)

        runtime = SeamRuntime(self.db_path)
        report = runtime.run_benchmark_suite(suite="long_context")
        self.assertEqual(report["summary"]["status"], "PASS")
        report = runtime.run_benchmark_suite(suite="agent_tasks")
        self.assertEqual(report["summary"]["status"], "PASS")

        leftovers = [path for pattern in patterns for path in temp_root.glob(pattern)]
        for path in leftovers:
            path.unlink(missing_ok=True)
        self.assertEqual(leftovers, [])

    def test_runtime_readable_benchmark_compares_rc1_to_source(self) -> None:
        runtime = SeamRuntime(self.db_path)
        report = runtime.run_benchmark_suite(suite="readable", tokenizer="char4_approx")
        self.assertEqual(report["summary"]["status"], "PASS")
        family = report["families"]["readable"]
        self.assertEqual(family["summary"]["direct_text_exact_rate"], 1.0)
        self.assertEqual(family["summary"]["direct_read_equivalence_rate"], 1.0)
        self.assertEqual(family["summary"]["direct_query_exactness_rate"], 1.0)
        self.assertTrue(family["cases"])
        for case in family["cases"]:
            self.assertTrue(case["metrics"]["roundtrip_match"])
            self.assertTrue(case["metrics"]["direct_text_match"])
            self.assertTrue(case["metrics"]["direct_quote_match"])
            self.assertTrue(case["metrics"]["direct_query_exactness"])
            self.assertTrue(case["metrics"]["term_coverage"])
            self.assertTrue(case["metrics"]["info_equivalent"])
        recipe = next(case for case in family["cases"] if case["case_id"] == "rc1_recipe_exact_direct_read")
        self.assertEqual(
            recipe["trace"]["direct_read_text"],
            "\n".join(
                [
                    "Recipe: Lemon Rice",
                    "Yield: 2 servings",
                    "Ingredients:",
                    "- 1 cup cooked rice",
                    "- 1 tablespoon lemon juice",
                    "- 1 teaspoon olive oil",
                    "- 1/4 teaspoon salt",
                    "Steps:",
                    "1. Warm the olive oil in a pan for 30 seconds.",
                    "2. Stir in the cooked rice and salt.",
                    "3. Turn off the heat and fold in the lemon juice.",
                    'Note: "Serve immediately while warm."',
                ]
            ),
        )

    def test_cli_benchmark_readable_json_reports_direct_equivalence(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["benchmark", "run", "readable", "--tokenizer", "char4_approx", "--format", "json"])
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["summary"]["status"], "PASS")
        self.assertEqual(payload["families"]["readable"]["summary"]["direct_text_exact_rate"], 1.0)
        self.assertEqual(payload["families"]["readable"]["summary"]["direct_read_equivalence_rate"], 1.0)
        self.assertEqual(payload["families"]["readable"]["summary"]["direct_query_exactness_rate"], 1.0)

    def test_runtime_surface_benchmark_gates_exact_visual_payloads(self) -> None:
        runtime = SeamRuntime(self.db_path)
        report = runtime.run_benchmark_suite(suite="surface")
        self.assertEqual(report["summary"]["status"], "PASS")
        family = report["families"]["surface"]
        self.assertEqual(family["summary"]["surface_exact_rate"], 1.0)
        self.assertEqual(family["summary"]["payload_hash_match_rate"], 1.0)
        self.assertEqual(family["summary"]["direct_query_exactness_rate"], 1.0)
        self.assertEqual(family["summary"]["stored_lookup_rate"], 1.0)
        self.assertEqual(family["summary"]["stored_query_exactness_rate"], 1.0)
        self.assertEqual(family["summary"]["repair_success_rate"], 1.0)
        self.assertEqual(family["summary"]["repair_query_exactness_rate"], 1.0)
        self.assertTrue(family["cases"])
        for case in family["cases"]:
            self.assertTrue(case["metrics"]["surface_exact"])
            self.assertTrue(case["metrics"]["payload_hash_match"])
            self.assertTrue(case["metrics"]["direct_query_exactness"])
            self.assertTrue(case["metrics"]["stored_lookup"])
            self.assertTrue(case["metrics"]["stored_query_exactness"])
            self.assertTrue(case["metrics"]["repair_ok"])
            self.assertTrue(case["metrics"]["repair_query_exactness"])
            self.assertTrue(case["trace"]["stored_surface"]["original_removed_before_stored_query"])

    def test_cli_benchmark_surface_json_reports_exact_gate(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["benchmark", "run", "surface", "--format", "json"])
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["summary"]["status"], "PASS")
        self.assertEqual(payload["families"]["surface"]["summary"]["surface_exact_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["payload_hash_match_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["direct_query_exactness_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["stored_lookup_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["stored_query_exactness_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["repair_success_rate"], 1.0)
        self.assertEqual(payload["families"]["surface"]["summary"]["repair_query_exactness_rate"], 1.0)

    def test_benchmark_diff_compares_case_deltas(self) -> None:
        runtime = SeamRuntime(self.db_path)
        before = runtime.run_benchmark_suite(suite="lossless", tokenizer="char4_approx")
        after = json.loads(json.dumps(before))
        case = after["families"]["lossless"]["cases"][0]
        case["metrics"]["token_savings_ratio"] = round(case["metrics"]["token_savings_ratio"] + 0.05, 6)
        after["families"]["lossless"]["cases"][0] = benchmark_module._stamp_case_hash(case)
        after["summary"] = benchmark_module._build_suite_summary(after["families"])
        after["bundle_hash"] = benchmark_module._hash_payload(after, "bundle_hash")

        diff = runtime.diff_benchmark_runs(before, after)
        self.assertEqual(diff["summary"]["cases_compared"], before["summary"]["case_count"])
        self.assertEqual(diff["summary"]["changed_case_matches"], 1)
        changed = [item for item in diff["cases"] if item["case_hash_changed"]]
        self.assertEqual(len(changed), 1)
        savings_delta = [item for item in changed[0]["metric_deltas"] if item["metric"] == "token_savings_ratio"][0]
        self.assertEqual(savings_delta["indicator"], "green")

    def test_benchmark_gate_passes_custom_lossless_policy(self) -> None:
        runtime = SeamRuntime(self.db_path)
        report = runtime.run_benchmark_suite(suite="lossless", tokenizer="char4_approx")
        policy = {
            "version": benchmark_module.BENCHMARK_GATE_VERSION,
            "required_families": ["lossless"],
            "summary": {
                "status": {"equals": "PASS"},
                "family_count": {"minimum": 1},
                "case_count": {"minimum": 2},
            },
            "families": {
                "lossless": {
                    "pass_rate": {"minimum": 1.0},
                    "exactness_rate": {"minimum": 1.0},
                }
            },
            "baseline": {
                "status_regressions": {"maximum": 0},
                "metric_regressions": {"maximum": 0},
                "removed_cases": {"maximum": 0},
            },
        }

        gate = runtime.evaluate_benchmark_gate(report, policy=policy)
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["summary"]["failed"], 0)
        self.assertTrue(all(check["status"] == "PASS" for check in gate["checks"]))
        check_statuses = {check["status"] for check in gate["checks"]}
        self.assertEqual(check_statuses, {"PASS"})

    def test_benchmark_gate_flags_threshold_failure(self) -> None:
        runtime = SeamRuntime(self.db_path)
        report = runtime.run_benchmark_suite(suite="lossless", tokenizer="char4_approx")
        policy = {
            "version": benchmark_module.BENCHMARK_GATE_VERSION,
            "required_families": ["lossless"],
            "summary": {"status": {"equals": "PASS"}},
            "families": {"lossless": {"worst_case_savings": {"minimum": 1.0}}},
            "baseline": {},
        }

        gate = runtime.evaluate_benchmark_gate(report, policy=policy)
        self.assertEqual(gate["status"], "FAIL")
        failed = [check for check in gate["checks"] if check["status"] == "FAIL"]
        failed_metrics = {check["metric"] for check in failed}
        self.assertIn("worst_case_savings", failed_metrics)

    def test_cli_benchmark_diff_json_accepts_bundle_paths(self) -> None:
        runtime = SeamRuntime(self.db_path)
        first_path = Path(f"benchmark_diff_a_{uuid4().hex}.json")
        second_path = Path(f"benchmark_diff_b_{uuid4().hex}.json")
        try:
            first = runtime.run_benchmark_suite(suite="lossless", tokenizer="char4_approx", bundle_path=first_path)
            second = json.loads(json.dumps(first))
            second["families"]["lossless"]["cases"][0]["status"] = "FAIL"
            second["families"]["lossless"]["cases"][0] = benchmark_module._stamp_case_hash(second["families"]["lossless"]["cases"][0])
            second["summary"] = benchmark_module._build_suite_summary(second["families"])
            second["bundle_hash"] = benchmark_module._hash_payload(second, "bundle_hash")
            second_path.write_text(json.dumps(second, indent=2), encoding="utf-8")

            stream = StringIO()
            with redirect_stdout(stream):
                run_cli(["--db", str(self.db_path), "benchmark", "diff", str(first_path), str(second_path), "--format", "json"])
            payload = json.loads(stream.getvalue())
            self.assertEqual(payload["summary"]["status_regressions"], 1)
            self.assertEqual(payload["summary"]["status"], "REGRESSED")
        finally:
            for path in (first_path, second_path):
                if path.exists():
                    path.unlink()

    def test_cli_benchmark_gate_exits_nonzero_on_baseline_regression(self) -> None:
        runtime = SeamRuntime(self.db_path)
        baseline_path = Path(f"benchmark_gate_a_{uuid4().hex}.json")
        candidate_path = Path(f"benchmark_gate_b_{uuid4().hex}.json")
        policy_path = Path(f"benchmark_gate_policy_{uuid4().hex}.json")
        try:
            baseline = runtime.run_benchmark_suite(suite="lossless", tokenizer="char4_approx", bundle_path=baseline_path)
            candidate = json.loads(json.dumps(baseline))
            candidate["families"]["lossless"]["cases"][0]["status"] = "FAIL"
            candidate["families"]["lossless"]["cases"][0] = benchmark_module._stamp_case_hash(candidate["families"]["lossless"]["cases"][0])
            candidate["summary"] = benchmark_module._build_suite_summary(candidate["families"])
            candidate["bundle_hash"] = benchmark_module._hash_payload(candidate, "bundle_hash")
            candidate_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
            policy_path.write_text(
                json.dumps(
                    {
                        "version": benchmark_module.BENCHMARK_GATE_VERSION,
                        "required_families": ["lossless"],
                        "summary": {},
                        "families": {},
                        "baseline": {"status_regressions": {"maximum": 0}},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            stream = StringIO()
            with redirect_stdout(stream), self.assertRaises(SystemExit) as raised:
                run_cli(
                    [
                        "--db",
                        str(self.db_path),
                        "benchmark",
                        "gate",
                        str(candidate_path),
                        "--baseline",
                        str(baseline_path),
                        "--policy",
                        str(policy_path),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(raised.exception.code, 1)
            payload = json.loads(stream.getvalue())
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["baseline_diff"]["summary"]["status_regressions"], 1)
        finally:
            for path in (baseline_path, candidate_path, policy_path):
                if path.exists():
                    path.unlink()

    def test_cli_benchmark_holdout_requires_confirmation(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            run_cli(["benchmark", "run", "lossless", "--holdout", "--format", "json"])
        self.assertIn("--confirm-holdout", str(raised.exception))

    def test_cli_benchmark_holdout_uses_private_fixture_and_separate_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seam-holdout-fixtures-") as fixture_dir, tempfile.TemporaryDirectory(
            prefix="seam-holdout-runs-"
        ) as run_dir:
            fixture_root = Path(fixture_dir)
            run_root = Path(run_dir)
            (fixture_root / "lossless_cases.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "private_lossless_repeat",
                            "text": "Holdout compression phrase stays hidden during tuning.\n" * 24,
                            "min_token_savings": 0.30,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with patch.object(benchmark_module, "HOLDOUT_FIXTURE_ROOT", fixture_root), patch.object(
                benchmark_module, "HOLDOUT_RUN_ROOT", run_root
            ):
                stream = StringIO()
                with redirect_stdout(stream):
                    run_cli(["benchmark", "run", "lossless", "--holdout", "--confirm-holdout", "--tokenizer", "char4_approx", "--format", "json"])
                payload = json.loads(stream.getvalue())
                self.assertEqual(payload["manifest"]["fixture_scope"], "holdout")
                self.assertTrue(payload["manifest"]["publish_only"])
                self.assertEqual(payload["manifest"]["executed_suites"], ["lossless"])
                self.assertEqual(payload["families"]["lossless"]["cases"][0]["case_id"], "private_lossless_repeat")
                self.assertTrue(list(run_root.glob("*.json")))

    def test_runtime_benchmark_verifier_flags_tampered_bundle(self) -> None:
        runtime = SeamRuntime(self.db_path)
        bundle_path = Path(f"benchmark_bundle_{uuid4().hex}.json")
        tampered_path = Path(f"benchmark_bundle_tampered_{uuid4().hex}.json")
        try:
            runtime.run_benchmark_suite(suite="lossless", bundle_path=bundle_path)
            payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            payload["families"]["lossless"]["cases"][0]["metrics"]["roundtrip_match"] = False
            tampered_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            verification = runtime.verify_benchmark_bundle(tampered_path)
            self.assertEqual(verification["status"], "FAIL")
            self.assertFalse(verification["bundle_hash_ok"])
            failed_cases = [item for item in verification["case_checks"] if not item["ok"]]
            self.assertTrue(failed_cases, "Expected at least one failed case check")
        finally:
            for target in (bundle_path, tampered_path):
                if target.exists():
                    target.unlink()

    def test_storage_machine_artifact_and_projection_roundtrip(self) -> None:
        runtime = SeamRuntime(self.db_path)
        artifact = compress_text_lossless("SEAM preserves exact context while compressing token usage for lossless recovery.\n" * 10)
        artifact_id = runtime.store.write_machine_artifact(
            source_type="test.machine",
            source_id="machine-roundtrip",
            artifact=artifact.to_dict(include_machine_text=True),
            roundtrip_ok=True,
            metadata={"suite": "unit"},
        )
        loaded_artifact = runtime.store.read_machine_artifact(artifact_id)
        self.assertTrue(loaded_artifact["roundtrip_ok"])
        self.assertEqual(loaded_artifact["metadata"], {"suite": "unit"})
        self.assertTrue(str(loaded_artifact["machine_text"]).startswith("SEAM-LX/1"))

        projection_id = runtime.store.write_projection(
            record_id="clm:test",
            projection_kind="prompt",
            projection_text="SEAM retrieved context\n[1] clm:test [CLM] translator_for natural_language",
            tokenizer="char4_approx",
            token_count=17,
            metadata={"suite": "unit"},
        )
        projections = runtime.store.read_projections(record_id="clm:test", projection_kind="prompt")
        self.assertEqual(len(projections), 1)
        self.assertEqual(projections[0]["projection_id"], projection_id)
        self.assertEqual(projections[0]["metadata"], {"suite": "unit"})

    def test_cli_benchmark_show_latest_reads_persisted_run(self) -> None:
        bundle_path = Path(f"benchmark_cli_bundle_{uuid4().hex}.json")
        try:
            run_stream = StringIO()
            with redirect_stdout(run_stream):
                run_cli([
                    "--db",
                    str(self.db_path),
                    "benchmark",
                    "run",
                    "lossless",
                    "--persist",
                    "--output",
                    str(bundle_path),
                    "--format",
                    "json",
                ])
            payload = run_stream.getvalue()
            self.assertIn('"requested_suite": "lossless"', payload)

            show_stream = StringIO()
            with redirect_stdout(show_stream):
                run_cli(["--db", str(self.db_path), "benchmark", "show", "latest", "--format", "json"])
            show_payload = show_stream.getvalue()
            self.assertIn('"requested_suite": "lossless"', show_payload)
            self.assertIn('"bundle_hash"', show_payload)
        finally:
            if bundle_path.exists():
                bundle_path.unlink()

    def test_cli_compile_nl_rag_sync_persists_and_syncs(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(
                [
                    "--db",
                    str(self.db_path),
                    "compile-nl",
                    "We need a translator back into natural language for memory workflows.",
                    "--index",
                ]
            )
        runtime = SeamRuntime(self.db_path)
        records = runtime.store.load_ir().records
        self.assertTrue(records)

    def test_cli_doctor_reports_pass(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["doctor"])
        payload = stream.getvalue()
        required = ["rich", "chromadb", "tiktoken"]
        missing = [name for name in required if find_spec(name) is None]
        expected = "PASS" if not missing else "FAIL"
        self.assertIn(f"SEAM doctor: {expected}", payload)
        self.assertIn("Compile smoke: PASS", payload)
        self.assertIn("PgVector:", payload)
        self.assertIn("Required deps:", payload)

    def test_cli_doctor_reports_pgvector_not_configured_when_dsn_absent(self) -> None:
        old = os.environ.pop("SEAM_PGVECTOR_DSN", None)
        try:
            stream = StringIO()
            with redirect_stdout(stream):
                run_cli(["doctor"])
            self.assertIn("PgVector: not configured", stream.getvalue())
        finally:
            if old is not None:
                os.environ["SEAM_PGVECTOR_DSN"] = old

    def test_cli_doctor_json_reports_dependency_status(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            run_cli(["doctor", "--format", "json"])
        payload = json.loads(stream.getvalue())
        required = ["rich", "chromadb", "tiktoken"]
        missing = [name for name in required if find_spec(name) is None]
        expected = "PASS" if not missing else "FAIL"
        self.assertEqual(payload["status"], expected)
        self.assertIn("dependencies", payload)
        self.assertIn("required_dependencies", payload)
        self.assertIn("missing_required_dependencies", payload)
        self.assertEqual(sorted(payload["required_dependencies"]), sorted(required))
        self.assertEqual(sorted(payload["missing_required_dependencies"]), sorted(missing))
        self.assertIn("psycopg", payload["dependencies"])
        self.assertIn("sentence_transformers", payload["dependencies"])
        self.assertIn("pgvector", payload)
        self.assertIn("configured", payload["pgvector"])

    def test_installer_windows_shim_sets_persistent_db(self) -> None:
        shim = render_windows_cmd_shim(
            Path(r"C:\SEAM\runtime\Scripts\seam.exe"),
            Path(r"C:\Repos\Seam"),
            r'powershell -ExecutionPolicy Bypass -File "C:\Repos\Seam\installers\install_seam_windows.ps1"',
            Path(r"C:\Users\iwana\AppData\Local\SEAM\state\seam.db"),
        )
        self.assertIn("SEAM_DB_PATH", shim)
        self.assertIn(r"C:\Users\iwana\AppData\Local\SEAM\state\seam.db", shim)

    def test_installer_posix_shim_sets_persistent_db(self) -> None:
        shim = render_posix_shim(
            Path("/home/iwana/.local/share/seam/runtime/bin/seam"),
            Path("/repos/seam"),
            '"/repos/seam/installers/install_seam_linux.sh"',
            Path("/home/iwana/.local/share/seam/state/seam.db"),
        )
        self.assertIn('export SEAM_DB_PATH="/home/iwana/.local/share/seam/state/seam.db"', shim)

    def test_default_runtime_db_path_prefers_env(self) -> None:
        original = os.environ.get("SEAM_DB_PATH")
        try:
            os.environ["SEAM_DB_PATH"] = "custom-seam.db"
            self.assertEqual(default_runtime_db_path(), "custom-seam.db")
        finally:
            if original is None:
                os.environ.pop("SEAM_DB_PATH", None)
            else:
                os.environ["SEAM_DB_PATH"] = original

    def test_dashboard_snapshot_renders_runtime_metrics(self) -> None:
        if Console is None:
            self.skipTest("rich is not installed")
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("We need a translator back into natural language for memory workflows."))
        stream = StringIO()
        console = Console(file=stream, force_terminal=False, color_system=None, width=140)
        run_dashboard(runtime, snapshot=True, no_clear=True, console=console)
        output = stream.getvalue()
        self.assertIn("SEAM Console", output)
        self.assertIn("Storage", output)
        self.assertIn("Records", output)

    def test_dashboard_script_handles_success_and_error(self) -> None:
        if Console is None:
            self.skipTest("rich is not installed")
        runtime = SeamRuntime(self.db_path)
        stream = StringIO()
        console = Console(file=stream, force_terminal=False, color_system=None, width=140)
        run_dashboard(
            runtime,
            no_clear=True,
            console=console,
            commands=[
                "compile We need a translator back into natural language for memory workflows.",
                "retrieve translator natural language --budget 3",
                "trace missing:id",
            ],
        )
        output = stream.getvalue()
        self.assertIn("SEAM Console", output)
        self.assertIn("missing:id", output)
        self.assertIn("Runtime Log", output)

    def test_mirl_animation_settles_on_completed_frame(self) -> None:
        engine = AnimationEngine(height=4)
        self.assertFalse(engine.active)
        self.assertIn("Idle", "\n".join(engine.tick_and_render(now=0.0)))

        engine.trigger_compress("compile", source_tokens=90, machine_tokens=30, kind="compile")
        rows: list[str] = []
        for tick in range(40):
            rows = engine.tick_and_render(now=tick * 0.25)

        self.assertFalse(engine.active)
        self.assertTrue(engine.has_completed_frame)
        self.assertIn("complete", "\n".join(rows))
        self.assertEqual(rows, engine.tick_and_render(now=30.0))

    def test_dashboard_benchmark_tab_renders_benchmark_surface(self) -> None:
        if Console is None:
            self.skipTest("rich is not installed")
        runtime = SeamRuntime(self.db_path)
        source_path = Path(f"lossless_dashboard_{uuid4().hex}.txt")
        try:
            source_path.write_text(
                ("SEAM preserves exact context while compressing token usage for lossless recovery. " * 20).strip(),
                encoding="utf-8",
            )
            stream = StringIO()
            console = Console(file=stream, force_terminal=False, color_system=None, width=160)
            run_dashboard(
                runtime,
                no_clear=True,
                console=console,
                commands=[
                    "tab benchmark",
                    f"benchmark {source_path} --min-savings 0.75",
                ],
            )
            output = stream.getvalue()
            self.assertIn("Benchmark", output)
            self.assertIn("Search log", output)
        finally:
            if source_path.exists():
                source_path.unlink()

    def test_dashboard_reload_refreshes_scripted_runtime_view(self) -> None:
        if Console is None:
            self.skipTest("rich is not installed")
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl("SEAM reload should refresh dashboard runtime charts."))
        stream = StringIO()
        console = Console(file=stream, force_terminal=False, color_system=None, width=160)
        run_dashboard(runtime, no_clear=True, console=console, commands=["reload"])
        output = stream.getvalue()
        self.assertIn("Reload", output)
        self.assertIn("reloaded", output)
        self.assertIn("Records", output)

    def test_textual_dashboard_mounts_core_panels(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                # IDE layout: panels exist in DOM regardless of which tab is active
                self.assertIsNotNone(app.query_one("#memory-panel"))
                self.assertIsNotNone(app.query_one("#retrieval-panel"))
                self.assertIsNotNone(app.query_one("#benchmark-panel"))
                self.assertIsNotNone(app.query_one("#overview-panel"))
                self.assertIsNotNone(app.query_one("#mirl-panel"))
                self.assertIsNotNone(app.query_one("#prov-panel"))
                self.assertIsNotNone(app.query_one("#explorer-tree"))
                self.assertIsNotNone(app.query_one("#ide-layout"))
                self.assertIsNotNone(app.query_one("#right-col"))
                self.assertIsNotNone(app.query_one("#chat-panel"))
                self.assertIsNotNone(app.query_one("#result-panel"))
                self.assertIsNotNone(app.query_one("#status-bar"))
                self.assertIsNotNone(app.query_one("#command-palette"))
                self.assertIsNotNone(app.query_one("#command-input"))

        asyncio.run(_check())

    def test_textual_dashboard_settings_apply_api_updates_env(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        from textual.widgets import TabbedContent

        saved = {
            "SEAM_CHAT_API_KEY": os.environ.get("SEAM_CHAT_API_KEY"),
            "SEAM_CHAT_BASE_URL": os.environ.get("SEAM_CHAT_BASE_URL"),
            "SEAM_CHAT_MODEL": os.environ.get("SEAM_CHAT_MODEL"),
        }
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(160, 60)) as pilot:
                await pilot.pause()
                app.query_one("#main-tabs", TabbedContent).active = "tab-settings"
                await pilot.pause()
                app.query_one("#cfg-api-key").value = "test-settings-key"
                app.query_one("#cfg-base-url").value = "https://example.invalid/v1"
                app.query_one("#cfg-model").value = "test-model"
                app._on_btn_apply_api(None)
                await pilot.pause()
                self.assertEqual(os.environ.get("SEAM_CHAT_API_KEY"), "test-settings-key")
                self.assertEqual(os.environ.get("SEAM_CHAT_BASE_URL"), "https://example.invalid/v1")
                self.assertEqual(os.environ.get("SEAM_CHAT_MODEL"), "test-model")
                self.assertTrue(any("Applied: SEAM_CHAT_API_KEY" in line for line in app.result_lines),
                                "Settings apply should log API key confirmation")

        try:
            asyncio.run(_check())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_textual_dashboard_new_layout_keeps_overview_live_and_tabs_chat_results(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        from textual.widgets import TabbedContent

        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(160, 60)) as pilot:
                await pilot.pause()
                tabs = app.query_one("#main-tabs", TabbedContent)
                overview = app.query_one("#overview-panel")
                chat = app.query_one("#chat-panel")
                results = app.query_one("#result-panel")

                self.assertEqual(getattr(overview.parent, "id", None), "right-col")
                self.assertNotIn("tab-overview", {tab.id for tab in tabs.query("TabPane")})
                self.assertEqual(getattr(chat.parent, "id", None), "tab-chat")
                self.assertEqual(getattr(results.parent, "id", None), "live-row")

        asyncio.run(_check())

    def test_textual_dashboard_settings_include_surface_and_provider_controls(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        from textual.widgets import TabbedContent

        saved_surface_mode = os.environ.get("SEAM_SURFACE_MODE")
        saved_openrouter = os.environ.get("OPENROUTER_API_KEY")
        saved_chat_key = os.environ.get("SEAM_CHAT_API_KEY")
        saved_chat_base = os.environ.get("SEAM_CHAT_BASE_URL")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(160, 70)) as pilot:
                await pilot.pause()
                app.query_one("#main-tabs", TabbedContent).active = "tab-settings"
                await pilot.pause()

                app.query_one("#cfg-surface-mode").value = "rgba32"
                app._on_btn_apply_surface(None)
                await pilot.pause()
                self.assertEqual(os.environ.get("SEAM_SURFACE_MODE"), "rgba32")
                surface_lines = [line for line in app.result_lines if "Holographic Surface" in line]
                self.assertTrue(surface_lines, "Expected Holographic Surface output")

                app.query_one("#cfg-key-openrouter").value = "test-openrouter-key"
                app._on_btn_use_openrouter(None)
                await pilot.pause()
                self.assertEqual(os.environ.get("OPENROUTER_API_KEY"), "test-openrouter-key")
                self.assertEqual(os.environ.get("SEAM_CHAT_BASE_URL"), "https://openrouter.ai/api/v1")
                self.assertEqual(app.chat_client.base_url, "https://openrouter.ai/api/v1")

        try:
            asyncio.run(_check())
        finally:
            if saved_surface_mode is None:
                os.environ.pop("SEAM_SURFACE_MODE", None)
            else:
                os.environ["SEAM_SURFACE_MODE"] = saved_surface_mode
            if saved_openrouter is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = saved_openrouter
            if saved_chat_key is None:
                os.environ.pop("SEAM_CHAT_API_KEY", None)
            else:
                os.environ["SEAM_CHAT_API_KEY"] = saved_chat_key
            if saved_chat_base is None:
                os.environ.pop("SEAM_CHAT_BASE_URL", None)
            else:
                os.environ["SEAM_CHAT_BASE_URL"] = saved_chat_base

    def test_textual_dashboard_settings_tab_scrolls(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        from textual.widgets import TabbedContent

        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app.query_one("#main-tabs", TabbedContent).active = "tab-settings"
                await pilot.pause()

                settings_scroll = app.query_one("#settings-scroll")
                self.assertGreater(settings_scroll.max_scroll_y, 0)
                settings_scroll.scroll_end(animate=False, force=True, immediate=True)
                await pilot.pause()
                self.assertEqual(settings_scroll.scroll_y, settings_scroll.max_scroll_y)

        asyncio.run(_check())

    def test_textual_dashboard_overview_shows_settings_health_and_pgvector_status(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")

        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                app._record_pgvector_status(
                    "pgvector status",
                    "NAME              STATUS\nseam-pgvector    running",
                    returncode=0,
                )
                await pilot.pause()

                overview = app.query_one("#overview-panel")
                joined = "\n".join(overview._panel_lines)
                self.assertIn("Live Health Bars", joined)
                self.assertIn("pgvector", joined)
                self.assertIn("[green]active[/]", joined)
                self.assertIn("Settings Paths", joined)
                self.assertIn("Settings Values", joined)
                self.assertIn("OpenRouter", joined)
                self.assertIn("Surface mode", joined)

        asyncio.run(_check())

    def test_textual_dashboard_overview_preserves_manual_scroll_on_refresh(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")

        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                overview = app.query_one("#overview-panel")
                self.assertGreater(overview.max_scroll_y, 0)
                overview.scroll_to(y=2, animate=False, force=True, immediate=True)
                await pilot.pause()
                before = overview.scroll_y
                app._refresh_overview()
                await pilot.pause()
                self.assertEqual(overview.scroll_y, before)

        asyncio.run(_check())

    def test_dashboard_shims_still_route_to_current_dashboard(self) -> None:
        pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
        launcher = Path("scripts/windows/launch_dashboard.ps1").read_text(encoding="utf-8")

        self.assertIn('seam-dash = "seam_runtime.dashboard:main"', pyproject)
        self.assertIn("python seam.py dashboard", launcher)
        self.assertIn("seam-dash.exe", launcher)
        self.assertIn("-m seam_runtime.dashboard", launcher)

    def test_textual_dashboard_command_palette_filters_prefix_menus(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app._update_command_palette("/retr")
                await pilot.pause()
                self.assertTrue(app._palette_matches)
                self.assertEqual(app._palette_matches[0].trigger, "/")
                self.assertEqual(app._palette_matches[0].command, "retrieve")

                app._update_command_palette("/")
                await pilot.pause()
                slash_commands = {item.command for item in app._palette_matches}
                self.assertIn("compile", slash_commands)
                self.assertIn("retrieve", slash_commands)
                self.assertIn("reload", slash_commands)
                self.assertIn("agent", slash_commands)
                self.assertIn("shell", slash_commands)
                self.assertIn("model", slash_commands)

                app._update_command_palette("!git")
                await pilot.pause()
                self.assertTrue(app._palette_matches)
                self.assertEqual(app._palette_matches[0].trigger, "!")
                self.assertIn("git", app._palette_matches[0].command)

                app._update_command_palette("?mod")
                await pilot.pause()
                self.assertTrue(app._palette_matches)
                self.assertEqual(app._palette_matches[0].trigger, "?")
                self.assertEqual(app._palette_matches[0].command, "model")

        asyncio.run(_check())

    def test_textual_dashboard_command_palette_accepts_selection(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                input_widget = app.query_one("#command-input")
                app._update_command_palette("/stats")
                await pilot.pause()
                app._accept_palette_selection(input_widget, submit=True)
                await pilot.pause()
                self.assertEqual(app.controller.result_title, "Stats")
                self.assertEqual(input_widget.value, "")

                app.process_command("/stats")
                await pilot.pause()
                self.assertEqual(app.controller.result_title, "Stats")

                app.process_command("/reload")
                await pilot.pause()
                self.assertEqual(app.controller.result_title, "Reload")

                app._update_command_palette("/compile")
                await pilot.pause()
                app._accept_palette_selection(input_widget, submit=True)
                await pilot.pause()
                self.assertEqual(input_widget.value, "/compile ")

        asyncio.run(_check())

    def test_textual_dashboard_reload_refreshes_panels_after_runtime_change(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                runtime.persist_ir(runtime.compile_nl("Reload refreshes dashboard metrics after external writes."))
                app.process_command("!reload")
                await pilot.pause()
                self.assertEqual(app.controller.result_title, "Reload")
                self.assertIn('"status": "reloaded"', "\n".join(app.result_lines))
                explorer = app.query_one("#explorer-tree")
                overview = app.query_one("#overview-panel")
                self.assertEqual(explorer.id, "explorer-tree")
                self.assertIn("Total", "\n".join(overview._panel_lines))
                reload_lines = [line for line in app.memory_lines if "Reload" in line]
                self.assertTrue(reload_lines, "Expected Reload command in memory output")

        asyncio.run(_check())

    def test_textual_dashboard_explorer_lists_namespaces(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(
            runtime.compile_nl(
                "Explorer namespace lazy loading should reveal persisted memory records.",
                ns="local.default",
                scope="thread",
            )
        )
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                explorer = app.query_one("#explorer-tree")
                namespace_labels = [str(child.label) for child in explorer.root.children]
                self.assertTrue(any("local.default" in label for label in namespace_labels),
                                "Expected local.default namespace among labels")
                ns_node = next(
                    child
                    for child in explorer.root.children
                    if (child.data or {}).get("ns") == "local.default"
                )
                scope_labels = [str(child.label) for child in ns_node.children]
                self.assertTrue(any("thread" in label for label in scope_labels),
                                "Expected 'thread' scope among labels")

        asyncio.run(_check())

    def test_textual_dashboard_routes_retrieval_output(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        seed = "We need a translator back into natural language for memory workflows."
        claim_id = _claim_ids(seed)[0]
        runtime = SeamRuntime(self.db_path)
        runtime.persist_ir(runtime.compile_nl(seed))
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("!retrieve translator natural language --budget 3")
                await pilot.pause()
                joined = "\n".join(app.retrieval_lines)
                self.assertIn("retrieve translator natural language", joined)
                self.assertIn(claim_id, joined)

        asyncio.run(_check())

    def test_textual_dashboard_chat_panel_sits_above_input(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                # In the IDE layout the right column (#right-col) holds chat
                # and result panels; it must sit above the docked command input.
                right_col = app.query_one("#right-col")
                command_input = app.query_one("#command-input")
                self.assertLess(right_col.region.y, command_input.region.y)

        asyncio.run(_check())

    def test_textual_dashboard_panels_autofollow_latest_output(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                for idx in range(320):
                    app._record_command("run", f"command-{idx}")
                await pilot.pause()
                panel = app.query_one("#command-history-panel")
                self.assertTrue(panel.can_focus)
                self.assertGreater(panel.max_scroll_y, 0)
                self.assertGreaterEqual(panel.scroll_y, panel.max_scroll_y - 1.0)

        asyncio.run(_check())

    def test_textual_dashboard_focused_panel_supports_keyboard_scrolling(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                for idx in range(500):
                    app._record_command("run", f"command-{idx}")
                # Switch to the Live tab where #command-history-panel lives
                from textual.widgets import TabbedContent
                app.query_one("#main-tabs", TabbedContent).active = "tab-live"
                await pilot.pause()
                panel = app.query_one("#command-history-panel")
                await pilot.click("#command-history-panel")
                await pilot.pause()
                self.assertIs(app.focused, panel)
                before = panel.scroll_y
                await pilot.press("pageup")
                await pilot.pause()
                after_pageup = panel.scroll_y
                await pilot.press("pagedown")
                await pilot.pause()
                after_pagedown = panel.scroll_y
                self.assertLess(after_pageup, before)
                self.assertGreater(after_pagedown, after_pageup)

        asyncio.run(_check())

    def test_textual_dashboard_focus_zoom_toggles_focused_panel(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                panel = app.query_one("#memory-panel")
                panel.focus()
                await pilot.pause()
                app.action_toggle_zoom()
                await pilot.pause()
                self.assertIn("zoomed", panel.classes)
                app.action_toggle_zoom()
                await pilot.pause()
                self.assertNotIn("zoomed", panel.classes)

        asyncio.run(_check())

    def test_textual_dashboard_routes_compile_output(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("!compile We need durable memory for AI systems")
                await pilot.pause()
                joined = "\n".join(app.memory_lines)
                self.assertIn("Compile", joined)
                self.assertIn("\"persist\"", joined)

        asyncio.run(_check())

    def test_textual_dashboard_hybrid_mode_routes_bare_commands(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("help")
                await pilot.pause()
                self.assertEqual(app.controller.result_title, "Dashboard Help")

        asyncio.run(_check())

    def test_textual_dashboard_tab_switch_updates_side_panel_mode(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        from textual.widgets import TabbedContent
        runtime = SeamRuntime(self.db_path)
        source_path = Path(f"lossless_textual_{uuid4().hex}.txt")
        source_path.write_text(("SEAM preserves exact context while compressing token usage. " * 10).strip(), encoding="utf-8")
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                # Switching to benchmark via the tab command should activate that tab
                app.process_command("!tab benchmark")
                await pilot.pause()
                tabs = app.query_one("#main-tabs", TabbedContent)
                self.assertEqual(tabs.active, "tab-benchmarks")

                # Running a benchmark populates benchmark_lines and switches the tab
                app.process_command(f"!benchmark {source_path} --min-savings 0.75")
                await pilot.pause()
                benchmark_lines = [line for line in app.benchmark_lines if "Benchmark" in line]
                self.assertTrue(benchmark_lines, "Expected Benchmark output")

                # Switching back to runtime shows overview tab
                app.process_command("!tab runtime")
                await pilot.pause()
                self.assertNotEqual(tabs.active, "tab-benchmarks")

        try:
            asyncio.run(_check())
        finally:
            if source_path.exists():
                source_path.unlink()

    def test_textual_dashboard_shortcuts_switch_modes(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("?shell")
                await pilot.pause()
                self.assertEqual(app.input_mode, "shell")
                app.process_command("?seam")
                await pilot.pause()
                self.assertEqual(app.input_mode, "seam")
                app.process_command("?agent")
                await pilot.pause()
                self.assertEqual(app.input_mode, "agent")
                app.process_command("?hybrid")
                await pilot.pause()
                self.assertEqual(app.input_mode, "hybrid")

        asyncio.run(_check())

    def test_textual_dashboard_shortcuts_switch_chat_model(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("?model gpt-4.1-mini")
                await pilot.pause()
                self.assertEqual(app.chat_client.model, "gpt-4.1-mini")
                self.assertIn("Switched chat model to gpt-4.1-mini", "\n".join(app.result_lines))

        asyncio.run(_check())

    def test_dashboard_default_chat_models_include_openrouter_agent_models(self) -> None:
        expected = {
            "openrouter/pareto-code",
            "qwen/qwen3-coder",
            "qwen/qwen3-coder-next",
            "qwen/qwen3-coder-plus",
            "deepseek/deepseek-v4-pro",
            "deepseek/deepseek-v4-flash",
            "xiaomi/mimo-v2.5-pro",
            "xiaomi/mimo-v2.5",
            "moonshotai/kimi-k2.6",
            "z-ai/glm-5.1",
            "x-ai/grok-4.20",
            "x-ai/grok-4.20-multi-agent",
            "x-ai/grok-4.1-fast",
            "x-ai/grok-code-fast-1",
            "google/gemma-4-31b-it",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it",
            "google/gemma-4-26b-a4b-it:free",
        }
        self.assertTrue(expected.issubset(set(DEFAULT_CHAT_MODELS)))
        with patch.dict(os.environ, {"SEAM_CHAT_MODEL": "gpt-4o-mini"}, clear=True):
            self.assertTrue(expected.issubset(set(SeamChatClient().available_models)))

    def test_textual_dashboard_bang_runs_shell_commands(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("!pwd")
                await pilot.pause()
                self.assertIn("Shell", "\n".join(app.result_lines))
                self.assertIn(str(app.shell_cwd), "\n".join(app.result_lines))
                history = "\n".join(app.command_history_lines)
                self.assertIn("[SHELL] pwd", history)

        asyncio.run(_check())

    def test_textual_dashboard_blocks_shell_subprocess_by_default(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("!python -c \"print('unsafe-shell-ran')\"")
                await pilot.pause()
                result_text = "\n".join(app.result_lines)
                self.assertIn("Shell execution is disabled", result_text)
                self.assertNotIn("unsafe-shell-ran", result_text)

        asyncio.run(_check())

    def test_textual_dashboard_double_question_forces_chat_outside_agent_mode(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("?shell")
                await pilot.pause()
                app.process_command("??What mode am I in?")
                await pilot.pause()
                self.assertGreaterEqual(len(app.chat_history), 2)
                self.assertEqual(app.chat_history[0]["role"], "user")
                self.assertEqual(app.chat_history[0]["content"], "What mode am I in?")

        asyncio.run(_check())

    def test_textual_dashboard_shortcuts_export_chat_transcript(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)
        export_path = Path(f"chat_export_{uuid4().hex}.jsonl")

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("What is the active mode?")
                await pilot.pause()
                app.process_command(f"?savechat {export_path}")
                await pilot.pause()
                self.assertTrue(export_path.exists())
                rows = [line.strip() for line in export_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertGreaterEqual(len(rows), 2)
                self.assertTrue(any('"role": "user"' in line for line in rows))
                self.assertTrue(any('"role": "assistant"' in line for line in rows))

        try:
            asyncio.run(_check())
        finally:
            if export_path.exists():
                export_path.unlink()

    def test_textual_dashboard_command_history_includes_status_badges_and_timing(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        runtime = SeamRuntime(self.db_path)
        app = TextualDashboardApp(runtime)

        async def _check() -> None:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.process_command("!help")
                await pilot.pause()
                app.process_command("!trace missing:id")
                await pilot.pause()
                history = "\n".join(app.command_history_lines)
                self.assertIn("[RUN] help", history)
                self.assertIn("[OK] help -> Dashboard Help", history)
                self.assertIn("[ERR] trace missing:id -> KeyError", history)
                self.assertRegex(history, r"\(\d+ms\)|\(\d+\.\d+s\)")

        asyncio.run(_check())

    def test_textual_dashboard_routes_readable_rc1_commands(self) -> None:
        if find_spec("textual") is None:
            self.skipTest("textual is not installed")
        source_path = Path(f"dashboard_readable_{uuid4().hex}.txt")
        rc_path = Path(f"dashboard_readable_{uuid4().hex}.seamrc")
        try:
            source_path.write_text(
                'Recipe: Lemon Rice\nYield: 2 bowls\nNote: "Toast the rice before adding broth."\n',
                encoding="utf-8",
            )
            runtime = SeamRuntime(self.db_path)
            app = TextualDashboardApp(runtime)

            async def _check() -> None:
                async with app.run_test() as pilot:
                    await pilot.pause()
                    app.process_command(f"!readable-compress {source_path.resolve()} --granularity line")
                    await pilot.pause()
                    self.assertEqual(app.controller.result_title, "Readable Compress")
                    rc_path.write_text(str(app.controller.last_machine_text), encoding="utf-8")

                    app.process_command(f"!readable-query {rc_path.resolve()} Toast rice --limit 3")
                    await pilot.pause()
                    self.assertEqual(app.controller.result_title, "Readable Query")
                    self.assertIn("Toast the rice", "\n".join(app.benchmark_lines))

                    app.process_command(f"!readable-rebuild {rc_path.resolve()}")
                    await pilot.pause()
                    self.assertEqual(app.controller.result_title, "Readable Rebuild")
                    self.assertIn("Recipe: Lemon Rice", "\n".join(app.benchmark_lines))

            asyncio.run(_check())
        finally:
            if source_path.exists():
                source_path.unlink()
            if rc_path.exists():
                rc_path.unlink()

class InstallerLinuxTests(unittest.TestCase):
    def test_powershell_single_quote_escaping_doubles_embedded_quotes(self) -> None:
        quoted = _powershell_single_quoted(r"C:\Users\O'Brien\SEAM")
        self.assertEqual(quoted, r"'C:\Users\O''Brien\SEAM'")
        self.assertNotIn("O'Brien", quoted[1:-1])

    def test_posix_shim_has_valid_sh_structure(self) -> None:
        shim = render_posix_shim(
            Path("/home/user/.local/share/seam/runtime/bin/seam"),
            Path("/home/user/seam"),
            '"/home/user/seam/installers/install_seam_linux.sh"',
            Path("/home/user/.local/share/seam/state/seam.db"),
        )
        self.assertTrue(shim.startswith("#!/usr/bin/env sh\n"))
        self.assertIn('SEAM_EXE="/home/user/.local/share/seam/runtime/bin/seam"', shim)
        self.assertIn('export SEAM_DB_PATH="/home/user/.local/share/seam/state/seam.db"', shim)
        self.assertIn('if [ ! -x "$SEAM_EXE" ]', shim)
        self.assertIn('exec "$SEAM_EXE" "$@"', shim)

    def test_path_in_environment_finds_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bin"
            target.mkdir()
            path_string = os.pathsep.join(["/usr/bin", str(target), "/usr/local/bin"])
            self.assertTrue(path_in_environment(target, path_string))

    def test_path_in_environment_returns_false_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bin"
            path_string = os.pathsep.join(["/usr/bin", "/usr/local/bin"])
            self.assertFalse(path_in_environment(target, path_string))

    def test_posix_profile_injection_adds_path_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / "bin"
            original_path = os.environ.get("PATH", "")
            try:
                with patch("pathlib.Path.home", return_value=home):
                    updated = _ensure_posix_shell_profiles(target)
                bashrc = home / ".bashrc"
                self.assertTrue(bashrc.exists())
                content = bashrc.read_text()
                self.assertIn(PATH_MARKER_BEGIN, content)
                self.assertIn(str(target), content)
                self.assertGreater(len(updated), 0)
            finally:
                os.environ["PATH"] = original_path

    def test_posix_profile_skips_injection_if_marker_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / "bin"
            marker_block = f"{PATH_MARKER_BEGIN}\nexport PATH=\"{target}:$PATH\"\n# <<< SEAM installer <<<\n"
            for name in (".profile", ".bashrc", ".zprofile"):
                (home / name).write_text(marker_block, encoding="utf-8")
            original_path = os.environ.get("PATH", "")
            try:
                with patch("pathlib.Path.home", return_value=home):
                    updated = _ensure_posix_shell_profiles(target)
                self.assertEqual(updated, [])
            finally:
                os.environ["PATH"] = original_path

    @unittest.skipIf(os.name == "nt", "POSIX permissions check")
    def test_dashboard_private_text_file_uses_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "local" / ".env"
            _write_private_text_file(env_path, "SEAM_API_TOKEN=test\n")
            self.assertEqual(env_path.read_text(encoding="utf-8"), "SEAM_API_TOKEN=test\n")
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_linux_installer_sh_delegates_to_python(self) -> None:
        sh_path = Path(__file__).resolve().parents[1] / "installers" / "install_seam_linux.sh"
        content = sh_path.read_text()
        self.assertTrue(content.startswith("#!/usr/bin/env sh"))
        self.assertIn("python3", content)
        self.assertIn("install_seam.py", content)
        self.assertIn("set -eu", content)

    def test_macos_installer_sh_delegates_to_python(self) -> None:
        sh_path = Path(__file__).resolve().parents[1] / "installers" / "install_seam_macos.sh"
        content = sh_path.read_text()
        self.assertTrue(content.startswith("#!/usr/bin/env sh"))
        self.assertIn("python3", content)
        self.assertIn("install_seam.py", content)
        self.assertIn("set -eu", content)

    def test_detect_layout_uses_macos_application_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo_root = Path(tmp) / "repo"
            with (
                patch("pathlib.Path.home", return_value=home),
                patch("seam_runtime.installer.platform.system", return_value="Darwin"),
            ):
                layout = detect_layout(repo_root)
            expected_root = home / "Library" / "Application Support" / "SEAM"
            self.assertFalse(layout.is_windows)
            self.assertEqual(layout.install_root, expected_root)
            self.assertEqual(layout.venv_dir, expected_root / "runtime")
            self.assertEqual(layout.persistent_db_path, expected_root / "state" / "seam.db")
            self.assertEqual(layout.bin_dir, home / ".local" / "bin")

    def test_current_platform_label_reports_macos_for_darwin(self) -> None:
        with patch("seam_runtime.installer.platform.system", return_value="Darwin"):
            self.assertEqual(installer_module.current_platform_label(), "macos")

    def test_detect_layout_includes_dashboard_entry(self) -> None:
        layout = detect_layout()
        self.assertIn("seam-dash", layout.dashboard_entry.name)
        if layout.is_windows:
            self.assertEqual(layout.dashboard_entry.name, "seam-dash.exe")
            self.assertEqual(layout.dashboard_entry.parent, layout.venv_dir / "Scripts")
        else:
            self.assertEqual(layout.dashboard_entry.name, "seam-dash")
            self.assertEqual(layout.dashboard_entry.parent, layout.venv_dir / "bin")

    def test_write_shims_returns_three_paths_posix_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            install_root = root / "install"
            venv_dir = install_root / "runtime"
            bin_dir = install_root / "bin"
            layout = InstallLayout(
                repo_root=repo_root,
                install_root=install_root,
                venv_dir=venv_dir,
                bin_dir=bin_dir,
                seam_entry=venv_dir / "bin" / "seam",
                benchmark_entry=venv_dir / "bin" / "seam-benchmark",
                dashboard_entry=venv_dir / "bin" / "seam-dash",
                persistent_db_path=install_root / "state" / "seam.db",
                is_windows=False,
            )
            seam_shim, benchmark_shim, dashboard_shim = write_shims(layout)
            self.assertEqual(seam_shim, bin_dir / "seam")
            self.assertEqual(benchmark_shim, bin_dir / "seam-benchmark")
            self.assertEqual(dashboard_shim, bin_dir / "seam-dash")
            self.assertTrue(dashboard_shim.exists())
            content = dashboard_shim.read_text(encoding="utf-8")
            self.assertIn("seam-dash", content)
            self.assertIn('export SEAM_DB_PATH=', content)

    def test_write_shims_uses_macos_bootstrap_hint_on_macos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            install_root = root / "install"
            venv_dir = install_root / "runtime"
            bin_dir = install_root / "bin"
            layout = InstallLayout(
                repo_root=repo_root,
                install_root=install_root,
                venv_dir=venv_dir,
                bin_dir=bin_dir,
                seam_entry=venv_dir / "bin" / "seam",
                benchmark_entry=venv_dir / "bin" / "seam-benchmark",
                dashboard_entry=venv_dir / "bin" / "seam-dash",
                persistent_db_path=install_root / "state" / "seam.db",
                is_windows=False,
            )
            with patch("seam_runtime.installer.platform.system", return_value="Darwin"):
                seam_shim, _, _ = write_shims(layout)
            content = seam_shim.read_text(encoding="utf-8")
            self.assertIn("install_seam_macos.sh", content)
            self.assertNotIn("install_seam_linux.sh", content)

    def test_write_shims_returns_three_paths_windows_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            install_root = root / "install"
            venv_dir = install_root / "runtime"
            bin_dir = install_root / "bin"
            layout = InstallLayout(
                repo_root=repo_root,
                install_root=install_root,
                venv_dir=venv_dir,
                bin_dir=bin_dir,
                seam_entry=venv_dir / "Scripts" / "seam.exe",
                benchmark_entry=venv_dir / "Scripts" / "seam-benchmark.exe",
                dashboard_entry=venv_dir / "Scripts" / "seam-dash.exe",
                persistent_db_path=install_root / "state" / "seam.db",
                is_windows=True,
            )
            seam_shim, benchmark_shim, dashboard_shim = write_shims(layout)
            self.assertEqual(seam_shim, bin_dir / "seam.cmd")
            self.assertEqual(benchmark_shim, bin_dir / "seam-benchmark.cmd")
            self.assertEqual(dashboard_shim, bin_dir / "seam-dash.cmd")
            self.assertTrue(dashboard_shim.exists())
            content = dashboard_shim.read_text(encoding="ascii")
            self.assertIn("seam-dash.exe", content)
            self.assertIn("SEAM_DB_PATH", content)

    def test_install_repo_includes_dashboard_extra_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            install_root = root / "install"
            venv_dir = install_root / "runtime"
            bin_dir = install_root / "bin"
            (repo_root).mkdir(parents=True, exist_ok=True)
            layout = InstallLayout(
                repo_root=repo_root,
                install_root=install_root,
                venv_dir=venv_dir,
                bin_dir=bin_dir,
                seam_entry=venv_dir / "bin" / "seam",
                benchmark_entry=venv_dir / "bin" / "seam-benchmark",
                dashboard_entry=venv_dir / "bin" / "seam-dash",
                persistent_db_path=install_root / "state" / "seam.db",
                is_windows=False,
            )
            calls: list[list[str]] = []
            def _fake_run(cmd, check=True, **kwargs):  # pragma: no cover - test shim
                calls.append(list(cmd))
                class _Result:
                    returncode = 0
                return _Result()
            with patch("seam_runtime.installer.subprocess.run", side_effect=_fake_run):
                install_repo(layout, upgrade_pip=False)
            install_cmds = [call for call in calls if "install" in call]
            self.assertTrue(install_cmds)
            package_specs = [arg for call in install_cmds for arg in call if arg.endswith("[dash]")]
            self.assertTrue(package_specs, f"Expected a [dash] extra install in {install_cmds}")
            self.assertEqual(package_specs[0], f"{repo_root}[dash]")

    def test_install_repo_respects_include_dashboard_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            install_root = root / "install"
            venv_dir = install_root / "runtime"
            bin_dir = install_root / "bin"
            repo_root.mkdir(parents=True, exist_ok=True)
            layout = InstallLayout(
                repo_root=repo_root,
                install_root=install_root,
                venv_dir=venv_dir,
                bin_dir=bin_dir,
                seam_entry=venv_dir / "bin" / "seam",
                benchmark_entry=venv_dir / "bin" / "seam-benchmark",
                dashboard_entry=venv_dir / "bin" / "seam-dash",
                persistent_db_path=install_root / "state" / "seam.db",
                is_windows=False,
            )
            calls: list[list[str]] = []
            def _fake_run(cmd, check=True, **kwargs):  # pragma: no cover - test shim
                calls.append(list(cmd))
                class _Result:
                    returncode = 0
                return _Result()
            with patch("seam_runtime.installer.subprocess.run", side_effect=_fake_run):
                install_repo(layout, upgrade_pip=False, include_dashboard=False)
            for call in calls:
                for arg in call:
                    self.assertFalse(arg.endswith("[dash]"), f"Unexpected [dash] arg in {call}")

    @unittest.skipUnless(os.name == "posix", "POSIX-only venv layout and lib64 fallback")
    def test_dev_virtualenv_precreates_lib64_for_posix_filesystems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls: list[list[str]] = []

            def _fake_run(cmd, check=True, **kwargs):  # pragma: no cover - test shim
                calls.append(list(cmd))
                (root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
                (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

                class _Result:
                    returncode = 0

                return _Result()

            with patch("seam_runtime.installer.subprocess.run", side_effect=_fake_run):
                self.assertTrue(hasattr(installer_module, "ensure_repo_virtualenv"))
                python_bin = installer_module.ensure_repo_virtualenv(root, python_executable="/usr/bin/python3")

            self.assertEqual(python_bin, root / ".venv" / "bin" / "python")
            self.assertTrue((root / ".venv" / "lib64").is_dir())
            self.assertEqual(calls[0], ["/usr/bin/python3", "-m", "venv", str(root / ".venv")])

    @unittest.skipUnless(os.name == "posix", "POSIX-only venv layout")
    def test_dev_install_installs_python_deps_and_ignores_existing_webui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("rich>=14.2\n", encoding="utf-8")
            webui = root / "experimental" / "webui"
            webui.mkdir(parents=True)
            (webui / "package.json").write_text('{"scripts":{}}\n', encoding="utf-8")
            (root / ".venv" / "bin").mkdir(parents=True)
            (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            calls: list[tuple[list[str], Path | None]] = []

            def _fake_run(cmd, check=True, cwd=None, **kwargs):  # pragma: no cover - test shim
                calls.append((list(cmd), Path(cwd) if cwd else None))

                class _Result:
                    returncode = 0
                    stdout = "PASS"

                return _Result()

            with patch("seam_runtime.installer.subprocess.run", side_effect=_fake_run):
                self.assertTrue(hasattr(installer_module, "install_repo_dev_environment"))
                result = installer_module.install_repo_dev_environment(root, upgrade_pip=False)

            self.assertTrue(hasattr(installer_module, "DevInstallResult"))
            self.assertIsInstance(result, installer_module.DevInstallResult)
            commands = [cmd for cmd, _cwd in calls]
            self.assertIn([str(root / ".venv" / "bin" / "python"), "-m", "pip", "install", "-r", str(root / "requirements.txt")], commands)
            self.assertIn([str(root / ".venv" / "bin" / "python"), "-m", "pip", "install", "-e", f"{root}[all-extras]", "pytest"], commands)
            self.assertNotIn((["npm", "install", "--no-bin-links"], webui), calls)

    def test_run_repo_dev_checks_writes_snapshot_and_runs_protocol_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_bin = root / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True)
            python_bin.write_text("", encoding="utf-8")
            (root / "HISTORY_INDEX.md").write_text(
                "| id | date | status | hash | topics | supersedes |\n"
                "|---|---|---|---|---|---|\n"
                "| 176 | 2026-05-16 | done | abc | installer,linux | 175 |\n"
                "| 175 | 2026-05-16 | done | def | verify | 174 |\n"
                "| 174 | 2026-05-16 | done | ghi | verify | 173 |\n",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def _fake_run(cmd, check=True, cwd=None, **kwargs):  # pragma: no cover - test shim
                calls.append(list(cmd))

                class _Result:
                    returncode = 0
                    stdout = "OK"

                return _Result()

            with patch("seam_runtime.installer.subprocess.run", side_effect=_fake_run):
                self.assertTrue(hasattr(installer_module, "run_repo_dev_checks"))
                installer_module.run_repo_dev_checks(root, python_bin)

            self.assertIn([str(python_bin), "seam.py", "doctor"], calls)
            self.assertIn([str(python_bin), "-m", "tools.history.verify_integrity"], calls)
            self.assertIn([str(python_bin), "-m", "tools.history.verify_routing"], calls)
            self.assertIn(
                [
                    str(python_bin),
                    "-m",
                    "tools.history.write_snapshot",
                    "--agent",
                    "codex",
                    "--entries",
                    "176,175,174",
                    "--token-budget",
                    "1800",
                ],
                calls,
            )
            self.assertIn([str(python_bin), "-m", "tools.history.verify_continuity"], calls)
            self.assertIn([str(python_bin), "-m", "tools.streams.verify_streams"], calls)


class PgVectorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(f"test_pgvector_{uuid4().hex}.db")
        self.model = HashEmbeddingModel()
        self.adapter = FakePgVectorAdapter(self.model)

    def tearDown(self) -> None:
        try:
            if self.db_path.exists():
                self.db_path.unlink()
        except PermissionError:
            pass

    def _make_batch(self):
        return compile_dsl(
            """
entity project "SEAM" as proj
claim c1:
  subject proj
  predicate supports
  object "databases"
claim c2:
  subject proj
  predicate supports
  object "context windows"
""",
            scope="project",
        )

    def test_pgvector_adapter_indexes_records(self) -> None:
        batch = self._make_batch()
        self.adapter.index_records(batch.records)
        indexable_count = sum(1 for r in batch.records if r.kind in INDEXABLE_KINDS)
        self.assertEqual(len(self.adapter._store), indexable_count)

    def test_pgvector_adapter_search_returns_scored_results(self) -> None:
        batch = self._make_batch()
        self.adapter.index_records(batch.records)
        scores = self.adapter.search("databases context windows", limit=5)
        self.assertGreater(len(scores), 0)
        for score in scores.values():
            self.assertIsInstance(score, float)
            self.assertGreater(score, 0.0)

    def test_pgvector_adapter_upsert_does_not_duplicate(self) -> None:
        batch = self._make_batch()
        self.adapter.index_records(batch.records)
        count_first = len(self.adapter._store)
        self.adapter.index_records(batch.records)
        self.assertEqual(len(self.adapter._store), count_first)

    def test_pgvector_adapter_schema_ddl_is_executed(self) -> None:
        batch = self._make_batch()
        self.adapter.index_records(batch.records)
        sql_lower = [s.lower() for s in self.adapter.sql_log]
        self.assertTrue(any("create extension" in s and "vector" in s for s in sql_lower))
        self.assertTrue(any("create table" in s and "seam_vector_index" in s for s in sql_lower))
        self.assertTrue(any("create index" in s and "seam_vector_index" in s for s in sql_lower))

    def test_runtime_uses_pgvector_adapter_when_dsn_provided(self) -> None:
        runtime = SeamRuntime(self.db_path, pgvector_dsn="postgresql://fake/db")
        self.assertIsInstance(runtime.vector_adapter, PgVectorAdapter)

    def test_runtime_picks_up_pgvector_dsn_from_env(self) -> None:
        old = os.environ.pop("SEAM_PGVECTOR_DSN", None)
        try:
            os.environ["SEAM_PGVECTOR_DSN"] = "postgresql://fake/db"
            runtime = SeamRuntime(self.db_path)
            self.assertIsInstance(runtime.vector_adapter, PgVectorAdapter)
        finally:
            if old is None:
                os.environ.pop("SEAM_PGVECTOR_DSN", None)
            else:
                os.environ["SEAM_PGVECTOR_DSN"] = old

    def test_runtime_persist_search_roundtrip_with_pgvector(self) -> None:
        runtime = SeamRuntime(self.db_path, vector_adapter=self.adapter)
        batch = runtime.compile_dsl(
            """
entity project "SEAM" as proj
claim c1:
  subject proj
  predicate supports
  object "databases"
claim c2:
  subject proj
  predicate supports
  object "context windows"
"""
        )
        runtime.persist_ir(batch)
        result = runtime.search_ir("databases context windows", budget=5)
        self.assertTrue(result.candidates)


class _FakePgCursor:
    def __init__(self, store: dict, sql_log: list) -> None:
        self._store = store
        self._sql_log = sql_log
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql: str, params=None) -> None:
        self._sql_log.append(sql.strip())
        sql_lower = sql.strip().lower()
        if sql_lower.startswith("insert") and params:
            record_id, model_name, dimension, source_text, source_hash, namespace, vec_literal, updated_at = params
            vec = [float(x) for x in vec_literal.strip("[]").split(",")]
            self._store[record_id] = {"model": model_name, "dim": dimension, "vec": vec, "source_hash": source_hash, "namespace": namespace}
        elif sql_lower.startswith("select") and params:
            if "information_schema.columns" in sql_lower:
                self._rows = [("source_hash",)]
                return
            if "pg_get_constraintdef" in sql_lower or "pg_constraint" in sql_lower:
                # Migration check: report composite PK already present so
                # no ALTER TABLE runs against the fake store.
                self._rows = [("PRIMARY KEY (record_id, model_name)",)]
                return
            if "source_hash, dimension" in sql_lower:
                record_id, model_name = params
                entry = self._store.get(record_id)
                self._rows = [(entry["source_hash"], entry["dim"])] if entry and entry["model"] == model_name else []
                return
            vec_literal, model_name, dimension, _, limit = params
            query_vec = [float(x) for x in vec_literal.strip("[]").split(",")]
            scored = []
            for rid, entry in self._store.items():
                if entry["model"] != model_name or entry["dim"] != dimension:
                    continue
                score = cosine(query_vec, entry["vec"])
                if score > 0:
                    scored.append((rid, score))
            scored.sort(key=lambda item: -item[1])
            self._rows = scored[:limit]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakePgConnection:
    def __init__(self, store: dict, sql_log: list) -> None:
        self._store = store
        self._sql_log = sql_log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return _FakePgCursor(self._store, self._sql_log)

    def commit(self):
        pass


class FakePgVectorAdapter(PgVectorAdapter):
    def __init__(self, model: HashEmbeddingModel) -> None:
        super().__init__(dsn="fake://", model=model)
        self._store: dict = {}
        self.sql_log: list[str] = []

    def _connect(self):
        return _FakePgConnection(self._store, self.sql_log)


class FakeChromaCollection:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, object]] = {}

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        for record_id, embedding, document, metadata in zip(ids, embeddings, documents, metadatas, strict=False):
            self.entries[record_id] = {
                "embedding": embedding,
                "document": document,
                "metadata": metadata,
            }

    def query(self, query_embeddings, n_results, include):
        query_embedding = query_embeddings[0]
        scored = []
        for record_id, payload in self.entries.items():
            similarity = cosine(query_embedding, payload["embedding"])
            distance = max(0.0, 1.0 - similarity)
            scored.append((record_id, distance, payload))
        scored.sort(key=lambda item: item[1])
        top = scored[:n_results]
        return {
            "ids": [[item[0] for item in top]],
            "distances": [[item[1] for item in top]],
            "documents": [[item[2]["document"] for item in top]],
            "metadatas": [[item[2]["metadata"] for item in top]],
        }


class FakeChromaClient:
    def __init__(self) -> None:
        self.collection = FakeChromaCollection()

    def get_or_create_collection(self, name, metadata=None):
        return self.collection


class LX1NotationTests(unittest.TestCase):
    """LX/1 compact AI-readable notation — encode/decode and token savings."""

    def _make_ent(self) -> "MIRLRecord":
        from seam_runtime.mirl import MIRLRecord, RecordKind, Status
        return MIRLRecord(
            id="ent:user:local",
            kind=RecordKind.ENT,
            ns="local.default",
            scope="project",
            attrs={"entity_type": "user", "label": "local_user"},
        )

    def _make_clm(self) -> "MIRLRecord":
        from seam_runtime.mirl import MIRLRecord, RecordKind, Status
        return MIRLRecord(
            id="clm:1",
            kind=RecordKind.CLM,
            ns="local.default",
            scope="project",
            conf=0.92,
            status=Status.ASSERTED,
            prov=["prov:compile:1"],
            evidence=["span:1"],
            attrs={"subject": "ent:project:seam", "predicate": "goal", "object": "build_memory_runtime"},
        )

    def _make_sta(self) -> "MIRLRecord":
        from seam_runtime.mirl import MIRLRecord, RecordKind
        return MIRLRecord(
            id="sta:ent:project:seam",
            kind=RecordKind.STA,
            ns="local.default",
            scope="project",
            conf=0.9,
            prov=["prov:compile:1"],
            evidence=["span:1"],
            attrs={"target": "ent:project:seam", "fields": {"goal": "build_memory_runtime", "scope": ["db", "rag"]}},
        )

    def _make_raw(self) -> "MIRLRecord":
        from seam_runtime.mirl import MIRLRecord, RecordKind, Status
        return MIRLRecord(
            id="raw:1",
            kind=RecordKind.RAW,
            ns="local.default",
            scope="project",
            status=Status.OBSERVED,
            attrs={"source_ref": "local://input", "content": "I want to build a memory runtime", "media_type": "text/plain"},
        )

    def test_encode_ent_omits_defaults(self) -> None:
        from seam_runtime.lx1 import encode_record
        line = encode_record(self._make_ent())
        self.assertTrue(line.startswith("E ent:user:local "))
        self.assertNotIn("local.default", line)
        self.assertNotIn("project", line)
        self.assertNotIn("asserted", line)
        self.assertIn("entity_type=user", line)
        self.assertIn("label=local_user", line)

    def test_roundtrip_ent(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        original = self._make_ent()
        line = encode_record(original)
        restored = decode_record(line)
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.kind, original.kind)
        self.assertEqual(restored.attrs, original.attrs)
        self.assertAlmostEqual(restored.conf, original.conf)
        self.assertEqual(restored.status, original.status)

    def test_roundtrip_clm_with_meta(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        original = self._make_clm()
        line = encode_record(original)
        self.assertIn("~c=0.92", line)
        self.assertIn("~@prov:compile:1", line)
        self.assertIn("~^span:1", line)
        restored = decode_record(line)
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.prov, original.prov)
        self.assertEqual(restored.evidence, original.evidence)
        self.assertAlmostEqual(restored.conf, 0.92)
        self.assertEqual(restored.attrs, original.attrs)

    def test_roundtrip_sta_with_nested_dict(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        original = self._make_sta()
        line = encode_record(original)
        restored = decode_record(line)
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.attrs["target"], "ent:project:seam")
        fields = restored.attrs["fields"]
        self.assertEqual(fields["goal"], "build_memory_runtime")
        self.assertEqual(fields["scope"], ["db", "rag"])

    def test_roundtrip_raw_with_quoted_content(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        original = self._make_raw()
        line = encode_record(original)
        self.assertIn('content="I want to build a memory runtime"', line)
        restored = decode_record(line)
        self.assertEqual(restored.attrs["content"], "I want to build a memory runtime")
        self.assertEqual(restored.attrs["source_ref"], "local://input")
        self.assertEqual(restored.attrs["media_type"], "text/plain")

    def test_roundtrip_observed_status(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        from seam_runtime.mirl import Status
        original = self._make_raw()
        line = encode_record(original)
        self.assertIn("~s=o", line)
        restored = decode_record(line)
        self.assertEqual(restored.status, Status.OBSERVED)

    def test_decode_rejects_unknown_status_code(self) -> None:
        from seam_runtime.lx1 import decode_record

        with self.assertRaisesRegex(ValueError, "unknown LX1 status code"):
            decode_record("R raw:1 ~s=unknown content=hello")

    def test_batch_roundtrip(self) -> None:
        from seam_runtime.lx1 import decode, encode
        from seam_runtime.mirl import IRBatch
        batch = IRBatch([self._make_ent(), self._make_clm(), self._make_sta()])
        compact = encode(batch)
        self.assertTrue(compact.startswith("!LX1 "))
        restored = decode(compact)
        self.assertEqual(len(restored.records), 3)
        ids = {r.id for r in restored.records}
        self.assertIn("ent:user:local", ids)
        self.assertIn("clm:1", ids)
        self.assertIn("sta:ent:project:seam", ids)

    def test_token_savings_vs_verbose_mirl(self) -> None:
        from seam_runtime.lx1 import encode, token_savings_report
        from seam_runtime.mirl import IRBatch
        batch = IRBatch([self._make_ent(), self._make_clm(), self._make_sta(), self._make_raw()])
        verbose = batch.to_text()
        compact = encode(batch)
        report = token_savings_report(verbose, compact)
        self.assertGreater(report["token_savings_ratio"], 0.50,
                           "LX/1 should save >50% of tokens vs verbose MIRL JSON")
        self.assertGreater(report["intelligence_per_token_gain"], 2.0,
                           "LX/1 should deliver >2x intelligence per token vs verbose MIRL")

    def test_compile_nl_lx1_roundtrip(self) -> None:
        from seam_runtime.lx1 import decode, encode, token_savings_report
        runtime = SeamRuntime(":memory:")
        batch = runtime.compile_nl(
            "I want to build a durable memory runtime for AI that works without losing information."
        )
        verbose = batch.to_text()
        compact = encode(batch)
        report = token_savings_report(verbose, compact)
        self.assertGreater(report["token_savings_ratio"], 0.50)
        restored = decode(compact)
        original_ids = {r.id for r in batch.records}
        restored_ids = {r.id for r in restored.records}
        self.assertEqual(original_ids, restored_ids)

    def test_lx1_encode_cli_command(self) -> None:
        import tempfile
        runtime = SeamRuntime(":memory:")
        batch = runtime.compile_nl("SEAM stores knowledge efficiently.")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mirl", delete=False) as f:
            f.write(batch.to_text())
            mirl_path = f.name
        try:
            buf = StringIO()
            with redirect_stdout(buf):
                run_cli(["lx1-encode", mirl_path])
            output = buf.getvalue()
            self.assertIn("!LX1", output)
            self.assertIn("ns=local.default", output)
        finally:
            Path(mirl_path).unlink(missing_ok=True)

    def test_lx1_benchmark_cli_command(self) -> None:
        import tempfile
        runtime = SeamRuntime(":memory:")
        batch = runtime.compile_nl("SEAM stores knowledge efficiently.")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mirl", delete=False) as f:
            f.write(batch.to_text())
            mirl_path = f.name
        try:
            buf = StringIO()
            with redirect_stdout(buf):
                run_cli(["lx1-benchmark", mirl_path])
            output = buf.getvalue()
            self.assertIn("Token savings", output)
            self.assertIn("Intelligence/token", output)
        finally:
            Path(mirl_path).unlink(missing_ok=True)

    def test_reserved_token_strings_roundtrip(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        from seam_runtime.mirl import MIRLRecord, RecordKind
        record = MIRLRecord(
            id="ent:test",
            kind=RecordKind.ENT,
            attrs={"status_label": "true", "flag": "null", "active": "false"},
        )
        line = encode_record(record)
        restored = decode_record(line)
        self.assertEqual(restored.attrs["status_label"], "true")
        self.assertEqual(restored.attrs["flag"], "null")
        self.assertEqual(restored.attrs["active"], "false")

    def test_numeric_attr_types_roundtrip(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        from seam_runtime.mirl import MIRLRecord, RecordKind
        record = MIRLRecord(
            id="span:1",
            kind=RecordKind.SPAN,
            attrs={"start": 0, "end": 42, "score": 0.95},
        )
        line = encode_record(record)
        restored = decode_record(line)
        self.assertEqual(restored.attrs["start"], 0)
        self.assertEqual(restored.attrs["end"], 42)
        self.assertAlmostEqual(restored.attrs["score"], 0.95)

    def test_lx1_int_float_type_preservation(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        from seam_runtime.mirl import MIRLRecord, RecordKind
        record = MIRLRecord(
            id="span:type-test",
            kind=RecordKind.SPAN,
            attrs={
                "int_zero": 0,
                "float_zero": 0.0,
                "int_one": 1,
                "float_one": 1.0,
                "int_large": 9223372036854775807,
                "float_small": 0.0001,
                "int_negative": -42,
                "float_negative": -3.14,
                "float_large": 1.7976931348623157e308,
            },
        )
        line = encode_record(record)
        restored = decode_record(line)
        self.assertIsInstance(restored.attrs["int_zero"], int)
        self.assertIsInstance(restored.attrs["float_zero"], float)
        self.assertEqual(restored.attrs["int_zero"], 0)
        self.assertEqual(restored.attrs["float_zero"], 0.0)
        self.assertIsInstance(restored.attrs["int_one"], int)
        self.assertIsInstance(restored.attrs["float_one"], float)
        self.assertEqual(restored.attrs["int_one"], 1)
        self.assertEqual(restored.attrs["float_one"], 1.0)
        self.assertIsInstance(restored.attrs["int_large"], int)
        self.assertEqual(restored.attrs["int_large"], 9223372036854775807)
        self.assertIsInstance(restored.attrs["float_small"], float)
        self.assertAlmostEqual(restored.attrs["float_small"], 0.0001)
        self.assertIsInstance(restored.attrs["int_negative"], int)
        self.assertEqual(restored.attrs["int_negative"], -42)
        self.assertIsInstance(restored.attrs["float_negative"], float)
        self.assertAlmostEqual(restored.attrs["float_negative"], -3.14)
        self.assertIsInstance(restored.attrs["float_large"], float)
        self.assertAlmostEqual(restored.attrs["float_large"], 1.7976931348623157e308)

    def test_lx1_mirl_conf_type_preservation(self) -> None:
        from seam_runtime.lx1 import decode_record, encode_record
        from seam_runtime.mirl import MIRLRecord, RecordKind, Status
        record = MIRLRecord(
            id="clm:conf-test",
            kind=RecordKind.CLM,
            ns="local.default",
            scope="project",
            conf=0.92,
            status=Status.ASSERTED,
            prov=["prov:compile:1"],
            evidence=["span:1"],
            attrs={"subject": "ent:x", "predicate": "test", "object": "y"},
        )
        line = encode_record(record)
        restored = decode_record(line)
        self.assertIsInstance(restored.conf, float)
        self.assertAlmostEqual(restored.conf, 0.92)


if __name__ == "__main__":
    unittest.main()
