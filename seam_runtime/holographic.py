from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .lossless import query_readable_compressed
from .mirl import IRBatch
from .pack import pack_records

SURFACE_MAGIC = "SEAM-HS/1"
SURFACE_MAGIC_BYTES = b"SEAM-HS/1\n"
SURFACE_MODES = ("bw1", "rgb", "rgb24", "rgba32", "rgba64")
SURFACE_PAYLOAD_FORMATS = ("auto", "MIRL", "SEAM-RC/1", "SEAM-LX/1", "bytes")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_MAX_SURFACE_PAYLOAD_BYTES = 64 * 1024 * 1024
# Hard ceiling on PNG raster dimensions read from an untrusted IHDR. A real
# SEAM-HS/1 surface for the default 64MiB payload is ~4096x4096; 8192 per side
# leaves generous headroom while preventing a malformed IHDR from driving a
# multi-gigabyte allocation (decompression-bomb / image-bomb OOM).
MAX_SURFACE_DIMENSION = 8192


@dataclass
class SurfaceArtifact:
    path: str
    mode: str
    payload_format: str
    payload_bytes: int
    payload_sha256: str
    surface_bytes: int
    width: int
    height: int
    capacity_bytes: int
    overhead_bytes: int
    source_ref: str = ""

    @property
    def capacity_used_ratio(self) -> float:
        if self.capacity_bytes <= 0:
            return 0.0
        return self.payload_bytes / self.capacity_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "format": SURFACE_MAGIC,
            "path": self.path,
            "mode": self.mode,
            "payload_format": self.payload_format,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "surface_bytes": self.surface_bytes,
            "width": self.width,
            "height": self.height,
            "capacity_bytes": self.capacity_bytes,
            "overhead_bytes": self.overhead_bytes,
            "capacity_used_ratio": round(self.capacity_used_ratio, 6),
            "source_ref": self.source_ref,
        }


@dataclass
class SurfacePayload:
    payload: bytes
    metadata: dict[str, Any]
    mode: str
    payload_format: str
    payload_sha256: str
    payload_bytes: int
    width: int
    height: int
    path: str

    @property
    def text(self) -> str:
        return self.payload.decode("utf-8")

    def to_dict(self, include_payload: bool = False) -> dict[str, object]:
        data: dict[str, object] = {
            "format": SURFACE_MAGIC,
            "path": self.path,
            "mode": self.mode,
            "payload_format": self.payload_format,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "width": self.width,
            "height": self.height,
            "metadata": dict(self.metadata),
        }
        if include_payload:
            data["payload_text"] = self.text if _is_utf8(self.payload) else None
            data["payload_hex"] = self.payload.hex() if not _is_utf8(self.payload) else None
        return data


@dataclass
class SurfaceVerification:
    ok: bool
    path: str
    mode: str | None = None
    payload_format: str | None = None
    payload_bytes: int | None = None
    payload_sha256: str | None = None
    actual_sha256: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "format": SURFACE_MAGIC,
            "status": "PASS" if self.ok else "FAIL",
            "path": self.path,
            "mode": self.mode,
            "payload_format": self.payload_format,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "actual_sha256": self.actual_sha256,
            "errors": list(self.errors),
        }


@dataclass
class SurfaceQueryResult:
    query: str
    source_path: str
    payload_format: str
    hits: list[dict[str, object]]
    context: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "format": SURFACE_MAGIC,
            "query": self.query,
            "source_path": self.source_path,
            "payload_format": self.payload_format,
            "hits": list(self.hits),
            "context": self.context,
        }


class HolographicReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> SurfacePayload:
        return decode_surface(self.path)

    def verify(self) -> SurfaceVerification:
        return verify_surface(self.path)

    def query(self, query: str, limit: int = 5) -> SurfaceQueryResult:
        return query_surface(self.path, query=query, limit=limit)

    def context(self, query: str, budget: int = 1200) -> dict[str, object]:
        return context_surface(self.path, query=query, budget=budget)


