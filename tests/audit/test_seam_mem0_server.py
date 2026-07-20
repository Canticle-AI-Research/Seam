"""Hermetic tests for the SEAM Mem0-OSS facade (no network, no provider calls).

Pins the three-endpoint contract the mem0ai/memory-benchmarks OSS client
depends on, so the shim can't silently drift from the harness it must satisfy.
"""

from __future__ import annotations

import inspect
import sqlite3
from types import SimpleNamespace

import pytest

from benchmarks.external.mem0_harness.seam_mem0_server import (
    SeamMem0Server,
    _apply_count_context_policy,
    _epoch_to_iso,
    _split_speaker,
)
from seam_runtime.derived_fact_context import (
    DERIVED_FACTS_EMBEDDING_CONFIG,
    GROUNDED_CLM_V1,
)
from seam_runtime.mirl import IRBatch, RecordKind, Status
from seam_runtime.nl_extract import Extraction, ground_extraction
from seam_runtime.retrieval import RetrievalFlags


@pytest.fixture(autouse=True)
def _isolated_sqlite_vector_contract(monkeypatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)


class _SurfingExtractor:
    def config_metadata(self):
        return {"type": "test-surfing", "version": 1}

    def extract(self, text: str) -> Extraction:
        if "surfing" not in text.lower():
            return Extraction()
        return ground_extraction(
            {
                "entities": [
                    {"name": "I", "type": "person"},
                    {"name": "surfing", "type": "activity"},
                ],
                "claims": [
                    {
                        "subject": "I",
                        "relation": "like",
                        "object": "surfing",
                        "epistemic_basis": "explicit",
                    }
                ],
            },
            text,
        )


def test_epoch_to_iso_and_speaker_split():
    assert _epoch_to_iso(1687000000) == "2023-06-17"
    assert _epoch_to_iso(None) == ""
    assert _epoch_to_iso("not-an-int") == ""
    assert _split_speaker("Melanie: I painted a sunrise") == (
        "Melanie",
        "I painted a sunrise",
        True,
    )
    # no colon convention -> legacy generic RAW speaker, non-explicit for facts
    assert _split_speaker("just some text") == (
        "user",
        "just some text",
        False,
    )
    assert _split_speaker("[odd]: text") == (
        "[odd]",
        "text",
        False,
    )


@pytest.fixture
def server(tmp_path):
    s = SeamMem0Server(db_path=str(tmp_path / "scopes"))
    yield s
    s.close()


def test_add_search_delete_round_trip(server):
    uid = "conv-1"
    add = server.add({
        "user_id": uid,
        "timestamp": 1687000000,
        "messages": [
            {"role": "user", "content": "Melanie: I painted a lake sunrise last year."},
            {"role": "assistant", "content": "Caroline: Beautiful! What colors?"},
            {"role": "user", "content": "Melanie: Warm oranges, and I adopted a cat named Luna."},
        ],
    })
    assert len(add["results"]) == 3  # three ingested turns

    res = server.search({"user_id": uid, "query": "What did Melanie paint?", "limit": 5})
    memories = res["results"]
    assert memories, "search returned no memories"
    # Mem0-OSS result shape the harness's format_search_results reads:
    for m in memories:
        assert set(m) >= {"memory", "score", "id"}
        assert isinstance(m["memory"], str) and m["memory"]
    # the relevant turn is retrieved and carries its date inline
    joined = " ".join(m["memory"].lower() for m in memories)
    assert "sunrise" in joined or "painted" in joined
    assert "2023-06-17" in " ".join(m["memory"] for m in memories)

    assert "deleted" in server.delete_user(uid)["message"]


def test_empty_messages_and_blank_content_are_skipped(server):
    out = server.add({"user_id": "conv-2", "messages": [
        {"role": "user", "content": "   "},
        {"role": "user", "content": ""},
    ]})
    assert out["results"] == []


