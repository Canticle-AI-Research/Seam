from __future__ import annotations

from seam_runtime import IRBatch, MIRLRecord, RecordKind, SeamSDK


def _evidenced_claims(seam: SeamSDK) -> tuple[MIRLRecord, MIRLRecord]:
    raw_one = MIRLRecord(
        id="raw:g4-r5:one",
        kind=RecordKind.RAW,
        ns="acme",
        scope="thread",
        attrs={
            "content": "Ada uses SQLite.",
            "source_ref": "test://g4-r5/one",
        },
    )
    raw_two = MIRLRecord(
        id="raw:g4-r5:two",
        kind=RecordKind.RAW,
        ns="acme",
        scope="thread",
        attrs={
            "content": "Ada uses Postgres.",
            "source_ref": "test://g4-r5/two",
        },
    )
    entity = MIRLRecord(
        id="ent:g4-r5:ada",
        kind=RecordKind.ENT,
        ns="acme",
        scope="thread",
        evidence=[raw_one.id, raw_two.id],
        attrs={"label": "Ada", "entity_type": "person"},
    )
    claims = (
        MIRLRecord(
            id="clm:g4-r5:sqlite",
            kind=RecordKind.CLM,
            ns="acme",
            scope="thread",
            evidence=[raw_one.id],
            attrs={
                "subject": entity.id,
                "predicate": "uses",
                "object": "SQLite",
            },
        ),
        MIRLRecord(
            id="clm:g4-r5:postgres",
            kind=RecordKind.CLM,
            ns="acme",
            scope="thread",
            evidence=[raw_two.id],
            attrs={
                "subject": entity.id,
                "predicate": "uses",
                "object": "Postgres",
            },
        ),
    )
    seam.runtime.persist_ir(IRBatch([raw_one, raw_two, entity, *claims]))
    return claims


def test_g4_sdk_rebuild_uses_current_trust_gated_graph(tmp_path) -> None:
    with SeamSDK(tmp_path / "g4.db", allow_pgvector_env=False) as seam:
        _evidenced_claims(seam)
        result = seam.rebuild_graph_products(
            namespace="acme", scope="thread"
        )
        products = seam.graph_products(
            namespace="acme", scope="thread"
        )

        assert result["accepted_fact_count"] == 2
        assert result["rejected_fact_count"] == 0
        assert products
        assert seam.graph_products(
            namespace="other", scope="thread"
        ) == []
        for product in products:
            for sentence in product["sentences"]:
                assert sentence["supporting_record_ids"]
                assert sentence["supporting_episode_ids"]


def test_r5_sdk_requires_review_then_applies_and_reverses_additively(
    tmp_path,
) -> None:
    with SeamSDK(tmp_path / "r5.db", allow_pgvector_env=False) as seam:
        claims = _evidenced_claims(seam)
        run = seam.start_reasoning(
            "Choose the storage backend.",
            ns="acme",
            scope="thread",
            agent_id="planner",
        )
        subject = run.add_node(
            "decision",
            "Use SQLite.",
            knowledge_refs=[claims[0].id],
            evidence_refs=[claims[0].evidence[0]],
        )
        check = run.verify(
            str(subject["node_id"]),
            check_kind="test",
            check_ref="tests/test_storage.py::test_sqlite",
            verdict="passed",
            summary="SQLite passed.",
            evidence_refs=[claims[0].evidence[0]],
        )
        outcome = run.finalize_verified(
            "Use SQLite.",
            verification_ids=[str(check["verification_id"])],
            knowledge_refs=[claims[0].id],
            supporting_node_ids=[str(subject["node_id"])],
        )
        proposal = run.propose_promotion(
            str(outcome["node_id"]),
            assertion_record_id="clm:g4-r5:reviewed",
            assertion_subject="project:storage",
            assertion_predicate="recommended_backend",
            assertion_object="SQLite",
        )

        assert seam.promotion_eligibility(
            str(proposal["proposal_id"])
        )["eligible"] is False
        assert seam.runtime.store.load_ir(
            ids=["clm:g4-r5:reviewed"]
        ).records == []

        seam.review_promotion(
            proposal_id=str(proposal["proposal_id"]),
            review_kind="human",
            decision="approved",
            reviewer_id="operator",
            rationale="The verified evidence supports this assertion.",
        )
        applied = seam.apply_promotion(
            proposal_id=str(proposal["proposal_id"]),
            applied_by="operator",
        )
        assert applied["stored_ids"] == ["clm:g4-r5:reviewed"]
        assert applied["application"]["assertion_record_id"] == (
            "clm:g4-r5:reviewed"
        )
        assert applied["record"]["evidence"] == [claims[0].evidence[0]]
        assert claims[0].id in proposal["evidence_fingerprints"]

        reversed_result = seam.reverse_promotion(
            proposal_id=str(proposal["proposal_id"]),
            reversed_by="operator",
            reason="A replacement decision will be reviewed separately.",
        )
        superseding_id = reversed_result["superseding_record"]["id"]
        stored = seam.runtime.store.load_ir(
            ids=["clm:g4-r5:reviewed", superseding_id]
        )
        assert [record.id for record in stored.records] == [
            "clm:g4-r5:reviewed",
            superseding_id,
        ]
        assert reversed_result["superseding_record"]["attrs"][
            "predicate"
        ] == "supersedes"
        current = seam.promotion(str(proposal["proposal_id"]))
        assert current["application"] is not None
        assert current["reversal"] is not None