def encode_surface(
    payload: bytes,
    output_path: Path,
    mode: str = "rgb24",
    payload_format: str = "auto",
    source_ref: str | None = None,
) -> SurfaceArtifact:
    mode = _normalize_surface_mode(mode)
    if mode not in SURFACE_MODES:
        raise ValueError(f"Unsupported holographic surface mode: {mode}")
    max_payload_bytes = _max_surface_payload_bytes()
    if max_payload_bytes and len(payload) > max_payload_bytes:
        raise ValueError(
            "Holographic surface payload exceeds configured limit: "
            f"{len(payload)} bytes > {max_payload_bytes} bytes"
        )
    resolved_format = _detect_payload_format(payload) if payload_format == "auto" else payload_format
    if resolved_format not in SURFACE_PAYLOAD_FORMATS or resolved_format == "auto":
        raise ValueError(f"Unsupported holographic payload format: {payload_format}")

    payload_sha256 = hashlib.sha256(payload).hexdigest()
    metadata = {
        "format": SURFACE_MAGIC,
        "mode": mode,
        "payload_format": resolved_format,
        "payload_bytes": len(payload),
        "payload_sha256": payload_sha256,
        "source_ref": source_ref or "",
        "contract": "direct_read_visual_container",
    }
    header = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    container = SURFACE_MAGIC_BYTES + struct.pack(">I", len(header)) + header + payload
    width, height, pixels, color_type, bit_depth, capacity_bytes = _container_to_pixels(container, mode)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_png(output_path, width=width, height=height, color_type=color_type, bit_depth=bit_depth, pixel_bytes=pixels)
    return SurfaceArtifact(
        path=str(output_path),
        mode=mode,
        payload_format=resolved_format,
        payload_bytes=len(payload),
        payload_sha256=payload_sha256,
        surface_bytes=output_path.stat().st_size,
        width=width,
        height=height,
        capacity_bytes=capacity_bytes,
        overhead_bytes=len(container) - len(payload),
        source_ref=source_ref or "",
    )


def decode_surface(path: Path) -> SurfacePayload:
    path = Path(path)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        raise ValueError("SEAM-HS/1 refuses lossy JPEG surfaces for exact memory")
    width, height, color_type, bit_depth, pixel_bytes = _read_png(path)
    if color_type in {2, 6}:
        container = pixel_bytes
    elif color_type == 0:
        container = _bits_to_bytes(pixel_bytes)
    else:
        raise ValueError(f"Unsupported PNG color type for SEAM-HS/1: {color_type}")

    metadata, payload = _parse_container(container)
    expected_sha = str(metadata["payload_sha256"])
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"Holographic surface hash mismatch: expected {expected_sha}, got {actual_sha}")
    return SurfacePayload(
        payload=payload,
        metadata=metadata,
        mode=_normalize_surface_mode(str(metadata["mode"])),
        payload_format=str(metadata["payload_format"]),
        payload_sha256=expected_sha,
        payload_bytes=int(metadata["payload_bytes"]),
        width=width,
        height=height,
        path=str(path),
    )


def verify_surface(path: Path) -> SurfaceVerification:
    try:
        payload = decode_surface(path)
    except Exception as exc:
        return SurfaceVerification(ok=False, path=str(path), errors=[str(exc)])
    actual_sha = hashlib.sha256(payload.payload).hexdigest()
    return SurfaceVerification(
        ok=actual_sha == payload.payload_sha256,
        path=str(path),
        mode=payload.mode,
        payload_format=payload.payload_format,
        payload_bytes=payload.payload_bytes,
        payload_sha256=payload.payload_sha256,
        actual_sha256=actual_sha,
        errors=[] if actual_sha == payload.payload_sha256 else ["payload hash mismatch"],
    )


