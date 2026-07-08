"""cosine() numpy fast path must be a behavioral no-op vs the pure-Python branch.

HISTORY#363: seam_runtime.models.cosine gained an optional numpy fast path
(profiling showed it as a retrieval-scan hotspot). numpy is NOT a core
dependency, so both branches stay live: numpy when importable, pure Python
otherwise. These tests pin the two branches to identical results so the fast
path can never silently change retrieval rankings.
"""
from __future__ import annotations

import math
import random

import pytest

from seam_runtime import models
from seam_runtime.models import cosine

numpy = pytest.importorskip("numpy")


def _cosine_pure_python(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def test_numpy_branch_is_active() -> None:
    assert models._numpy is not None


def test_edge_cases_match_pure_python() -> None:
    edge_pairs = [
        ([], []),
        ([], [1.0]),
        ([1.0], []),
        ([1.0, 2.0], [1.0]),
        ([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]),
        ([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]),
        ([0.0], [0.0]),
    ]
    for left, right in edge_pairs:
        assert cosine(left, right) == 0.0
        assert cosine(left, right) == _cosine_pure_python(left, right)


def test_known_values() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_random_vectors_match_pure_python() -> None:
    rng = random.Random(7)
    for dimension in (2, 8, 384, 1152):
        for _ in range(25):
            left = [rng.uniform(-1.0, 1.0) for _ in range(dimension)]
            right = [rng.uniform(-1.0, 1.0) for _ in range(dimension)]
            assert cosine(left, right) == pytest.approx(
                _cosine_pure_python(left, right), abs=1e-12
            )


def test_pure_python_fallback_when_numpy_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "_numpy", None)
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([], [1.0]) == 0.0
    left = [0.3, -0.7, 0.2]
    right = [0.1, 0.4, -0.9]
    assert cosine(left, right) == pytest.approx(_cosine_pure_python(left, right))
