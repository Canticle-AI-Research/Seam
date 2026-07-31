"""Hermetic gates for the local-only LoCoMo REL corpus builder."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from seam_runtime.models import HashEmbeddingModel
from seam_runtime.nl_extract import Extraction, ground_extraction
from tools.relation_extraction_ingest import (
    RELATION_POLICY,
    RelationIngestConfig,
    RelationIngestError,
    build_relation_qualification_corpus,
)
from tools.relation_extraction_qualification import raw_turn_identity


class _FakeGroundedExtractor:
    def __init__(self) -> None:
        self.calls = 0
        self.validations = 0

    def validate_for_derived_facts(self) -> None:
        self.validations += 1

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "provider-free-fixture",
            "model": "fixture-v1",
            "model_digest": "sha256:" + "1" * 64,
            "host": "none",
            "timeout": 1.0,
            "num_predict": 32,
        }

    def extract(self, text: str) -> Extraction:
        self.calls += 1
        words = text.rstrip(".").split()
        if len(words) != 3 or words[1] != "mentors":
            return Extraction()
        subject, relation, obj = words
        return ground_extraction(
            {
                "entities": [
                    {"name": subject, "type": "person"},
                    {"name": obj, "type": "person"},
                ],
                "claims": [
                    {
                        "subject": subject,
                        "relation": relation,
                        "object": obj,
                        "epistemic_basis": "explicit",
                    }
                ],
            },
            text,
        )


def _write_dataset(path: Path, *, duplicate_first_turn: bool = False) -> str:
    payload = [
        {
            "sample_id": "scope-a",
            "conversation": {
                "sessions": [
                    {
                        "date_time": "2024-01-02T09:30:00Z",
                        "dialogs": [
                            {"speaker": "Ada", "text": "Ada mentors Bob."},
                            {"speaker": "Bob", "text": "Bob mentors Cara."},
                        ],
                    }
                ]
            },
            "qa": [
                {
                    "question": "Who mentors Bob?",
                    "answer": "Ada",
                    "category": 1,
                }
            ],
        },
        {
            "sample_id": "scope-b",
            "conversation": {
                "sessions": [
                    {
                        "date_time": "2024-01-03T10:00:00Z",
                        "dialogs": [
                            {"speaker": "Dora", "text": "Dora mentors Eli."}
                        ],
                    }
                ]
            },
            "qa": [
                {
                    "question": "Who mentors Eli?",
                    "answer": "Dora",
                    "category": 1,
                }
            ],
        },
    ]
    if duplicate_first_turn:
        dialogs = payload[0]["conversation"]["sessions"][0]["dialogs"]
        dialogs.append(dict(dialogs[0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config(tmp_path: Path, dataset: Path, digest: str) -> RelationIngestConfig:
    return RelationIngestConfig(
        dataset_path=dataset,
        dataset_sha256=digest,
        scope_id="scope-a",
        output_db=tmp_path / "candidate.db",
        cache_path=tmp_path / "external-cache.sqlite3",
        ollama_model="fixture-model",
        ollama_model_digest="sha256:" + "1" * 64,
        ollama_host="http://127.0.0.1:11434",
        timeout=3.0,
        num_predict=64,
    )


def test_build_pins_source_identity_selects_one_scope_and_backtraces_rel(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    config = _config(tmp_path, dataset, digest)
    extractor = _FakeGroundedExtractor()

    report = build_relation_qualification_corpus(
        config,
        extractor=extractor,
        embedding_model=HashEmbeddingModel(),
    )

    assert report["status"] == "built"
    assert report["provider"] == "injected-extractor-unattested/1"
    assert report["cloud_calls"] is None
    assert report["dataset_sha256"] == digest
    assert report["scope_id"] == "scope-a"
    assert report["relation_policy"] == RELATION_POLICY
    assert report["raw_identity"] == raw_turn_identity([config.output_db])
    assert report["raw_identity"]["turns"] == 2
    assert report["cache"] == {"hits": 0, "misses": 2}
    assert extractor.validations == 1
    assert extractor.calls == 2
    qualification = report["qualification"]
    assert qualification["funnel"]["turns_observed"] == 2
    assert qualification["funnel"]["relations_persisted"] == 2
    assert qualification["funnel"]["relations_exact_backtrace"] == 2
    assert qualification["checks"]["exact_backtrace"] is True

    with sqlite3.connect(config.output_db) as connection:
        namespaces = {
            row[0]
            for row in connection.execute("select distinct ns from ir_records")
        }
        metadata = json.loads(
            connection.execute(
                "select payload_json from ir_records "
                "where json_extract(payload_json, '$.kind') = 'REL' limit 1"
            ).fetchone()[0]
        )["ext"]["extractor"]
    assert namespaces == {"locomo:scope-a"}
    assert metadata["relation_policy"] == RELATION_POLICY
    assert "scope-b" not in json.dumps(report)
    assert "Ada mentors Bob" not in json.dumps(report)


def test_existing_output_is_refused_before_extractor_validation(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    config = _config(tmp_path, dataset, digest)
    config.output_db.write_bytes(b"occupied")
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match="output_database_not_fresh"):
        build_relation_qualification_corpus(config, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


def test_dataset_digest_and_scope_mismatch_fail_before_extraction(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match="dataset_sha256_mismatch"):
        build_relation_qualification_corpus(
            _config(tmp_path, dataset, "0" * 64),
            extractor=extractor,
        )

    missing_scope = _config(tmp_path, dataset, digest)
    missing_scope = RelationIngestConfig(
        **{**missing_scope.__dict__, "scope_id": "missing-scope"}
    )
    with pytest.raises(RelationIngestError, match="scope_id_not_found"):
        build_relation_qualification_corpus(missing_scope, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


@pytest.mark.parametrize(
    ("model", "model_digest", "error"),
    [
        (
            "gemma4:cloud",
            "1" * 64,
            "cloud_backed_ollama_model_rejected",
        ),
        ("local-model", "not-a-digest", "ollama_model_digest_invalid"),
        ("local-model", "1" * 63, "ollama_model_digest_invalid"),
    ],
)
def test_cloud_model_and_malformed_digest_are_rejected_before_extraction(
    tmp_path: Path,
    model: str,
    model_digest: str,
    error: str,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    base = _config(tmp_path, dataset, digest)
    config = RelationIngestConfig(
        **{
            **base.__dict__,
            "ollama_model": model,
            "ollama_model_digest": model_digest,
        }
    )
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match=error):
        build_relation_qualification_corpus(config, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_timeout_is_rejected_before_extraction(
    tmp_path: Path,
    timeout: float,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    base = _config(tmp_path, dataset, digest)
    config = RelationIngestConfig(**{**base.__dict__, "timeout": timeout})
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match="timeout_invalid"):
        build_relation_qualification_corpus(config, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


def test_duplicate_canonical_turn_is_rejected_before_extraction(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset, duplicate_first_turn=True)
    config = _config(tmp_path, dataset, digest)
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match="canonical_source_ref_collision"):
        build_relation_qualification_corpus(config, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


@pytest.mark.parametrize("sidecar", ["-wal", "-shm"])
def test_artifact_cannot_collide_with_cache_sidecar(
    tmp_path: Path,
    sidecar: str,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    base = _config(tmp_path, dataset, digest)
    config = RelationIngestConfig(
        **{
            **base.__dict__,
            "report_path": Path(f"{base.cache_path}{sidecar}"),
        }
    )
    extractor = _FakeGroundedExtractor()

    with pytest.raises(RelationIngestError, match="artifact_path_collision"):
        build_relation_qualification_corpus(config, extractor=extractor)

    assert extractor.validations == 0
    assert extractor.calls == 0


def test_content_cache_replays_into_a_different_fresh_database(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    first = _config(tmp_path, dataset, digest)
    first_extractor = _FakeGroundedExtractor()
    build_relation_qualification_corpus(first, extractor=first_extractor)
    assert first_extractor.calls == 2

    second = RelationIngestConfig(
        **{**first.__dict__, "output_db": tmp_path / "candidate-restart.db"}
    )
    replay_extractor = _FakeGroundedExtractor()
    report = build_relation_qualification_corpus(second, extractor=replay_extractor)

    assert report["cache"] == {"hits": 2, "misses": 0}
    assert replay_extractor.calls == 0
    assert report["raw_identity"] == raw_turn_identity([second.output_db])


def test_report_and_review_template_are_written_atomically(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo.json"
    digest = _write_dataset(dataset)
    base = _config(tmp_path, dataset, digest)
    report_path = tmp_path / "artifacts" / "report.json"
    review_path = tmp_path / "artifacts" / "review.json"
    config = RelationIngestConfig(
        **{
            **base.__dict__,
            "ollama_model_digest": "SHA256:" + "A" * 64,
            "report_path": report_path,
            "review_template_path": review_path,
        }
    )

    report = build_relation_qualification_corpus(
        config,
        extractor=_FakeGroundedExtractor(),
    )

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["schema"] == "relation-extraction-review/1"
    assert len(review["relations"]) == 2
    assert report["model_digest"] == "a" * 64
    assert not list(report_path.parent.glob(".*.tmp"))