def inspect_surface(path: Path) -> dict[str, object]:
    payload = decode_surface(path)
    path = Path(path)
    surface_bytes = path.stat().st_size
    capacity_bytes = _capacity_bytes(payload.width, payload.height, payload.mode)
    return {
        "format": SURFACE_MAGIC,
        "path": str(path),
        "mode": payload.mode,
        "payload_format": payload.payload_format,
        "payload_bytes": payload.payload_bytes,
        "payload_sha256": payload.payload_sha256,
        "surface_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "surface_bytes": surface_bytes,
        "width": payload.width,
        "height": payload.height,
        "capacity_bytes": capacity_bytes,
        "overhead_bytes": None,
        "capacity_used_ratio": round(payload.payload_bytes / capacity_bytes, 6) if capacity_bytes else 0.0,
        "source_ref": str(payload.metadata.get("source_ref", "")),
        "metadata": dict(payload.metadata),
    }


def query_surface(path: Path, query: str, limit: int = 5) -> SurfaceQueryResult:
    """Query a surface; MIRL payloads must satisfy the canonical IR contract.

    Decoding proves byte integrity, not semantic validity. MIRL surfaces are
    therefore admitted through ``persist_ir`` and fail closed on invalid or
    incomplete records instead of falling back to the retired direct scorer.
    """

    payload = decode_surface(path)
    if payload.payload_format == "SEAM-RC/1":
        result = query_readable_compressed(payload.text, query=query, limit=limit).to_dict()
        return SurfaceQueryResult(
            query=query,
            source_path=str(path),
            payload_format=payload.payload_format,
            hits=list(result["hits"]),
        )
    if payload.payload_format == "MIRL":
        batch = IRBatch.from_text(payload.text)
        with _surface_retrieval_runtime() as runtime:
            runtime.persist_ir(batch)
            result = runtime.retrieve(
                query=query,
                budget=limit,
                include_raw=True,
                mode="mix",
            ).to_dict()
        hits = [
            {
                "record_id": candidate["record"]["id"],
                "record_type": candidate["record"]["kind"],
                "score": candidate["score"],
                "text": json.dumps(candidate["record"], sort_keys=True),
                "reasons": candidate.get("reasons", []),
            }
            for candidate in result.get("candidates", [])
        ]
        return SurfaceQueryResult(query=query, source_path=str(path), payload_format=payload.payload_format, hits=hits)
    raise ValueError(f"Surface query requires MIRL or SEAM-RC/1 payloads, got {payload.payload_format}")


