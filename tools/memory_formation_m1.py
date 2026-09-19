"""Reproduce M1 formation observations using synthetic inputs and local models.

This is an observation probe, not a quality benchmark or a candidate compiler.
It exercises the real LoCoMo adapter with its pinned, cached embedding model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.mirl import RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.nl import compile_nl
from seam_runtime.runtime import SeamRuntime

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    "bracket_alice": "[Alice 2026-09-01] I moved to Oslo. I enjoy painting.",
    "bracket_bob": "[Bob 2026-09-02] I moved to Rome. I enjoy hiking.",
    "colon_control": "Alice: I moved to Oslo. I enjoy painting.",
    "unicode": "東京が好きです。大阪に住んでいます。",
    "abbreviation": "Dr. Chen moved to Oslo. She works there.",
    "newline_speakers": "Alice: I like tea\nBob: I like coffee",
    "state_changes": "Alice: I lived in Oslo. I now live in Rome.",
}


def describe(batch) -> dict:
    by_id = batch.by_id()
    raws = batch.kind(RecordKind.RAW)
    claims = batch.kind(RecordKind.CLM)
    spans = batch.kind(RecordKind.SPAN)
    return {
        "kinds": dict(sorted(Counter(r.kind.value for r in batch.records).items())),
        "raw": [{"id": r.id, "content": r.attrs["content"],
                 "source_metadata": r.ext.get("source_metadata")} for r in raws],
        "claims": [{"id": r.id, "text": r.attrs["object"],
                    "predicate": r.attrs["predicate"],
                    "subject_id": r.attrs["subject"],
                    "subject_label": by_id[r.attrs["subject"]].attrs["label"],
                    "t0": r.t0, "t1": r.t1, "status": r.status.value,
                    "evidence": r.evidence} for r in claims],
        "span_count": len(spans),
        "span_bounds": [[r.attrs["start"], r.attrs["end"]] for r in spans],
        "span_text_exact": all(
            by_id[r.attrs["raw_id"]].attrs["content"][r.attrs["start"]:r.attrs["end"]]
            == next((c.attrs["object"] for c in claims if r.id in c.evidence), None)
            for r in spans
        ),
    }


def run(root: Path) -> dict:
    compiled = {}
    for name, text in SAMPLES.items():
        batch = compile_nl(text, allow_env_extractor=False)
        observation = describe(batch)
        observation["raw_exact"] = batch.kind(RecordKind.RAW)[0].attrs["content"] == text
        assert observation["raw_exact"] and observation["span_text_exact"]
        compiled[name] = observation
    long_text = "word " * 2000
    long_batch = compile_nl(long_text, allow_env_extractor=False)
    compiled["unpunctuated_long"] = {
        "input_recipe": "word plus space repeated 2000 times",
        "input_characters": len(long_text),
        "span_count": len(long_batch.kind(RecordKind.SPAN)),
        "maximum_span_characters": max(
            r.attrs["end"] - r.attrs["start"] for r in long_batch.kind(RecordKind.SPAN)
        ),
        "raw_exact": long_batch.kind(RecordKind.RAW)[0].attrs["content"] == long_text,
    }

    sample = [{"sample_id": "m1-synthetic", "conversation": {"sessions": [{
        "date_time": "2026-09-03", "dialogs": [
            {"speaker": "Eve", "text": "I visited the museum.",
             "dia_id": "D1:1", "blip_caption": "M1_CAPTION_CEDAR"},
            {"speaker": "Eve", "text": "I visited the museum.",
             "dia_id": "D1:2", "blip_caption": "M1_CAPTION_CEDAR"},
        ]}], "session_id": "distinct-session"},
        "qa": [{"question": "Synthetic loader control?", "answer": "museum", "category": 4}]}]
    fixture = root / "synthetic-loader.json"
    fixture.write_text(json.dumps(sample), encoding="utf-8")
    loaded = load_locomo_cases(fixture)[0]
    loader = {"input": sample, "output_turns": [asdict(t) for t in loaded.conversation],
              "distinct_input_dialogue_ids": ["D1:1", "D1:2"],
              "loaded_turns_equal": loaded.conversation[0] == loaded.conversation[1]}

    adapter = SeamLocomoAdapter(db_path=str(root / "adapter"), derived_facts_policy="off",
                                record_retrieval_events=False)
    scope = "formation-audit"
    namespace = "locomo:" + scope
    try:
        turns = [ConversationTurn("Alice", "I moved to Oslo. I enjoy painting.", "2026-09-01"),
                 ConversationTurn("Bob", "I moved to Rome. I enjoy hiking.", "2026-09-02"),
                 *loaded.conversation]
        for turn in turns:
            adapter.ingest_turn(scope, turn)
        rt = adapter._runtime(scope)
        observed = describe(rt.store.load_ir(ns=namespace))
        observed["input_turns"] = [asdict(t) for t in turns]
        observed["embedding_model"] = rt.embedding_model.name
        with closing(rt.store._connect()) as connection:
            observed["text_column_checks"] = {
                term: connection.execute(
                    "select count(*) from raw_docs where ns=? and content like ?",
                    (namespace, "%" + term + "%"),
                ).fetchone()[0]
                for term in ("painting", "museum", "M1_CAPTION_CEDAR", "M1_UNSTATED_SENTINEL")
            }
            observed["graph_edge_count"] = connection.execute(
                "select count(*) from knowledge_edges where ns=?", (namespace,)
            ).fetchone()[0]
            observed["canonical_relation_rows"] = connection.execute(
                "select count(*) from ir_records where ns=? and kind='REL'", (namespace,)
            ).fetchone()[0]
        assert observed["text_column_checks"]["painting"] == 1
        assert observed["text_column_checks"]["M1_UNSTATED_SENTINEL"] == 0
        answer = adapter.answer(scope, "What does Alice enjoy?")
        observed["retrieval"] = {"query": "What does Alice enjoy?",
                                 "context": answer.retrieved_context,
                                 "generated_answer": answer.generated_answer}
        assert "painting" in answer.retrieved_context and answer.generated_answer is None
        observed["graph_product_build"] = rt.store.rebuild_graph_products(
            namespace=namespace, scope="thread")
        observed["graph_products"] = rt.store.graph_products(namespace=namespace, scope="thread")
    finally:
        adapter.close()

    with SeamRuntime(root / "direct-control.db", embedding_model=HashEmbeddingModel(),
                     allow_pgvector_env=False) as rt:
        for ref in ("fixture:distinct-event-1", "fixture:distinct-event-2"):
            rt.ingest_conversation_turn("Eve: I visited the museum.", source_ref=ref,
                                        ns="control", allow_env_extractor=False)
        direct = describe(rt.store.load_ir(ns="control"))
        direct["embedding_model"] = rt.embedding_model.name
        assert len(direct["raw"]) == 2
        unicode_outcome = rt.ingest_conversation_turn(SAMPLES["unicode"],
            source_ref="fixture:unicode", ns="unicode", allow_env_extractor=False)
        unicode = describe(rt.store.load_ir(ns="unicode"))
        unicode["ingest_chunk_count"] = unicode_outcome.document["chunk_count"]
        unicode["ingest_extraction_status"] = unicode_outcome.document["extraction_status"]
    return {"compiler": compiled, "loader": loader, "adapter": observed,
            "distinct_source_reference_control": direct, "persisted_unicode": unicode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; select a new destination")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "diff", "HEAD", "--", "seam_runtime",
                                "benchmarks/external"], cwd=ROOT):
        parser.error("runtime or adapter differs from the recorded revision")
    settings = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1", "SEAM_PGVECTOR_DSN": "",
                "SEAM_NL_REGEX_ENRICH": "", "SEAM_BENCH_ENTITY_AGG": "",
                "SEAM_AGENT": "", "SEAM_RECORD_RETRIEVAL_EVENTS": ""}
    scratch = ROOT / "test_seam" / "formation-audit"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with patch.dict("os.environ", settings), TemporaryDirectory(dir=scratch) as directory:
            result = run(Path(directory))
    except Exception as exc:
        print(f"M1 probe failed: {type(exc).__name__}; inspect privately", file=sys.stderr)
        return 1
    result.update({"schema": "seam-m1-formation-observations/v1", "revision": revision,
                   "observed_at": datetime.now(timezone.utc).isoformat(),
                   "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "synthetic_inputs_only": True, "quality_benchmark": False,
                   "provider_calls": 0, "website_publication": False})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("M1 synthetic compiler, loader, real-adapter, storage and retrieval observations saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
