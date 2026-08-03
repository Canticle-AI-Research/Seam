from __future__ import annotations

from pathlib import Path

import pytest

from seam_runtime.knowledge_graph import (
    ASSERTABLE_TRUST_STATES,
    assertable_record_ids,
    predicate_family,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.nl import compile_nl
from seam_runtime.nl_extract import ExtractedClaim, ExtractedEntity, Extraction, ground_extraction
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.runtime import SeamRuntime
from seam_runtime.self_improve import (
    GraphProbe,
    RatchetGateEvidence,
    generate_graph_probes,
    strict_ratchet_decision,
)


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "deep-graph.db")
    try:
        yield instance
    finally:
        instance.close()


class _FacetExtractor:
    def extract(self, text: str) -> Extraction:
        if "deployed" not in text:
            return Extraction()
        return Extraction(
            entities=(
                ExtractedEntity("Mina", "person"),
                ExtractedEntity("Orion", "project"),
                ExtractedEntity("Helsinki", "place"),
            ),
            claims=(
                ExtractedClaim(
                    "Mina",
                    "deployed",
                    "Orion",
                    when="Tuesday",
                    where="Helsinki",
                    why="because tests passed",
                    how="using the release tool",
                    then="then monitored Orion",
                ),
            ),
        )


def _claim_id(batch: IRBatch, predicate: str = "content") -> str:
    return next(
        record.id
        for record in batch.records
        if record.kind == RecordKind.CLM and record.attrs.get("predicate") == predicate
    )


def _entity(
    record_id: str,
    label: str,
    *,
    ns: str = "local.default",
    scope: str = "project",
) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.ENT,
        ns=ns,
        scope=scope,
        attrs={"label": label, "entity_type": "thing"},
    )


def test_grounded_extractor_carries_5w1h_then_and_epistemic_basis() -> None:
    raw = {
        "claims": [{
            "subject": "Mina",
            "relation": "deployed",
            "object": "Orion",
            "when": "Tuesday",
            "where": "Helsinki",
            "why": "because tests passed",
            "how": "using the release tool",
            "then": "then monitored Orion",
            "epistemic_basis": "inferred",
        }],
    }
    extraction = ground_extraction(
        raw,
        "Mina deployed Orion Tuesday in Helsinki because tests passed using the release tool, then monitored Orion.",
    )
    [claim] = extraction.claims
    assert claim.facets() == {
        "who": "Mina",
        "what": "Orion",
        "when": "Tuesday",
        "where": "Helsinki",
        "why": "because tests passed",
        "how": "using the release tool",
        "then": "then monitored Orion",
    }
    assert claim.epistemic_basis == "inferred"


def test_graph_preserves_open_predicate_and_adds_typed_facets(runtime: SeamRuntime) -> None:
    batch = compile_nl(
        "Mina deployed Orion Tuesday in Helsinki because tests passed using the release tool, then monitored Orion.",
        source_ref="unit://release-report",
        extractor=_FacetExtractor(),
    )
    runtime.persist_ir(batch)
    claim_id = _claim_id(batch, "deployed")

    graph = runtime.store.knowledge_graph(root_id=claim_id, limit=100, hops=2)
    claim = next(node for node in graph["nodes"] if node["id"] == claim_id)
    assert set(claim["facets"]) == {"who", "what", "when", "where", "why", "how", "then"}
    assert claim["epistemic_basis"] == "explicit"
    facet_edges = {edge["predicate"]: edge for edge in graph["edges"] if edge["source"] == claim_id}
    assert {"who", "what", "when", "where", "why", "how", "then"} <= facet_edges.keys()
    assert all(facet_edges[name]["edge_kind"] == "facet" for name in claim["facets"])
    assert any(edge["predicate"] == "deployed" for edge in graph["edges"])
    assert predicate_family("caused_by") == "causal"
    assert predicate_family("precedes") == "temporal"
    assert predicate_family("refutes") == "epistemic"
    assert predicate_family("invented_open_predicate") == "semantic"


