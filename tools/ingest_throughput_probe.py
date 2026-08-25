"""Reproducible ingest-throughput probe (HISTORY#608/#609).

The batched-embedding change was justified by throughput numbers measured on a
private corpus. A claim nobody can re-run is not evidence, so this probe makes
those numbers reproducible on ANY text input and prints the hardware, model,
and device alongside them.

    python -m tools.ingest_throughput_probe --text-dir <dir> --chunks 40
    python -m tools.ingest_throughput_probe --synthetic 40

Reported:
  * embed rate per-record vs batched, for the configured model/device
  * end-to-end chunks/s for per-chunk persist vs one bulk IRBatch persist
  * bytes written per chunk
"""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

from seam_runtime.mirl import IRBatch
from seam_runtime.models import default_embedding_model
from seam_runtime.runtime import SeamRuntime

NS = "probe.ingest"
SCOPE = "project"


def _device(model) -> str:
    inner = getattr(model, "_model", None)
    try:
        return str(next(inner.parameters()).device)  # type: ignore[union-attr]
    except Exception:
        return "cpu/unknown"


def _synthetic(count: int) -> list[str]:
    body = (
        "The mind concentrates its force upon a single sustained purpose, and "
        "that concentration is the whole of the method described here. "
    )
    return [f"Passage {i}. {body * 6}" for i in range(count)]


def _from_dir(root: Path, count: int) -> list[str]:
    chunks: list[str] = []
    for path in sorted(root.rglob("*.txt")):
        text = path.read_text(errors="ignore")
        for start in range(0, len(text), 1200):
            piece = text[start : start + 1200].strip()
            if len(piece) > 400:
                chunks.append(piece)
            if len(chunks) >= count:
                return chunks
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text-dir", type=Path, help="directory of .txt files")
    source.add_argument("--synthetic", type=int, metavar="N", help="generate N chunks")
    parser.add_argument("--chunks", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.synthetic is not None:
        if args.synthetic < 1:
            parser.error("--synthetic must be a positive chunk count")
        chunks = _synthetic(args.synthetic)
    else:
        chunks = _from_dir(args.text_dir, args.chunks)
    if not chunks:
        parser.error("no chunks collected")

    model = default_embedding_model()
    model.embed("warm up")
    texts = [c[:512] for c in chunks]

    t = time.perf_counter()
    for text in texts:
        model.embed(text)
    per_record = time.perf_counter() - t

    from seam_runtime.models import embed_texts

    t = time.perf_counter()
    embed_texts(model, texts)
    batched = time.perf_counter() - t

    def run(bulk: bool) -> tuple[float, float]:
        # TemporaryDirectory, not mkdtemp: at the measured storage
        # amplification a large run would otherwise leave hundreds of
        # megabytes behind in the system temp directory on every invocation.
        with tempfile.TemporaryDirectory(prefix="seam-probe-") as tmp:
            rt = SeamRuntime(Path(tmp) / "probe.db", allow_pgvector_env=False)
            try:
                start = time.perf_counter()
                records = []
                for index, chunk in enumerate(chunks):
                    batch = rt.compile_nl(
                        chunk, source_ref=f"probe://{index}", ns=NS, scope=SCOPE
                    )
                    if bulk:
                        records.extend(batch.records)
                    else:
                        rt.persist_ir(batch)
                if bulk:
                    rt.persist_ir(IRBatch(records))
                elapsed = time.perf_counter() - start
                size = Path(rt.store.path).stat().st_size
            finally:
                rt.close()
        return elapsed, size

    per_chunk_s, per_chunk_bytes = run(bulk=False)
    bulk_s, bulk_bytes = run(bulk=True)

    n = len(chunks)
    result = {
        "chunks": n,
        "model": getattr(model, "name", "?"),
        "device": _device(model),
        "python": platform.python_version(),
        "embed_per_record_rec_s": round(n / per_record, 1),
        "embed_batched_rec_s": round(n / batched, 1),
        "embed_speedup": round(per_record / batched, 2),
        "persist_per_chunk_chunks_s": round(n / per_chunk_s, 2),
        "persist_bulk_chunks_s": round(n / bulk_s, 2),
        "persist_speedup": round(per_chunk_s / bulk_s, 2),
        "bytes_per_chunk_bulk": int(bulk_bytes / n),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key:32} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
