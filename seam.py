from __future__ import annotations

import sys
from pathlib import Path

from seam_runtime.cli import run_cli
from seam_runtime.dsl import compile_dsl  # noqa: F401 -- re-exported for `from seam import compile_dsl`
from seam_runtime.holographic import (
    HolographicReader,  # noqa: F401 -- re-exported for `from seam import HolographicReader`
    SurfaceArtifact,
    SurfacePayload,
    SurfaceQueryResult,
    SurfaceVerification,
    context_surface,  # noqa: F401 -- re-exported for `from seam import context_surface`
    decode_surface,
    encode_surface,
    query_surface,
    verify_surface,
)
from seam_runtime.lossless import (
    LosslessArtifact,
    LosslessBenchmarkResult,
    ReadableCompressionArtifact,
    ReadableQueryResult,
    benchmark_text_lossless,
    compress_text_lossless,
    compress_text_readable,
    decompress_text_lossless,
    decompress_text_readable,
    query_readable_compressed,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, Pack, RecordKind
from seam_runtime.models import (
    HashEmbeddingModel,  # noqa: F401 -- re-exported for `from seam import HashEmbeddingModel`
    OpenAICompatibleEmbeddingModel,  # noqa: F401 -- re-exported for `from seam import OpenAICompatibleEmbeddingModel`
)
from seam_runtime.nl import compile_nl
from seam_runtime.pack import pack_records, unpack_exact_pack
from seam_runtime.runtime import SeamRuntime  # noqa: F401 -- re-exported for `from seam import SeamRuntime`
from seam_runtime.verify import verify_ir  # noqa: F401 -- re-exported for `from seam import verify_ir`


def pack_ir(records, lens: str = "general", budget: int = 512, mode: str = "context") -> Pack:
    if isinstance(records, IRBatch):
        batch = records
    else:
        batch = IRBatch(list(records))
    return pack_records(batch.records, lens=lens, budget=budget, mode=mode)


def decompile_ir(records, mode: str = "expanded") -> str:
    if isinstance(records, IRBatch):
        batch = records
    else:
        batch = IRBatch(list(records))
    states = [record for record in batch.records if record.kind == RecordKind.STA]
    claims = [record for record in batch.records if record.kind == RecordKind.CLM]
    if states:
        summary = "; ".join(f"{key}={value}" for key, value in states[0].attrs.get("fields", {}).items())
    elif claims:
        summary = "; ".join(f"{record.attrs.get('subject')} {record.attrs.get('predicate')} {record.attrs.get('object')}" for record in claims)
    else:
        summary = "No MIRL records available."
    return summary if mode == "minimal" else f"MIRL summary: {summary}"


def render_ir(records) -> str:
    if isinstance(records, IRBatch):
        return records.to_text()
    return IRBatch(list(records)).to_text()


def load_ir_lines(text: str) -> list[MIRLRecord]:
    return IRBatch.from_text(text).records


def unpack_pack(pack: Pack | str):
    if isinstance(pack, Pack):
        if pack.mode == "exact":
            return unpack_exact_pack(pack).to_json()
        return pack.payload
    raise TypeError("unpack_pack now expects a Pack instance")


def lossless_compress(text: str, codec: str = "auto", transform: str = "auto", tokenizer: str = "auto") -> LosslessArtifact:
    return compress_text_lossless(text, codec=codec, transform=transform, tokenizer=tokenizer)


def lossless_decompress(machine_text: str) -> str:
    return decompress_text_lossless(machine_text)


def readable_compress(text: str, source_ref: str = "local://input", granularity: str = "auto", tokenizer: str = "auto") -> ReadableCompressionArtifact:
    return compress_text_readable(text, source_ref=source_ref, granularity=granularity, tokenizer=tokenizer)


def readable_query(machine_text: str, query: str, limit: int = 5) -> ReadableQueryResult:
    return query_readable_compressed(machine_text, query=query, limit=limit)


def readable_decompress(machine_text: str) -> str:
    return decompress_text_readable(machine_text)


def surface_encode(payload: bytes, output_path: str | Path, mode: str = "rgb24", payload_format: str = "auto") -> SurfaceArtifact:
    return encode_surface(payload, Path(output_path), mode=mode, payload_format=payload_format)


def surface_compile(text: str, output_path: str | Path, mode: str = "rgb24", source_ref: str = "local://input") -> SurfaceArtifact:
    batch = compile_nl(text, source_ref=source_ref)
    return encode_surface(batch.to_text().encode("utf-8"), Path(output_path), mode=mode, payload_format="MIRL", source_ref=source_ref)


def surface_decode(path: str | Path) -> SurfacePayload:
    return decode_surface(Path(path))


def surface_verify(path: str | Path) -> SurfaceVerification:
    return verify_surface(Path(path))


def surface_query(path: str | Path, query: str, limit: int = 5) -> SurfaceQueryResult:
    return query_surface(Path(path), query=query, limit=limit)


def lossless_benchmark(
    text: str,
    codec: str = "auto",
    transform: str = "auto",
    min_token_savings: float = 0.30,
    tokenizer: str = "auto",
) -> LosslessBenchmarkResult:
    return benchmark_text_lossless(text, codec=codec, transform=transform, min_token_savings=min_token_savings, tokenizer=tokenizer)


def main() -> None:
    run_cli()


def benchmark_main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] not in {"run", "show", "verify", "diff", "gate", "-h", "--help"} and Path(argv[0]).exists():
        run_cli(["lossless-benchmark", *argv])
        return
    if not argv:
        run_cli(["benchmark", "run"])
        return
    if argv[0] in {"run", "show", "verify", "diff", "gate"}:
        run_cli(["benchmark", *argv])
        return
    run_cli(["benchmark", "run", *argv])


if __name__ == "__main__":
    main()
