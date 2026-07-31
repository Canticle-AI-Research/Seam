"""Read-only qualification for extractor-produced entity-to-entity REL records.

The analyzer never compiles text and never invokes an embedding or extraction
model. It audits one or more already-built SQLite corpus databases, emits a
content-free gate report, and can separately write a content-bearing human
review template.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import quote

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator.adapters import (
    _CANONICAL_RELATION_EDGE_FROM,
    _canonical_relation_edge_where,
)
from seam_runtime.retrieval_orchestrator.planner import build_plan

QUALIFICATION_SCHEMA = "relation-extraction-qualification/1"
REVIEW_SCHEMA = "relation-extraction-review/1"
MIN_RELATIONS = 30
MIN_TURN_COVERAGE = 0.10
MIN_SAMPLE_SIZE = 50
MIN_POINT_PRECISION = 0.90
MIN_WILSON_LOWER = 0.80
LABEL_FIELDS = (
    "subject_entity_supported",
    "predicate_supported",
    "object_entity_supported",
    "direction_correct",
    "coreference_correct",
)
_REQUIRED_TABLES = {
    "ir_records",
    "knowledge_edges",
    "knowledge_nodes",
    "knowledge_episodes",
    "knowledge_edge_episodes",
    "raw_docs",
    "raw_spans",
}
_DIGEST_TABLE_KEYS = {
    "ir_records": "id",
    "knowledge_edges": "id",
    "knowledge_nodes": "id",
    "knowledge_episodes": "id",
    "knowledge_edge_episodes": "edge_id, episode_id",
    "raw_docs": "id",
    "raw_spans": "id",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }


@dataclass
class RelationObservation:
    database_index: int
    database_digest: str
    record: MIRLRecord
    admitted_edge: sqlite3.Row | None
    subject_label: str = ""
    object_label: str = ""
    raw_id: str | None = None
    evidence_text: str | None = None
    exact_backtrace: bool = False
    violations: list[str] = field(default_factory=list)

    @property
    def sample_id(self) -> str:
        return _digest_text(
            f"{self.database_index}\0{self.database_digest}\0{self.record.id}"
        )

    @property
    def node_keys(self) -> tuple[tuple[object, ...], tuple[object, ...]]:
        attrs = self.record.attrs
        boundary = (
            self.database_index,
            self.record.ns,
            self.record.scope,
        )
        return (
            (*boundary, str(attrs.get("src") or "")),
            (*boundary, str(attrs.get("dst") or "")),
        )


@dataclass
class QualificationArtifacts:
    report: dict[str, object]
    review_template: dict[str, object]


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _readonly_connection(
    path: Path,
    *,
    required_tables: set[str] | None = None,
) -> sqlite3.Connection:
    resolved = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(
        f"file:{quote(str(resolved), safe='/')}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("pragma query_only = on")
    missing = sorted((required_tables or set()) - _table_names(connection))
    if missing:
        connection.close()
        raise ValueError(
            "qualification database is missing required tables: "
            + ", ".join(missing)
        )
    return connection


def _database_digest(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    tables = _table_names(connection)
    for table, order_by in _DIGEST_TABLE_KEYS.items():
        digest.update(f"{table}\0".encode())
        if table not in tables:
            digest.update(b"<missing>\n")
            continue
        cursor = connection.execute(f"select * from {table} order by {order_by}")
        for row in cursor:
            digest.update(
                json.dumps(
                    list(row),
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _load_records(connection: sqlite3.Connection) -> dict[str, MIRLRecord]:
    records: dict[str, MIRLRecord] = {}
    for row in connection.execute(
        "select id, payload_json from ir_records order by id"
    ):
        try:
            record = MIRLRecord.from_dict(json.loads(row["payload_json"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid MIRL payload for {row['id']!r}") from exc
        if record.id != row["id"]:
            raise ValueError(f"MIRL payload id mismatch for {row['id']!r}")
        records[record.id] = record
    return records


def _admitted_edges(
    connection: sqlite3.Connection,
) -> dict[str, list[sqlite3.Row]]:
    plan = build_plan(
        "relation qualification",
        budget=1,
        mode="graph",
        graph_hops=1,
    )
    where, params = _canonical_relation_edge_where(plan)
    rows = connection.execute(
        "select e.id, e.src_id, e.dst_id, e.predicate, e.edge_kind, "
        "e.ns, e.scope, e.source_record_id, e.properties_json "
        + _CANONICAL_RELATION_EDGE_FROM
        + f"where {' and '.join(where)} order by e.source_record_id, e.id",
        params,
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_record_id"])].append(row)
    return grouped


def _raw_identities(
    records: Mapping[str, MIRLRecord],
    database_index: int,
) -> list[dict[str, object]]:
    return [
        {
            "database_index": database_index,
            "record_id": record.id,
            "namespace": record.ns,
            "scope": record.scope,
            "source_ref": record.attrs.get("source_ref"),
            "content_digest": _digest_text(
                str(record.attrs.get("content") or "")
            ),
        }
        for record in sorted(records.values(), key=lambda item: item.id)
        if record.kind == RecordKind.RAW
    ]


def raw_turn_identity(
    database_paths: Iterable[Path],
) -> dict[str, object]:
    """Return the content-free RAW identity to pin before qualification."""

    paths = sorted(
        {path.expanduser().resolve(strict=True) for path in database_paths},
        key=str,
    )
    if not paths:
        raise ValueError("at least one qualification database is required")
    identities: list[dict[str, object]] = []
    for database_index, path in enumerate(paths):
        connection = _readonly_connection(
            path,
            required_tables={"ir_records"},
        )
        try:
            identities.extend(
                _raw_identities(
                    _load_records(connection),
                    database_index,
                )
            )
        finally:
            connection.close()
    return {
        "turns": len(identities),
        "digest": _canonical_digest(identities),
    }


def _span_map(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("field"), str):
            grouped[str(item["field"])].append(item)
    if any(len(items) != 1 for items in grouped.values()):
        return {}
    return {field: items[0] for field, items in grouped.items()}


def _relation_backtrace(
    connection: sqlite3.Connection,
    record: MIRLRecord,
    records: Mapping[str, MIRLRecord],
    edge: sqlite3.Row | None,
) -> tuple[list[str], str | None, str | None, str, str]:
    violations: list[str] = []
    attrs = record.attrs
    src_id = attrs.get("src")
    dst_id = attrs.get("dst")
    predicate = attrs.get("predicate")
    claim_id = attrs.get("claim_id")
    src = records.get(str(src_id)) if isinstance(src_id, str) else None
    dst = records.get(str(dst_id)) if isinstance(dst_id, str) else None
    subject_label = str(src.attrs.get("label") or "") if src else ""
    object_label = str(dst.attrs.get("label") or "") if dst else ""

    if src_id == dst_id:
        violations.append("self_relation")
    for endpoint, name in ((src, "src"), (dst, "dst")):
        if endpoint is None or endpoint.kind != RecordKind.ENT:
            violations.append(f"{name}_not_entity")
        elif endpoint.ns != record.ns or endpoint.scope != record.scope:
            violations.append("cross_boundary_endpoint")
            violations.append("canonical_entity_scope_mismatch")

    claim = records.get(str(claim_id)) if isinstance(claim_id, str) else None
    if claim is None or claim.kind != RecordKind.CLM:
        violations.append("claim_missing")
    else:
        if claim.ns != record.ns or claim.scope != record.scope:
            violations.append("claim_cross_boundary")
        if claim.attrs.get("subject") != src_id:
            violations.append("claim_subject_mismatch")
        if _normalize(claim.attrs.get("predicate")) != _normalize(predicate):
            violations.append("claim_predicate_mismatch")
        if _normalize(claim.attrs.get("object")) != _normalize(object_label):
            violations.append("claim_object_mismatch")
        if claim.evidence != record.evidence:
            violations.append("claim_evidence_mismatch")

    extractor = record.ext.get("extractor")
    metadata_fingerprint = record.ext.get("extractor_metadata_fingerprint")
    config_fingerprint = record.ext.get("extractor_config_fingerprint")
    if not isinstance(extractor, dict) or not extractor:
        violations.append("extractor_metadata_missing")
    elif metadata_fingerprint != _canonical_digest(extractor):
        violations.append("extractor_metadata_fingerprint_mismatch")
    if not isinstance(config_fingerprint, str) or not config_fingerprint:
        violations.append("extractor_config_fingerprint_missing")

    relation_spans = _span_map(record.ext.get("grounded_spans"))
    if not all(field in relation_spans for field in ("subject", "relation", "object")):
        violations.append("grounded_spans_missing")
    if claim is not None and claim.ext.get("grounded_spans") != record.ext.get(
        "grounded_spans"
    ):
        violations.append("claim_grounded_spans_mismatch")
    if claim is not None and claim.ext.get("subject_resolution") != record.ext.get(
        "subject_resolution"
    ):
        violations.append("claim_subject_resolution_mismatch")

    raw_id: str | None = None
    evidence_text: str | None = None
    span_record: MIRLRecord | None = None
    raw: MIRLRecord | None = None
    if len(record.evidence) != 1:
        violations.append("evidence_span_count")
    else:
        span_record = records.get(record.evidence[0])
        if span_record is None or span_record.kind != RecordKind.SPAN:
            violations.append("evidence_not_span")
        elif span_record.ns != record.ns or span_record.scope != record.scope:
            violations.append("evidence_cross_boundary")
        else:
            candidate_raw_id = span_record.attrs.get("raw_id")
            raw_id = (
                candidate_raw_id
                if isinstance(candidate_raw_id, str)
                else None
            )
            raw = records.get(raw_id) if raw_id else None
            if raw is None or raw.kind != RecordKind.RAW:
                violations.append("raw_missing")
            elif raw.ns != record.ns or raw.scope != record.scope:
                violations.append("raw_cross_boundary")

    span_start = span_record.attrs.get("start") if span_record else None
    span_end = span_record.attrs.get("end") if span_record else None
    raw_content = str(raw.attrs.get("content") or "") if raw else ""
    if (
        isinstance(span_start, bool)
        or isinstance(span_end, bool)
        or not isinstance(span_start, int)
        or not isinstance(span_end, int)
        or span_start < 0
        or span_end <= span_start
        or span_end > len(raw_content)
    ):
        violations.append("evidence_offsets_invalid")
    else:
        evidence_text = raw_content[span_start:span_end]

    if span_record is not None and raw_id is not None:
        raw_span = connection.execute(
            "select raw_id, start, end, span_text from raw_spans where id = ?",
            (span_record.id,),
        ).fetchone()
        if raw_span is None:
            violations.append("raw_span_row_missing")
        elif (
            raw_span["raw_id"] != raw_id
            or raw_span["start"] != span_start
            or raw_span["end"] != span_end
        ):
            violations.append("raw_span_row_mismatch")
        elif raw_span["span_text"] is not None and raw_span["span_text"] != evidence_text:
            violations.append("raw_span_text_mismatch")

    if raw is not None:
        raw_doc = connection.execute(
            "select ns, scope, source_ref, content from raw_docs where id = ?",
            (raw.id,),
        ).fetchone()
        if raw_doc is None:
            violations.append("raw_doc_row_missing")
        elif (
            raw_doc["ns"] != raw.ns
            or raw_doc["scope"] != raw.scope
            or raw_doc["source_ref"] != raw.attrs.get("source_ref")
            or raw_doc["content"] != raw_content
        ):
            violations.append("raw_doc_row_mismatch")
        resolution = record.ext.get("subject_resolution")
        if resolution is not None:
            source_metadata = raw.ext.get("source_metadata")
            if (
                not isinstance(resolution, dict)
                or resolution.get("method")
                != "first_person_to_turn_speaker"
                or not isinstance(source_metadata, dict)
                or source_metadata.get("format") != "locomo-turn/1"
                or _normalize(source_metadata.get("speaker"))
                != _normalize(resolution.get("speaker"))
                or _normalize(resolution.get("speaker"))
                != _normalize(subject_label)
            ):
                violations.append("subject_resolution_source_mismatch")

    for span_field, expected in (
        ("subject", subject_label),
        ("relation", predicate),
        ("object", claim.attrs.get("object") if claim else object_label),
    ):
        grounded = relation_spans.get(span_field)
        if grounded is None:
            continue
        start = grounded.get("start")
        end = grounded.get("end")
        text = grounded.get("text")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(raw_content)
            or raw_content[start:end] != text
            or not isinstance(span_start, int)
            or not isinstance(span_end, int)
            or start < span_start
            or end > span_end
        ):
            violations.append(f"{span_field}_span_invalid")
        elif _normalize(text) != _normalize(expected):
            resolution = record.ext.get("subject_resolution")
            resolved_subject = (
                span_field == "subject"
                and isinstance(resolution, dict)
                and resolution.get("method") == "first_person_to_turn_speaker"
                and _normalize(resolution.get("surface")) == _normalize(text)
                and _normalize(resolution.get("speaker")) == _normalize(expected)
            )
            if not resolved_subject:
                violations.append(f"{span_field}_span_value_mismatch")

    if raw_id is not None:
        if not record.prov:
            violations.append("provenance_missing")
        for prov_id in record.prov:
            prov = records.get(prov_id)
            if (
                prov is None
                or prov.kind != RecordKind.PROV
                or prov.attrs.get("entity") != raw_id
                or prov.ns != record.ns
                or prov.scope != record.scope
            ):
                violations.append("provenance_raw_mismatch")
                break

    if edge is None:
        violations.append("canonical_edge_missing")
    elif raw is not None:
        episodes = connection.execute(
            "select ep.source_record_id, ep.source_ref, ep.content_hash, "
            "ep.ns, ep.scope "
            "from knowledge_edge_episodes kee "
            "join knowledge_episodes ep on ep.id = kee.episode_id "
            "where kee.edge_id = ? order by ep.id",
            (edge["id"],),
        ).fetchall()
        expected_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        if len(episodes) != 1:
            violations.append("edge_episode_count")
        else:
            episode = episodes[0]
            if str(episode["source_ref"] or "").startswith("mirl://"):
                violations.append("direct_write_episode")
            if (
                episode["source_record_id"] != raw.id
                or episode["source_ref"] != raw.attrs.get("source_ref")
                or episode["content_hash"] != expected_hash
                or episode["ns"] != record.ns
                or episode["scope"] != record.scope
            ):
                violations.append("edge_episode_raw_mismatch")

    return (
        sorted(set(violations)),
        raw_id,
        evidence_text,
        subject_label,
        object_label,
    )


def _analyze_database(
    path: Path,
    database_index: int,
) -> tuple[
    str,
    list[dict[str, object]],
    list[RelationObservation],
    set[str],
]:
    connection = _readonly_connection(
        path,
        required_tables={"ir_records"},
    )
    try:
        database_digest = _database_digest(connection)
        records = _load_records(connection)
        raw_identities = _raw_identities(records, database_index)
        missing_tables = _REQUIRED_TABLES - _table_names(connection)
        if missing_tables:
            observations = []
            for record in sorted(records.values(), key=lambda item: item.id):
                if record.kind != RecordKind.REL:
                    continue
                src = records.get(str(record.attrs.get("src") or ""))
                dst = records.get(str(record.attrs.get("dst") or ""))
                observations.append(
                    RelationObservation(
                        database_index=database_index,
                        database_digest=database_digest,
                        record=record,
                        admitted_edge=None,
                        subject_label=(
                            str(src.attrs.get("label") or "") if src else ""
                        ),
                        object_label=(
                            str(dst.attrs.get("label") or "") if dst else ""
                        ),
                        exact_backtrace=False,
                        violations=["missing_graph_projection_schema"],
                    )
                )
            return (
                database_digest,
                raw_identities,
                observations,
                missing_tables,
            )
        edges_by_relation = _admitted_edges(connection)
        observations: list[RelationObservation] = []
        for record in sorted(records.values(), key=lambda item: item.id):
            if record.kind != RecordKind.REL:
                continue
            admitted = edges_by_relation.get(record.id, [])
            edge = admitted[0] if len(admitted) == 1 else None
            violations, raw_id, evidence_text, subject_label, object_label = (
                _relation_backtrace(
                    connection,
                    record,
                    records,
                    edge,
                )
            )
            if len(admitted) > 1:
                violations.append("multiple_canonical_edges")
            observations.append(
                RelationObservation(
                    database_index=database_index,
                    database_digest=database_digest,
                    record=record,
                    admitted_edge=edge,
                    subject_label=subject_label,
                    object_label=object_label,
                    raw_id=raw_id,
                    evidence_text=evidence_text,
                    exact_backtrace=not violations,
                    violations=sorted(set(violations)),
                )
            )
        return database_digest, raw_identities, observations, set()
    finally:
        connection.close()


def _graph_metrics(
    observations: Iterable[RelationObservation],
) -> tuple[dict[str, object], dict[tuple[object, ...], int]]:
    adjacency: dict[tuple[object, ...], set[tuple[object, ...]]] = defaultdict(set)
    raw_by_edge: dict[
        frozenset[tuple[object, ...]],
        set[tuple[int, str]],
    ] = defaultdict(set)
    relation_count_by_edge: dict[frozenset[tuple[object, ...]], int] = (
        defaultdict(int)
    )
    unique_edges: set[frozenset[tuple[object, ...]]] = set()
    for observation in observations:
        if observation.admitted_edge is None:
            continue
        src, dst = observation.node_keys
        if src == dst:
            continue
        edge_key = frozenset((src, dst))
        unique_edges.add(edge_key)
        relation_count_by_edge[edge_key] += 1
        adjacency[src].add(dst)
        adjacency[dst].add(src)
        if observation.raw_id:
            raw_by_edge[edge_key].add(
                (observation.database_index, observation.raw_id)
            )

    simple_two_hop_paths = 0
    incremental_two_hop_pairs: set[frozenset[tuple[object, ...]]] = set()
    cross_turn_incremental_paths = 0
    entities_with_incremental_reach: set[tuple[object, ...]] = set()
    for center, neighbors in adjacency.items():
        ordered = sorted(neighbors)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                if left == right or left == center or right == center:
                    continue
                simple_two_hop_paths += 1
                if right in adjacency.get(left, set()):
                    continue
                incremental_two_hop_pairs.add(frozenset((left, right)))
                entities_with_incremental_reach.update((left, right))
                left_raw = raw_by_edge[frozenset((left, center))]
                right_raw = raw_by_edge[frozenset((center, right))]
                if any(a != b for a in left_raw for b in right_raw):
                    cross_turn_incremental_paths += 1

    degrees = {node: len(neighbors) for node, neighbors in adjacency.items()}
    ordered_degrees = sorted(degrees.values())

    def percentile(percentile_value: float) -> int:
        if not ordered_degrees:
            return 0
        index = max(
            0,
            math.ceil(percentile_value * len(ordered_degrees)) - 1,
        )
        return ordered_degrees[index]

    unique_edge_count = len(unique_edges)
    hub_bound = max(8, math.ceil(0.05 * unique_edge_count))
    max_degree = max(degrees.values(), default=0)
    multiplicities = list(relation_count_by_edge.values())
    return (
        {
            "unique_edges": unique_edge_count,
            "entity_count": len(adjacency),
            "max_hub_degree": max_degree,
            "p95_degree": percentile(0.95),
            "p99_degree": percentile(0.99),
            "hub_degree_bound": hub_bound,
            "simple_two_hop_paths": simple_two_hop_paths,
            "incremental_two_hop_pairs": len(incremental_two_hop_pairs),
            "cross_turn_incremental_two_hop_paths": (
                cross_turn_incremental_paths
            ),
            "entities_with_incremental_two_hop_reach": len(
                entities_with_incremental_reach
            ),
            "incremental_two_hop_entity_coverage": (
                len(entities_with_incremental_reach) / len(adjacency)
                if adjacency
                else 0.0
            ),
            "parallel_edge_pair_count": sum(
                multiplicity > 1 for multiplicity in multiplicities
            ),
            "max_parallel_edge_multiplicity": max(
                multiplicities,
                default=0,
            ),
        },
        degrees,
    )


def _sample_relations(
    observations: list[RelationObservation],
    degrees: Mapping[tuple[object, ...], int],
) -> list[RelationObservation]:
    ordered = sorted(observations, key=lambda item: item.sample_id)
    if len(ordered) < MIN_SAMPLE_SIZE:
        return ordered

    selected: dict[str, RelationObservation] = {}
    by_predicate: dict[str, list[RelationObservation]] = defaultdict(list)
    for observation in ordered:
        by_predicate[_normalize(observation.record.attrs.get("predicate"))].append(
            observation
        )
    for predicate in sorted(by_predicate, key=_digest_text):
        candidate = min(
            by_predicate[predicate],
            key=lambda item: item.sample_id,
        )
        selected[candidate.sample_id] = candidate

    ranked_hubs = sorted(
        degrees,
        key=lambda node: (-degrees[node], _digest_text(repr(node))),
    )[:10]
    for hub in ranked_hubs:
        incident = [
            observation
            for observation in ordered
            if hub in observation.node_keys
        ]
        if incident:
            candidate = min(incident, key=lambda item: item.sample_id)
            selected[candidate.sample_id] = candidate

    for observation in ordered:
        if len(selected) >= MIN_SAMPLE_SIZE:
            break
        selected[observation.sample_id] = observation
    return [selected[key] for key in sorted(selected)]


def _load_label_payload(
    labels_path: Path | None,
) -> tuple[dict[str, dict[str, bool | None]], dict[str, object] | None]:
    if labels_path is None:
        return {}, None
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("label file must contain a JSON object")
    relations = payload.get("relations")
    if not isinstance(relations, list):
        raise ValueError("label file must contain a relations array")
    labels: dict[str, dict[str, bool | None]] = {}
    for item in relations:
        if not isinstance(item, dict) or not isinstance(item.get("sample_id"), str):
            raise ValueError("each label row needs a sample_id")
        verdicts = item.get("labels")
        if not isinstance(verdicts, dict):
            raise ValueError("each label row needs a labels object")
        normalized: dict[str, bool | None] = {}
        for field_name in LABEL_FIELDS:
            value = verdicts.get(field_name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field_name} must be true, false, or null")
            normalized[field_name] = value
        labels[str(item["sample_id"])] = normalized
    return labels, payload


def _wilson_lower(successes: int, total: int) -> float:
    if total <= 0:
        return 0.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    center = proportion + (z * z / (2.0 * total))
    margin = z * math.sqrt(
        (proportion * (1.0 - proportion) / total)
        + (z * z / (4.0 * total * total))
    )
    return (center - margin) / denominator


def qualify_relation_extraction(
    database_paths: Iterable[Path],
    *,
    expected_turns: int,
    expected_raw_digest: str,
    labels_path: Path | None = None,
) -> QualificationArtifacts:
    if (
        isinstance(expected_turns, bool)
        or not isinstance(expected_turns, int)
        or expected_turns < 1
    ):
        raise ValueError("expected_turns must be a positive integer")
    if (
        not isinstance(expected_raw_digest, str)
        or len(expected_raw_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_raw_digest
        )
    ):
        raise ValueError(
            "expected_raw_digest must be a lowercase SHA-256 digest"
        )
    paths = sorted(
        {path.expanduser().resolve(strict=True) for path in database_paths},
        key=str,
    )
    if not paths:
        raise ValueError("at least one qualification database is required")

    database_digests: list[str] = []
    raw_identities: list[dict[str, object]] = []
    observations: list[RelationObservation] = []
    missing_schema_database_count = 0
    missing_schema_table_count = 0
    for database_index, path in enumerate(paths):
        (
            digest,
            database_raw_identities,
            database_observations,
            missing_tables,
        ) = _analyze_database(path, database_index)
        database_digests.append(digest)
        raw_identities.extend(database_raw_identities)
        observations.extend(database_observations)
        if missing_tables:
            missing_schema_database_count += 1
            missing_schema_table_count += len(missing_tables)

    turn_count = len(raw_identities)
    observed_raw_digest = _canonical_digest(raw_identities)
    corpus_digest = _canonical_digest(sorted(database_digests))
    config_values = sorted(
        {
            str(observation.record.ext.get("extractor_config_fingerprint"))
            for observation in observations
            if observation.record.ext.get("extractor_config_fingerprint")
        }
    )
    config_digest = _canonical_digest(config_values)
    graph, degrees = _graph_metrics(observations)
    sample = _sample_relations(observations, degrees)
    sample_ids = [observation.sample_id for observation in sample]
    sample_digest = _canonical_digest(sample_ids)

    labels, label_payload = _load_label_payload(labels_path)
    if label_payload is not None:
        if label_payload.get("expected_turns") != expected_turns:
            raise ValueError(
                "label file expected_turns does not match this qualification lane"
            )
        if label_payload.get("expected_raw_digest") != expected_raw_digest:
            raise ValueError(
                "label file expected_raw_digest does not match this qualification lane"
            )
        for key, expected in (
            ("corpus_digest", corpus_digest),
            ("config_digest", config_digest),
            ("sample_digest", sample_digest),
        ):
            if label_payload.get(key) != expected:
                raise ValueError(f"label file {key} does not match this corpus")
        if set(labels) != set(sample_ids):
            raise ValueError("label file sample ids do not match the selected sample")

    complete_labels = 0
    correct_labels = 0
    normalized_label_rows: list[dict[str, object]] = []
    for observation in sample:
        verdicts = labels.get(
            observation.sample_id,
            {field_name: None for field_name in LABEL_FIELDS},
        )
        complete = all(
            isinstance(verdicts.get(field_name), bool)
            for field_name in LABEL_FIELDS
        )
        if complete:
            complete_labels += 1
            if all(bool(verdicts[field_name]) for field_name in LABEL_FIELDS):
                correct_labels += 1
        normalized_label_rows.append(
            {
                "sample_id": observation.sample_id,
                **{
                    field_name: verdicts.get(field_name)
                    for field_name in LABEL_FIELDS
                },
            }
        )
    labels_digest = (
        _canonical_digest(normalized_label_rows)
        if label_payload is not None
        else None
    )
    point_precision = (
        correct_labels / complete_labels if complete_labels else 0.0
    )
    wilson_lower = _wilson_lower(correct_labels, complete_labels)

    persisted = len(observations)
    admitted = sum(
        observation.admitted_edge is not None for observation in observations
    )
    exact = sum(observation.exact_backtrace for observation in observations)
    covered_turns = {
        (observation.database_index, observation.raw_id)
        for observation in observations
        if observation.admitted_edge is not None and observation.raw_id is not None
    }
    turn_coverage = len(covered_turns) / expected_turns
    unique_pairs = {
        observation.node_keys
        for observation in observations
        if observation.admitted_edge is not None
    }
    unique_predicates = {
        _normalize(observation.record.attrs.get("predicate"))
        for observation in observations
        if observation.admitted_edge is not None
    }
    violation_counts: dict[str, int] = defaultdict(int)
    for observation in observations:
        for violation in observation.violations:
            violation_counts[violation] += 1
    if missing_schema_database_count:
        violation_counts["missing_graph_projection_schema"] = (
            missing_schema_database_count
        )

    checks = {
        "graph_projection_schema": missing_schema_database_count == 0,
        "turn_denominator": turn_count == expected_turns,
        "raw_digest": observed_raw_digest == expected_raw_digest,
        "nonzero_relations": persisted > 0,
        "relation_volume": persisted >= MIN_RELATIONS,
        "turn_coverage": turn_coverage >= MIN_TURN_COVERAGE,
        "full_admission": persisted > 0 and admitted == persisted,
        "exact_backtrace": persisted > 0 and exact == persisted,
        "single_extractor_config": persisted > 0 and len(config_values) == 1,
        "hub_degree": graph["max_hub_degree"] <= graph["hub_degree_bound"],
        "no_self_relations": violation_counts.get("self_relation", 0) == 0,
        "no_cross_boundary": (
            violation_counts.get("cross_boundary_endpoint", 0) == 0
        ),
        "labels_complete": bool(sample) and complete_labels == len(sample),
        "precision_point": (
            complete_labels == len(sample)
            and point_precision >= MIN_POINT_PRECISION
        ),
        "precision_wilson": (
            complete_labels == len(sample)
            and wilson_lower >= MIN_WILSON_LOWER
        ),
    }
    hard_failure = (
        missing_schema_database_count > 0
        or turn_count != expected_turns
        or observed_raw_digest != expected_raw_digest
        or persisted == 0
        or not checks["full_admission"]
        or not checks["exact_backtrace"]
        or not checks["single_extractor_config"]
        or not checks["hub_degree"]
        or not checks["no_self_relations"]
        or not checks["no_cross_boundary"]
    )
    if hard_failure:
        status = "failed"
    elif not checks["relation_volume"] or not checks["turn_coverage"]:
        status = "insufficient_evidence"
    elif not checks["labels_complete"]:
        status = "needs_review"
    elif not checks["precision_point"] or not checks["precision_wilson"]:
        status = "failed"
    else:
        status = "passed"
    scorer_checks = {
        "qualified_substrate": status == "passed",
        "predicate_diversity": len(unique_predicates) >= 2,
        "cross_turn_incremental_paths": (
            graph["cross_turn_incremental_two_hop_paths"] > 0
        ),
    }
    scorer_eligible = all(scorer_checks.values())

    report: dict[str, object] = {
        "schema": QUALIFICATION_SCHEMA,
        "status": status,
        "passed": status == "passed",
        "provider_calls": 0,
        "identity": {
            "database_count": len(paths),
            "corpus_digest": corpus_digest,
            "expected_raw_digest": expected_raw_digest,
            "observed_raw_digest": observed_raw_digest,
            "config_digest": config_digest,
            "config_count": len(config_values),
            "missing_schema_database_count": (
                missing_schema_database_count
            ),
            "missing_schema_table_count": missing_schema_table_count,
            "sample_digest": sample_digest,
            "labels_digest": labels_digest,
        },
        "funnel": {
            "turns_expected": expected_turns,
            "turns_observed": turn_count,
            "relations_persisted": persisted,
            "relations_admitted": admitted,
            "relations_exact_backtrace": exact,
            "turns_covered": len(covered_turns),
            "turn_coverage": turn_coverage,
            "unique_entity_pairs": len(unique_pairs),
            "unique_predicates": len(unique_predicates),
        },
        "graph": graph,
        "sample": {
            "required": len(sample),
            "labeled": complete_labels,
            "correct": correct_labels,
            "point_precision": point_precision,
            "wilson_lower_95": wilson_lower,
        },
        "thresholds": {
            "minimum_relations": MIN_RELATIONS,
            "minimum_turn_coverage": MIN_TURN_COVERAGE,
            "minimum_sample_size": MIN_SAMPLE_SIZE,
            "minimum_point_precision": MIN_POINT_PRECISION,
            "minimum_wilson_lower_95": MIN_WILSON_LOWER,
        },
        "rejections": dict(sorted(violation_counts.items())),
        "checks": checks,
        "scorer_eligible": scorer_eligible,
        "scorer_checks": scorer_checks,
    }
    review_template = {
        "schema": REVIEW_SCHEMA,
        "corpus_digest": corpus_digest,
        "config_digest": config_digest,
        "sample_digest": sample_digest,
        "expected_turns": expected_turns,
        "observed_turns": turn_count,
        "expected_raw_digest": expected_raw_digest,
        "observed_raw_digest": observed_raw_digest,
        "relations": [
            {
                "sample_id": observation.sample_id,
                "database_index": observation.database_index,
                "relation_id": observation.record.id,
                "claim_id": observation.record.attrs.get("claim_id"),
                "namespace": observation.record.ns,
                "scope": observation.record.scope,
                "subject": observation.subject_label,
                "predicate": observation.record.attrs.get("predicate"),
                "object": observation.object_label,
                "evidence": observation.evidence_text,
                "grounded_spans": observation.record.ext.get("grounded_spans"),
                "labels": {
                    field_name: labels.get(
                        observation.sample_id,
                        {},
                    ).get(field_name)
                    for field_name in LABEL_FIELDS
                },
                "notes": "",
            }
            for observation in sample
        ],
    }
    return QualificationArtifacts(
        report=report,
        review_template=review_template,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "databases",
        type=Path,
        nargs="+",
        help="One or more existing SQLite corpus databases.",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        help="Completed review-template JSON carrying human labels.",
    )
    parser.add_argument(
        "--expected-turns",
        type=int,
        required=True,
        help="Pinned expected RAW-turn denominator for the corpus lane.",
    )
    parser.add_argument(
        "--expected-raw-digest",
        required=True,
        help=(
            "Pinned lowercase SHA-256 digest of the expected ordered RAW-turn "
            "identity set."
        ),
    )
    parser.add_argument(
        "--review-template",
        type=Path,
        help=(
            "Write the separate content-bearing review template here. "
            "The stdout report remains content-free."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifacts = qualify_relation_extraction(
        args.databases,
        expected_turns=args.expected_turns,
        expected_raw_digest=args.expected_raw_digest,
        labels_path=args.labels,
    )
    if args.review_template is not None:
        args.review_template.write_text(
            json.dumps(
                artifacts.review_template,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(artifacts.report, indent=2, sort_keys=True))
    return 0 if artifacts.report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
