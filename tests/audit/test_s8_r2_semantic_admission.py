"""Exact semantic retrieval fills pages after canonical field filtering."""

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator.adapters import ChromaSemanticAdapter
from seam_runtime.runtime import SeamRuntime


class _Embedding:
    name = "r2-admission/1"
    dimension = 2

    def embed(self, text):
        return [1.0, 0.0]


@pytest.mark.parametrize("query", [
    "kind:STA", "predicate:keep", "object:keep", "subject:ent:keep",
    "id:clm:z-000,clm:z-001,clm:z-002",
])
@pytest.mark.parametrize("backend", ["sqlite", pytest.param("chroma", marks=pytest.mark.external)])
def test_public_exact_semantic_filters_reach_past_initial_candidate_cutoff(
    tmp_path, monkeypatch, query, backend,
):
    runtime = SeamRuntime(tmp_path / "admission.db", embedding_model=_Embedding(), allow_pgvector_env=False)
    try:
        entities = [
            MIRLRecord(id=record_id, kind=RecordKind.ENT, ns="selected", scope="thread", attrs={"name": record_id})
            for record_id in ("ent:skip", "ent:keep")
        ]
        records = [
            MIRLRecord(
                id=f"clm:a-{index:03d}", kind=RecordKind.CLM, ns="selected", scope="thread",
                attrs={"subject": "ent:skip", "predicate": "skip", "object": "skip"},
            ) for index in range(180)
        ] + [
            MIRLRecord(
                id=f"clm:z-{index:03d}", kind=RecordKind.STA, ns="selected", scope="thread",
                attrs={"subject": "ent:keep", "predicate": "keep", "object": "keep"},
            ) for index in range(3)
        ]
        runtime.store.persist_ir(IRBatch([*entities, *records]))
        runtime.vector_adapter.index_records(records)
        requested_pages = []
        original_load = runtime.store.load_ir

        def load_ir(*args, **kwargs):
            if kwargs.get("ids"):
                requested_pages.append(len(kwargs["ids"]))
            return original_load(*args, **kwargs)

        monkeypatch.setattr(runtime.store, "load_ir", load_ir)
        result = runtime.retrieve(
            query, mode="vector", ns="selected", scope="thread", budget=3,
        )

        assert [candidate.record.id for candidate in result.candidates] == [
            "clm:z-000", "clm:z-001", "clm:z-002",
        ]
        assert requested_pages and max(requested_pages) <= 128
        if backend == "chroma":
            import chromadb
            from chromadb.config import Settings

            directory = str(tmp_path / "chroma")
            adapter = ChromaSemanticAdapter(
                runtime.store, runtime.embedding_model, persist_directory=directory,
                client=chromadb.PersistentClient(
                    path=directory, settings=Settings(anonymized_telemetry=False),
                ),
            )
            adapter.sync_batch(IRBatch(records))
            runtime._retrieval_orchestrator_cached().semantic_adapter = adapter
            chroma_result = runtime.retrieve(
                query, mode="vector", ns="selected", scope="thread", budget=3,
            )

            def public_signature(result):
                return [
                    (candidate.record.to_dict(), candidate.score, list(candidate.sources.values()))
                    for candidate in result.candidates
                ]

            assert public_signature(chroma_result) == public_signature(result)
    finally:
        runtime.close()
