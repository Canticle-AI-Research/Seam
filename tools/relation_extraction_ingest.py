"""Build one fresh LoCoMo scope for grounded-REL qualification.

This is an explicit research lane, not a runtime default.  The command accepts
only a pinned local Ollama extractor, stores into a new SQLite database, and
prints a content-free build/qualification receipt.  The extraction cache is a
separate content-addressed SQLite file so a failed or interrupted attempt can
restart against a *different fresh output database* without paying again for
completed turns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.runner import _group_cases
from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import _format_turn
from benchmarks.external.locomo.run import _locomo_scope_id
from seam_runtime.agent_memory import namespace_ingest_batch, stable_document_id
from seam_runtime.derived_fact_context import CachedExtractor
from seam_runtime.mirl import RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.nl import compile_nl
from seam_runtime.nl_extract import Extraction, OllamaExtractor
from seam_runtime.runtime import SeamRuntime
from tools.relation_extraction_qualification import (
    _canonical_digest,
    qualify_relation_extraction,
    raw_turn_identity,
)

REPORT_SCHEMA = "relation-extraction-ingest/1"
RELATION_POLICY = "grounded-rel/1"
EXTRACTOR_CONFIG_SCHEMA = "grounded-rel-extractor-config/1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MODEL_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})", re.IGNORECASE)


class RelationIngestError(RuntimeError):
    """Expected fail-closed configuration or integrity error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RelationIngestConfig:
    dataset_path: Path
    dataset_sha256: str
    scope_id: str
    output_db: Path
    cache_path: Path
    ollama_model: str
    ollama_model_digest: str
    ollama_host: str
    timeout: float
    num_predict: int
    num_ctx: int = 2048
    seed: int = 7
    report_path: Path | None = None
    review_template_path: Path | None = None


@dataclass(frozen=True)
class _PlannedTurn:
    turn: ConversationTurn
    text: str
    source_ref: str


class _GroundedRelationPolicyExtractor:
    """Freeze one extractor configuration and label the REL-only policy."""

    def __init__(self, extractor: object) -> None:
        self._extractor = extractor
        self._metadata = self._live_metadata()
        self._metadata = {
            "schema": EXTRACTOR_CONFIG_SCHEMA,
            "relation_policy": RELATION_POLICY,
            "extractor": self._metadata,
        }

    def _live_metadata(self) -> dict[str, object]:
        metadata = getattr(self._extractor, "config_metadata", None)
        if not callable(metadata):
            raise RelationIngestError("extractor_metadata_missing")
        payload = metadata()
        if not isinstance(payload, dict) or not payload:
            raise RelationIngestError("extractor_metadata_missing")
        try:
            return json.loads(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )
        except (TypeError, ValueError) as exc:
            raise RelationIngestError("extractor_metadata_invalid") from exc

    def config_metadata(self) -> dict[str, object]:
        return json.loads(
            json.dumps(self._metadata, sort_keys=True, separators=(",", ":"))
        )

    def extract(self, text: str) -> Extraction:
        live = self._live_metadata()
        if live != self._metadata["extractor"]:
            raise RelationIngestError("extractor_configuration_changed")
        extract = getattr(self._extractor, "extract", None)
        if not callable(extract):
            raise RelationIngestError("extractor_method_missing")
        result = extract(text)
        if not isinstance(result, Extraction):
            raise RelationIngestError("extractor_result_invalid")
        return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_loopback_origin(host: str) -> str:
    parsed = urlsplit(host)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.hostname.casefold() not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RelationIngestError("ollama_host_not_credential_free_loopback")
    return host


