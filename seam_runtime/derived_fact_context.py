from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mirl import MIRLRecord, RecordKind, Status
from .nl_extract import (
    ExtractedClaim,
    ExtractedEntity,
    Extraction,
    Extractor,
    GroundedSpan,
    OllamaExtractor,
    grounded_sro_is_coherent,
)

DERIVED_FACTS_OFF = "off"
GROUNDED_CLM_V1 = "grounded-clm/1"
GROUNDED_CLM_V2 = "grounded-clm/2"
GROUNDED_CLM_POLICIES = frozenset({GROUNDED_CLM_V1, GROUNDED_CLM_V2})
DERIVED_FACTS_POLICIES = frozenset({DERIVED_FACTS_OFF}) | GROUNDED_CLM_POLICIES
DERIVED_FACTS_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DERIVED_FACTS_EMBEDDING_REVISION = (
    "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
)
DERIVED_FACTS_EMBEDDING_CONFIG = {
    "provider": "sentence-transformers-local/1",
    "model": DERIVED_FACTS_EMBEDDING_MODEL,
    "revision": DERIVED_FACTS_EMBEDDING_REVISION,
    "name": (
        f"st:{DERIVED_FACTS_EMBEDDING_MODEL}"
        f"@{DERIVED_FACTS_EMBEDDING_REVISION}"
    ),
    "dimension": 384,
    "normalization": "seam-model-wrapper/1",
    "local_files_only": True,
}

_CONFIG_SCHEMA = "seam-derived-facts-config/1"
_CACHE_SCHEMA = "seam-derived-facts-cache/2"
_SPEAKER_ATTRIBUTION_VERSION = "first-person-speaker/3"
_COMPILER_POLICY_VERSION = "grounded-clm-compiler/3"
_SPLICE_POLICY_VERSION = "raw-prefix-floor/2"
_FACT_RENDER_VERSION = "SEAM-FACT/1"
_SINGULAR_FIRST_PERSON = frozenset({"i", "me", "my", "mine", "myself"})
_ISO_TIMESTAMP = re.compile(
    r"^(?:|\d{4}-\d{2}-\d{2}(?:[Tt ][0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.\d+)?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?)$"
)
_LOCOMO_TIMESTAMP = re.compile(
    r"^(?:1[0-2]|[1-9]):[0-5][0-9]\s+(?:am|pm)\s+on\s+"
    r"(?:3[01]|[12][0-9]|[1-9])\s+[A-Za-z]+,\s+\d{4}$",
    flags=re.IGNORECASE,
)
_PROPOSITION_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
_SENTENCE_PUNCTUATION = frozenset(".!?")


def resolve_derived_facts_policy(value: str | None = None) -> str:
    policy = (
        value
        if value is not None
        else os.environ.get("SEAM_DERIVED_FACTS_POLICY", DERIVED_FACTS_OFF)
    )
    policy = str(policy).strip().lower() or DERIVED_FACTS_OFF
    if policy not in DERIVED_FACTS_POLICIES:
        raise ValueError(f"unsupported derived-facts policy {policy!r}")
    return policy