def test_first_add_after_restart_preserves_persisted_user_memories(tmp_path):
    db_root = str(tmp_path / "scopes")
    uid = "resume-user"

    first = SeamMem0Server(db_path=db_root)
    try:
        first.add({
            "user_id": uid,
            "timestamp": 1687000000,
            "messages": [{
                "role": "user",
                "content": "Melanie: I painted a lake sunrise.",
            }],
        })
    finally:
        first.close()

    resumed = SeamMem0Server(db_path=db_root)
    try:
        resumed.add({
            "user_id": uid,
            "timestamp": 1687086400,
            "messages": [{
                "role": "user",
                "content": "Melanie: I later adopted a cat named Luna.",
            }],
        })
        batch = resumed._adapter._runtime(uid).store.load_ir(ns=f"locomo:{uid}")
        raw_contents = {
            record.attrs.get("content")
            for record in batch.records
            if record.kind.value == "RAW"
        }
        assert any("lake sunrise" in content for content in raw_contents if content)
        assert any("cat named Luna" in content for content in raw_contents if content)
    finally:
        resumed.close()


def test_add_requires_user_id_and_messages(server):
    with pytest.raises(ValueError):
        server.add({"messages": []})
    with pytest.raises(ValueError):
        server.search({"user_id": "x", "query": "  "})


def test_user_scopes_are_isolated(server):
    server.add({"user_id": "a", "timestamp": 1687000000,
                "messages": [{"role": "user", "content": "Ana: I live in Seattle."}]})
    server.add({"user_id": "b", "timestamp": 1687000000,
                "messages": [{"role": "user", "content": "Ben: I live in Denver."}]})
    a = server.search({"user_id": "a", "query": "where does the speaker live", "limit": 10})
    joined_a = " ".join(m["memory"] for m in a["results"])
    assert "Seattle" in joined_a
    assert "Denver" not in joined_a  # cross-user leakage would fail the head-to-head


