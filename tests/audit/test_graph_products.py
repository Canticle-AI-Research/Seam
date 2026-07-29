from __future__ import annotations

import random
import sqlite3

import pytest

from seam_runtime.graph_products import (
    GraphProductFact,
    graph_product_history,
    init_graph_products,
    read_graph_products,
    update_graph_products,
)


def _fact(
    record_id: str,
    episode_ids: tuple[str, ...],
    subject_id: str,
    subject_label: str,
    predicate: str,
    object_id: str | None,
    object_label: str,
    *,
    ns: str = "acme",
    scope: str = "thread-1",
    trust_state: str = "verified",
    current: bool = True,
) -> GraphProductFact:
    return GraphProductFact(
        ns=ns,
        scope=scope,
        record_id=record_id,
        episode_ids=episode_ids,
        subject_id=subject_id,
        subject_label=subject_label,
        predicate=predicate,
        object_id=object_id,
        object_label=object_label,
        trust_state=trust_state,
        current=current,
    )


def _connected_facts() -> list[GraphProductFact]:
    return [
        _fact(
            "rel:1",
            ("episode:1",),
            "ent:ada",
            "Ada",
            "works_on",
            "ent:seam",
            "SEAM",
        ),
        _fact(
            "rel:2",
            ("episode:2",),
            "ent:ada",
            "Ada",
            "works_on",
            "ent:compiler",
            "compiler",
            trust_state="supported",
        ),
    ]


def test_products_are_deterministic_and_identical_rebuild_is_reused() -> None:
    connection = sqlite3.connect(":memory:")
    init_graph_products(connection)
    facts = _connected_facts()

    first = update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=facts,
        created_at="2026-07-29T10:00:00+00:00",
    )
    shuffled = list(facts)
    random.Random(7).shuffle(shuffled)
    second = update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=shuffled,
        created_at="2099-01-01T00:00:00+00:00",
    )

    assert second["reused"] is True
    assert second["build_id"] == first["build_id"]
    assert connection.execute(
        "select count(*) from graph_product_build"
    ).fetchone()[0] == 1
    products = read_graph_products(
        connection, namespace="acme", scope="thread-1"
    )
    assert [item["kind"] for item in products] == [
        "community_summary",
        "entity_summary",
        "entity_summary",
        "entity_summary",
        "observation",
    ]
    community = products[0]
    assert community["payload"]["member_ids"] == [
        "ent:ada",
        "ent:compiler",
        "ent:seam",
    ]


def test_current_trust_boundary_and_provenance_gates_fail_closed() -> None:
    connection = sqlite3.connect(":memory:")
    facts = [
        _fact(
            "rel:trusted",
            ("episode:trusted",),
            "ent:a",
            "A",
            "uses",
            "ent:b",
            "B",
        ),
        _fact(
            "rel:untrusted",
            ("episode:secret",),
            "ent:a",
            "A",
            "reveals",
            "ent:x",
            "SECRET",
            trust_state="unverified",
        ),
        _fact(
            "rel:stale",
            ("episode:stale",),
            "ent:a",
            "A",
            "formerly_used",
            "ent:y",
            "STALE",
            current=False,
        ),
        _fact(
            "rel:other-tenant",
            ("episode:other",),
            "ent:a",
            "A",
            "leaks",
            "ent:z",
            "OTHER",
            ns="other",
        ),
        _fact(
            "rel:no-episode",
            (),
            "ent:a",
            "A",
            "missing",
            "ent:m",
            "MISSING",
        ),
    ]
    result = update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=facts,
    )

    assert result["accepted_fact_count"] == 1
    assert result["rejected_fact_count"] == 4
    rendered = repr(
        read_graph_products(
            connection, namespace="acme", scope="thread-1"
        )
    )
    assert "SECRET" not in rendered
    assert "STALE" not in rendered
    assert "OTHER" not in rendered
    assert "MISSING" not in rendered