def is_singular_first_person(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().casefold() in _SINGULAR_FIRST_PERSON


def canonical_turn_prefix_end(
    source_text: str,
    *,
    speaker: object,
    timestamp: object,
) -> int | None:
    """Validate and return the end of the exact LoCoMo turn envelope."""

    if not isinstance(speaker, str) or not isinstance(timestamp, str):
        return None
    candidate = speaker.strip()
    resolved_timestamp = timestamp.strip()
    if (
        not candidate
        or len(candidate) > 64
        or len(resolved_timestamp) > 64
        or any(char in candidate for char in "\r\n[]")
        or any(char in resolved_timestamp for char in "\r\n[]")
        or (
            _ISO_TIMESTAMP.fullmatch(resolved_timestamp) is None
            and _LOCOMO_TIMESTAMP.fullmatch(resolved_timestamp) is None
        )
    ):
        return None
    prefix = f"[{candidate} {resolved_timestamp}]"
    if not source_text.startswith(prefix):
        return None
    prefix_end = len(prefix)
    if (
        prefix_end < len(source_text)
        and not source_text[prefix_end].isspace()
    ):
        return None
    while (
        prefix_end < len(source_text)
        and source_text[prefix_end].isspace()
    ):
        prefix_end += 1
    return prefix_end


def segment_propositions(text: str) -> list[tuple[str, int, int]]:
    """Return the compiler's exact proposition text and source bounds."""

    result: list[tuple[str, int, int]] = []

    def emit(start: int, end: int) -> None:
        segment = text[start:end]
        lead = len(segment) - len(segment.lstrip())
        trimmed = segment.strip()
        if trimmed and _PROPOSITION_WORD.search(trimmed):
            real_start = start + lead
            result.append(
                (
                    text[real_start:real_start + len(trimmed)],
                    real_start,
                    real_start + len(trimmed),
                )
            )

    length = len(text)
    cursor = 0
    index = 0
    while index < length:
        if text[index] in _SENTENCE_PUNCTUATION:
            run_end = index
            while (
                run_end < length
                and text[run_end] in _SENTENCE_PUNCTUATION
            ):
                run_end += 1
            if run_end >= length or text[run_end].isspace():
                emit(cursor, run_end)
                cursor = run_end
            index = run_end
        else:
            index += 1
    if cursor < length:
        emit(cursor, length)
    if not result:
        emit(0, length)
    return result


def _extractor_metadata(extractor: Extractor) -> dict[str, object]:
    metadata = getattr(extractor, "config_metadata", None)
    if callable(metadata):
        payload = metadata()
        if isinstance(payload, dict) and payload:
            try:
                encoded = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "derived-facts extractor metadata must be JSON-serializable"
                ) from exc
            return json.loads(encoded)
    raise ValueError(
        "grounded-clm/1 requires nonempty extractor config_metadata()"
    )


@dataclass(frozen=True)
class DerivedFactsConfig:
    policy: str
    fingerprint: str
    payload: dict[str, object]
    cache_path: str | None = None

    @property
    def enabled(self) -> bool:
        return self.policy in GROUNDED_CLM_POLICIES

    def manifest(self) -> dict[str, object]:
        return {
            "schema": _CONFIG_SCHEMA,
            "fingerprint": self.fingerprint,
            "config": self.payload,
        }


@dataclass
class DerivedFactsRuntime:
    config: DerivedFactsConfig
    extractor: Extractor | None