def test_grounded_clm_policy_serves_readable_fact_with_raw_provenance(
    monkeypatch,
    tmp_path,
):
    server = SeamMem0Server(
        db_path=str(tmp_path / "derived-scopes"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_SurfingExtractor(),
    )
    try:
        monkeypatch.setenv(
            "SEAM_PGVECTOR_DSN",
            "postgresql://invalid.local/seam",
        )
        monkeypatch.setenv("SEAM_EMBEDDING_PROVIDER", "openai")
        server.add({
            "user_id": "derived-user",
            "timestamp": 1687000000,
            "messages": [
                {
                    "role": "user",
                    "content": "John: I like surfing.",
                },
                {
                    "role": "assistant",
                    "content": "Caroline: That sounds fun.",
                },
                {
                    "role": "user",
                    "content": "John: The weather was sunny.",
                },
                {
                    "role": "assistant",
                    "content": "Caroline: The beach was nearby.",
                },
                {
                    "role": "user",
                    "content": "John: I packed a blue towel.",
                },
            ],
        })
        results = server.search({
            "user_id": "derived-user",
            "query": "What sport does John like?",
            "limit": 10,
        })["results"]

        facts = [
            item for item in results
            if str(item["id"]).startswith("clm:")
        ]
        assert facts
        runtime = server._adapter._runtime("derived-user")
        assert type(runtime.vector_adapter).__name__ == "SQLiteVectorAdapter"
        assert (
            runtime.embedding_model.name
            == DERIVED_FACTS_EMBEDDING_CONFIG["name"]
        )
        assert (
            runtime.embedding_model.dimension
            == DERIVED_FACTS_EMBEDDING_CONFIG["dimension"]
        )
        assert facts[0]["memory"].startswith("SEAM-FACT/1|")
        assert '"subject":"John"' in facts[0]["memory"]
        assert '"object":"surfing"' in facts[0]["memory"]
        assert "SEAM-SOURCE/1|" in facts[0]["memory"]

        fact_payload = facts[0]["memory"].splitlines()[0]
        import json

        source_raw_id = json.loads(fact_payload.split("|", 1)[1])[
            "source_raw_id"
        ]
        assert source_raw_id in {str(item["id"]) for item in results}
        assert any(
            "I like surfing" in str(item["memory"])
            for item in results
            if item["id"] == source_raw_id
        )
    finally:
        server.close()


def test_grounded_clm_policy_never_crosses_user_namespace(tmp_path):
    server = SeamMem0Server(
        db_path=str(tmp_path / "derived-isolation"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_SurfingExtractor(),
    )
    try:
        server.add({
            "user_id": "a",
            "messages": [{
                "role": "user",
                "content": "John: I like surfing.",
            }],
        })
        server.add({
            "user_id": "b",
            "messages": [{
                "role": "user",
                "content": "Maya: I like painting.",
            }],
        })
        results = server.search({
            "user_id": "b",
            "query": "Who likes surfing?",
            "limit": 10,
        })["results"]
        assert all("surfing" not in str(item["memory"]).lower() for item in results)
        assert all(not str(item["id"]).startswith("clm:") for item in results)
    finally:
        server.close()


@pytest.mark.parametrize("retired_kind", [RecordKind.SPAN, RecordKind.RAW])
def test_grounded_clm_policy_requires_live_assertable_provenance_chain(
    tmp_path,
    retired_kind,
):
    server = SeamMem0Server(
        db_path=str(tmp_path / f"retired-{retired_kind.value.lower()}"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_SurfingExtractor(),
    )
    try:
        server.add({
            "user_id": "retired-source",
            "messages": [{
                "role": "user",
                "content": "John: I like surfing.",
            }],
        })
        runtime = server._adapter._runtime("retired-source")
        batch = runtime.store.load_ir(ns="locomo:retired-source")
        rich_claim = next(
            record
            for record in batch.records
            if record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
        )
        by_id = batch.by_id()
        span = by_id[rich_claim.evidence[0]]
        raw = by_id[span.attrs["raw_id"]]
        retired = span if retired_kind == RecordKind.SPAN else raw
        retired.status = Status.SUPERSEDED
        runtime.persist_ir(IRBatch([retired]))

        assert server._search_derived_facts(
            "retired-source",
            "What does John like?",
            10,
        ) == []
    finally:
        server.close()


def test_grounded_clm_policy_does_not_attribute_unlabeled_first_person_to_role(
    tmp_path,
):
    server = SeamMem0Server(
        db_path=str(tmp_path / "derived-unlabeled"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_SurfingExtractor(),
    )
    try:
        server.add({
            "user_id": "unlabeled",
            "messages": [{
                "role": "assistant",
                "content": "I like surfing.",
            }],
        })
        batch = server._adapter._runtime("unlabeled").store.load_ir(
            ns="locomo:unlabeled",
        )
        assert not any(
            record.ext.get("derived_fact_policy") == GROUNDED_CLM_V1
            for record in batch.records
        )
        raw = next(
            record
            for record in batch.records
            if record.kind.value == "RAW"
        )
        assert raw.attrs["content"] == "[user ] I like surfing."
    finally:
        server.close()


def test_delete_user_purges_unshared_derived_fact_cache_rows(tmp_path):
    server = SeamMem0Server(
        db_path=str(tmp_path / "derived-delete"),
        derived_facts_policy=GROUNDED_CLM_V1,
        nl_extractor=_SurfingExtractor(),
    )
    try:
        server.add({
            "user_id": "delete-me",
            "messages": [{
                "role": "user",
                "content": "John: I like surfing.",
            }],
        })
        cache_path = (
            server._adapter._derived_facts.config.cache_path
        )
        with sqlite3.connect(cache_path) as connection:
            assert connection.execute(
                "select count(*) from derived_fact_cache",
            ).fetchone()[0] == 1

        server.delete_user("delete-me")

        with sqlite3.connect(cache_path) as connection:
            assert connection.execute(
                "select count(*) from derived_fact_cache",
            ).fetchone()[0] == 0
            assert connection.execute(
                "select count(*) from derived_fact_cache_owners",
            ).fetchone()[0] == 0
    finally:
        server.close()


def test_retrieve_passes_temporal_constraints_to_search():
    captured = {}
    runtime = SimpleNamespace(
        search_ir=lambda query, **kwargs: (
            captured.update(query=query, **kwargs)
            or SimpleNamespace(candidates=[])
        ),
    )
    adapter = SimpleNamespace(
        _runtime=lambda user_id: runtime,
        _build_temporal_window=lambda query: "window-sentinel",
        _build_temporal_reference=lambda user_id, query: "reference-sentinel",
    )
    server = SeamMem0Server.__new__(SeamMem0Server)
    server._adapter = adapter

    assert server._retrieve("conv-temporal", "What happened last May?", 7) == []
    assert captured["temporal_window"] == "window-sentinel"
    assert captured["temporal_reference"] == "reference-sentinel"
    assert captured["ns"] == "locomo:conv-temporal"
    assert captured["budget"] == 7


def test_retrieve_expands_span_raw_id_before_filtering():
    def kind(value):
        return SimpleNamespace(value=value)

    candidate_record = SimpleNamespace(
        id="claim-1",
        evidence=["span-1"],
        prov=[],
        kind=kind("CLM"),
        attrs={},
    )
    candidate = SimpleNamespace(record=candidate_record, score=0.91)
    span = SimpleNamespace(
        id="span-1",
        kind=kind("SPAN"),
        attrs={"raw_id": "raw-1"},
    )
    raw = SimpleNamespace(
        id="raw-1",
        kind=kind("RAW"),
        attrs={"content": "[Melanie 2023-06-17] I painted a sunrise."},
    )

    class FakeStore:
        def __init__(self):
            self.loaded_ids = []

        def load_ir(self, *, ids):
            self.loaded_ids.append(list(ids))
            records = [candidate_record, span]
            if "raw-1" in ids:
                records.append(raw)
            return SimpleNamespace(records=records)

    store = FakeStore()
    runtime = SimpleNamespace(
        store=store,
        search_ir=lambda query, **kwargs: SimpleNamespace(candidates=[candidate]),
    )
    adapter = SimpleNamespace(
        _runtime=lambda user_id: runtime,
        _build_temporal_window=lambda query: None,
        _build_temporal_reference=lambda user_id, query: None,
    )
    server = SeamMem0Server.__new__(SeamMem0Server)
    server._adapter = adapter

    results = server._retrieve("conv-span", "What did Melanie paint?", 5)

    assert store.loaded_ids == [
        ["claim-1", "span-1"],
        ["claim-1", "span-1", "raw-1"],
    ]
    assert results == [{
        "memory": "[Melanie 2023-06-17] I painted a sunrise.",
        "score": 0.91,
        "id": "raw-1",
        "created_at": "",
    }]


def test_count_context_policy_off_preserves_results_byte_for_byte():
    results = [
        {
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.8,
            "id": "raw:1",
            "created_at": "2023-03-01",
        }
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags()
    )

    assert _apply_count_context_policy(
        runtime, "How many tournaments did Nate win?", results, 10
    ) is results


def test_count_context_policy_prepends_projection_and_preserves_raw_provenance():
    results = [
        {
            "memory": "[Nate 2023-03-03] I will enter a tournament next week.",
            "score": 0.9,
            "id": "raw:plan",
            "created_at": "2023-03-03",
        },
        {
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.7,
            "id": "raw:observed",
            "created_at": "2023-03-01",
        },
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags(
            count_context_policy="event-count/distinct/1"
        )
    )

    projected = _apply_count_context_policy(
        runtime, "How many tournaments did Nate win?", results, 3
    )

    assert len(projected) == 3
    assert projected[0]["id"].startswith("seam-count:")
    assert projected[0]["memory"].startswith("SEAM-COUNT/1|")
    assert projected[1]["id"] == "raw:observed"
    assert {item["id"] for item in projected[1:]} == {
        "raw:observed",
        "raw:plan",
    }


def test_count_context_v2_renders_explicit_same_event_groups():
    results = [
        {
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.9,
            "id": "raw:win",
            "created_at": "2023-03-01",
        },
        {
            "memory": "[Nate 2023-03-01] Winning that tournament felt great.",
            "score": 0.8,
            "id": "raw:followup",
            "created_at": "2023-03-01",
        },
        {
            "memory": "[Nate 2023-04-01] I won another tournament.",
            "score": 0.7,
            "id": "raw:another",
            "created_at": "2023-04-01",
        },
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags(
            count_context_policy="event-count/distinct/2"
        )
    )

    projected = _apply_count_context_policy(
        runtime, "How many tournaments did Nate win?", results, 4
    )

    assert projected[0]["memory"].startswith("SEAM-COUNT/2|")
    assert "direct_match_group_count=2" in projected[0]["memory"]
    assert '"member_count":2' in projected[0]["memory"]
    assert all(raw_id in projected[0]["memory"] for raw_id in {
        "raw:win",
        "raw:followup",
        "raw:another",
    })


def test_count_context_at_capacity_references_only_retained_raw_records():
    results = [
        {
            "memory": f"[Nate 2023-03-0{index}] I won tournament {index}.",
            "score": 1.0 - index / 10,
            "id": f"raw:{index}",
            "created_at": f"2023-03-0{index}",
        }
        for index in range(1, 4)
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags(
            count_context_policy="event-count/distinct/1"
        )
    )

    projected = _apply_count_context_policy(
        runtime, "How many tournaments did Nate win?", results, 3
    )

    assert len(projected) == 3
    retained_ids = {item["id"] for item in projected[1:]}
    projection_text = projected[0]["memory"]
    for raw_id in retained_ids:
        assert raw_id in projection_text
    dropped_ids = {item["id"] for item in results} - retained_ids
    for raw_id in dropped_ids:
        assert raw_id not in projection_text


def test_count_context_policy_does_not_change_non_count_queries():
    results = [
        {
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.8,
            "id": "raw:1",
            "created_at": "2023-03-01",
        }
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags(
            count_context_policy="event-count/distinct/1"
        )
    )

    assert _apply_count_context_policy(
        runtime, "Which tournament did Nate win?", results, 10
    ) is results


def test_specialized_count_projection_takes_precedence_over_derived_facts():
    raw = [
        {
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.9,
            "id": "raw:win",
            "created_at": "2023-03-01",
        },
        {
            "memory": "[Nate 2023-03-02] I will enter another tournament.",
            "score": 0.8,
            "id": "raw:plan",
            "created_at": "2023-03-02",
        },
    ]
    runtime = SimpleNamespace(
        _retrieval_flags_cached=lambda: RetrievalFlags(
            count_context_policy="event-count/distinct/1"
        )
    )
    adapter = SimpleNamespace(_runtime=lambda user_id: runtime)
    server = SeamMem0Server.__new__(SeamMem0Server)
    server._adapter = adapter
    server._derived_facts_policy = GROUNDED_CLM_V1
    server._search_raw = lambda user_id, query, limit: raw
    server._apply_second_hop_policy = (
        lambda user_id, query, results, limit: results
    )
    server._search_derived_facts = lambda *args: pytest.fail(
        "derived facts must not run after a specialized projection"
    )

    results = server._retrieve(
        "count-user",
        "How many tournaments did Nate win?",
        3,
    )
    assert results[0]["memory"].startswith("SEAM-COUNT/1|")
    assert all(
        not str(item["memory"]).startswith("SEAM-FACT/1|")
        for item in results
    )


def test_count_context_policy_env_reaches_real_facade(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAM_COUNT_CONTEXT_POLICY", "event-count/distinct/1")
    server = SeamMem0Server(db_path=str(tmp_path / "count-scopes"))
    try:
        server.add(
            {
                "user_id": "count-user",
                "timestamp": 1687000000,
                "messages": [
                    {
                        "role": "user",
                        "content": "Nate: I won a tournament yesterday.",
                    },
                    {
                        "role": "user",
                        "content": "Nate: I will enter another tournament next week.",
                    },
                ],
            }
        )
        results = server.search(
            {
                "user_id": "count-user",
                "query": "How many tournaments did Nate win?",
                "limit": 10,
            }
        )["results"]

        assert results[0]["id"].startswith("seam-count:")
        assert results[0]["memory"].startswith("SEAM-COUNT/1|")
        assert any(item["id"].startswith("raw:") for item in results[1:])
    finally:
        server.close()


def test_asgi_routes_match_mem0_oss_contract(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from benchmarks.external.mem0_harness.seam_mem0_server import build_asgi_app

    server = SeamMem0Server(db_path=str(tmp_path / "scopes"))
    try:
        app = build_asgi_app(server)
        blocking_paths = {"/memories", "/search"}
        assert all(
            not inspect.iscoroutinefunction(route.endpoint)
            for route in app.routes
            if getattr(route, "path", None) in blocking_paths
        )
        client = TestClient(app)
        assert client.get("/health").json() == {"status": "ok"}
        r = client.post("/memories", json={
            "user_id": "conv-x", "timestamp": 1687000000,
            "messages": [{"role": "user", "content": "Sam: I took up kayaking in October."}],
        })
        assert r.status_code == 200 and "results" in r.json()
        s = client.post("/search", json={"user_id": "conv-x", "query": "new activity", "limit": 5})
        assert s.status_code == 200
        assert any("kayaking" in m["memory"].lower() for m in s.json()["results"])
        d = client.request("DELETE", "/memories", json={"user_id": "conv-x"})
        assert d.status_code == 200
    finally:
        server.close()