def test_every_derived_sentence_has_exact_record_and_episode_ids() -> None:
    connection = sqlite3.connect(":memory:")
    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=_connected_facts(),
    )

    products = read_graph_products(
        connection, namespace="acme", scope="thread-1"
    )
    assert products
    for product in products:
        assert product["sentences"]
        for sentence in product["sentences"]:
            assert sentence["text"].strip()
            assert sentence["supporting_record_ids"]
            assert sentence["supporting_episode_ids"]
            assert set(sentence["supporting_record_ids"]) <= {"rel:1", "rel:2"}
            assert set(sentence["supporting_episode_ids"]) <= {
                "episode:1",
                "episode:2",
            }

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "update graph_product_sentence set sentence_text = 'rewritten'"
        )


def test_latest_reads_are_tenant_isolated() -> None:
    connection = sqlite3.connect(":memory:")
    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=_connected_facts(),
    )
    update_graph_products(
        connection,
        namespace="beta",
        scope="thread-1",
        facts=[
            _fact(
                "rel:beta",
                ("episode:beta",),
                "ent:beta",
                "Beta",
                "owns",
                "ent:private",
                "Private",
                ns="beta",
            )
        ],
    )

    acme = read_graph_products(
        connection, namespace="acme", scope="thread-1"
    )
    beta = read_graph_products(
        connection, namespace="beta", scope="thread-1"
    )
    assert "Beta" not in repr(acme)
    assert "Ada" not in repr(beta)
    assert {item["namespace"] for item in acme} == {"acme"}
    assert {item["namespace"] for item in beta} == {"beta"}


def test_product_evolution_is_versioned_and_old_versions_remain_readable() -> None:
    connection = sqlite3.connect(":memory:")
    original = [
        _fact(
            "rel:1",
            ("episode:1",),
            "ent:ada",
            "Ada",
            "uses",
            "ent:sqlite",
            "SQLite",
        )
    ]
    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=original,
    )
    changed = [
        *original,
        _fact(
            "rel:2",
            ("episode:2",),
            "ent:ada",
            "Ada",
            "uses",
            "ent:pg",
            "Postgres",
        ),
    ]
    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=changed,
    )

    current = read_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        kinds=["entity_summary"],
        subject_id="ent:ada",
    )
    assert current[0]["version"] == 2
    history = graph_product_history(
        connection,
        namespace="acme",
        scope="thread-1",
        stable_key="entity:ent:ada",
    )
    assert [item["version"] for item in history] == [2, 1]
    assert "Postgres" in repr(history[0])
    assert "Postgres" not in repr(history[1])

    reverted = update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=original,
    )
    assert reverted["reused"] is False
    latest = read_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        kinds=["entity_summary"],
        subject_id="ent:ada",
    )
    assert latest[0]["version"] == 3
    assert "Postgres" not in repr(latest[0])


def test_observations_require_two_distinct_eligible_episodes() -> None:
    connection = sqlite3.connect(":memory:")
    one_episode = [
        _fact(
            "clm:1",
            ("episode:1",),
            "ent:ada",
            "Ada",
            "prefers",
            None,
            "dark mode",
        ),
        _fact(
            "clm:rejected",
            ("episode:2",),
            "ent:ada",
            "Ada",
            "prefers",
            None,
            "compact mode",
            trust_state="contested",
        ),
    ]
    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=one_episode,
    )
    assert read_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        kinds=["observation"],
    ) == []

    update_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        facts=[
            one_episode[0],
            _fact(
                "clm:2",
                ("episode:2",),
                "ent:ada",
                "Ada",
                "prefers",
                None,
                "compact mode",
                trust_state="supported",
            ),
        ],
    )
    observations = read_graph_products(
        connection,
        namespace="acme",
        scope="thread-1",
        kinds=["observation"],
    )
    assert len(observations) == 1
    sentence = observations[0]["sentences"][0]
    assert sentence["supporting_record_ids"] == ["clm:1", "clm:2"]
    assert sentence["supporting_episode_ids"] == ["episode:1", "episode:2"]