def _resolved_paths(config: RelationIngestConfig) -> tuple[Path, Path, Path]:
    try:
        dataset = config.dataset_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RelationIngestError("dataset_not_file") from exc
    output = config.output_db.expanduser().resolve(strict=False)
    cache = config.cache_path.expanduser().resolve(strict=False)
    if not dataset.is_file():
        raise RelationIngestError("dataset_not_file")
    if output in {dataset, cache} or cache == dataset:
        raise RelationIngestError("input_output_path_collision")
    _assert_output_fresh(output)
    if output.parent.exists() and not output.parent.is_dir():
        raise RelationIngestError("output_parent_not_directory")
    if cache.exists() and not cache.is_file():
        raise RelationIngestError("cache_not_file")
    if cache.parent.exists() and not cache.parent.is_dir():
        raise RelationIngestError("cache_parent_not_directory")
    artifacts = [
        path.expanduser().resolve(strict=False)
        for path in (config.report_path, config.review_template_path)
        if path is not None
    ]
    if len(set(artifacts)) != len(artifacts):
        raise RelationIngestError("report_review_path_collision")
    reserved = {
        dataset,
        output,
        cache,
        Path(f"{output}-wal"),
        Path(f"{output}-shm"),
        Path(f"{cache}-wal"),
        Path(f"{cache}-shm"),
    }
    for artifact in artifacts:
        if artifact in reserved:
            raise RelationIngestError("artifact_path_collision")
        if artifact.exists() and not artifact.is_file():
            raise RelationIngestError("artifact_path_not_file")
        if artifact.parent.exists() and not artifact.parent.is_dir():
            raise RelationIngestError("artifact_parent_not_directory")
    return dataset, output, cache


def _assert_output_fresh(output: Path) -> None:
    for candidate in (
        output,
        Path(f"{output}-wal"),
        Path(f"{output}-shm"),
    ):
        if candidate.exists():
            raise RelationIngestError("output_database_not_fresh")


def _reserve_output(output: Path) -> None:
    """Atomically claim the fresh output path before SQLite opens it."""

    _assert_output_fresh(output)
    try:
        with output.open("x", encoding="utf-8"):
            pass
    except FileExistsError as exc:
        raise RelationIngestError("output_database_not_fresh") from exc


def _validate_config(config: RelationIngestConfig) -> tuple[Path, Path, Path]:
    if _SHA256.fullmatch(config.dataset_sha256) is None:
        raise RelationIngestError("dataset_sha256_invalid")
    if not config.scope_id or config.scope_id != config.scope_id.strip():
        raise RelationIngestError("scope_id_invalid")
    if not config.ollama_model or config.ollama_model != config.ollama_model.strip():
        raise RelationIngestError("ollama_model_invalid")
    if ":cloud" in config.ollama_model.casefold():
        raise RelationIngestError("cloud_backed_ollama_model_rejected")
    _normalized_model_digest(config.ollama_model_digest)
    if not math.isfinite(config.timeout) or config.timeout <= 0:
        raise RelationIngestError("timeout_invalid")
    if config.num_predict <= 0 or config.num_ctx <= 0:
        raise RelationIngestError("generation_bounds_invalid")
    _validate_loopback_origin(config.ollama_host)
    paths = _resolved_paths(config)
    if _sha256_file(paths[0]) != config.dataset_sha256:
        raise RelationIngestError("dataset_sha256_mismatch")
    return paths


def _normalized_model_digest(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise RelationIngestError("ollama_model_digest_invalid")
    match = _MODEL_DIGEST.fullmatch(value)
    if match is None:
        raise RelationIngestError("ollama_model_digest_invalid")
    return match.group(1).lower()


def _atomic_write_json(path: Path, payload: object) -> None:
    resolved = path.expanduser().resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, resolved)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _select_turns(dataset: Path, scope_id: str) -> tuple[_PlannedTurn, ...]:
    groups = _group_cases(load_locomo_cases(dataset), _locomo_scope_id)
    group = groups.get(scope_id)
    if not group:
        raise RelationIngestError("scope_id_not_found")
    conversations = {case.conversation for case in group}
    if len(conversations) != 1:
        raise RelationIngestError("scope_conversation_mismatch")
    planned: list[_PlannedTurn] = []
    source_refs: set[str] = set()
    for turn in group[0].conversation:
        text = _format_turn(turn)
        turn_hash = hashlib.sha256(text.encode()).hexdigest()[:12]
        source_ref = f"locomo:{scope_id}:turn:{turn_hash}"
        if source_ref in source_refs:
            # Keep the canonical LoCoMo adapter source-ref contract exact.
            # Repeated canonical turns cannot be disambiguated without also
            # changing that contract, so refuse the corpus before extraction.
            raise RelationIngestError("canonical_source_ref_collision")
        source_refs.add(source_ref)
        planned.append(
            _PlannedTurn(
                turn=turn,
                text=text,
                source_ref=source_ref,
            )
        )
    if not planned:
        raise RelationIngestError("scope_has_no_turns")
    return tuple(planned)


