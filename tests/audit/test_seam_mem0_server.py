"""Hermetic tests for the SEAM Mem0-OSS facade (no network, no provider calls).

Pins the three-endpoint contract the mem0ai/memory-benchmarks OSS client
depends on, so the shim can't silently drift from the harness it must satisfy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks.external.mem0_harness.seam_mem0_server import (
    SeamMem0Server,
    _apply_count_context_policy,
    _epoch_to_iso,
    _split_speaker,
)
from seam_runtime.retrieval import RetrievalFlags


def test_epoch_to_iso_and_speaker_split():
    assert _epoch_to_iso(1687000000) == "2023-06-17"
    assert _epoch_to_iso(None) == ""
    assert _epoch_to_iso("not-an-int") == ""
    assert _split_speaker("Melanie: I painted a sunrise") == ("Melanie", "I painted a sunrise")
    # no colon convention -> generic speaker, full text preserved
    assert _split_speaker("just some text") == ("user", "just some text")


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
        client = TestClient(build_asgi_app(server))
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
