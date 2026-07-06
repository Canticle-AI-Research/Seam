from __future__ import annotations

from benchmarks.external.common.scoring import (
    _normalize,
    context_recall,
    exact_match,
    token_f1,
)

# ---------------------------------------------------------------------------
# exact_match
# ---------------------------------------------------------------------------

def test_exact_match_identical() -> None:
    """Identical strings score 1.0."""
    assert exact_match("hello world", "hello world") == 1.0


def test_exact_match_normalized() -> None:
    """Normalization removes articles and punctuation so 'The cat' matches 'cat'."""
    assert exact_match("The cat.", "cat") == 1.0


def test_exact_match_different() -> None:
    """Strings with different meaning score 0.0."""
    assert exact_match("hello", "goodbye") == 0.0


# ---------------------------------------------------------------------------
# token_f1
# ---------------------------------------------------------------------------

def test_token_f1_perfect() -> None:
    """Identical strings after normalization give token F1 of 1.0."""
    assert token_f1("the quick brown fox", "quick brown fox") == 1.0


def test_token_f1_partial() -> None:
    """Partial overlap yields an F1 strictly between 0 and 1."""
    score = token_f1("the quick brown fox", "the lazy brown dog")
    assert 0.0 < score < 1.0, f"expected 0 < score < 1, got {score}"


def test_token_f1_no_overlap() -> None:
    """Zero token overlap gives 0.0."""
    assert token_f1("hello world", "foo bar") == 0.0


def test_token_f1_empty_pred() -> None:
    """An empty prediction yields 0.0 regardless of gold."""
    assert token_f1("", "the quick brown fox") == 0.0


# ---------------------------------------------------------------------------
# context_recall
# ---------------------------------------------------------------------------

def test_context_recall_full() -> None:
    """When every gold token appears in retrieved, context_recall is 1.0."""
    retrieved = "the cat sat on the mat"
    gold = "cat sat on mat"
    assert context_recall(retrieved, gold) == 1.0


def test_context_recall_none() -> None:
    """When zero gold tokens appear in retrieved, context_recall is 0.0."""
    retrieved = "the quick brown fox"
    gold = "cat sat on mat"
    assert context_recall(retrieved, gold) == 0.0


def test_context_recall_empty_gold() -> None:
    """Empty gold answer is defined as 1.0 recall."""
    assert context_recall("anything", "") == 1.0


# ---------------------------------------------------------------------------
# _normalize (internal helper exercised via scoring functions above)
# ---------------------------------------------------------------------------

def test_normalize_strips_articles_and_punctuation() -> None:
    """_normalize lowercases, removes articles, and strips punctuation."""
    result = _normalize("The quick, brown fox! A lazy dog? An elephant.")
    # "the", "a", "an" removed; punctuation stripped; lowercased
    expected = "quick brown fox lazy dog elephant"
    assert result == expected, f"got {result!r}"