def configure_derived_facts(
    db_root: str | Path,
    *,
    policy: str | None = None,
    extractor: Extractor | None = None,
    cache_path: str | Path | None = None,
) -> DerivedFactsRuntime:
    resolved = resolve_derived_facts_policy(policy)
    if resolved == DERIVED_FACTS_OFF:
        _refuse_enriched_store_on_off_path(Path(db_root))
        payload = {"schema": _CONFIG_SCHEMA, "policy": DERIVED_FACTS_OFF}
        return DerivedFactsRuntime(
            config=DerivedFactsConfig(
                policy=DERIVED_FACTS_OFF,
                fingerprint=_fingerprint(payload),
                payload=payload,
            ),
            extractor=None,
        )

    resolved_extractor = extractor or OllamaExtractor(strict=True)
    if str(os.environ.get("SEAM_PGVECTOR_DSN") or "").strip():
        raise RuntimeError(
            "grounded-clm/1 requires SEAM_PGVECTOR_DSN to be unset so "
            "baseline and candidate use isolated SQLite vectors"
        )
    embedding_provider = str(
        os.environ.get("SEAM_EMBEDDING_PROVIDER") or "hash"
    ).strip().lower()
    if embedding_provider not in {"hash", "local", "deterministic"}:
        raise RuntimeError(
            "grounded-clm/1 requires a local benchmark embedding contract; "
            "unset SEAM_EMBEDDING_PROVIDER or set it to hash/local"
        )
    if isinstance(resolved_extractor, OllamaExtractor):
        resolved_extractor.validate_for_derived_facts()
    root = Path(db_root)
    resolved_cache = (
        Path(cache_path)
        if cache_path is not None
        else root / ".derived-facts-cache.sqlite3"
    )
    cache_identity = (
        str(resolved_cache.expanduser().resolve())
        if cache_path is not None
        else ".derived-facts-cache.sqlite3"
    )
    extractor_metadata = _extractor_metadata(resolved_extractor)
    payload = {
        "schema": _CONFIG_SCHEMA,
        "policy": resolved,
        "compiler_policy_version": _COMPILER_POLICY_VERSION,
        "speaker_attribution_version": _SPEAKER_ATTRIBUTION_VERSION,
        "fact_render_version": _FACT_RENDER_VERSION,
        "splice_policy_version": _SPLICE_POLICY_VERSION,
        "cache_schema": _CACHE_SCHEMA,
        "cache_identity": cache_identity,
        "vector_backend": "sqlite-local/1",
        "embedding": dict(DERIVED_FACTS_EMBEDDING_CONFIG),
        "extractor": extractor_metadata,
    }
    fingerprint = _fingerprint(payload)
    resumed = _write_or_validate_manifest(root, payload, fingerprint)
    if resumed and not resolved_cache.is_file():
        raise RuntimeError(
            "derived-facts extraction cache is missing from the manifested "
            f"shadow store: {resolved_cache}"
        )
    cached = CachedExtractor(
        resolved_extractor,
        cache_path=resolved_cache,
        config_fingerprint=fingerprint,
        expected_metadata=extractor_metadata,
    )
    return DerivedFactsRuntime(
        config=DerivedFactsConfig(
            policy=resolved,
            fingerprint=fingerprint,
            payload=payload,
            cache_path=str(resolved_cache),
        ),
        extractor=cached,
    )


def _refuse_enriched_store_on_off_path(root: Path) -> None:
    """Prevent a rich candidate store from masquerading as the floor baseline."""

    manifest_path = root / ".seam-derived-facts.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        configured_policy = manifest["config"]["policy"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"invalid derived-facts store manifest: {manifest_path}"
        ) from exc
    if configured_policy != DERIVED_FACTS_OFF:
        raise RuntimeError(
            "the derived-facts off baseline cannot reuse an enriched shadow "
            f"store: {manifest_path}"
        )


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_or_validate_manifest(
    root: Path,
    payload: dict[str, object],
    fingerprint: str,
) -> bool:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / ".seam-derived-facts.json"
    expected = {
        "schema": _CONFIG_SCHEMA,
        "fingerprint": fingerprint,
        "config": payload,
    }
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"invalid derived-facts store manifest: {manifest_path}"
            ) from exc
        if existing != expected:
            raise RuntimeError(
                "derived-facts configuration does not match the existing "
                f"shadow store manifest at {manifest_path}"
            )
        return True

    warm_databases = sorted(
        path
        for pattern in ("*.db", "*.db-wal", "*.db-shm")
        for path in root.glob(pattern)
        if path.is_file() and path.stat().st_size > 0
    )
    if warm_databases:
        raise RuntimeError(
            "grounded-clm/1 requires a fresh shadow store; found existing "
            f"database {warm_databases[0]}"
        )

    body = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=root,
        prefix=".seam-derived-facts.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(body)
        temp_path = Path(handle.name)
    os.replace(temp_path, manifest_path)
    return False