def _expected_raw_identity(
    planned: Iterable[_PlannedTurn],
    *,
    namespace: str,
) -> dict[str, object]:
    identities: list[dict[str, object]] = []
    record_ids: set[str] = set()
    for item in planned:
        batch = namespace_ingest_batch(
            compile_nl(
                item.text,
                source_ref=item.source_ref,
                ns=namespace,
                scope="thread",
                speaker=item.turn.speaker,
                source_timestamp=item.turn.timestamp or "",
                extractor=None,
                derived_fact_policy=None,
                allow_env_extractor=False,
            ),
            stable_document_id(item.source_ref, item.text),
        )
        raw_records = batch.kind(RecordKind.RAW)
        if len(raw_records) != 1:
            raise RelationIngestError("source_compilation_raw_cardinality")
        raw = raw_records[0]
        if raw.id in record_ids:
            raise RelationIngestError("source_compilation_raw_collision")
        record_ids.add(raw.id)
        identities.append(
            {
                "database_index": 0,
                "record_id": raw.id,
                "namespace": raw.ns,
                "scope": raw.scope,
                "source_ref": raw.attrs.get("source_ref"),
                "content_digest": hashlib.sha256(
                    str(raw.attrs.get("content") or "").encode()
                ).hexdigest(),
            }
        )
    identities.sort(key=lambda item: str(item["record_id"]))
    return {"turns": len(identities), "digest": _canonical_digest(identities)}


def _default_extractor(config: RelationIngestConfig) -> OllamaExtractor:
    return OllamaExtractor(
        model=config.ollama_model,
        host=config.ollama_host,
        timeout=config.timeout,
        temperature=0.0,
        seed=config.seed,
        num_ctx=config.num_ctx,
        num_predict=config.num_predict,
        strict=True,
        model_digest=_normalized_model_digest(config.ollama_model_digest),
    )


