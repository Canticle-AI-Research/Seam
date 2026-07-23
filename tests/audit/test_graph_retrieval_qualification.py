"""Provider-free G3 corpus/query-shape qualification contract."""

from __future__ import annotations

import pytest

from seam_runtime.retrieval_policy import FUSION_POLICY
from tools.graph_retrieval_qualification import (
    QUALIFICATION_SCHEMA,
    run_qualification,
)


def test_graph_retrieval_qualification_is_bounded_and_deterministic() -> None:
    report = run_qualification(
        node_count=256,
        repeats=2,
        max_latency_ms=5_000.0,
    )

    assert report["schema"] == QUALIFICATION_SCHEMA
    assert report["fusion_policy"] == FUSION_POLICY
    assert report["provider_calls"] == 0
    assert report["corpus"]["nodes"] == 256
    assert report["corpus"]["edges"] == 255
    assert report["passed"] is True
    assert [shape["name"] for shape in report["shapes"]] == [
        "structured-filter",
        "lexical-hop-1",
        "lexical-hop-3",
        "history-hop-3",
        "mixed-semantic-seeded",
    ]
    assert all(shape["passed"] for shape in report["shapes"])
    assert all(shape["total_candidates"] <= 60 for shape in report["shapes"])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"node_count": 7}, "node_count"),
        ({"repeats": 0}, "repeats"),
        ({"max_latency_ms": 0.0}, "max_latency_ms"),
    ],
)
def test_graph_retrieval_qualification_rejects_invalid_bounds(
    kwargs: dict[str, object], message: str
) -> None:
    defaults: dict[str, object] = {
        "node_count": 8,
        "repeats": 1,
        "max_latency_ms": 1000.0,
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError, match=message):
        run_qualification(**defaults)
