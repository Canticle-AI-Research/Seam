"""Graph maturity stage G2: reversible identity resolution ledger.

Contract under test: alias candidates, merge evidence, canonical-of links,
undo/split, and conflict states, with the hard acceptance boundary that no
merge is ever silently destructive and old identities plus their supporting
evidence stay auditable -- and that accepted decisions survive the projection
drop+rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seam_runtime.cli import run_cli
from seam_runtime.identity_resolution import (
    STATUS_ACCEPTED,
    STATUS_CONFLICT,
    STATUS_PROPOSED,
    STATUS_SPLIT,
    IdentityMergeError,
    accept_merge,
    apply_identity_merges,
    generate_merge_candidates,
    list_merges,
    merge_audit,
    propose_merge,
    resolve_canonical,
    split_merge,
)
from seam_runtime.knowledge_graph import init_knowledge_graph
from seam_runtime.mcp import TOOL_METADATA, dispatch_tool
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "knowledge.db")
    try:
        yield instance
    finally:
        instance.close()


def _seed_entities(runtime: SeamRuntime) -> None:
    """Two real entity nodes we can address by stable id."""
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:ibm",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": "IBM", "entity_type": "org"},
                ),
                MIRLRecord(
                    id="ent:ibm-corp",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": "International Business Machines", "entity_type": "org"},
                ),
            ]
        )
    )


def test_propose_then_accept_resolves_alias_to_canonical(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        merge_id = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
            evidence=[("symbol-expansion", "IBM = International Business Machines", "ent:ibm")],
            confidence=0.9,
        )
        connection.commit()

        # A proposal is non-committal: no resolution yet.
        assert (
            resolve_canonical(connection, "ent:ibm-corp", ns="people", scope="project")
            == "ent:ibm-corp"
        )

        assert accept_merge(connection, merge_id) == STATUS_ACCEPTED
        connection.commit()

        assert (
            resolve_canonical(connection, "ent:ibm-corp", ns="people", scope="project")
            == "ent:ibm"
        )
        # An unrelated / canonical node resolves to itself.
        assert (
            resolve_canonical(connection, "ent:ibm", ns="people", scope="project")
            == "ent:ibm"
        )


def test_self_merge_is_rejected(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        with pytest.raises(IdentityMergeError):
            propose_merge(
                connection,
                canonical_node_id="ent:ibm",
                alias_node_id="ent:ibm",
                ns="people",
                scope="project",
            )


def test_split_is_reversible_and_evidence_is_retained(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        merge_id = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
            evidence=[("operator", "confirmed same org", None)],
        )
        accept_merge(connection, merge_id)
        connection.commit()

        split_merge(connection, merge_id, reason="was a mistake")
        connection.commit()

        # Split undoes resolution but does not delete the decision.
        assert (
            resolve_canonical(connection, "ent:ibm-corp", ns="people", scope="project")
            == "ent:ibm-corp"
        )
        audit = merge_audit(connection, "ent:ibm-corp")
        assert len(audit) == 1
        assert audit[0]["status"] == STATUS_SPLIT
        assert audit[0]["superseded_by"].startswith("split:")
        # Evidence survives the split -- the original justification stays auditable.
        assert audit[0]["evidence"] == [
            {
                "evidence_kind": "operator",
                "detail": "confirmed same org",
                "source_record_id": None,
                "created_at": audit[0]["evidence"][0]["created_at"],
            }
        ]


def test_reverse_merge_is_flagged_conflict_not_applied(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        first = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
        )
        accept_merge(connection, first)
        connection.commit()

        reverse = propose_merge(
            connection,
            canonical_node_id="ent:ibm-corp",
            alias_node_id="ent:ibm",
            ns="people",
            scope="project",
        )
        connection.commit()

        rows = {m["id"]: m for m in list_merges(connection)}
        assert rows[reverse]["status"] == STATUS_CONFLICT
        assert rows[reverse]["reason"] == "reverse merge already recorded"
        # The original decision is untouched.
        assert rows[first]["status"] == STATUS_ACCEPTED


def test_cycle_creating_accept_is_flagged_conflict(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id=f"ent:node-{n}",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": f"Node {n}", "entity_type": "org"},
                )
                for n in ("a", "b", "c")
            ]
        )
    )
    with runtime.store._pool.checkout() as connection:
        # a <- b, b <- c accepted; then propose c <- a which would close a cycle.
        m1 = propose_merge(
            connection,
            canonical_node_id="ent:node-a",
            alias_node_id="ent:node-b",
            ns="people",
            scope="project",
        )
        accept_merge(connection, m1)
        m2 = propose_merge(
            connection,
            canonical_node_id="ent:node-b",
            alias_node_id="ent:node-c",
            ns="people",
            scope="project",
        )
        accept_merge(connection, m2)
        connection.commit()

        cyclic = propose_merge(
            connection,
            canonical_node_id="ent:node-c",
            alias_node_id="ent:node-a",
            ns="people",
            scope="project",
        )
        connection.commit()
        rows = {m["id"]: m for m in list_merges(connection)}
        assert rows[cyclic]["status"] == STATUS_CONFLICT
        assert rows[cyclic]["reason"] == "merge would create an identity cycle"
        # Transitive resolution still works over the acyclic accepted chain.
        assert (
            resolve_canonical(connection, "ent:node-c", ns="people", scope="project")
            == "ent:node-a"
        )


def test_alias_absorbed_twice_is_conflict(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id=f"ent:x{n}",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": f"X{n}", "entity_type": "org"},
                )
                for n in (1, 2, 3)
            ]
        )
    )
    with runtime.store._pool.checkout() as connection:
        m1 = propose_merge(
            connection,
            canonical_node_id="ent:x1",
            alias_node_id="ent:x3",
            ns="people",
            scope="project",
        )
        accept_merge(connection, m1)
        m2 = propose_merge(
            connection,
            canonical_node_id="ent:x2",
            alias_node_id="ent:x3",
            ns="people",
            scope="project",
        )
        connection.commit()
        # x3 is already absorbed by x1; accepting into x2 must not silently win.
        assert accept_merge(connection, m2) == STATUS_CONFLICT
        connection.commit()
        assert (
            resolve_canonical(connection, "ent:x3", ns="people", scope="project")
            == "ent:x1"
        )


def test_accepted_merge_survives_reprojection(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        merge_id = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
        )
        accept_merge(connection, merge_id)
        connection.commit()

        # Force a full projection drop+rebuild.
        connection.execute(
            "delete from knowledge_graph_meta where key = 'projection_version'"
        )
        connection.commit()
        init_knowledge_graph(connection)
        connection.commit()

        # Nodes were rebuilt from MIRL, so the merge stays accepted and resolving.
        surviving = {m["id"]: m for m in list_merges(connection)}
        assert surviving[merge_id]["status"] == STATUS_ACCEPTED
        assert (
            resolve_canonical(connection, "ent:ibm-corp", ns="people", scope="project")
            == "ent:ibm"
        )


def test_apply_flags_conflict_when_node_vanishes(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        merge_id = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
        )
        accept_merge(connection, merge_id)
        # Simulate the alias node disappearing from the projection.
        connection.execute("delete from knowledge_nodes where id = 'ent:ibm-corp'")
        connection.commit()

        flagged = apply_identity_merges(connection)
        connection.commit()
        assert flagged == 1
        row = {m["id"]: m for m in list_merges(connection)}[merge_id]
        assert row["status"] == STATUS_CONFLICT
        assert "ent:ibm-corp" in row["reason"]
        # The decision and its history remain auditable.
        assert merge_audit(connection, "ent:ibm-corp")


def test_proposed_status_default(runtime: SeamRuntime) -> None:
    _seed_entities(runtime)
    with runtime.store._pool.checkout() as connection:
        merge_id = propose_merge(
            connection,
            canonical_node_id="ent:ibm",
            alias_node_id="ent:ibm-corp",
            ns="people",
            scope="project",
        )
        connection.commit()
        row = {m["id"]: m for m in list_merges(connection)}[merge_id]
        assert row["status"] == STATUS_PROPOSED


def _seed_alias_pair(runtime: SeamRuntime) -> None:
    """An entity whose canonical name is another entity's explicit alias."""
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:ibm",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": "IBM", "entity_type": "org"},
                ),
                MIRLRecord(
                    id="ent:ibm-corp",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={
                        "label": "International Business Machines",
                        "entity_type": "org",
                        "aliases": ["IBM"],
                    },
                ),
            ]
        )
    )


