from __future__ import annotations

import base64
import bz2
import hashlib
import json
import lzma
import math
import re
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

LOSSLESS_MAGIC = "SEAM-LX/1"
READABLE_MAGIC = "SEAM-RC/1"
LOSSLESS_CODECS = ("zlib", "bz2", "lzma")
LOSSLESS_TRANSFORMS = ("identity", "line_table", "paragraph_table")
READABLE_GRANULARITIES = ("auto", "line", "paragraph", "chunk")
TOKEN_ESTIMATOR = "char4_approx"
TOKENIZER_CHOICES = ("auto", TOKEN_ESTIMATOR, "cl100k_base", "o200k_base")

_COMPRESSORS: dict[str, Callable[[bytes], bytes]] = {
    "zlib": lambda payload: zlib.compress(payload, level=9),
    "bz2": lambda payload: bz2.compress(payload, compresslevel=9),
    "lzma": lambda payload: lzma.compress(payload, preset=9 | lzma.PRESET_EXTREME),
}
_DECOMPRESSORS: dict[str, Callable[[bytes], bytes]] = {
    "zlib": zlib.decompress,
    "bz2": bz2.decompress,
    "lzma": lzma.decompress,
}


@dataclass
class LosslessArtifact:
    codec: str
    transform: str
    machine_text: str
    sha256: str
    original_bytes: int
    transformed_bytes: int
    compressed_bytes: int
    machine_bytes: int
    original_tokens: int
    machine_tokens: int
    token_estimator: str = TOKEN_ESTIMATOR

    @property
    def byte_savings_ratio(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return 1.0 - (self.machine_bytes / self.original_bytes)

    @property
    def token_savings_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return 1.0 - (self.machine_tokens / self.original_tokens)

    @property
    def intelligence_per_token_gain(self) -> float:
        if self.machine_tokens <= 0:
            return 0.0
        return self.original_tokens / self.machine_tokens

    def to_dict(self, include_machine_text: bool = True) -> dict[str, object]:
        payload = {
            "codec": self.codec,
            "transform": self.transform,
            "sha256": self.sha256,
            "original_bytes": self.original_bytes,
            "transformed_bytes": self.transformed_bytes,
            "compressed_bytes": self.compressed_bytes,
            "machine_bytes": self.machine_bytes,
            "original_tokens": self.original_tokens,
            "machine_tokens": self.machine_tokens,
            "byte_savings_ratio": round(self.byte_savings_ratio, 6),
            "token_savings_ratio": round(self.token_savings_ratio, 6),
            "intelligence_per_token_gain": round(self.intelligence_per_token_gain, 6),
            "token_estimator": self.token_estimator,
        }
        if include_machine_text:
            payload["machine_text"] = self.machine_text
        return payload


@dataclass
class LosslessAttempt:
    iteration: int
    transform: str
    codec: str
    transformed_bytes: int
    compressed_bytes: int
    machine_bytes: int
    machine_tokens: int
    token_savings_ratio: float
    byte_savings_ratio: float
    delta_vs_best: float
    delta_vs_previous: float
    status: str
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "transform": self.transform,
            "codec": self.codec,
            "transformed_bytes": self.transformed_bytes,
            "compressed_bytes": self.compressed_bytes,
            "machine_bytes": self.machine_bytes,
            "machine_tokens": self.machine_tokens,
            "token_savings_ratio": round(self.token_savings_ratio, 6),
            "byte_savings_ratio": round(self.byte_savings_ratio, 6),
            "delta_vs_best": round(self.delta_vs_best, 6),
            "delta_vs_previous": round(self.delta_vs_previous, 6),
            "status": self.status,
            "flags": list(self.flags),
        }


@dataclass
class LosslessBenchmarkResult:
    artifact: LosslessArtifact
    roundtrip_text: str
    roundtrip_match: bool
    target_token_savings: float
    search_log: list[LosslessAttempt] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def meets_target(self) -> bool:
        return self.artifact.token_savings_ratio >= self.target_token_savings

    @property
    def passed(self) -> bool:
        return self.roundtrip_match and self.meets_target

    def to_dict(self, include_machine_text: bool = False, include_roundtrip_text: bool = False) -> dict[str, object]:
        payload = {
            "passed": self.passed,
            "roundtrip_match": self.roundtrip_match,
            "meets_target": self.meets_target,
            "target_token_savings": round(self.target_token_savings, 6),
            "stop_reason": self.stop_reason,
            "flags": list(self.flags),
            "artifact": self.artifact.to_dict(include_machine_text=include_machine_text),
            "search_log": [attempt.to_dict() for attempt in self.search_log],
        }
        if include_roundtrip_text:
            payload["roundtrip_text"] = self.roundtrip_text
        return payload


