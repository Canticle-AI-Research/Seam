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


def test_unlimited_load_and_tied_budget_one_survive_unrelated_rewrite(tmp_path):
    path = tmp_path / "stable-ties.db"
    store = SQLiteStore(path)
    store.persist_ir(
        IRBatch(
            [
                _raw("raw:z", "same tied phrase"),
                _raw("raw:a", "same tied phrase"),
                _raw("raw:m", "unrelated payload"),
            ]
        )
    )

    def observe(current: SQLiteStore) -> tuple[list[str], list[str]]:
        loaded = current.load_ir().records
        from seam_runtime.retrieval import search_batch

        ranked = search_batch(
            IRBatch(loaded),
            query="same tied phrase",
            include_raw=True,
            limit=1,
        )
        return [record.id for record in loaded], [item.record.id for item in ranked.candidates]

    before = observe(store)
    store.persist_ir(IRBatch([_raw("raw:m", "rewritten unrelated payload")]))
    store.close()
    with SQLiteStore(path) as reopened:
        after = observe(reopened)

    assert before == after == (["raw:a", "raw:m", "raw:z"], ["raw:a"])


def _raw(record_id: str, content: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        scope="thread",
        status=Status.OBSERVED,
        attrs={"content": content, "media_type": "text/plain"},
    )
