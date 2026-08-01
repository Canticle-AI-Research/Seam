"""Provider-free qualification of grounded entity-to-entity REL extraction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.nl_extract import Extraction, ground_extraction
from seam_runtime.runtime import SeamRuntime
from tools.relation_extraction_qualification import (
    LABEL_FIELDS,
    QUALIFICATION_SCHEMA,
    qualify_relation_extraction,
    raw_turn_identity,
)


class _GroundedRelationExtractor:
    config_fingerprint = "provider-free-fixture/1"

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "provider-free-fixture",
            "model": "none",
            "prompt_version": "fixture/1",
        }

    def extract(self, text: str) -> Extraction:
        words = text.rstrip(".").split()
        if len(words) != 3 or words[1] != "mentors":
            return Extraction()
        subject, predicate, obj = words
        return ground_extraction(
            {
                "entities": [
                    {"name": subject, "type": "person"},
                    {"name": obj, "type": "person"},
                ],
                "claims": [
                    {
                        "subject": subject,
                        "relation": predicate,
                        "object": obj,
                        "epistemic_basis": "explicit",
                    }
                ],
            },
            text,
        )


def _seed_corpus(
    path: Path,
    *,
    turns: int,
    relations: int,
) -> None:
    runtime = SeamRuntime(path, allow_pgvector_env=False)
    extractor = _GroundedRelationExtractor()
    try:
        for index in range(turns):
            if index < relations:
                text = f"Node{index:03d} mentors Node{index + 1:03d}."
            else:
                text = f"Turn{index:03d} contains no relation."
            runtime.ingest_conversation_turn(
                text,
                source_ref=f"fixture://turn/{index:03d}",
                ns="relation-qualification",
                scope="thread",
                extractor=extractor,
                allow_env_extractor=False,
            )
    finally:
        runtime.close()


def _qualify(
    path: Path,
    *,
    labels_path: Path | None = None,
):
    identity = raw_turn_identity([path])
    return qualify_relation_extraction(
        [path],
        expected_turns=int(identity["turns"]),
        expected_raw_digest=str(identity["digest"]),
        labels_path=labels_path,
    )


def _complete_review(template: dict[str, object], path: Path) -> None:
    relations = template["relations"]
    assert isinstance(relations, list)
    for relation in relations:
        labels = relation["labels"]
        for field_name in LABEL_FIELDS:
            labels[field_name] = True
    path.write_text(
        json.dumps(template, sort_keys=True),
        encoding="utf-8",
    )


def test_qualifier_requires_review_then_passes_complete_precise_labels(
    tmp_path: Path,
) -> None:
    database = tmp_path / "qualified.db"
    _seed_corpus(database, turns=50, relations=50)

    unlabeled = _qualify(database)

    assert unlabeled.report["schema"] == QUALIFICATION_SCHEMA
    assert unlabeled.report["provider_calls"] == 0
    assert unlabeled.report["status"] == "needs_review"
    assert unlabeled.report["funnel"] == {
        "turns_expected": 50,
        "turns_observed": 50,
        "relations_persisted": 50,
        "relations_admitted": 50,
        "relations_exact_backtrace": 50,
        "turns_covered": 50,
        "turn_coverage": 1.0,
        "unique_entity_pairs": 50,
        "unique_predicates": 1,
    }
    assert unlabeled.report["graph"]["incremental_two_hop_pairs"] == 49
    assert (
        unlabeled.report["graph"]["cross_turn_incremental_two_hop_paths"]
        == 49
    )
    assert unlabeled.report["graph"]["max_hub_degree"] == 2
    assert unlabeled.report["graph"]["max_parallel_edge_multiplicity"] == 1
    assert len(unlabeled.review_template["relations"]) == 50
    assert "evidence" not in json.dumps(unlabeled.report)
    assert "Node" not in json.dumps(unlabeled.report)

    labels = tmp_path / "labels.json"
    _complete_review(unlabeled.review_template, labels)
    qualified = _qualify(database, labels_path=labels)

    assert qualified.report["status"] == "passed"
    assert qualified.report["passed"] is True
    assert qualified.report["checks"]["labels_complete"] is True
    assert qualified.report["checks"]["sample_size"] is True
    assert qualified.report["checks"]["single_extractor_config"] is True
    assert qualified.report["sample"]["point_precision"] == 1.0
    assert qualified.report["sample"]["wilson_lower_95"] >= 0.80
    assert qualified.report["identity"]["labels_digest"]
    assert qualified.report["scorer_eligible"] is False
    assert qualified.report["scorer_checks"] == {
        "qualified_substrate": True,
        "predicate_diversity": False,
        "cross_turn_incremental_paths": True,
    }


def test_perfect_labels_below_minimum_sample_remain_insufficient(
    tmp_path: Path,
) -> None:
    database = tmp_path / "below-minimum-sample.db"
    _seed_corpus(database, turns=30, relations=30)

    unlabeled = _qualify(database)
    assert unlabeled.report["status"] == "insufficient_evidence"
    assert unlabeled.report["checks"]["relation_volume"] is True
    assert unlabeled.report["checks"]["sample_size"] is False

    labels = tmp_path / "below-minimum-sample-labels.json"
    _complete_review(unlabeled.review_template, labels)
    reviewed = _qualify(database, labels_path=labels)

    assert reviewed.report["sample"]["required"] == 30
    assert reviewed.report["sample"]["point_precision"] == 1.0
    assert reviewed.report["checks"]["labels_complete"] is True
    assert reviewed.report["checks"]["sample_size"] is False
    assert reviewed.report["status"] == "insufficient_evidence"
    assert reviewed.report["passed"] is False
    assert reviewed.report["scorer_eligible"] is False


def test_seven_relations_over_thirty_turns_is_insufficient_evidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "seven-of-thirty.db"
    _seed_corpus(database, turns=30, relations=7)

    artifacts = _qualify(database)

    assert artifacts.report["status"] == "insufficient_evidence"
    assert artifacts.report["funnel"]["relations_persisted"] == 7
    assert artifacts.report["funnel"]["turn_coverage"] == 7 / 30
    assert artifacts.report["checks"]["relation_volume"] is False
    assert len(artifacts.review_template["relations"]) == 7


def test_zero_relations_over_419_turns_fails(
    tmp_path: Path,
) -> None:
    database = tmp_path / "zero-of-419.db"
    runtime = SeamRuntime(database, allow_pgvector_env=False)
    records: list[MIRLRecord] = []
    try:
        for index in range(419):
            records.extend(
                runtime.compile_nl(
                    f"Turn{index:03d} contains no relation.",
                    source_ref=f"fixture://zero/{index:03d}",
                    ns="relation-qualification",
                    scope="thread",
                    allow_env_extractor=False,
                ).records
            )
        runtime.persist_ir(IRBatch(records))
    finally:
        runtime.close()

    artifacts = _qualify(database)

    assert artifacts.report["funnel"]["turns_observed"] == 419
    assert artifacts.report["funnel"]["relations_persisted"] == 0
    assert artifacts.report["status"] == "failed"
    assert artifacts.report["checks"]["nonzero_relations"] is False


def test_exact_backtrace_rejects_episode_hash_corruption(
    tmp_path: Path,
) -> None:
    database = tmp_path / "corrupt-backtrace.db"
    _seed_corpus(database, turns=7, relations=7)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "update knowledge_episodes set content_hash = ? "
            "where id = (select id from knowledge_episodes order by id limit 1)",
            ("0" * 64,),
        )

    artifacts = _qualify(database)

    assert artifacts.report["status"] == "failed"
    assert artifacts.report["rejections"]["edge_episode_raw_mismatch"] == 1
    assert artifacts.report["checks"]["exact_backtrace"] is False


def test_namespace_wide_coreference_scope_trap_is_named(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cross-scope.db"
    runtime = SeamRuntime(database, allow_pgvector_env=False)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id="ent:node-a-project",
                        kind=RecordKind.ENT,
                        ns="relation-qualification",
                        scope="project",
                        attrs={"label": "NodeA", "entity_type": "person"},
                    ),
                    MIRLRecord(
                        id="ent:node-b-project",
                        kind=RecordKind.ENT,
                        ns="relation-qualification",
                        scope="project",
                        attrs={"label": "NodeB", "entity_type": "person"},
                    ),
                ]
            )
        )
        runtime.ingest_conversation_turn(
            "NodeA mentors NodeB.",
            source_ref="fixture://cross-scope",
            ns="relation-qualification",
            scope="thread",
            extractor=_GroundedRelationExtractor(),
            allow_env_extractor=False,
        )
    finally:
        runtime.close()

    artifacts = _qualify(database)

    assert artifacts.report["status"] == "failed"
    assert (
        artifacts.report["rejections"]["canonical_entity_scope_mismatch"]
        == 1
    )
    assert artifacts.report["checks"]["full_admission"] is False


def test_raw_identity_pin_mismatch_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "pin-mismatch.db"
    _seed_corpus(database, turns=1, relations=1)
    identity = raw_turn_identity([database])

    artifacts = qualify_relation_extraction(
        [database],
        expected_turns=int(identity["turns"]),
        expected_raw_digest="0" * 64,
    )

    assert artifacts.report["status"] == "failed"
    assert artifacts.report["checks"]["turn_denominator"] is True
    assert artifacts.report["checks"]["raw_digest"] is False


def test_legacy_zero_rel_database_without_graph_schema_fails_cleanly(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-zero.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "create table ir_records "
            "(id text primary key, payload_json text not null)"
        )
        for index in range(2):
            record = MIRLRecord(
                id=f"raw:legacy-{index}",
                kind=RecordKind.RAW,
                ns="legacy-audit",
                scope="thread",
                attrs={
                    "source_ref": f"legacy://turn/{index}",
                    "content": f"private legacy turn {index}",
                },
            )
            connection.execute(
                "insert into ir_records (id, payload_json) values (?, ?)",
                (
                    record.id,
                    json.dumps(
                        record.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

    identity = raw_turn_identity([database])
    artifacts = qualify_relation_extraction(
        [database],
        expected_turns=2,
        expected_raw_digest=str(identity["digest"]),
    )

    assert identity["turns"] == 2
    assert artifacts.report["status"] == "failed"
    assert artifacts.report["funnel"]["relations_persisted"] == 0
    assert artifacts.report["funnel"]["relations_admitted"] == 0
    assert artifacts.report["funnel"]["relations_exact_backtrace"] == 0
    assert artifacts.report["checks"]["graph_projection_schema"] is False
    assert artifacts.report["rejections"] == {
        "missing_graph_projection_schema": 1
    }
    assert "private legacy turn" not in json.dumps(artifacts.report)


def test_mixed_extractor_configs_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "mixed-config.db"
    _seed_corpus(database, turns=2, relations=2)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "select id, payload_json from ir_records "
            "where kind = 'REL' order by id limit 1"
        ).fetchone()
        payload = json.loads(row[1])
        payload["ext"]["extractor_config_fingerprint"] = "different-config"
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                row[0],
            ),
        )

    artifacts = _qualify(database)

    assert artifacts.report["identity"]["config_count"] == 2
    assert artifacts.report["checks"]["single_extractor_config"] is False
    assert artifacts.report["status"] == "failed"