def test_model_output_is_unverified_but_independent_raw_evidence_is_supported(runtime: SeamRuntime) -> None:
    supported_batch = runtime.compile_nl("A human report says Orion shipped.", source_ref="unit://human-report")
    runtime.persist_ir(supported_batch)
    supported_id = _claim_id(supported_batch)
    model_claim = MIRLRecord(
        id="clm:model-only",
        kind=RecordKind.CLM,
        ext={"agent_id": "planner"},
        attrs={"subject": "ent:planner", "predicate": "predicts", "object": "Orion shipped"},
    )
    runtime.persist_ir(IRBatch([_entity("ent:planner", "Planner"), model_claim]))
    model_raw_batch = runtime.compile_nl(
        "A model says another unsupported thing.",
        source_ref="agent://planner/model-output",
        agent_id="planner",
    )
    runtime.persist_ir(model_raw_batch)
    model_raw_id = next(
        record.id for record in model_raw_batch.records if record.kind == RecordKind.RAW
    )

    supported = runtime.store.knowledge_node(supported_id)["node"]
    unverified = runtime.store.knowledge_node(model_claim.id)["node"]
    assert supported["trust_state"] == "supported"
    assert supported["assertable"] is True
    assert unverified["trust_state"] == "unverified"
    assert unverified["trust"]["model_output_evidence_count"] == 1
    assert unverified["assertable"] is False

    with runtime.store._pool.checkout() as connection:
        allowed = assertable_record_ids(
            connection,
            [supported_id, model_claim.id, model_raw_id, "missing:fail-closed"],
        )
        cross_boundary = assertable_record_ids(
            connection,
            [supported_id],
            namespace="another.namespace",
            scope="project",
        )
    assert allowed == {supported_id}
    assert cross_boundary == set()
    assert supported["trust_state"] in ASSERTABLE_TRUST_STATES


def test_assistant_chat_output_cannot_self_corroborate_on_a_later_turn(runtime: SeamRuntime) -> None:
    first = runtime.compile_nl(
        "Assistant: Orion definitely shipped on Friday.",
        source_ref="chat://turn-one/assistant",
        ns="team.alpha",
        scope="thread",
        agent_id="assistant-model",
    )
    second = runtime.compile_nl(
        "Assistant: I confirm Orion shipped on Friday.",
        source_ref="chat://turn-two/assistant",
        ns="team.alpha",
        scope="thread",
        agent_id="assistant-model",
    )
    first_claim = _claim_id(first)
    second_claim = _claim_id(second)
    second_raw_record = next(record for record in second.records if record.kind == RecordKind.RAW)
    second_raw = second_raw_record.id
    second_prov_record = next(record for record in second.records if record.kind == RecordKind.PROV)
    runtime.persist_ir(first)
    runtime.persist_ir(second)
    runtime.persist_ir(IRBatch([second_raw_record, second_prov_record,
        MIRLRecord(
            id="rel:assistant-self-support",
            kind=RecordKind.REL,
            ns="team.alpha",
            scope="thread",
                prov=[second_prov_record.id],
            ext={"agent_id": "assistant-model"},
            attrs={"src": second_claim, "predicate": "corroborates", "dst": first_claim},
        )
    ]))

    target = runtime.store.knowledge_node(first_claim)["node"]
    assert target["trust_state"] == "unverified"
    assert target["trust"]["independent_evidence_count"] == 0
    assert target["trust"]["support_edge_count"] == 0
    assert target["trust"]["model_output_evidence_count"] >= 1
    with runtime.store._pool.checkout() as connection:
        assert assertable_record_ids(
            connection,
            [first_claim, second_claim, second_raw],
            namespace="team.alpha",
            scope="thread",
        ) == set()


@pytest.mark.parametrize(
    ("foreign_namespace", "foreign_scope"),
    [("team.beta", "project"), ("team.alpha", "thread")],
)
def test_cross_tenant_epistemic_evidence_cannot_upgrade_claim(
    runtime: SeamRuntime,
    foreign_namespace: str,
    foreign_scope: str,
) -> None:
    foreign = runtime.compile_nl(
        "A beta audit claims Orion shipped.",
        source_ref="human://beta-audit",
        ns=foreign_namespace,
        scope=foreign_scope,
    )
    foreign_claim = _claim_id(foreign)
    foreign_raw_record = next(record for record in foreign.records if record.kind == RecordKind.RAW)
    foreign_prov_record = next(record for record in foreign.records if record.kind == RecordKind.PROV)
    target = MIRLRecord(
        id="clm:alpha-target",
        kind=RecordKind.CLM,
        ns="team.alpha",
        scope="project",
        ext={"agent_id": "planner"},
        attrs={"subject": "ent:orion", "predicate": "state", "object": "shipped"},
    )
    runtime.persist_ir(foreign)
    runtime.persist_ir(
        IRBatch([
            _entity(
                "ent:orion",
                "Orion",
                ns="team.alpha",
                scope="project",
            ),
            target,
        ])
    )
    # The edge is deliberately stamped alpha/project while its source node and
    # source episode differ by namespace or scope. Trust evaluation must
    # constrain every part of the path, rather than accepting the edge's
    # target-facing tenant alone.
    runtime.persist_ir(IRBatch([foreign_raw_record, foreign_prov_record,
        MIRLRecord(
            id="rel:cross-tenant-support",
            kind=RecordKind.REL,
            ns="team.alpha",
            scope="project",
                prov=[foreign_prov_record.id],
            attrs={"src": foreign_claim, "predicate": "supports", "dst": target.id},
        )
    ]))

    node = runtime.store.knowledge_node(target.id)["node"]
    assert node["trust_state"] == "unverified"
    assert node["trust"]["support_edge_count"] == 0
    with runtime.store._pool.checkout() as connection:
        assert assertable_record_ids(
            connection,
            [target.id],
            namespace="team.alpha",
            scope="project",
        ) == set()


