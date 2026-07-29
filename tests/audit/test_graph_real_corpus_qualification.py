from __future__ import annotations

from tools.graph_real_corpus_qualification import (
    QUALIFICATION_SCHEMA,
    qualify_real_corpus,
)


def test_real_corpus_graph_qualification_uses_pinned_locomo_without_providers():
    report = qualify_real_corpus(
        sessions=1,
        probe_sample=12,
    )
    assert report["schema"] == QUALIFICATION_SCHEMA
    assert report["provider_calls"] == 0
    assert report["dataset"]["sample_id"] == "conv-26"
    assert report["probe_count"] > 0
    assert report["node_vectors"]["coverage"] == 1.0
    assert report["graph_node_trace_rate"] > 0.0
    assert report["passed"] is True
