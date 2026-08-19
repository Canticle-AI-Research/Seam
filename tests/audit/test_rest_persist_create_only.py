"""The REST MIRL persistence surface is create-only.

Internal runtime/store callers deliberately retain canonical upsert behavior;
an HTTP token holder must not be able to replace a known same-kind record id.
"""

from fastapi.testclient import TestClient

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.server import create_app_from_env
from seam_runtime.storage import SQLiteStore


def test_rest_persist_rejects_existing_id_without_changing_record(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "rest-create-only.db"
    monkeypatch.setenv("SEAM_SERVER_DB", str(db_path))
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)

    original = MIRLRecord(
        id="raw:rest-create-only",
        kind=RecordKind.RAW,
        attrs={"content": "original"},
    )
    replacement = MIRLRecord.from_dict(original.to_dict())
    replacement.attrs = {"content": "forged replacement"}

    with TestClient(create_app_from_env()) as client:
        first = client.post("/persist", json={"records": [original.to_dict()]})
        conflict = client.post(
            "/persist",
            json={"records": [replacement.to_dict()]},
        )

        # A rejected create must release its BEGIN IMMEDIATE lock before the
        # pooled connection is returned. Prove a separate store can write
        # immediately instead of waiting for or inheriting that transaction.
        probe_store = SQLiteStore(db_path)
        try:
            probe_store.persist_ir(
                IRBatch(
                    [
                        MIRLRecord(
                            id="raw:after-rest-conflict",
                            kind=RecordKind.RAW,
                            attrs={"content": "independent writer"},
                        )
                    ]
                )
            )
        finally:
            probe_store.close()

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": "one or more canonical record ids already exist"
    }

    store = SQLiteStore(db_path)
    try:
        persisted = store.load_ir(ids=[original.id]).records
    finally:
        store.close()
    assert [record.to_dict() for record in persisted] == [original.to_dict()]
