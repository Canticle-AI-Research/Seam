"""Cross-turn entity coreference at persist time (HISTORY#321/#323 cat1 root
cause fix). ``compile_nl`` is per-call/per-turn and mints a fresh ``ent:`` id
per label every time, so the same real-world entity ("Melanie") previously
got a different id in every turn she was mentioned in -- there was nothing to
aggregate her claims against. ``SQLiteStore.persist_ir`` now resolves this at
persist time: within one ``ns``, the FIRST occurrence of a normalized label
is canonical and later duplicates are remapped to it, never inserted as a
second ``ENT`` row. This must never merge across ``ns`` (SEAM's existing
multi-tenant isolation boundary, HISTORY#274's leak-seal).
"""

from contextlib import closing

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.storage import SQLiteStore


def _ent(record_id: str, label: str, ns: str = "test") -> MIRLRecord:
    return MIRLRecord(id=record_id, kind=RecordKind.ENT, ns=ns, scope="thread",
                      attrs={"entity_type": "person", "label": label})


def _clm(record_id: str, subject: str, obj: str, ns: str = "test") -> MIRLRecord:
    return MIRLRecord(id=record_id, kind=RecordKind.CLM, ns=ns, scope="thread",
                      attrs={"subject": subject, "predicate": "content", "object": obj})


def _ent_rows(store: SQLiteStore, ns: str) -> list[tuple[str, str]]:
    with closing(store._connect()) as conn:
        rows = conn.execute(
            "select id, payload_json from ir_records where kind = 'ENT' and ns = ? order by created_at, id",
            (ns,),
        ).fetchall()
    import json
    return [(row[0], json.loads(row[1])["attrs"]["label"]) for row in rows]


def test_same_label_same_ns_across_two_batches_merges_to_one_entity():
    store = SQLiteStore(":memory:")
    # Turn 1: "Melanie" gets a fresh id (as compile_nl always mints).
    store.persist_ir(IRBatch([_ent("ent:melanie:hash1", "Melanie"), _clm("clm:1", "ent:melanie:hash1", "I love pottery.")]))
    # Turn 2 (later, independent compile_nl call): "Melanie" mentioned again,
    # a DIFFERENT fresh id from compile_nl's per-call hashing.
    store.persist_ir(IRBatch([_ent("ent:melanie:hash2", "Melanie"), _clm("clm:2", "ent:melanie:hash2", "I moved to Sweden.")]))

    rows = _ent_rows(store, "test")
    assert len(rows) == 1, f"expected exactly one Melanie ENT row, got {rows}"
    canonical_id = rows[0][0]

    batch = store.load_ir(ns="test")
    claims = [r for r in batch.records if r.kind == RecordKind.CLM]
    assert {c.attrs["subject"] for c in claims} == {canonical_id}, (
        "both claims must be remapped to the SAME canonical entity id"
    )


def test_case_and_whitespace_variants_normalize_to_one_entity():
    store = SQLiteStore(":memory:")
    store.persist_ir(IRBatch([_ent("ent:a", "Melanie")]))
    store.persist_ir(IRBatch([_ent("ent:b", "  melanie  ")]))
    store.persist_ir(IRBatch([_ent("ent:c", "MELANIE")]))
    assert len(_ent_rows(store, "test")) == 1


def test_different_labels_stay_distinct():
    store = SQLiteStore(":memory:")
    store.persist_ir(IRBatch([_ent("ent:a", "Melanie"), _ent("ent:b", "Caroline")]))
    labels = {label for _id, label in _ent_rows(store, "test")}
    assert labels == {"Melanie", "Caroline"}


def test_same_label_different_ns_never_merges():
    store = SQLiteStore(":memory:")
    store.persist_ir(IRBatch([_ent("ent:a", "Melanie", ns="conv:1")]))
    store.persist_ir(IRBatch([_ent("ent:b", "Melanie", ns="conv:2")]))
    assert len(_ent_rows(store, "conv:1")) == 1
    assert len(_ent_rows(store, "conv:2")) == 1
    id_conv1 = _ent_rows(store, "conv:1")[0][0]
    id_conv2 = _ent_rows(store, "conv:2")[0][0]
    assert id_conv1 != id_conv2


def test_duplicate_within_the_same_batch_also_merges():
    # Two ENT records for the same label arriving in ONE persist_ir call
    # (e.g. a batch spanning more than one proposition) must also dedup,
    # not just across separate calls.
    store = SQLiteStore(":memory:")
    store.persist_ir(IRBatch([
        _ent("ent:a", "Melanie"),
        _ent("ent:b", "Melanie"),
        _clm("clm:1", "ent:a", "first mention"),
        _clm("clm:2", "ent:b", "second mention"),
    ]))
    rows = _ent_rows(store, "test")
    assert len(rows) == 1
    canonical_id = rows[0][0]
    batch = store.load_ir(ns="test")
    claims = [r for r in batch.records if r.kind == RecordKind.CLM]
    assert {c.attrs["subject"] for c in claims} == {canonical_id}


def test_rel_src_dst_also_remapped():
    store = SQLiteStore(":memory:")
    store.persist_ir(IRBatch([_ent("ent:a", "Akira"), _ent("ent:b", "Priya")]))
    rel = MIRLRecord(id="rel:1", kind=RecordKind.REL, ns="test", scope="thread",
                     attrs={"src": "ent:c", "predicate": "mentored", "dst": "ent:b"})
    # "Akira" re-mentioned with a fresh id ent:c in a later turn/batch.
    store.persist_ir(IRBatch([_ent("ent:c", "Akira"), rel]))
    batch = store.load_ir(ns="test")
    rels = [r for r in batch.records if r.kind == RecordKind.REL]
    assert len(rels) == 1
    assert rels[0].attrs["src"] == "ent:a", "REL.src must remap to the canonical Akira id, not the fresh ent:c"


def test_idempotent_rerun_does_not_duplicate():
    store = SQLiteStore(":memory:")
    batch = IRBatch([_ent("ent:a", "Melanie"), _clm("clm:1", "ent:a", "text")])
    store.persist_ir(batch)
    store.persist_ir(batch)  # re-persist the same batch again
    assert len(_ent_rows(store, "test")) == 1


def test_end_to_end_via_ingest_conversation_turn(tmp_path):
    """The real ingest path (SeamRuntime.ingest_conversation_turn -> compile_nl
    -> persist_ir) coreferences a name mentioned across separate turns."""
    from seam_runtime.runtime import SeamRuntime

    rt = SeamRuntime(str(tmp_path / "coref.db"))
    rt.ingest_conversation_turn(text="Melanie: I love pottery.", source_ref="t1", ns="conv:1", scope="thread")
    rt.ingest_conversation_turn(text="Melanie: I moved to Sweden last year.", source_ref="t2", ns="conv:1", scope="thread")

    batch = rt.store.load_ir(ns="conv:1")
    melanie_ent_ids = {r.id for r in batch.records if r.kind == RecordKind.ENT and r.attrs.get("label", "").lower() == "melanie"}
    assert len(melanie_ent_ids) == 1

    claims_about_melanie = [r for r in batch.records if r.kind == RecordKind.CLM and r.attrs.get("subject") in melanie_ent_ids]
    assert len(claims_about_melanie) == 2
