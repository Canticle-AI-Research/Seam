"""Tests for BM25 lexical channel over RAW records."""

from seam_runtime.bm25 import BM25Index


def test_bm25_ranks_term_frequency_higher():
    """BM25 ranks a doc with the query term repeated 5x above a doc with it once."""
    idx = BM25Index()
    idx.add("doc_a", "cat cat cat cat cat dog")
    idx.add("doc_b", "cat dog bird fish cow")
    scores = idx.score("cat")
    assert scores.get("doc_a", 0) > scores.get("doc_b", 0), (
        f"doc_a (5x 'cat') should score higher than doc_b (1x 'cat'); "
        f"got a={scores.get('doc_a')}, b={scores.get('doc_b')}"
    )


def test_bm25_uses_idf():
    """When a term appears in every doc, IDF is low; ranking reflects term frequency distribution."""
    idx = BM25Index()
    idx.add("doc_a", "common word here extra stuff for length padding")
    idx.add("doc_b", "common word there extra padding to make this document a bit longer")
    scores = idx.score("common")
    # Both docs contain "common", so IDF should be near zero and scores low
    assert all(v < 0.5 for v in scores.values()), (
        f"Common-term scores should be low (high IDF penalty); got {scores}"
    )


def test_bm25_empty_on_absent_terms():
    """Query with absent terms returns empty dict."""
    idx = BM25Index()
    idx.add("doc_a", "hello world")
    scores = idx.score("xyzzy_nonexistent")
    assert scores == {}, f"Expected empty scores for absent term, got {scores}"


def test_bm25_empty_corpus():
    """Empty corpus returns empty scores."""
    idx = BM25Index()
    scores = idx.score("anything")
    assert scores == {}, f"Empty corpus should return empty scores, got {scores}"


def test_bm25_empty_query():
    """Empty query returns empty scores."""
    idx = BM25Index()
    idx.add("doc_a", "hello world")
    scores = idx.score("")
    assert scores == {}, f"Empty query should return empty scores, got {scores}"


def test_bm25_empty_doc_text():
    """Documents with only non-token characters are skipped."""
    idx = BM25Index()
    idx.add("doc_a", "!!!")
    idx.add("doc_b", "hello world")
    scores = idx.score("hello")
    assert "doc_a" not in scores, "Empty-token doc should not appear in scores"
    assert "doc_b" in scores, "Doc with matching text should appear in scores"