def test_candidate_generator_proposes_shared_alias_in_canonical_direction(
    runtime: SeamRuntime,
) -> None:
    _seed_alias_pair(runtime)
    with runtime.store._pool.checkout() as connection:
        summary = generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()

        assert len(summary["proposed"]) == 1
        assert summary["conflicts"] == []
        merges = list_merges(connection, statuses=[STATUS_PROPOSED])
        assert len(merges) == 1
        merge = merges[0]
        # The node that OWNS "ibm" as its canonical label is canonical; the one
        # that merely aliases it is absorbed.
        assert merge["canonical_node_id"] == "ent:ibm"
        assert merge["alias_node_id"] == "ent:ibm-corp"
        assert merge["confidence"] == 0.6
        # Never auto-accepted.
        assert merge["status"] == STATUS_PROPOSED
        audit = merge_audit(connection, "ent:ibm-corp")[0]
        assert audit["evidence"][0]["evidence_kind"] == "shared-alias"
        assert audit["evidence"][0]["detail"] == "ibm"


def test_candidate_generator_excludes_pure_homonyms(runtime: SeamRuntime) -> None:
    # Two distinct people both literally named "John", neither aliasing the other.
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id=f"ent:john-{n}",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": "John", "entity_type": "person"},
                )
                for n in (1, 2)
            ]
        )
    )
    with runtime.store._pool.checkout() as connection:
        summary = generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()
        assert summary["proposed"] == []
        assert list_merges(connection) == []


