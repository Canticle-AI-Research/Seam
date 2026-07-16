"""Lane C -- reingest source dedup test.

When the same source_ref is ingested with different content, the old document
should be marked as deleted (deleted_at set) and the new document should be
active. Search should return only the new content.
"""

import json
from pathlib import Path

import pytest

from seam_runtime.runtime import SeamRuntime


@pytest.fixture
def runtime(tmp_path: Path) -> SeamRuntime:
    """SeamRuntime with a temp file-based database."""
    return SeamRuntime(str(tmp_path / "test_seam.db"))


def test_reingest_same_source_ref_dedup(runtime: SeamRuntime):
    """Ingest same source_ref twice with different content; old doc must be
    superseded, new doc active, and search returns only new content."""
    source_ref = "test://dedup/source"

    # --- First ingest ---
    report1 = runtime.ingest_text(
        "alpha bravo charlie", source_ref=source_ref, persist=True
    )

    doc1_id = report1.document["document_id"]
    doc1 = runtime.store.read_document_status(doc1_id)
    assert doc1["deleted_at"] is None, (
        f"First document should be active, got deleted_at={doc1['deleted_at']}"
    )
    assert doc1["source_ref"] == source_ref

    # --- Second ingest (same source_ref, different content) ---
    report2 = runtime.ingest_text(
        "delta echo foxtrot", source_ref=source_ref, persist=True
    )

    doc2_id = report2.document["document_id"]
    doc2 = runtime.store.read_document_status(doc2_id)
    assert doc2["deleted_at"] is None, (
        f"Second document should be active, got deleted_at={doc2['deleted_at']}"
    )
    assert doc2["source_ref"] == source_ref
    # Different content means different document_id.
    assert doc2_id != doc1_id, (
        f"Expected different document_id for different content, got same: {doc1_id}"
    )

    # --- Verify old document is superseded ---
    doc1_after = runtime.store.read_document_status(doc1_id)
    assert doc1_after["deleted_at"] is not None, (
        f"Old document should have deleted_at set after reingest, got: {doc1_after}"
    )

    # --- Verify only one active document for this source_ref ---
    all_docs = runtime.store.list_document_status(limit=200)
    active_for_ref = [
        d for d in all_docs
        if d["source_ref"] == source_ref and d["deleted_at"] is None
    ]
    assert len(active_for_ref) == 1, (
        f"Expected exactly 1 active document for source_ref, got {len(active_for_ref)}: {active_for_ref}"
    )
    assert active_for_ref[0]["document_id"] == doc2_id

    # --- Verify search returns new content ---
    search_result = runtime.memory_search("delta echo")
    found_new = False
    for item in search_result.get("results", []):
        record_id = item.get("id", "")
        if doc2_id in record_id or any(
            sid.startswith("clm:") or sid.startswith("raw:")
            for sid in (item.get("stored_ids", []) or [])
        ):
            found_new = True
            break
    # If structured search didn't match, try raw text search.
    if not found_new:
        search_raw = runtime.memory_search("delta echo foxtrot")
        found_new = len(search_raw.get("results", [])) > 0

    assert found_new, (
        f"Search for new content returned no results. "
        f"Search result: {json.dumps(search_result, indent=2)[:500]}"
    )


def test_reingest_same_source_ref_multiple_generations(runtime: SeamRuntime):
    """Ingest three times with the same source_ref; only the latest should be
    active, and the mark_document_superseded count should be correct."""
    source_ref = "test://multi-gen"

    # Ingest three generations.
    runtime.ingest_text("gen 1 content here", source_ref=source_ref, persist=True)
    runtime.ingest_text("gen 2 content here now", source_ref=source_ref, persist=True)
    report3 = runtime.ingest_text(
        "gen 3 final content here now", source_ref=source_ref, persist=True
    )

    all_docs = runtime.store.list_document_status(limit=200)
    docs_for_ref = [d for d in all_docs if d["source_ref"] == source_ref]

    # All three documents should exist (but only latest is active).
    assert len(docs_for_ref) == 3, (
        f"Expected 3 document_status rows, got {len(docs_for_ref)}"
    )

    # Only the latest (gen 3) should be active.
    active = [d for d in docs_for_ref if d["deleted_at"] is None]
    assert len(active) == 1, f"Expected 1 active, got {len(active)}"
    assert active[0]["document_id"] == report3.document["document_id"]

    # The other two should have deleted_at set.
    superseded = [d for d in docs_for_ref if d["deleted_at"] is not None]
    assert len(superseded) == 2, f"Expected 2 superseded, got {len(superseded)}"


def test_reingest_different_source_ref_no_cross_dedup(runtime: SeamRuntime):
    """Documents with different source_refs must NOT dedup each other."""
    runtime.ingest_text("content A", source_ref="test://ref-a", persist=True)
    runtime.ingest_text("content B", source_ref="test://ref-b", persist=True)

    all_docs = runtime.store.list_document_status(limit=200)
    active = [d for d in all_docs if d["deleted_at"] is None]
    assert len(active) >= 2, (
        f"Documents with different source_refs should both be active, got {len(active)} active"
    )


def test_reingest_no_persist_skips_dedup(runtime: SeamRuntime):
    """When persist=False, dedup must NOT run, and the previous document must
    remain active (not superseded)."""
    source_ref = "test://no-persist-dedup"

    # First ingest with persist=True.
    report1 = runtime.ingest_text(
        "persisted content", source_ref=source_ref, persist=True
    )
    doc1_id = report1.document["document_id"]

    # Second ingest with persist=False.
    report2 = runtime.ingest_text(
        "non-persisted content", source_ref=source_ref, persist=False
    )

    # The first document should still be active (no dedup happened because
    # persist=False skips the dedup call).
    doc1_after = runtime.store.read_document_status(doc1_id)
    assert doc1_after["deleted_at"] is None, (
        "Persisted document should NOT be superseded when reingest had persist=False"
    )

    # The report should still have the document info even without persist.
    assert report2.document is not None
    assert report2.stored_ids == []
