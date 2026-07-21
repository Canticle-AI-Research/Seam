"""Tests for RAW records being indexable in the vector index."""

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.vector import INDEXABLE_KINDS, SQLiteVectorIndex


def test_raw_is_in_indexable_kinds():
    """RecordKind.RAW is included in INDEXABLE_KINDS."""
    assert RecordKind.RAW in INDEXABLE_KINDS, (
        f"RAW must be in INDEXABLE_KINDS; got {INDEXABLE_KINDS}"
    )


def test_render_record_text_returns_content_for_raw():
    """render_record_text returns the content attr directly for RAW records."""
    raw = MIRLRecord(
        id="raw:1",
        kind=RecordKind.RAW,
        attrs={"source_ref": "test://input", "content": "Hello world, this is a conversation turn.", "media_type": "text/plain"},
    )
    text = SQLiteVectorIndex.render_record_text(raw)
    assert text == "Hello world, this is a conversation turn.", f"Unexpected text: {text!r}"


def test_render_record_text_falls_back_for_raw_without_content():
    """render_record_text uses iter_textual_fields fallback when RAW has no content attr."""
    raw = MIRLRecord(
        id="raw:1",
        kind=RecordKind.RAW,
        attrs={"source_ref": "test://input"},
    )
    text = SQLiteVectorIndex.render_record_text(raw)
    assert "RAW" in text, f"Expected kind marker in fallback text, got: {text!r}"
    assert "test://input" in text, f"Expected source_ref in fallback text, got: {text!r}"


def test_render_record_text_still_works_for_clm():
    """render_record_text continues to use iter_textual_fields for non-RAW records."""
    clm = MIRLRecord(
        id="clm:1",
        kind=RecordKind.CLM,
        attrs={"subject": "ent:project:seam_abc123", "predicate": "goal", "object": "build_a_vector_search"},
    )
    text = SQLiteVectorIndex.render_record_text(clm)
    assert "CLM" in text, f"Expected CLM kind marker in text, got: {text!r}"
    assert "build_a_vector_search" in text, f"Expected object in text, got: {text!r}"


def test_render_record_text_uses_readable_subject_for_grounded_fact():
    clm = MIRLRecord(
        id="clm:derived",
        kind=RecordKind.CLM,
        ext={"derived_fact_policy": "grounded-clm/1"},
        attrs={
            "subject": "ent:opaque:john",
            "subject_label": "John",
            "predicate": "likes",
            "object": "surfing",
        },
    )
    assert SQLiteVectorIndex.render_record_text(clm) == "John likes surfing"


def test_raw_record_is_indexed(tmp_path):
    """RAW records pass through index_records and get vector entries."""
    from seam_runtime.models import HashEmbeddingModel

    db_path = str(tmp_path / "test_raw_indexed.db")
    model = HashEmbeddingModel()
    vector_idx = SQLiteVectorIndex(db_path, model)
    vector_idx.ensure_schema()

    raw = MIRLRecord(
        id="raw:1",
        kind=RecordKind.RAW,
        attrs={"source_ref": "test://input", "content": "Caroline: I went to the LGBTQ support group on 7 May 2023.", "media_type": "text/plain"},
    )
    # Also include a non-indexable record to confirm it is skipped
    sym = MIRLRecord(
        id="sym:1",
        kind=RecordKind.SYM,
        attrs={"symbol": "X", "expansion": "example"},
    )

    vector_idx.index_records([raw, sym])
    count = vector_idx.vector_count()
    assert count == 1, f"Expected 1 vector for the RAW record, got {count}"


def test_raw_record_is_searchable(tmp_path):
    """RAW record content is searchable after indexing."""
    from seam_runtime.models import HashEmbeddingModel

    db_path = str(tmp_path / "test_raw_searchable.db")
    model = HashEmbeddingModel()
    vector_idx = SQLiteVectorIndex(db_path, model)
    vector_idx.ensure_schema()

    raw = MIRLRecord(
        id="raw:1",
        kind=RecordKind.RAW,
        attrs={"source_ref": "test://input", "content": "Caroline: I went to the LGBTQ support group on 7 May 2023.", "media_type": "text/plain"},
    )
    vector_idx.index_records([raw])

    results = vector_idx.search("LGBTQ support group", limit=5)
    assert len(results) > 0, f"Expected at least one search result, got {len(results)}"
    assert "raw:1" in results, f"Expected raw:1 in search results, got {list(results.keys())}"
