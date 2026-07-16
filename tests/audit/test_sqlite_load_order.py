from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.storage import SQLiteStore


def test_sqlite_store_load_ir_preserves_requested_id_order(tmp_path):
    store = SQLiteStore(tmp_path / "order.db")
    store.persist_ir(
        IRBatch(
            [
                _raw("raw:a", "second requested evidence"),
                _raw("raw:z", "first requested evidence"),
            ]
        )
    )

    loaded = store.load_ir(ids=["raw:z", "raw:a"])

    assert [record.id for record in loaded.records] == ["raw:z", "raw:a"]


def test_locomo_evidence_context_preserves_ranked_order_with_sqlite_store(tmp_path):
    store = SQLiteStore(tmp_path / "evidence.db")
    store.persist_ir(
        IRBatch(
            [
                _raw("raw:a", "second ranked distractor"),
                _raw("raw:z", "first ranked answer evidence"),
            ]
        )
    )

    class Runtime:
        def __init__(self, store):
            self.store = store

    adapter = SeamLocomoAdapter(budget=2000)

    context = adapter._build_evidence_context_from_ids(
        Runtime(store),
        ["raw:z", "raw:a"],
    )

    assert context.index("first ranked") < context.index("second ranked")


def _raw(record_id: str, content: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        scope="thread",
        status=Status.OBSERVED,
        attrs={"content": content, "media_type": "text/plain"},
    )