@dataclass
class ReadableCompressionArtifact:
    machine_text: str
    sha256: str
    source_ref: str
    granularity: str
    original_bytes: int
    machine_bytes: int
    original_tokens: int
    machine_tokens: int
    unique_chunks: int
    chunk_occurrences: int
    quote_count: int
    token_estimator: str = TOKEN_ESTIMATOR

    @property
    def token_savings_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return 1.0 - (self.machine_tokens / self.original_tokens)

    @property
    def intelligence_per_token_gain(self) -> float:
        if self.machine_tokens <= 0:
            return 0.0
        return self.original_tokens / self.machine_tokens

    def to_dict(self, include_machine_text: bool = True) -> dict[str, object]:
        payload = {
            "format": READABLE_MAGIC,
            "sha256": self.sha256,
            "source_ref": self.source_ref,
            "granularity": self.granularity,
            "original_bytes": self.original_bytes,
            "machine_bytes": self.machine_bytes,
            "original_tokens": self.original_tokens,
            "machine_tokens": self.machine_tokens,
            "token_savings_ratio": round(self.token_savings_ratio, 6),
            "intelligence_per_token_gain": round(self.intelligence_per_token_gain, 6),
            "unique_chunks": self.unique_chunks,
            "chunk_occurrences": self.chunk_occurrences,
            "quote_count": self.quote_count,
            "token_estimator": self.token_estimator,
        }
        if include_machine_text:
            payload["machine_text"] = self.machine_text
        return payload


@dataclass
class ReadableQueryHit:
    record_id: str
    record_type: str
    text: str
    score: float
    start: int | None = None
    end: int | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "text": self.text,
            "score": round(self.score, 6),
            "start": self.start,
            "end": self.end,
            "reasons": list(self.reasons),
        }


@dataclass
class ReadableQueryResult:
    query: str
    source_ref: str
    sha256: str
    hits: list[ReadableQueryHit]

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "source_ref": self.source_ref,
            "sha256": self.sha256,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def estimate_prompt_tokens(text: str, tokenizer: str = "auto") -> int:
    return count_prompt_tokens(text, tokenizer=tokenizer)[0]


def count_prompt_tokens(text: str, tokenizer: str = "auto") -> tuple[int, str]:
    counter, estimator = _resolve_token_counter(tokenizer)
    return counter(text), estimator


def compress_text_lossless(
    text: str,
    codec: str = "auto",
    transform: str = "auto",
    max_rounds: int = 4,
    tokenizer: str = "auto",
) -> LosslessArtifact:
    artifact, _, _, _ = _run_lossless_search(text, codec=codec, transform=transform, max_rounds=max_rounds, tokenizer=tokenizer)
    return artifact