def build_relation_qualification_corpus(
    config: RelationIngestConfig,
    *,
    extractor: object | None = None,
    embedding_model: object | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    """Build and immediately audit one pinned LoCoMo conversation scope."""

    dataset, output, cache = _validate_config(config)
    planned = _select_turns(dataset, config.scope_id)
    if _sha256_file(dataset) != config.dataset_sha256:
        raise RelationIngestError("dataset_changed_during_source_compilation")
    namespace = f"locomo:{config.scope_id}"
    expected_identity = _expected_raw_identity(planned, namespace=namespace)

    default_extractor = extractor is None
    base_extractor = extractor if extractor is not None else _default_extractor(config)
    validate = getattr(base_extractor, "validate_for_derived_facts", None)
    if callable(validate):
        validate()
    policy_extractor = _GroundedRelationPolicyExtractor(base_extractor)
    extractor_metadata = policy_extractor.config_metadata()
    config_fingerprint = _canonical_json_sha256(extractor_metadata)
    cached = CachedExtractor(
        policy_extractor,
        cache_path=cache,
        config_fingerprint=config_fingerprint,
        expected_metadata=extractor_metadata,
    )
    scoped_extractor = cached.bind(namespace)

    output.parent.mkdir(parents=True, exist_ok=True)
    _reserve_output(output)
    runtime = SeamRuntime(
        output,
        embedding_model=embedding_model or HashEmbeddingModel(),
        pgvector_dsn=None,
        allow_pgvector_env=False,
    )
    try:
        total = len(planned)
        for index, item in enumerate(planned, start=1):
            runtime.ingest_conversation_turn(
                text=item.text,
                source_ref=item.source_ref,
                ns=namespace,
                scope="thread",
                persist=True,
                extractor=scoped_extractor,
                speaker=item.turn.speaker,
                source_timestamp=item.turn.timestamp or "",
                derived_fact_policy=None,
                allow_env_extractor=False,
            )
            if progress is not None:
                progress(index, total)
    finally:
        runtime.close()

    observed_identity = raw_turn_identity([output])
    if observed_identity != expected_identity:
        raise RelationIngestError("stored_raw_identity_mismatch")
    if _sha256_file(dataset) != config.dataset_sha256:
        raise RelationIngestError("dataset_changed_during_ingest")

    qualification = qualify_relation_extraction(
        [output],
        expected_turns=int(expected_identity["turns"]),
        expected_raw_digest=str(expected_identity["digest"]),
    )
    database_sha256 = _sha256_file(output)
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "status": "built",
        "provider": (
            "ollama-loopback-local/1"
            if default_extractor
            else "injected-extractor-unattested/1"
        ),
        "cloud_calls": 0 if default_extractor else None,
        "dataset_sha256": config.dataset_sha256,
        "scope_id": config.scope_id,
        "model": config.ollama_model,
        "model_digest": _normalized_model_digest(config.ollama_model_digest),
        "raw_identity": expected_identity,
        "database_sha256": database_sha256,
        "relation_policy": RELATION_POLICY,
        "extractor_config_fingerprint": config_fingerprint,
        "cache": {"hits": cached.hits, "misses": cached.misses},
        "qualification": qualification.report,
    }
    report["integrity_sha256"] = _canonical_json_sha256(report)
    if config.review_template_path is not None:
        _atomic_write_json(
            config.review_template_path,
            qualification.review_template,
        )
    if config.report_path is not None:
        _atomic_write_json(config.report_path, report)
    return report


def _progress_printer() -> Callable[[int, int], None]:
    last_bucket = -1

    def emit(done: int, total: int) -> None:
        nonlocal last_bucket
        bucket = min(20, (done * 20) // total)
        if done == total or bucket > last_bucket:
            last_bucket = bucket
            print(f"[relation-ingest] {done}/{total}", file=sys.stderr, flush=True)

    return emit


def _parse_args(argv: list[str] | None) -> RelationIngestConfig:
    parser = argparse.ArgumentParser(
        description="Build one fresh local-only LoCoMo REL qualification database"
    )
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--cache-path", type=Path, required=True)
    parser.add_argument("--ollama-model", required=True)
    parser.add_argument("--ollama-model-digest", required=True)
    parser.add_argument("--ollama-host", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--num-predict", type=int, required=True)
    parser.add_argument("--num-ctx", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--review-template", type=Path)
    args = parser.parse_args(argv)
    return RelationIngestConfig(
        dataset_path=args.dataset_path,
        dataset_sha256=args.dataset_sha256,
        scope_id=args.scope_id,
        output_db=args.output_db,
        cache_path=args.cache_path,
        ollama_model=args.ollama_model,
        ollama_model_digest=args.ollama_model_digest,
        ollama_host=args.ollama_host,
        timeout=args.timeout,
        num_predict=args.num_predict,
        num_ctx=args.num_ctx,
        seed=args.seed,
        report_path=args.report_path,
        review_template_path=args.review_template,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        report = build_relation_qualification_corpus(
            _parse_args(argv),
            progress=_progress_printer(),
        )
    except RelationIngestError as exc:
        print(
            json.dumps(
                {"schema": REPORT_SCHEMA, "status": "failed", "error": exc.code},
                sort_keys=True,
            )
        )
        return 2
    except Exception as exc:  # never echo content-bearing provider exceptions
        print(
            json.dumps(
                {
                    "schema": REPORT_SCHEMA,
                    "status": "failed",
                    "error": f"unexpected_{type(exc).__name__}",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
