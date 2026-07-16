from __future__ import annotations

import pytest

from seam_runtime.evals import (
    RetrievalFixture,
    _aggregate_pack,
    _aggregate_track,
    _beats,
    _rank_vector_only,
    _track_report,
)


class TestTrackReport:
    def test_hit_when_expected_id_in_ranked(self):
        report = _track_report(["a", "b", "c"], ["b"])
        assert report["hit"] is True
        assert report["first_relevant_rank"] == 2
        assert report["reciprocal_rank"] == 0.5
        assert report["recall_at_k"] == 1.0

    def test_miss_when_no_expected_id(self):
        report = _track_report(["a", "b", "c"], ["x"])
        assert report["hit"] is False
        assert report["first_relevant_rank"] is None
        assert report["recall_at_k"] == 0.0

    def test_partial_recall(self):
        report = _track_report(["a", "b", "c"], ["a", "x", "y"])
        assert report["relevant_hits"] == 1
        assert report["recall_at_k"] == pytest.approx(1 / 3)

    def test_empty_expected_guards_division(self):
        report = _track_report(["a"], [])
        assert report["recall_at_k"] == 0.0


class TestAggregateTrack:
    def test_aggregates_across_multiple_results(self):
        results = [
            {"tracks": {"t1": {"hit": True, "reciprocal_rank": 1.0, "recall_at_k": 1.0}}},
            {"tracks": {"t1": {"hit": False, "reciprocal_rank": 0.0, "recall_at_k": 0.0}}},
        ]
        agg = _aggregate_track(results, "t1")
        assert agg["hit_rate"] == 0.5
        assert agg["mrr"] == 0.5
        assert agg["recall_at_k"] == 0.5

    def test_empty_results_returns_zero(self):
        agg = _aggregate_track([], "t1")
        assert agg["hit_rate"] == 0.0


class TestAggregatePack:
    def test_aggregates_pack_modes(self):
        results = [
            {"packs": {"exact": {"overall": 1.0, "compression_ratio": 0.5, "traceability": 0.8}}},
            {"packs": {"exact": {"overall": 0.0, "compression_ratio": 0.3, "traceability": 0.4}}},
        ]
        agg = _aggregate_pack(results, "exact")
        assert agg["overall"] == 0.5
        assert agg["compression_ratio"] == 0.4
        assert agg["traceability"] == 0.6


class TestBeats:
    def test_better_recall_and_rr_wins(self):
        a = {"tracks": {"a": {"recall_at_k": 0.8, "reciprocal_rank": 0.5}, "b": {"recall_at_k": 0.5, "reciprocal_rank": 0.3}}}
        assert _beats(a, "a", "b") is True

    def test_worse_loses(self):
        a = {"tracks": {"a": {"recall_at_k": 0.5, "reciprocal_rank": 0.3}, "b": {"recall_at_k": 0.8, "reciprocal_rank": 0.5}}}
        assert _beats(a, "a", "b") is False


class TestRankVectorOnly:
    def test_ranks_by_score_descending(self):
        scores = {"a": 0.5, "b": 0.9, "c": 0.1}
        ranked = _rank_vector_only(scores, limit=2)
        assert ranked == ["b", "a"]

    def test_respects_limit(self):
        scores = {"a": 0.5, "b": 0.9, "c": 0.1}
        ranked = _rank_vector_only(scores, limit=1)
        assert ranked == ["b"]


class TestRetrievalFixture:
    def test_fixture_is_frozen(self):
        f = RetrievalFixture(name="x", category="fact", format="dsl", source="", query="", expected_ids=[])
        with pytest.raises(Exception):
            f.name = "y"