def test_candidate_generator_respects_scope_isolation(runtime: SeamRuntime) -> None:
    _seed_alias_pair(runtime)
    # A same-named org in a different scope must not be pulled into the merge.
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:ibm-eu",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="user",
                    attrs={"label": "IBM Europe", "entity_type": "org", "aliases": ["IBM"]},
                )
            ]
        )
    )
    with runtime.store._pool.checkout() as connection:
        generate_merge_candidates(connection)
        connection.commit()
        proposals = list_merges(connection, statuses=[STATUS_PROPOSED])
        # Only the within-scope pair; nothing crosses scope.
        assert len(proposals) == 1
        assert {proposals[0]["canonical_node_id"], proposals[0]["alias_node_id"]} == {
            "ent:ibm",
            "ent:ibm-corp",
        }
        assert proposals[0]["scope"] == "project"


def test_candidate_generator_is_idempotent(runtime: SeamRuntime) -> None:
    _seed_alias_pair(runtime)
    with runtime.store._pool.checkout() as connection:
        first = generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()
        second = generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()
        assert first["proposed"] == second["proposed"]
        assert len(list_merges(connection)) == 1


def test_candidate_generator_does_not_downgrade_accepted(runtime: SeamRuntime) -> None:
    _seed_alias_pair(runtime)
    with runtime.store._pool.checkout() as connection:
        summary = generate_merge_candidates(connection, ns="people", scope="project")
        merge_id = summary["proposed"][0]
        accept_merge(connection, merge_id)
        connection.commit()
        # Re-running the generator must not revert an accepted decision.
        generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()
        assert list_merges(connection)[0]["status"] == STATUS_ACCEPTED
        assert (
            resolve_canonical(connection, "ent:ibm-corp", ns="people", scope="project")
            == "ent:ibm"
        )


