"""Hermetic tests for the SEAM Mem0-OSS facade (no network, no provider calls).

Pins the three-endpoint contract the mem0ai/memory-benchmarks OSS client
depends on, so the shim can't silently drift from the harness it must satisfy.
"""

from __future__ import annotations

import pytest

from benchmarks.external.mem0_harness.seam_mem0_server import (
    SeamMem0Server,
    _epoch_to_iso,
    _split_speaker,
)


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


def test_asgi_routes_match_mem0_oss_contract(tmp_path):
    fastapi = pytest.importorskip("fastapi")
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