def compress_text_readable(
    text: str,
    source_ref: str = "local://input",
    granularity: str = "auto",
    tokenizer: str = "auto",
) -> ReadableCompressionArtifact:
    if granularity not in READABLE_GRANULARITIES:
        raise ValueError(f"Unsupported readable granularity: {granularity}")
    raw_bytes = text.encode("utf-8")
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    parts = _split_readable_parts(text, granularity)
    chunk_to_id: dict[str, str] = {}
    chunks: list[dict[str, object]] = []
    order: list[dict[str, object]] = []
    offset = 0

    for occurrence, part in enumerate(parts, start=1):
        chunk_id = chunk_to_id.get(part)
        if chunk_id is None:
            chunk_id = f"c:{len(chunks) + 1}"
            chunk_to_id[part] = chunk_id
            chunks.append(
                {
                    "id": chunk_id,
                    "text": part,
                    "sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(),
                    "terms": _readable_terms(part),
                }
            )
        end = offset + len(part)
        order.append({"id": chunk_id, "occurrence": occurrence, "start": offset, "end": end})
        offset = end

    quotes = _extract_readable_quotes(text, order, {str(chunk["id"]): str(chunk["text"]) for chunk in chunks})
    term_index = _build_readable_term_index(chunks)
    meta = {
        "format": READABLE_MAGIC,
        "source_ref": source_ref,
        "media_type": "text/plain",
        "granularity": _resolved_readable_granularity(text, granularity),
        "sha256": sha256,
        "original_bytes": len(raw_bytes),
        "unique_chunks": len(chunks),
        "chunk_occurrences": len(order),
        "quote_count": len(quotes),
        "contract": "direct_read_lossless",
    }
    machine_lines = [
        READABLE_MAGIC,
        "META|" + json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ]
    machine_lines.extend("CHUNK|" + json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for chunk in chunks)
    machine_lines.append("ORDER|" + json.dumps({"items": order}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    machine_lines.extend("QUOTE|" + json.dumps(quote, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for quote in quotes)
    machine_lines.append("INDEX|" + json.dumps({"terms": term_index}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    machine_text = "\n".join(machine_lines)
    original_tokens, estimator = count_prompt_tokens(text, tokenizer=tokenizer)
    machine_tokens, _ = count_prompt_tokens(machine_text, tokenizer=tokenizer)
    return ReadableCompressionArtifact(
        machine_text=machine_text,
        sha256=sha256,
        source_ref=source_ref,
        granularity=str(meta["granularity"]),
        original_bytes=len(raw_bytes),
        machine_bytes=len(machine_text.encode("utf-8")),
        original_tokens=original_tokens,
        machine_tokens=machine_tokens,
        unique_chunks=len(chunks),
        chunk_occurrences=len(order),
        quote_count=len(quotes),
        token_estimator=estimator,
    )


def decompress_text_readable(machine_text: str) -> str:
    parsed = parse_readable_machine_text(machine_text)
    chunks = {str(chunk["id"]): str(chunk["text"]) for chunk in parsed["chunks"]}
    rebuilt_parts: list[str] = []
    for item in parsed["order"]:
        chunk_id = str(item["id"])
        if chunk_id not in chunks:
            raise ValueError(
                f"Readable payload is corrupt: order references unknown chunk id {chunk_id!r}"
            )
        rebuilt_parts.append(chunks[chunk_id])
    rebuilt = "".join(rebuilt_parts)
    actual_sha256 = hashlib.sha256(rebuilt.encode("utf-8")).hexdigest()
    expected_sha256 = str(parsed["meta"]["sha256"])
    if actual_sha256 != expected_sha256:
        raise ValueError(f"Readable payload hash mismatch: expected {expected_sha256}, got {actual_sha256}")
    return rebuilt


def decompress_text_lossless(machine_text: str) -> str:
    codec, transform, sha256, payload = parse_lossless_machine_text(machine_text)
    compressed_bytes = base64.b85decode(payload.encode("ascii"))
    transformed_bytes = _DECOMPRESSORS[codec](compressed_bytes)
    raw_text = _restore_transform(transform, transformed_bytes)
    raw_bytes = raw_text.encode("utf-8")
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != sha256:
        raise ValueError(f"Lossless payload hash mismatch: expected {sha256}, got {actual_sha256}")
    return raw_text


def query_readable_compressed(machine_text: str, query: str, limit: int = 5) -> ReadableQueryResult:
    parsed = parse_readable_machine_text(machine_text)
    query_terms = set(_readable_terms(query))
    exact_phrases = _quoted_phrases(query)
    if not exact_phrases and len(query.strip()) >= 3:
        exact_phrases = [query.strip()]
    hits: list[ReadableQueryHit] = []

    for quote in parsed["quotes"]:
        text = str(quote["text"])
        score, reasons = _readable_match_score(text, query_terms, exact_phrases, prefix="quote")
        if score <= 0:
            continue
        hits.append(
            ReadableQueryHit(
                record_id=str(quote["id"]),
                record_type="QUOTE",
                text=text,
                score=score + 0.25,
                start=int(quote["start"]),
                end=int(quote["end"]),
                reasons=reasons,
            )
        )

    chunk_occurrences = _chunk_occurrence_lookup(parsed["order"])
    for chunk in parsed["chunks"]:
        text = str(chunk["text"])
        score, reasons = _readable_match_score(text, query_terms, exact_phrases, prefix="chunk")
        if score <= 0:
            continue
        first_occurrence = chunk_occurrences.get(str(chunk["id"]), [{}])[0]
        hits.append(
            ReadableQueryHit(
                record_id=str(chunk["id"]),
                record_type="CHUNK",
                text=text,
                score=score,
                start=int(first_occurrence["start"]) if "start" in first_occurrence else None,
                end=int(first_occurrence["end"]) if "end" in first_occurrence else None,
                reasons=reasons,
            )
        )

    hits = sorted(hits, key=lambda hit: (hit.score, -(hit.start or 0)), reverse=True)[:limit]
    return ReadableQueryResult(
        query=query,
        source_ref=str(parsed["meta"].get("source_ref", "")),
        sha256=str(parsed["meta"]["sha256"]),
        hits=hits,
    )


def benchmark_text_lossless(
    text: str,
    codec: str = "auto",
    transform: str = "auto",
    min_token_savings: float = 0.30,
    max_rounds: int = 4,
    tokenizer: str = "auto",
) -> LosslessBenchmarkResult:
    artifact, search_log, flags, stop_reason = _run_lossless_search(text, codec=codec, transform=transform, max_rounds=max_rounds, tokenizer=tokenizer)
    roundtrip_text = decompress_text_lossless(artifact.machine_text)
    result = LosslessBenchmarkResult(
        artifact=artifact,
        roundtrip_text=roundtrip_text,
        roundtrip_match=roundtrip_text == text,
        target_token_savings=min_token_savings,
        search_log=search_log,
        flags=flags,
        stop_reason=stop_reason,
    )
    if not result.roundtrip_match:
        result.flags.append("roundtrip_mismatch")
    if not result.meets_target:
        result.flags.append("target_not_met")
    return result


def render_lossless_benchmark_pretty(payload: dict[str, object]) -> str:
    artifact = payload.get("artifact", {})
    status = "PASS" if payload.get("passed") else "FAIL"
    roundtrip = "PASS" if payload.get("roundtrip_match") else "FAIL"
    target = float(payload.get("target_token_savings", 0.0))
    token_savings = float(artifact.get("token_savings_ratio", 0.0))
    lines = [
        f"Benchmark: {status}",
        f"Lossless roundtrip: {roundtrip}",
        f"Transform: {artifact.get('transform')}",
        f"Codec: {artifact.get('codec')}",
        f"Original tokens: {artifact.get('original_tokens')}",
        f"Machine tokens: {artifact.get('machine_tokens')}",
        f"Token savings: {token_savings:.1%}",
        f"Target savings: {target:.1%}",
        f"Intelligence per token gain: {float(artifact.get('intelligence_per_token_gain', 0.0)):.2f}x",
        f"Original bytes: {artifact.get('original_bytes')}",
        f"Machine bytes: {artifact.get('machine_bytes')}",
        f"SHA256: {artifact.get('sha256')}",
        f"Estimator: {artifact.get('token_estimator')}",
        f"Stop reason: {payload.get('stop_reason') or '(none)'}",
    ]
    flags = payload.get("flags", [])
    if flags:
        lines.append(f"Flags: {', '.join(str(flag) for flag in flags)}")
    search_log = payload.get("search_log", [])
    if search_log:
        lines.extend(["", "Search log:"])
        for attempt in search_log:
            attempt_flags = f" flags={','.join(attempt.get('flags', []))}" if attempt.get("flags") else ""
            lines.append(
                f"- iter={attempt.get('iteration')} transform={attempt.get('transform')} codec={attempt.get('codec')} "
                f"tokens={attempt.get('machine_tokens')} savings={float(attempt.get('token_savings_ratio', 0.0)):.1%} "
                f"status={attempt.get('status')}{attempt_flags}"
            )
    if "machine_text" in artifact:
        lines.extend(["", "Machine text:", str(artifact["machine_text"])])
    return "\n".join(lines)


def parse_lossless_machine_text(machine_text: str) -> tuple[str, str, str, str]:
    lines = [line.rstrip("\n") for line in machine_text.splitlines() if line.strip()]
    if not lines or lines[0] != LOSSLESS_MAGIC:
        raise ValueError(f"Expected {LOSSLESS_MAGIC} header")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if "=" not in line:
            raise ValueError(f"Invalid lossless payload line: {line}")
        key, value = line.split("=", 1)
        fields[key] = value
    codec = fields.get("c")
    transform = fields.get("t", "identity")
    sha256 = fields.get("h")
    payload = fields.get("p")
    if codec not in LOSSLESS_CODECS:
        raise ValueError(f"Unsupported or missing lossless codec: {codec}")
    if transform not in LOSSLESS_TRANSFORMS:
        raise ValueError(f"Unsupported or missing lossless transform: {transform}")
    if not sha256 or not payload:
        raise ValueError("Lossless machine text is missing required fields")
    return codec, transform, sha256, payload


def parse_readable_machine_text(machine_text: str) -> dict[str, object]:
    lines = [line.rstrip("\n") for line in machine_text.splitlines() if line.strip()]
    if not lines or lines[0] != READABLE_MAGIC:
        raise ValueError(f"Expected {READABLE_MAGIC} header")
    meta: dict[str, object] | None = None
    chunks: list[dict[str, object]] = []
    order: list[dict[str, object]] = []
    quotes: list[dict[str, object]] = []
    index: dict[str, object] = {}
    for line in lines[1:]:
        if "|" not in line:
            raise ValueError(f"Invalid readable payload line: {line}")
        kind, payload = line.split("|", 1)
        data = json.loads(payload)
        if kind == "META":
            meta = dict(data)
        elif kind == "CHUNK":
            chunks.append(dict(data))
        elif kind == "ORDER":
            order = [dict(item) for item in data.get("items", [])]
        elif kind == "QUOTE":
            quotes.append(dict(data))
        elif kind == "INDEX":
            index = dict(data)
        else:
            raise ValueError(f"Unsupported readable payload record: {kind}")
    if meta is None:
        raise ValueError("Readable machine text is missing META")
    if not chunks:
        raise ValueError("Readable machine text is missing CHUNK records")
    if not order:
        raise ValueError("Readable machine text is missing ORDER records")
    if not meta.get("sha256"):
        raise ValueError("Readable machine text is missing source hash")
    return {"meta": meta, "chunks": chunks, "order": order, "quotes": quotes, "index": index}


def lossless_benchmark_json(
    text: str,
    codec: str = "auto",
    transform: str = "auto",
    min_token_savings: float = 0.30,
    tokenizer: str = "auto",
    include_machine_text: bool = False,
) -> str:
    result = benchmark_text_lossless(text, codec=codec, transform=transform, min_token_savings=min_token_savings, tokenizer=tokenizer)
    return json.dumps(result.to_dict(include_machine_text=include_machine_text), indent=2)


def _run_lossless_search(
    text: str,
    codec: str = "auto",
    transform: str = "auto",
    max_rounds: int = 4,
    tokenizer: str = "auto",
) -> tuple[LosslessArtifact, list[LosslessAttempt], list[str], str]:
    codecs = [codec] if codec != "auto" else list(LOSSLESS_CODECS)
    transforms = [transform] if transform != "auto" else list(LOSSLESS_TRANSFORMS)
    invalid_codecs = [name for name in codecs if name not in LOSSLESS_CODECS]
    invalid_transforms = [name for name in transforms if name not in LOSSLESS_TRANSFORMS]
    if invalid_codecs:
        raise ValueError(f"Unsupported lossless codec: {invalid_codecs[0]}")
    if invalid_transforms:
        raise ValueError(f"Unsupported lossless transform: {invalid_transforms[0]}")

    search_space = [(transform_name, codec_name) for transform_name in transforms for codec_name in codecs]
    attempts: list[LosslessAttempt] = []
    flags: list[str] = []
    previous_ratio = 0.0
    best_artifact: LosslessArtifact | None = None
    best_key: tuple[int, int, int, str, str] | None = None
    iteration = 1
    remaining = search_space[:]
    stop_reason = "search space exhausted"

    while remaining and iteration <= max_rounds:
        improved_this_round = False
        round_best_artifact: LosslessArtifact | None = None
        round_best_key: tuple[int, int, int, str, str] | None = None
        round_best_index: int | None = None
        current_best_ratio = best_artifact.token_savings_ratio if best_artifact is not None else 0.0

        for index, (transform_name, codec_name) in enumerate(remaining):
            artifact = _compress_variant(text, transform_name, codec_name, tokenizer=tokenizer)
            candidate_key = _artifact_key(artifact)
            delta_vs_best = artifact.token_savings_ratio - current_best_ratio
            delta_vs_previous = artifact.token_savings_ratio - previous_ratio
            attempt_flags: list[str] = []
            status = "baseline"
            if delta_vs_previous < -0.02:
                attempt_flags.append("compression_regressed")
            if best_key is not None and candidate_key < best_key:
                status = "improved"
                improved_this_round = True
                if round_best_key is None or candidate_key < round_best_key:
                    round_best_artifact = artifact
                    round_best_key = candidate_key
                    round_best_index = index
            elif best_key is None:
                status = "improved"
                improved_this_round = True
                if round_best_key is None or candidate_key < round_best_key:
                    round_best_artifact = artifact
                    round_best_key = candidate_key
                    round_best_index = index
            elif delta_vs_best < -0.02:
                status = "regressed"
                attempt_flags.append("below_best")
            else:
                status = "flat"

            attempts.append(
                LosslessAttempt(
                    iteration=iteration,
                    transform=transform_name,
                    codec=codec_name,
                    transformed_bytes=artifact.transformed_bytes,
                    compressed_bytes=artifact.compressed_bytes,
                    machine_bytes=artifact.machine_bytes,
                    machine_tokens=artifact.machine_tokens,
                    token_savings_ratio=artifact.token_savings_ratio,
                    byte_savings_ratio=artifact.byte_savings_ratio,
                    delta_vs_best=delta_vs_best,
                    delta_vs_previous=delta_vs_previous,
                    status=status,
                    flags=attempt_flags,
                )
            )
            previous_ratio = artifact.token_savings_ratio

        if not improved_this_round or round_best_artifact is None or round_best_key is None:
            stop_reason = "no further improvement across known lossless rules"
            break

        best_artifact = round_best_artifact
        best_key = round_best_key
        flags.extend(flag for flag in _collect_round_flags(attempts, iteration) if flag not in flags)

        if round_best_index is not None:
            remaining.pop(round_best_index)
        if not remaining:
            stop_reason = "search space exhausted after selecting best candidate"
            break
        iteration += 1

    if best_artifact is None:
        raise ValueError("Lossless search did not produce any artifact")
    return best_artifact, attempts, flags, stop_reason


def _artifact_key(artifact: LosslessArtifact) -> tuple[int, int, int, str, str]:
    return (
        artifact.machine_tokens,
        artifact.machine_bytes,
        artifact.compressed_bytes,
        artifact.transform,
        artifact.codec,
    )


def _compress_variant(text: str, transform: str, codec: str, tokenizer: str = "auto") -> LosslessArtifact:
    transformed_bytes = _apply_transform(text, transform)
    compressed_bytes = _COMPRESSORS[codec](transformed_bytes)
    payload = base64.b85encode(compressed_bytes).decode("ascii")
    raw_bytes = text.encode("utf-8")
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    machine_text = "\n".join(
        [
            LOSSLESS_MAGIC,
            f"c={codec}",
            f"t={transform}",
            f"h={sha256}",
            f"p={payload}",
        ]
    )
    original_tokens, estimator = count_prompt_tokens(text, tokenizer=tokenizer)
    machine_tokens, _ = count_prompt_tokens(machine_text, tokenizer=tokenizer)
    return LosslessArtifact(
        codec=codec,
        transform=transform,
        machine_text=machine_text,
        sha256=sha256,
        original_bytes=len(raw_bytes),
        transformed_bytes=len(transformed_bytes),
        compressed_bytes=len(compressed_bytes),
        machine_bytes=len(machine_text.encode("utf-8")),
        original_tokens=original_tokens,
        machine_tokens=machine_tokens,
        token_estimator=estimator,
    )


def _approximate_prompt_tokens(text: str) -> int:
    if not text:
        return 0
    return int(math.ceil(len(text.encode("utf-8")) / 4))


def _resolve_token_counter(tokenizer: str) -> tuple[Callable[[str], int], str]:
    if tokenizer == "auto":
        try:
            encoder = _load_tiktoken_encoding("cl100k_base")
        except Exception:
            return _approximate_prompt_tokens, TOKEN_ESTIMATOR
        return lambda text: len(encoder.encode(text)), "tiktoken:cl100k_base"
    if tokenizer == TOKEN_ESTIMATOR:
        return _approximate_prompt_tokens, TOKEN_ESTIMATOR
    if tokenizer in TOKENIZER_CHOICES:
        encoder = _load_tiktoken_encoding(tokenizer)
        return lambda text: len(encoder.encode(text)), f"tiktoken:{tokenizer}"
    raise ValueError(f"Unsupported tokenizer: {tokenizer}")


@lru_cache(maxsize=8)
def _load_tiktoken_encoding(name: str):
    try:
        import tiktoken
    except ImportError as exc:
        raise RuntimeError("tiktoken is not installed. Install it or use the char4_approx tokenizer.") from exc
    try:
        return tiktoken.get_encoding(name)
    except ValueError as exc:
        raise ValueError(f"Unsupported tiktoken encoding: {name}") from exc


def _collect_round_flags(attempts: list[LosslessAttempt], iteration: int) -> list[str]:
    round_attempts = [attempt for attempt in attempts if attempt.iteration == iteration]
    if not round_attempts:
        return []
    flagged = [attempt for attempt in round_attempts if attempt.flags]
    flags: list[str] = []
    if flagged:
        flags.append(f"iteration_{iteration}_fluctuations")
    regressed = [attempt for attempt in round_attempts if attempt.status == "regressed"]
    if regressed:
        flags.append(f"iteration_{iteration}_regressions")
    return flags


def _apply_transform(text: str, transform: str) -> bytes:
    if transform == "identity":
        return text.encode("utf-8")
    if transform == "line_table":
        lines = text.splitlines(keepends=True)
        payload = _build_table_payload(lines)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if transform == "paragraph_table":
        blocks = _split_paragraph_blocks(text)
        payload = _build_table_payload(blocks)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raise ValueError(f"Unsupported lossless transform: {transform}")


def _restore_transform(transform: str, transformed_bytes: bytes) -> str:
    if transform == "identity":
        return transformed_bytes.decode("utf-8")
    data = json.loads(transformed_bytes.decode("utf-8"))
    chunks = data.get("chunks", [])
    order = data.get("order", [])
    return "".join(str(chunks[index]) for index in order)


def _build_table_payload(parts: list[str]) -> dict[str, object]:
    chunk_to_index: dict[str, int] = {}
    chunks: list[str] = []
    order: list[int] = []
    for part in parts:
        chunk_index = chunk_to_index.get(part)
        if chunk_index is None:
            chunk_index = len(chunks)
            chunk_to_index[part] = chunk_index
            chunks.append(part)
        order.append(chunk_index)
    return {"chunks": chunks, "order": order}


def _split_paragraph_blocks(text: str) -> list[str]:
    parts = re.split(r"(\n\s*\n)", text)
    return [part for part in parts if part]


def _resolved_readable_granularity(text: str, granularity: str) -> str:
    if granularity != "auto":
        return granularity
    if "\n\n" in text:
        return "paragraph"
    if "\n" in text:
        return "line"
    return "chunk"


def _split_readable_parts(text: str, granularity: str) -> list[str]:
    resolved = _resolved_readable_granularity(text, granularity)
    if resolved == "line":
        return text.splitlines(keepends=True) or [""]
    if resolved == "paragraph":
        return _split_paragraph_blocks(text) or [""]
    return _split_fixed_readable_chunks(text)


def _split_fixed_readable_chunks(text: str, target_chars: int = 320) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_chars)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + max(80, target_chars // 3):
                end = boundary + (2 if text[boundary : boundary + 2] == ". " else 1)
        chunks.append(text[start:end])
        start = end
    return chunks


def _readable_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9_:-]+", text.lower()):
        terms.append(token)
        stripped = token.strip(":-")
        if stripped and stripped != token:
            terms.append(stripped)
    return terms


def _structural_quote_spans(text: str) -> list[dict[str, object]]:
    """Shared structural span extraction used by the readable compiler and the
    benchmark gate verifier. Both must observe identical text/value/start/end
    records or the readable family's direct_quote_match invariant fails — so
    extraction lives in exactly one place."""
    spans: list[dict[str, object]] = []
    for match in re.finditer(r'"([^"]*)"', text):
        spans.append(
            {
                "text": match.group(0),
                "value": match.group(1),
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in re.finditer(r'(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$', text):
        title = match.group(2).strip()
        spans.append(
            {
                "text": f"heading:{title}",
                "value": title,
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in re.finditer(r'(?m)^\|([^|\n]+)\|([^|\n]+)\|[ \t]*$', text):
        col1 = match.group(1).strip()
        col2 = match.group(2).strip()
        if not col1 or not col2:
            continue
        if re.fullmatch(r'[\s\-:]+', col1) or re.fullmatch(r'[\s\-:]+', col2):
            continue
        spans.append(
            {
                "text": f"cell:{col1}={col2}",
                "value": f"{col1}={col2}",
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in re.finditer(r'\[([A-Za-z][A-Za-z0-9_]*\d+[A-Za-z0-9_]*)\]', text):
        spans.append(
            {
                "text": f"citation:{match.group(0)}",
                "value": match.group(1),
                "start": match.start(),
                "end": match.end(),
            }
        )
    for line_match in re.finditer(r'(?m)^\[([^\]\n]+)\][ \t]+(.+?)[ \t]*$', text):
        rest = line_match.group(2)
        rest_start = line_match.start(2)
        cursor = rest_start
        for piece in re.split(r'(\. )', rest):
            if not piece:
                continue
            if piece == ". ":
                cursor += len(piece)
                continue
            phrase = piece.strip().rstrip(".").strip()
            piece_start = cursor
            piece_end = cursor + len(piece)
            cursor = piece_end
            if not phrase:
                continue
            spans.append(
                {
                    "text": f"ref:{phrase}",
                    "value": phrase,
                    "start": piece_start,
                    "end": piece_end,
                }
            )
    return spans


def _extract_readable_quotes(text: str, order: list[dict[str, object]], chunk_text_by_id: dict[str, str]) -> list[dict[str, object]]:
    quotes: list[dict[str, object]] = []
    for span in _structural_quote_spans(text):
        chunk_id = _chunk_id_for_span(int(span["start"]), order)
        quotes.append(
            {
                "id": f"q:{len(quotes) + 1}",
                "text": span["text"],
                "value": span["value"],
                "start": span["start"],
                "end": span["end"],
                "chunk": chunk_id,
                "chunk_text_sha256": hashlib.sha256(chunk_text_by_id.get(chunk_id, "").encode("utf-8")).hexdigest() if chunk_id else None,
            }
        )
    return quotes


def _chunk_id_for_span(start: int, order: list[dict[str, object]]) -> str | None:
    for item in order:
        if int(item["start"]) <= start < int(item["end"]):
            return str(item["id"])
    return None


def _build_readable_term_index(chunks: list[dict[str, object]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for chunk in chunks:
        chunk_id = str(chunk["id"])
        for term in chunk.get("terms", []):
            postings = index.setdefault(str(term), [])
            if chunk_id not in postings:
                postings.append(chunk_id)
    return index


def _quoted_phrases(query: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r'"([^"]+)"', query)]


def _readable_match_score(text: str, query_terms: set[str], exact_phrases: list[str], prefix: str) -> tuple[float, list[str]]:
    lowered = text.lower()
    reasons: list[str] = []
    score = 0.0
    for phrase in exact_phrases:
        phrase = phrase.strip()
        if phrase and phrase.lower() in lowered:
            score += 1.0
            reasons.append(f"{prefix}_exact_phrase")
    terms = set(_readable_terms(text))
    if query_terms and terms:
        overlap = query_terms & terms
        if overlap:
            score += len(overlap) / max(len(query_terms), 1)
            reasons.append(f"{prefix}_term_overlap={len(overlap)}")
    return score, reasons


def _chunk_occurrence_lookup(order: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    lookup: dict[str, list[dict[str, object]]] = {}
    for item in order:
        lookup.setdefault(str(item["id"]), []).append(item)
    return lookup