def test_candidate_generator_does_not_resurrect_split_decision(
    runtime: SeamRuntime,
) -> None:
    _seed_alias_pair(runtime)
    with runtime.store._pool.checkout() as connection:
        summary = generate_merge_candidates(connection, ns="people", scope="project")
        merge_id = summary["proposed"][0]
        accept_merge(connection, merge_id)
        split_merge(connection, merge_id, reason="operator undo")
        connection.commit()

        rerun = generate_merge_candidates(connection, ns="people", scope="project")
        connection.commit()

        merge = merge_audit(connection, "ent:ibm-corp")[0]
        assert merge["status"] == STATUS_SPLIT
        assert merge["reason"] == "operator undo"
        assert merge["superseded_by"].startswith("split:")
        assert merge_id not in rerun["proposed"]


def test_candidate_generator_bounds_pairs_before_materialization(
    runtime: SeamRuntime,
) -> None:
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id=f"ent:{prefix}",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={"label": short, "entity_type": "org"},
                )
                for prefix, short in (("ibm", "IBM"), ("ms", "MS"))
            ]
            + [
                MIRLRecord(
                    id=f"ent:{prefix}-corp",
                    kind=RecordKind.ENT,
                    ns="people",
                    scope="project",
                    attrs={
                        "label": label,
                        "entity_type": "org",
                        "aliases": [short],
                    },
                )
                for prefix, short, label in (
                    ("ibm", "IBM", "International Business Machines"),
                    ("ms", "MS", "Microsoft"),
                )
            ]
        )
    )
    with runtime.store._pool.checkout() as connection:
        summary = generate_merge_candidates(
            connection,
            ns="people",
            scope="project",
            max_candidates=1,
        )
        connection.commit()

        assert summary["pairs_examined"] == 1
        assert len(summary["proposed"]) == 1
        assert len(list_merges(connection)) == 1

        with pytest.raises(ValueError, match="at least 1"):
            generate_merge_candidates(connection, max_candidates=0)


def test_store_surface_read_and_operator_actions(runtime: SeamRuntime) -> None:
    _seed_alias_pair(runtime)
    summary = runtime.store.generate_identity_merge_candidates(
        ns="people", scope="project"
    )
    assert len(summary["proposed"]) == 1
    merge_id = summary["proposed"][0]

    proposals = runtime.store.identity_merges(statuses=[STATUS_PROPOSED])
    assert [m["id"] for m in proposals] == [merge_id]
    audit = runtime.store.identity_merge_audit("ent:ibm-corp")
    assert audit[0]["evidence"][0]["evidence_kind"] == "shared-alias"

    assert runtime.store.accept_identity_merge(merge_id) == STATUS_ACCEPTED
    assert runtime.store.identity_merges(statuses=[STATUS_ACCEPTED])[0]["id"] == merge_id

    runtime.store.split_identity_merge(merge_id, reason="operator undo")
    split = runtime.store.identity_merges(statuses=[STATUS_SPLIT])
    assert split[0]["id"] == merge_id
    # Evidence survives the operator split.
    assert runtime.store.identity_merge_audit("ent:ibm-corp")[0]["evidence"]


def test_mcp_identity_merges_tool_is_read_only(runtime: SeamRuntime) -> None:
    assert TOOL_METADATA["seam_identity_merges"]["annotations"]["readOnlyHint"] is True
    _seed_alias_pair(runtime)
    runtime.store.generate_identity_merge_candidates(ns="people", scope="project")

    listed = dispatch_tool(
        runtime,
        {"tool": "seam_identity_merges", "arguments": {"statuses": "proposed"}},
    )["result"]
    assert len(listed["merges"]) == 1
    assert listed["merges"][0]["canonical_node_id"] == "ent:ibm"

    audited = dispatch_tool(
        runtime,
        {"tool": "seam_identity_merges", "arguments": {"node_id": "ent:ibm-corp"}},
    )["result"]
    assert audited["node_id"] == "ent:ibm-corp"
    assert audited["merges"][0]["evidence"][0]["detail"] == "ibm"


