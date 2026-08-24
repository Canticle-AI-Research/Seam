"""Track S S7 entity evidence and term-admission regressions."""

from __future__ import annotations

from contextlib import closing

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.provenance import chain_completeness, resolve_provenance_many
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.runtime import SeamRuntime


def test_compiled_entities_have_exact_span_to_raw_evidence(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "entity-evidence.db", allow_pgvector_env=False)
    try:
        batch = compile_nl(
            "Priya met Alex Morgan in New York City.",
            source_ref="fixture://s7/entity-evidence",
            ns="s7",
            scope="thread",
            allow_env_extractor=False,
        )
        entities = batch.kind(RecordKind.ENT)

        assert {record.attrs["label"] for record in entities} >= {
            "Priya",
            "Alex Morgan",
            "New York City",
        }
        assert all(record.evidence for record in entities)

        runtime.persist_ir(batch)
        stored = runtime.store.load_ir(ids=[record.id for record in entities]).records
        chains = resolve_provenance_many(runtime.store, stored)

        assert chain_completeness(list(chains.values())) == {
            "contract": "provenance-chain/1",
            "total": len(entities),
            "complete": len(entities),
            "completeness": 1.0,
            "defects": {},
        }
        for entity in stored:
            assert chains[entity.id].source_text == (
                "Priya met Alex Morgan in New York City.",
            )
    finally:
        runtime.close()


def test_repeated_entity_retains_every_exact_mention_span() -> None:
    batch = compile_nl(
        "Priya met Alex Morgan. Alex Morgan thanked Priya.",
        source_ref="fixture://s7/repeated-entity",
        ns="s7",
        scope="thread",
        allow_env_extractor=False,
    )
    entities = {
        str(record.attrs["label"]): record
        for record in batch.kind(RecordKind.ENT)
    }

    assert len(entities["Priya"].evidence) == 2
    assert len(entities["Alex Morgan"].evidence) == 2
    assert len(set(entities["Priya"].evidence)) == 2
    assert len(set(entities["Alex Morgan"].evidence)) == 2
    records = {record.id: record for record in batch.records}
    raw = next(record for record in batch.records if record.kind is RecordKind.RAW)
    expected_propositions = {
        "Priya met Alex Morgan.",
        "Alex Morgan thanked Priya.",
    }
    for label in ("Priya", "Alex Morgan"):
        assert {
            raw.attrs["content"][
                records[span_id].attrs["start"] : records[span_id].attrs["end"]
            ]
            for span_id in entities[label].evidence
        } == expected_propositions


def test_every_retrieved_entity_has_exact_source_coverage(tmp_path) -> None:
    runtime = SeamRuntime(tmp_path / "retrieved-entity-evidence.db", allow_pgvector_env=False)
    try:
        source_texts = (
            "Priya met Alex Morgan in New York City.",
            "Alex Morgan reviewed the Aurora Project with Jordan Lee.",
            "Jordan Lee thanked Priya after the Aurora Project review.",
        )
        for index, source_text in enumerate(source_texts):
            runtime.persist_ir(
                compile_nl(
                    source_text,
                    source_ref=f"fixture://s7/retrieved-entity/{index}",
                    ns="s7",
                    scope="thread",
                    allow_env_extractor=False,
                )
            )

        stored = runtime.store.load_ir(ns="s7", scope="thread")
        entities = {
            str(record.attrs["label"]): record
            for record in stored.kind(RecordKind.ENT)
        }
        expected_labels = {
            "Priya",
            "Alex Morgan",
            "New York City",
            "Aurora Project",
            "Jordan Lee",
        }
        assert expected_labels <= set(entities)
        relations = (
            ("Priya", "met", "Alex Morgan"),
            ("Alex Morgan", "located_in", "New York City"),
            ("Alex Morgan", "uses", "Aurora Project"),
            ("Jordan Lee", "reviews_with", "Alex Morgan"),
        )
        runtime.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=f"rel:s7-entity-coverage:{index}",
                        kind=RecordKind.REL,
                        ns="s7",
                        scope="thread",
                        evidence=list(entities[source].evidence),
                        attrs={
                            "src": entities[source].id,
                            "predicate": predicate,
                            "dst": entities[target].id,
                        },
                    )
                    for index, (source, predicate, target) in enumerate(relations)
                ]
            )
        )

        orchestrator = RetrievalOrchestrator(runtime)
        retrieved: dict[str, MIRLRecord] = {}
        for query in sorted(expected_labels):
            result = orchestrator.search(
                query,
                namespace="s7",
                scope="thread",
                budget=20,
                mode="graph",
                include_provenance=True,
            )
            for candidate in result.candidates:
                if candidate.record.kind is not RecordKind.ENT:
                    continue
                assert candidate.provenance is not None
                retrieved[candidate.record.id] = candidate.record

        assert {str(record.attrs["label"]) for record in retrieved.values()} == expected_labels
        chains = resolve_provenance_many(runtime.store, list(retrieved.values()))
        assert chain_completeness(list(chains.values())) == {
            "contract": "provenance-chain/1",
            "total": len(expected_labels),
            "complete": len(expected_labels),
            "completeness": 1.0,
            "defects": {},
        }
        for entity in retrieved.values():
            label = str(entity.attrs["label"]).casefold()
            assert any(label in source.casefold() for source in chains[entity.id].source_text)
    finally:
        runtime.close()


def test_entity_term_admission_rejects_stopword_only_and_keeps_multiword(
    tmp_path,
) -> None:
    runtime = SeamRuntime(tmp_path / "entity-terms.db", allow_pgvector_env=False)
    try:
        runtime.persist_ir(
            compile_nl(
                "We met New York City officials.",
                source_ref="fixture://s7/entity-terms",
                ns="s7",
                scope="thread",
                allow_env_extractor=False,
            )
        )
        with closing(runtime.store._connect()) as connection:
            terms = {
                str(row[0])
                for row in connection.execute(
                    "select normalized_term from knowledge_node_terms"
                ).fetchall()
            }

        assert "we" not in terms
        assert "new york city" in terms
    finally:
        runtime.close()