class CachedExtractor:
    """Content-addressed replay cache for one immutable extractor configuration."""

    def __init__(
        self,
        extractor: Extractor,
        *,
        cache_path: str | Path,
        config_fingerprint: str,
        expected_metadata: dict[str, object],
    ) -> None:
        self.extractor = extractor
        self.cache_path = Path(cache_path)
        self.config_fingerprint = config_fingerprint
        self._expected_metadata = json.loads(
            json.dumps(
                expected_metadata,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        self.hits = 0
        self.misses = 0
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def config_metadata(self) -> dict[str, object]:
        return json.loads(
            json.dumps(
                self._expected_metadata,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def _validate_extractor_config(self) -> None:
        if _extractor_metadata(self.extractor) != self._expected_metadata:
            raise RuntimeError(
                "derived-facts extractor configuration changed after setup"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.cache_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma busy_timeout=30000")
        connection.execute("pragma journal_mode=WAL")
        return connection

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    create table if not exists derived_fact_cache (
                        cache_key text primary key,
                        config_fingerprint text not null,
                        source_hash text not null,
                        payload_json text not null
                    )
                    """
                )
                connection.execute(
                    """
                    create table if not exists derived_fact_cache_owners (
                        cache_key text not null,
                        owner text not null,
                        primary key (cache_key, owner)
                    )
                    """
                )
                connection.execute(
                    """
                    create index if not exists
                    idx_derived_fact_cache_owners_owner
                    on derived_fact_cache_owners(owner)
                    """
                )

    def bind(self, owner: str) -> ScopedCachedExtractor:
        candidate = str(owner).strip()
        if not candidate:
            raise ValueError("derived-facts cache owner must be nonempty")
        return ScopedCachedExtractor(self, candidate)

    def _record_owner(self, cache_key: str, owner: str | None) -> None:
        if owner is None:
            return
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    insert or ignore into derived_fact_cache_owners
                    (cache_key, owner)
                    values (?, ?)
                    """,
                    (cache_key, owner),
                )

    def extract(
        self,
        text: str,
        *,
        owner: str | None = None,
    ) -> Extraction:
        self._validate_extractor_config()
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        cache_key = hashlib.sha256(
            f"{self.config_fingerprint}\0{source_hash}".encode()
        ).hexdigest()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                select payload_json
                from derived_fact_cache
                where cache_key = ? and config_fingerprint = ?
                """,
                (cache_key, self.config_fingerprint),
            ).fetchone()
        if row is not None:
            self.hits += 1
            self._record_owner(cache_key, owner)
            return _extraction_from_dict(json.loads(row["payload_json"]))

        self.misses += 1
        extraction = self.extractor.extract(text)
        if not isinstance(extraction, Extraction):
            raise TypeError("derived-facts extractor must return Extraction")
        payload_json = json.dumps(
            _extraction_to_dict(extraction),
            sort_keys=True,
            separators=(",", ":"),
        )
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    insert or replace into derived_fact_cache
                    (cache_key, config_fingerprint, source_hash, payload_json)
                    values (?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        self.config_fingerprint,
                        source_hash,
                        payload_json,
                    ),
                )
                if owner is not None:
                    connection.execute(
                        """
                        insert or ignore into derived_fact_cache_owners
                        (cache_key, owner)
                        values (?, ?)
                        """,
                        (cache_key, owner),
                    )
        return extraction

    def purge_owner(self, owner: str) -> None:
        """Forget one scope and remove cache rows no remaining scope owns."""

        candidate = str(owner).strip()
        if not candidate:
            raise ValueError("derived-facts cache owner must be nonempty")
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "delete from derived_fact_cache_owners where owner = ?",
                    (candidate,),
                )
                connection.execute(
                    """
                    delete from derived_fact_cache
                    where not exists (
                        select 1
                        from derived_fact_cache_owners owners
                        where owners.cache_key = derived_fact_cache.cache_key
                    )
                    """
                )

    def stats(self) -> dict[str, int | str]:
        return {
            "schema": _CACHE_SCHEMA,
            "hits": self.hits,
            "misses": self.misses,
        }


class ScopedCachedExtractor:
    """Attach one namespace owner to cache reads/writes for selective erasure."""

    def __init__(self, cache: CachedExtractor, owner: str) -> None:
        self._cache = cache
        self.owner = owner
        self.config_fingerprint = cache.config_fingerprint

    def config_metadata(self) -> dict[str, object]:
        return self._cache.config_metadata()

    def extract(self, text: str) -> Extraction:
        return self._cache.extract(text, owner=self.owner)


def _extraction_to_dict(extraction: Extraction) -> dict[str, object]:
    return {
        "entities": [
            {"name": entity.name, "entity_type": entity.entity_type}
            for entity in extraction.entities
        ],
        "claims": [
            {
                "subject": claim.subject,
                "relation": claim.relation,
                "object": claim.obj,
                "when": claim.when,
                "where": claim.where,
                "why": claim.why,
                "how": claim.how,
                "then": claim.then,
                "epistemic_basis": claim.epistemic_basis,
                "source_spans": [
                    {
                        "field": span.field,
                        "text": span.text,
                        "start": span.start,
                        "end": span.end,
                    }
                    for span in claim.source_spans
                ],
            }
            for claim in extraction.claims
        ],
    }


def _extraction_from_dict(payload: dict[str, Any]) -> Extraction:
    entities = tuple(
        ExtractedEntity(
            name=str(item["name"]),
            entity_type=str(item.get("entity_type") or "entity"),
        )
        for item in payload.get("entities", [])
    )
    claims = []
    for item in payload.get("claims", []):
        spans = tuple(
            GroundedSpan(
                field=str(span["field"]),
                text=str(span["text"]),
                start=int(span["start"]),
                end=int(span["end"]),
            )
            for span in item.get("source_spans", [])
        )
        claims.append(
            ExtractedClaim(
                subject=str(item["subject"]),
                relation=str(item["relation"]),
                obj=str(item["object"]),
                when=item.get("when"),
                where=item.get("where"),
                why=item.get("why"),
                how=item.get("how"),
                then=item.get("then"),
                epistemic_basis=str(item.get("epistemic_basis") or "unknown"),
                source_spans=spans,
            )
        )
    return Extraction(entities=entities, claims=tuple(claims))


def is_eligible_derived_claim(
    record: MIRLRecord,
    *,
    policy: str = GROUNDED_CLM_V1,
) -> bool:
    if (
        record.kind != RecordKind.CLM
        or record.status not in {Status.ASSERTED, Status.OBSERVED}
        or record.ns == ""
        or record.scope == ""
    ):
        return False
    attrs = record.attrs
    ext = record.ext
    subject_label = attrs.get("subject_label")
    predicate = attrs.get("predicate")
    obj = attrs.get("object")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (subject_label, predicate, obj)
    ):
        return False
    if str(predicate).strip().lower() == "content":
        return False
    if is_singular_first_person(subject_label):
        return False
    if (
        ext.get("derived_fact_policy") != policy
        or ext.get("extraction_method") != "grounded_local_model"
        or ext.get("epistemic_basis") != "explicit"
    ):
        return False
    resolution = ext.get("subject_resolution")
    if (
        not isinstance(resolution, dict)
        or resolution.get("method") != "first_person_to_turn_speaker"
        or not is_singular_first_person(resolution.get("surface"))
        or " ".join(str(resolution.get("speaker") or "").lower().split())
        != " ".join(str(subject_label).lower().split())
    ):
        return False
    spans = ext.get("grounded_spans")
    if not isinstance(spans, list):
        return False
    fields = {
        str(span.get("field"))
        for span in spans
        if isinstance(span, dict)
        and isinstance(span.get("start"), int)
        and isinstance(span.get("end"), int)
    }
    return {"subject", "relation", "object"} <= fields


def grounded_spans_match_source(
    record: MIRLRecord,
    source_text: str,
    *,
    evidence_start: int | None = None,
    evidence_end: int | None = None,
    source_speaker: str | None = None,
    source_timestamp: str | None = None,
    source_prefix_end: int | None = None,
    require_evidence_bounds: bool = False,
    require_source_metadata: bool = False,
) -> bool:
    """Bind rich claim fields to exact offsets in their cited RAW evidence."""

    spans = record.ext.get("grounded_spans")
    if not isinstance(spans, list) or not spans:
        return False
    if require_evidence_bounds and (
        evidence_start is None or evidence_end is None
    ):
        return False
    if evidence_start is not None or evidence_end is not None:
        if (
            not isinstance(evidence_start, int)
            or not isinstance(evidence_end, int)
            or evidence_start < 0
            or evidence_end <= evidence_start
            or evidence_end > len(source_text)
        ):
            return False
    if require_evidence_bounds and (
        evidence_start,
        evidence_end,
    ) not in {
        (start, end)
        for _, start, end in segment_propositions(source_text)
    }:
        return False
    required: dict[str, dict[str, object]] = {}
    for span in spans:
        if not isinstance(span, dict):
            return False
        field = span.get("field")
        start = span.get("start")
        end = span.get("end")
        text = span.get("text")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(text, str)
            or start < 0
            or end <= start
            or end > len(source_text)
            or source_text[start:end] != text
        ):
            return False
        if (
            evidence_start is not None
            and evidence_end is not None
            and (start < evidence_start or end > evidence_end)
        ):
            return False
        if field in {"subject", "relation", "object"}:
            if field in required:
                return False
            required[str(field)] = span
    if set(required) != {"subject", "relation", "object"}:
        return False
    resolution = record.ext.get("subject_resolution")
    metadata_requested = (
        require_source_metadata
        or resolution is not None
        or source_speaker is not None
        or source_timestamp is not None
        or source_prefix_end is not None
    )
    canonical_prefix_end = None
    if metadata_requested:
        canonical_prefix_end = canonical_turn_prefix_end(
            source_text,
            speaker=source_speaker,
            timestamp=source_timestamp,
        )
        if (
            canonical_prefix_end is None
            or source_prefix_end != canonical_prefix_end
        ):
            return False
    required_spans = {
        field: GroundedSpan(
            field=field,
            text=str(span["text"]),
            start=int(span["start"]),
            end=int(span["end"]),
        )
        for field, span in required.items()
    }
    if not grounded_sro_is_coherent(
        source_text,
        required_spans["subject"],
        required_spans["relation"],
        required_spans["object"],
        evidence_start=(
            evidence_start
            if isinstance(evidence_start, int)
            else 0
        ),
        evidence_end=(
            evidence_end
            if isinstance(evidence_end, int)
            else len(source_text)
        ),
        require_complete_clause=True,
        allowed_prefix_end=(
            canonical_prefix_end
            if canonical_prefix_end is not None
            and (
                not isinstance(evidence_start, int)
                or canonical_prefix_end >= evidence_start
            )
            else None
        ),
    ):
        return False

    def normalized(value: object) -> str:
        return " ".join(str(value or "").lower().split())

    attrs = record.attrs
    if normalized(required["relation"]["text"]) != normalized(
        attrs.get("predicate")
    ):
        return False
    if normalized(required["object"]["text"]) != normalized(attrs.get("object")):
        return False

    subject_label = normalized(attrs.get("subject_label"))
    if resolution is None:
        return normalized(required["subject"]["text"]) == subject_label
    if not isinstance(resolution, dict):
        return False
    return (
        resolution.get("method") == "first_person_to_turn_speaker"
        and is_singular_first_person(resolution.get("surface"))
        and normalized(resolution.get("surface"))
        == normalized(required["subject"]["text"])
        and normalized(resolution.get("speaker")) == subject_label
        and normalized(source_speaker) == subject_label
    )


@dataclass(frozen=True)
class DerivedFact:
    claim_id: str
    subject: str
    predicate: str
    obj: str
    source_raw_id: str
    source_text: str
    score: float
    created_at: str = ""

    def dedupe_key(self) -> tuple[str, str, str, str]:
        normalized = tuple(
            " ".join(re.findall(r"[a-z0-9]+", value.lower()))
            for value in (self.subject, self.predicate, self.obj)
        )
        return (*normalized, self.source_raw_id)

    def render(self) -> str:
        fact = {
            "claim_id": self.claim_id,
            "object": self.obj,
            "predicate": self.predicate,
            "source_raw_id": self.source_raw_id,
            "subject": self.subject,
        }
        source = {"id": self.source_raw_id, "raw": self.source_text}
        return (
            f"{_FACT_RENDER_VERSION}|"
            + json.dumps(fact, sort_keys=True, separators=(",", ":"))
            + "\nSEAM-SOURCE/1|"
            + json.dumps(source, sort_keys=True, separators=(",", ":"))
        )

    def result(self) -> dict[str, object]:
        return {
            "memory": self.render(),
            "score": float(self.score),
            "id": self.claim_id,
            "created_at": self.created_at,
        }

    def source_result(self) -> dict[str, object]:
        return {
            "memory": self.source_text,
            "score": float(self.score),
            "id": self.source_raw_id,
            "created_at": self.created_at,
        }


def splice_derived_facts(
    raw_results: list[dict],
    facts: list[DerivedFact],
    *,
    limit: int,
    policy: str,
) -> list[dict]:
    resolved = resolve_derived_facts_policy(policy)
    if resolved == DERIVED_FACTS_OFF:
        # The disabled lever is an exact no-op, including object identity.
        return raw_results
    bounded_raw = raw_results[: max(limit, 0)]
    if limit <= 0 or not facts:
        return bounded_raw

    deduped: list[DerivedFact] = []
    seen_fact_keys: set[tuple[str, str, str, str]] = set()
    for fact in facts:
        key = fact.dedupe_key()
        if key in seen_fact_keys:
            continue
        seen_fact_keys.add(key)
        deduped.append(fact)

    fact_cap = min(40, limit // 5, len(deduped))
    if fact_cap <= 0:
        return bounded_raw
    selected = deduped[:fact_cap]

    existing_raw = {
        str(item.get("id")): item
        for item in raw_results
        if str(item.get("id") or "")
    }

    def build_raw_candidates(chosen: list[DerivedFact]) -> list[dict]:
        raw_candidates: list[dict] = []
        seen_raw_ids: set[str] = set()

        def add_raw(item: dict) -> None:
            record_id = str(item.get("id") or "")
            if record_id and record_id not in seen_raw_ids:
                seen_raw_ids.add(record_id)
                raw_candidates.append(item)

        for item in raw_results:
            add_raw(item)
        for fact in chosen:
            add_raw(existing_raw.get(fact.source_raw_id, fact.source_result()))
        return raw_candidates

    # Enforce the 20% ceiling against the rows actually returned, not merely
    # the requested limit. Sparse retrieval must not become fact-dominated.
    raw_candidates = build_raw_candidates(selected)
    while selected:
        raw_slots = max(0, limit - len(selected))
        output_size = len(selected) + min(raw_slots, len(raw_candidates))
        if len(selected) * 5 <= output_size:
            break
        selected.pop()
        raw_candidates = build_raw_candidates(selected)
    if not selected:
        return bounded_raw

    remaining_raw = list(raw_candidates)
    output: list[dict] = []
    emitted_raw_ids: set[str] = set()
    emitted_raw_count = 0

    def emit_raw(item: dict) -> None:
        nonlocal emitted_raw_count
        record_id = str(item.get("id") or "")
        if record_id and record_id not in emitted_raw_ids:
            emitted_raw_ids.add(record_id)
            output.append(item)
            emitted_raw_count += 1

    def pop_raw(record_id: str | None = None) -> dict | None:
        if record_id is None:
            return remaining_raw.pop(0) if remaining_raw else None
        for index, item in enumerate(remaining_raw):
            if str(item.get("id") or "") == record_id:
                return remaining_raw.pop(index)
        return None

    # A fact appears only after four RAW rows. This enforces the 20% ceiling
    # at every response prefix (including the harness's 10/20/50 slices), and
    # each fact's source RAW is emitted before that fact.
    for fact_index, fact in enumerate(selected, start=1):
        if fact.source_raw_id not in emitted_raw_ids:
            source = pop_raw(fact.source_raw_id)
            if source is None:
                source = fact.source_result()
            emit_raw(source)
        target_raw_count = fact_index * 4
        while emitted_raw_count < target_raw_count:
            item = pop_raw()
            if item is None:
                break
            emit_raw(item)
        if emitted_raw_count < target_raw_count:
            break
        output.append(fact.result())

    while len(output) < limit:
        item = pop_raw()
        if item is None:
            break
        emit_raw(item)
    return output[:limit]