def test_rest_identity_merge_ledger_and_actions(runtime: SeamRuntime) -> None:
    _seed_alias_pair(runtime)
    with TestClient(create_app(runtime)) as client:
        gen = client.post(
            "/identity-merges/generate",
            params={"namespace": "people", "scope": "project"},
        )
        assert gen.status_code == 200
        merge_id = gen.json()["proposed"][0]

        listed = client.get("/identity-merges", params={"statuses": "proposed"})
        assert listed.status_code == 200
        assert listed.json()["merges"][0]["id"] == merge_id

        audit = client.get("/identity-merges", params={"node_id": "ent:ibm-corp"})
        assert audit.json()["merges"][0]["alias_node_id"] == "ent:ibm-corp"

        accepted = client.post(f"/identity-merges/{merge_id}/accept")
        assert accepted.status_code == 200
        assert accepted.json()["status"] == STATUS_ACCEPTED

        split = client.post(
            f"/identity-merges/{merge_id}/split", params={"reason": "undo"}
        )
        assert split.status_code == 200
        assert split.json()["status"] == "split"

        # Unknown merge id -> 404; accepting a split merge -> 409 invalid state.
        assert client.post("/identity-merges/merge:missing/accept").status_code == 404
        assert client.post(f"/identity-merges/{merge_id}/accept").status_code == 409


def test_cli_merges_generate_list_accept_split_roundtrip(tmp_path, capsys) -> None:
    db = str(tmp_path / "s.db")
    run_cli(
        [
            "--db",
            db,
            "compile-nl",
            "IBM ships mainframes.",
        ]
    )
    capsys.readouterr()

    # Seed a second entity that aliases the first, via a fresh runtime on the db.
    seed = SeamRuntime(Path(db))
    try:
        seed.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id="ent:ibm",
                        kind=RecordKind.ENT,
                        ns="people",
                        scope="project",
                        attrs={"label": "IBM", "entity_type": "org"},
                    ),
                    MIRLRecord(
                        id="ent:ibm-corp",
                        kind=RecordKind.ENT,
                        ns="people",
                        scope="project",
                        attrs={
                            "label": "International Business Machines",
                            "entity_type": "org",
                            "aliases": ["IBM"],
                        },
                    ),
                ]
            )
        )
    finally:
        seed.close()

    run_cli(["--db", db, "knowledge", "merges", "--generate", "--namespace", "people", "--scope", "project"])
    gen = json.loads(capsys.readouterr().out)
    merge_id = gen["proposed"][0]

    run_cli(["--db", db, "graph", "merges", "--status", "proposed"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["merges"][0]["id"] == merge_id

    run_cli(["--db", db, "knowledge", "merges", "--accept", merge_id])
    assert json.loads(capsys.readouterr().out)["status"] == STATUS_ACCEPTED

    run_cli(["--db", db, "knowledge", "merges", "--split", merge_id, "--reason", "undo"])
    assert json.loads(capsys.readouterr().out)["status"] == "split"

    run_cli(["--db", db, "knowledge", "merges", "--node-id", "ent:ibm-corp"])
    audit = json.loads(capsys.readouterr().out)
    assert audit["merges"][0]["status"] == STATUS_SPLIT
    # Evidence survives the operator split at the CLI surface too.
    assert audit["merges"][0]["evidence"][0]["evidence_kind"] == "shared-alias"


def test_cli_merge_actions_are_unambiguous(tmp_path: Path) -> None:
    db = str(tmp_path / "s.db")
    with pytest.raises(SystemExit) as conflicting:
        run_cli(
            [
                "--db",
                db,
                "knowledge",
                "merges",
                "--generate",
                "--accept",
                "merge:example",
            ]
        )
    assert conflicting.value.code == 2

    with pytest.raises(SystemExit) as orphan_reason:
        run_cli(["--db", db, "knowledge", "merges", "--reason", "why"])
    assert orphan_reason.value.code == 2