def test_epistemic_edges_support_contest_refute_and_supersede(runtime: SeamRuntime) -> None:
    source_batch = runtime.compile_nl(
        "Verified audit evidence supports the release.",
        source_ref="unit://audit",
        scope="project",
    )
    runtime.persist_ir(source_batch)
    source_id = _claim_id(source_batch)
    source_raw_record = next(record for record in source_batch.records if record.kind == RecordKind.RAW)
    source_prov_record = next(record for record in source_batch.records if record.kind == RecordKind.PROV)
    targets = [
        MIRLRecord(
            id=f"clm:{name}",
            kind=RecordKind.CLM,
            ext={"agent_id": "planner"},
            attrs={"subject": "ent:release", "predicate": "state", "object": name},
        )
        for name in (
            "supported-target",
            "contested-target",
            "refuted-target",
            "unevidenced-edge-target",
        )
    ]
    unsupported_dispute = MIRLRecord(
        id="clm:unsupported-dispute",
        kind=RecordKind.CLM,
        ext={"agent_id": "planner"},
        attrs={
            "subject": "ent:release",
            "predicate": "disputes",
            "object": "unsupported",
        },
    )
    runtime.persist_ir(
        IRBatch([
            _entity("ent:release", "Release"),
            unsupported_dispute,
            *targets,
        ])
    )
    runtime.persist_ir(IRBatch([source_raw_record, source_prov_record,
        MIRLRecord(
            id="rel:support",
            kind=RecordKind.REL,
            prov=[source_prov_record.id],
            attrs={"src": source_id, "predicate": "supports", "dst": targets[0].id},
        ),
        MIRLRecord(
            id="rel:contradict",
            kind=RecordKind.REL,
            attrs={"src": unsupported_dispute.id, "predicate": "contradicts", "dst": targets[1].id},
        ),
        MIRLRecord(
            id="rel:refute",
            kind=RecordKind.REL,
            prov=[source_prov_record.id],
            attrs={"src": source_id, "predicate": "refutes", "dst": targets[2].id},
        ),
        MIRLRecord(
            id="rel:unevidenced-support",
            kind=RecordKind.REL,
            attrs={"src": source_id, "predicate": "supports", "dst": targets[3].id},
        ),
    ]))

    states = {
        target.id: runtime.store.knowledge_node(target.id)["node"]["trust_state"]
        for target in targets
    }
    assert states == {
        "clm:supported-target": "supported",
        "clm:contested-target": "contested",
        "clm:refuted-target": "refuted",
        "clm:unevidenced-edge-target": "unverified",
    }
    with runtime.store._pool.checkout() as connection:
        assert assertable_record_ids(connection, [target.id for target in targets]) == {
            "clm:supported-target"
        }


def test_hypothetical_stale_and_superseded_claims_are_not_assertable(runtime: SeamRuntime) -> None:
    claims = [
        MIRLRecord(
            id="clm:hypothesis",
            kind=RecordKind.CLM,
            status=Status.HYPOTHETICAL,
            attrs={"subject": "ent:x", "predicate": "might", "object": "happen"},
        ),
        MIRLRecord(
            id="clm:stale",
            kind=RecordKind.CLM,
            t1="2020-01-01T00:00:00+00:00",
            attrs={"subject": "ent:x", "predicate": "was", "object": "current"},
        ),
        MIRLRecord(
            id="clm:superseded",
            kind=RecordKind.CLM,
            status=Status.SUPERSEDED,
            attrs={"subject": "ent:x", "predicate": "old", "object": "value"},
        ),
    ]
    runtime.persist_ir(IRBatch([_entity("ent:x", "X"), *claims]))
    with runtime.store._pool.checkout() as connection:
        assert assertable_record_ids(connection, [claim.id for claim in claims]) == set()
    history = runtime.store.knowledge_graph(include_history=True, limit=200, hops=0)
    states = {node["id"]: node["trust_state"] for node in history["nodes"] if node["id"] in {c.id for c in claims}}
    assert states == {
        "clm:hypothesis": "unverified",
        "clm:stale": "stale",
        "clm:superseded": "superseded",
    }


