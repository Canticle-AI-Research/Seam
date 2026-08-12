import hashlib
import json
from contextlib import closing

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.vector import SQLiteVectorIndex, _VectorCache


def _record(
    *,
    record_id: str = "raw:cache-stable",
    content: str = "alpha beta gamma",
    scope: str = "",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        attrs={"content": content},
        ns="performance",
        scope=scope,
        updated_at=updated_at,
    )


def test_idempotent_index_preserves_warmed_cache(tmp_path) -> None:
    index = SQLiteVectorIndex(str(tmp_path / "vectors.db"), HashEmbeddingModel())
    record = _record()
    index.index_records([record])

    cache_key = (index.model.name, index.model.dimension, "performance", None)
    warmed_cache = _VectorCache((1, ""), [], object(), object())
    index._cache[cache_key] = warmed_cache

    index.index_records([record])

    assert index._cache[cache_key] is warmed_cache


def test_index_mutations_invalidate_warmed_cache(tmp_path) -> None:
    index = SQLiteVectorIndex(str(tmp_path / "vectors.db"), HashEmbeddingModel())
    index.index_records([_record()])

    cache_key = (index.model.name, index.model.dimension, "performance", None)
    index._cache[cache_key] = _VectorCache((1, ""), [], object(), object())
    index.index_records([_record(content="alpha beta delta")])
    assert index._cache == {}

    index._cache[cache_key] = _VectorCache((1, ""), [], object(), object())
    index.index_records([_record(content="alpha beta delta", scope="session-a")])
    assert index._cache == {}


def test_cache_fingerprint_detects_external_replace_with_older_timestamp(tmp_path) -> None:
    index = SQLiteVectorIndex(str(tmp_path / "vectors.db"), HashEmbeddingModel())
    index.index_records(
        [
            _record(
                record_id="raw:older",
                content="alpha beta gamma",
                updated_at="2026-01-01T00:00:01Z",
            ),
            _record(
                record_id="raw:newest",
                content="delta epsilon zeta",
                updated_at="2026-01-01T00:00:02Z",
            ),
        ]
    )

    with closing(index._connect()) as connection:
        before = index._fingerprint(
            connection, index.model.dimension, "performance", None
        )
        row = connection.execute(
            "select * from vector_index where record_id = ? and model_name = ?",
            ("raw:older", index.model.name),
        ).fetchone()
        connection.execute(
            """
            insert or replace into vector_index
                (record_id, model_name, dimension, source_text, source_hash,
                 render_version, namespace, scope, vector_json, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["record_id"],
                row["model_name"],
                row["dimension"],
                "replacement vector source",
                hashlib.sha256(b"replacement vector source").hexdigest(),
                row["render_version"],
                row["namespace"],
                row["scope"],
                json.dumps([0.0] * index.model.dimension),
                row["updated_at"],
            ),
        )
        connection.commit()
        after = index._fingerprint(
            connection, index.model.dimension, "performance", None
        )

    assert after[0] == before[0]
    assert after[1] != before[1]


def test_cache_fingerprint_detects_delete_and_reindex_with_same_timestamp(tmp_path) -> None:
    index = SQLiteVectorIndex(str(tmp_path / "vectors.db"), HashEmbeddingModel())
    index.index_records(
        [
            _record(
                record_id="raw:retired",
                content="alpha beta gamma",
                updated_at="2026-01-01T00:00:01Z",
            ),
            _record(
                record_id="raw:latest",
                content="delta epsilon zeta",
                updated_at="2026-01-01T00:00:02Z",
            ),
        ]
    )

    with closing(index._connect()) as connection:
        before = index._fingerprint(
            connection, index.model.dimension, "performance", None
        )

    index.delete_records(["raw:latest"])
    index.index_records(
        [
            _record(
                record_id="raw:replacement",
                content="delta epsilon zeta",
                updated_at="2026-01-01T00:00:02Z",
            )
        ]
    )

    with closing(index._connect()) as connection:
        after = index._fingerprint(
            connection, index.model.dimension, "performance", None
        )

    assert after[0] == before[0]
    assert after[1] != before[1]