def context_surface(path: Path, query: str, budget: int = 1200) -> dict[str, object]:
    payload = decode_surface(path)
    if payload.payload_format == "MIRL":
        batch = IRBatch.from_text(payload.text)
        with _surface_retrieval_runtime() as runtime:
            runtime.persist_ir(batch)
            result = runtime.retrieve(
                query=query,
                budget=max(1, min(10, budget // 120)),
                include_raw=True,
                mode="mix",
            )
        records = [candidate.record for candidate in result.candidates]
        pack = pack_records(records, lens="holographic", budget=budget, mode="context")
        return {
            "format": SURFACE_MAGIC,
            "source_path": str(path),
            "payload_format": payload.payload_format,
            "query": query,
            "context": pack.to_dict(),
        }
    result = query_surface(path, query=query, limit=max(1, min(10, budget // 120)))
    context_lines = [str(hit.get("text", "")).rstrip() for hit in result.hits]
    return {
        "format": SURFACE_MAGIC,
        "source_path": str(path),
        "payload_format": payload.payload_format,
        "query": query,
        "context": {
            "mode": "context",
            "lens": "holographic",
            "budget": budget,
            "snippets": context_lines,
            "token_cost": sum(max(1, len(line) // 4) for line in context_lines),
        },
    }


def _surface_retrieval_runtime():
    """Build a fully in-memory runtime over the canonical retrieval engine."""

    from .models import HashEmbeddingModel
    from .runtime import SeamRuntime
    from .vector_adapters import MemoryVectorAdapter

    model = HashEmbeddingModel()
    return SeamRuntime(
        ":memory:",
        embedding_model=model,
        vector_adapter=MemoryVectorAdapter(model),
        allow_pgvector_env=False,
    )


def _detect_payload_format(payload: bytes) -> str:
    if payload.startswith(b"SEAM-RC/1"):
        return "SEAM-RC/1"
    if payload.startswith(b"SEAM-LX/1"):
        return "SEAM-LX/1"
    if _looks_like_mirl(payload):
        return "MIRL"
    return "bytes"


def _looks_like_mirl(payload: bytes) -> bool:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.split("|", 2)[0] in {"RAW", "SPAN", "ENT", "CLM", "EVT", "REL", "STA", "SYM", "PACK", "FLOW", "PROV", "META"} for line in lines)


def _normalize_surface_mode(mode: str) -> str:
    return "rgb24" if mode == "rgb" else mode


def _max_surface_payload_bytes() -> int:
    raw = os.environ.get("SEAM_SURFACE_MAX_PAYLOAD_BYTES")
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_SURFACE_PAYLOAD_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SEAM_SURFACE_MAX_PAYLOAD_BYTES must be an integer") from exc
    if value < 0:
        raise ValueError("SEAM_SURFACE_MAX_PAYLOAD_BYTES must be non-negative")
    return value


def _container_to_pixels(container: bytes, mode: str) -> tuple[int, int, bytes, int, int, int]:
    mode = _normalize_surface_mode(mode)
    if mode in {"rgb24", "rgba32", "rgba64"}:
        channels = 8 if mode == "rgba64" else 4 if mode == "rgba32" else 3
        color_type = 6 if mode in {"rgba32", "rgba64"} else 2
        bit_depth = 16 if mode == "rgba64" else 8
        total_pixels = max(1, math.ceil(len(container) / channels))
        width = max(1, math.ceil(math.sqrt(total_pixels)))
        height = math.ceil(total_pixels / width)
        capacity_bytes = width * height * channels
        return width, height, container.ljust(capacity_bytes, b"\x00"), color_type, bit_depth, capacity_bytes
    bit_count = len(container) * 8
    width = max(1, math.ceil(math.sqrt(bit_count)))
    height = math.ceil(bit_count / width)
    capacity_bits = width * height
    bits = "".join(f"{byte:08b}" for byte in container).ljust(capacity_bits, "0")
    pixels = bytes(255 if bit == "1" else 0 for bit in bits)
    return width, height, pixels, 0, 8, capacity_bits // 8


def _capacity_bytes(width: int, height: int, mode: str) -> int:
    mode = _normalize_surface_mode(mode)
    if mode == "rgba64":
        return width * height * 8
    if mode == "rgba32":
        return width * height * 4
    if mode == "rgb24":
        return width * height * 3
    if mode == "bw1":
        return (width * height) // 8
    return 0


def _parse_container(container: bytes) -> tuple[dict[str, Any], bytes]:
    if not container.startswith(SURFACE_MAGIC_BYTES):
        raise ValueError("PNG does not contain a SEAM-HS/1 surface")
    offset = len(SURFACE_MAGIC_BYTES)
    if len(container) < offset + 4:
        raise ValueError("SEAM-HS/1 surface header is truncated")
    header_length = struct.unpack(">I", container[offset : offset + 4])[0]
    offset += 4
    header_end = offset + header_length
    metadata = json.loads(container[offset:header_end].decode("utf-8"))
    if metadata.get("format") != SURFACE_MAGIC:
        raise ValueError("SEAM-HS/1 metadata format mismatch")
    payload_length = int(metadata["payload_bytes"])
    payload = container[header_end : header_end + payload_length]
    if len(payload) != payload_length:
        raise ValueError("SEAM-HS/1 payload is truncated")
    return metadata, payload


def _write_png(path: Path, width: int, height: int, color_type: int, bit_depth: int, pixel_bytes: bytes) -> None:
    channels = 4 if color_type == 6 else 3 if color_type == 2 else 1
    bytes_per_sample = 2 if bit_depth == 16 else 1
    stride = width * channels * bytes_per_sample
    expected = stride * height
    if len(pixel_bytes) != expected:
        raise ValueError(f"Pixel payload has {len(pixel_bytes)} bytes, expected {expected}")
    raw = b"".join(b"\x00" + pixel_bytes[row * stride : (row + 1) * stride] for row in range(height))
    png = bytearray(PNG_SIGNATURE)
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)))
    png.extend(_png_chunk(b"IDAT", zlib.compress(raw, level=9)))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _bounded_inflate(data: bytes, max_output: int) -> bytes:
    """Inflate `data`, refusing to materialize more than `max_output` bytes.

    A well-formed SEAM-HS/1 surface inflates to exactly ``(stride + 1) * height``
    bytes, so callers pass that as the bound. A crafted IDAT that tries to expand
    past it (decompression bomb) is rejected instead of driving an unbounded
    allocation.
    """
    decompressor = zlib.decompressobj()
    out = decompressor.decompress(data, max_output)
    if decompressor.unconsumed_tail:
        raise ValueError("PNG IDAT inflates beyond the declared raster size (possible image bomb)")
    out += decompressor.flush()
    if len(out) > max_output:
        raise ValueError("PNG IDAT inflates beyond the declared raster size (possible image bomb)")
    return out


def _read_png(path: Path) -> tuple[int, int, int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("SEAM-HS/1 only supports lossless PNG surfaces")
    offset = len(PNG_SIGNATURE)
    width = height = color_type = bit_depth = None
    idat = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        crc_expected = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
        crc_actual = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if crc_actual != crc_expected:
            raise ValueError(f"PNG chunk CRC mismatch: {chunk_type.decode('ascii', errors='replace')}")
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if bit_depth not in {8, 16} or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("Unsupported PNG encoding for SEAM-HS/1")
            if color_type not in {0, 2, 6}:
                raise ValueError(f"Unsupported PNG color type for SEAM-HS/1: {color_type}")
            if bit_depth == 16 and color_type != 6:
                raise ValueError("SEAM-HS/1 16-bit surfaces require RGBA color type")
            if not (0 < width <= MAX_SURFACE_DIMENSION and 0 < height <= MAX_SURFACE_DIMENSION):
                raise ValueError(
                    f"PNG dimensions {width}x{height} exceed the SEAM-HS/1 limit of "
                    f"{MAX_SURFACE_DIMENSION}px per side"
                )
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or color_type is None or bit_depth is None:
        raise ValueError("PNG is missing IHDR metadata")
    channels = 4 if color_type == 6 else 3 if color_type == 2 else 1
    bytes_per_pixel = channels * (2 if bit_depth == 16 else 1)
    stride = width * bytes_per_pixel
    expected_raw = (stride + 1) * height  # PNG prepends one filter byte per row
    raw = _bounded_inflate(bytes(idat), expected_raw)
    return width, height, color_type, bit_depth, _unfilter_png(raw, width, height, bytes_per_pixel, stride)


def _unfilter_png(raw: bytes, width: int, height: int, bytes_per_pixel: int, stride: int) -> bytes:
    rows = []
    offset = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        for i in range(stride):
            left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            up = previous[i]
            upper_left = previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 0xFF
            elif filter_type == 2:
                row[i] = (row[i] + up) & 0xFF
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (row[i] + _paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"Unsupported PNG filter type: {filter_type}")
        rows.append(bytes(row))
        previous = row
    return b"".join(rows)


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def _bits_to_bytes(pixels: bytes) -> bytes:
    bits = "".join("1" if pixel > 127 else "0" for pixel in pixels)
    return bytes(int(bits[index : index + 8], 2) for index in range(0, len(bits) - 7, 8))


def _is_utf8(payload: bytes) -> bool:
    try:
        payload.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
