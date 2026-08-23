"""Track S S7 entity evidence and term-admission regressions."""

from __future__ import annotations

from contextlib import closing

from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.provenance import chain_completeness, resolve_provenance_many
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
            assert all(
                entity.attrs["label"].casefold() in source.casefold()
                for source in chains[entity.id].source_text
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
