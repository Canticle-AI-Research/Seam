from __future__ import annotations

from seam_runtime.models import EmbeddingModel
from seam_runtime.vector import SQLiteVectorIndex


class StubModel(EmbeddingModel):
    """Stub embedding model for pragma tests."""
    def encode(self, texts):
        return [[0.0] * 384 for _ in texts]

    @property
    def dimension(self) -> int:
        return 384

    @property
    def model_name(self) -> str:
        return "stub-pragma-test"


def test_vector_connect_pragmas(tmp_path):
    index = SQLiteVectorIndex(str(tmp_path / "v.db"), StubModel())
    index.ensure_schema()
    connection = index._connect()
    try:
        jm = connection.execute("pragma journal_mode").fetchone()[0]
        assert jm.lower() == "wal", f"expected wal, got {jm}"
        bt = connection.execute("pragma busy_timeout").fetchone()[0]
        assert bt == 5000, f"expected busy_timeout 5000, got {bt}"
        fk = connection.execute("pragma foreign_keys").fetchone()[0]
        assert fk == 1, f"expected foreign_keys 1, got {fk}"
        sync = connection.execute("pragma synchronous").fetchone()[0]
        assert sync == 1, f"expected synchronous 1 (NORMAL), got {sync}"
    finally:
        connection.close()
