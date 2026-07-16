"""Tests for vector orphan detection."""
import json
import sqlite3
from contextlib import closing

from seam_runtime.storage import SQLiteStore
from seam_runtime.vector import SQLiteVectorIndex


class TestVectorOrphanDetection:
    def test_orphan_detected_when_record_missing(self, tmp_path):
        db_path = str(tmp_path / "test_orphan.db")
        SQLiteStore(db_path)  # side effect: initializes ir_records schema
        vector_idx = SQLiteVectorIndex(
            db_path, _make_hash_embedding_model()
        )
        vector_idx.ensure_schema()

        # Insert a vector row for a non-existent record
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "insert into vector_index (record_id, model_name, dimension, source_text, source_hash, vector_json, updated_at) "
                "values (?, ?, ?, ?, ?, ?, ?)",
                ("clm:orphan:1", "test-model", 4, "test", "hash", json.dumps([0.1, 0.2, 0.3, 0.4]), "2025-01-01T00:00:00Z"),
            )
            conn.commit()

        orphans = vector_idx.orphan_records()
        assert len(orphans) >= 1, f"Expected at least 1 orphan, got {len(orphans)}"
        assert orphans[0]["record_id"] == "clm:orphan:1"
        assert orphans[0]["reason"] == "orphan"

    def test_no_orphans_when_all_records_present(self, tmp_path):
        db_path = str(tmp_path / "test_no_orphan.db")
        SQLiteStore(db_path)  # side effect: initializes ir_records schema
        vector_idx = SQLiteVectorIndex(
            db_path, _make_hash_embedding_model()
        )
        vector_idx.ensure_schema()

        # Insert a real IR record, then a vector row for it
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "insert into ir_records (id, kind, ns, scope, status, conf, t0, t1, created_at, updated_at, payload_json) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("clm:present:1", "CLM", "test", "test", "active", 1.0, "0", "0", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "{}"),
            )
            conn.execute(
                "insert into vector_index (record_id, model_name, dimension, source_text, source_hash, vector_json, updated_at) "
                "values (?, ?, ?, ?, ?, ?, ?)",
                ("clm:present:1", "test-model", 4, "test", "hash", json.dumps([0.1, 0.2, 0.3, 0.4]), "2025-01-01T00:00:00Z"),
            )
            conn.commit()

        orphans = vector_idx.orphan_records()
        assert len(orphans) == 0, f"Expected 0 orphans, got {len(orphans)}"


def _make_hash_embedding_model():
    from seam_runtime.models import HashEmbeddingModel
    return HashEmbeddingModel()