def test_graph_probe_generation_covers_safety_and_reasoning_motifs(runtime: SeamRuntime) -> None:
    rich = compile_nl(
        "Mina deployed Orion Tuesday in Helsinki because tests passed using the release tool, then monitored Orion.",
        source_ref="unit://rich",
        extractor=_FacetExtractor(),
    )
    runtime.persist_ir(rich)
    unsupported = MIRLRecord(
        id="clm:unsupported-probe",
        kind=RecordKind.CLM,
        ext={"agent_id": "model", VIRTUAL_REFS_EXTENSION: ["ent:a"]},
        attrs={"subject": "ent:a", "predicate": "claims", "object": "unverified"},
    )
    runtime.persist_ir(IRBatch([
        unsupported,
        MIRLRecord(
            id="rel:a-b",
            kind=RecordKind.REL,
            ext={VIRTUAL_REFS_EXTENSION: ["ent:a", "ent:b"]},
            attrs={"src": "ent:a", "predicate": "uses", "dst": "ent:b"},
        ),
        MIRLRecord(
            id="rel:b-c",
            kind=RecordKind.REL,
            ext={VIRTUAL_REFS_EXTENSION: ["ent:b", "ent:c"]},
            attrs={"src": "ent:b", "predicate": "precedes", "dst": "ent:c"},
        ),
        MIRLRecord(
            id="rel:cause",
            kind=RecordKind.REL,
            ext={VIRTUAL_REFS_EXTENSION: ["ent:c", "ent:d"]},
            attrs={"src": "ent:c", "predicate": "caused_by", "dst": "ent:d"},
        ),
        MIRLRecord(id="rel:dispute", kind=RecordKind.REL, attrs={"src": unsupported.id, "predicate": "contradicts", "dst": _claim_id(rich)}),
    ]))
    with runtime.store._pool.checkout() as connection:
        first = generate_graph_probes(connection, sample=None, seed=9)
        second = generate_graph_probes(connection, sample=None, seed=9)
    assert first == second
    assert all(isinstance(probe, GraphProbe) for probe in first)
    assert {
        "five_w_one_h_then",
        "multi_hop",
        "causal",
        "temporal",
        "contradiction",
        "provenance",
        "unsupported",
    } <= {probe.motif for probe in first}
    unsupported_probe = next(probe for probe in first if probe.motif == "unsupported")
    assert unsupported_probe.expected_action == "abstain_or_qualify"


def _passing_gates() -> list[RatchetGateEvidence]:
    return [
        RatchetGateEvidence(name=family, family=family, passed=True, refs=(f"case:{family}",))
        for family in ("aggregate", "category", "integrity", "trust", "temporal", "provenance", "holdout")
    ]


def test_strict_ratchet_requires_every_gate_and_operator_approval() -> None:
    decision = strict_ratchet_decision(_passing_gates())
    assert decision.status == "pending_approval"
    assert decision.accepted_for_review is True
    assert decision.requires_approval is True
    assert decision.can_apply is False
    assert decision.failed_gates == ()


def test_strict_ratchet_rejects_any_failure_or_missing_family_but_keeps_evidence() -> None:
    gates = _passing_gates()
    gates[3] = RatchetGateEvidence(
        name="trust-hallucination-rate",
        family="trust",
        passed=False,
        baseline=0.01,
        candidate=0.02,
        threshold=0.01,
        refs=("probe:unsupported:1",),
    )
    rejected = strict_ratchet_decision(gates)
    assert rejected.status == "rejected"
    assert rejected.failed_gates == ("trust-hallucination-rate",)
    assert rejected.to_dict()["evidence"][3]["refs"] == ["probe:unsupported:1"]

    missing = strict_ratchet_decision(_passing_gates()[:-1])
    assert missing.status == "rejected"
    assert missing.failed_gates == ("missing:holdout",)
