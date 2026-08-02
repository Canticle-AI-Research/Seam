from __future__ import annotations

import logging

import pytest

from seam_runtime.knowledge_graph import _time_reached


@pytest.mark.parametrize("value", ["Jan 1 2020", "01/01/2020"])
def test_time_reached_fails_closed_for_non_iso_timestamp(
    value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="seam_runtime.knowledge_graph"):
        assert _time_reached(value, "2026-08-01T00:00:00+00:00") is True

    assert "treating the validity interval as expired" in caplog.text
    assert value not in caplog.text


def test_time_reached_fails_closed_for_incomparable_iso_timestamps(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="seam_runtime.knowledge_graph"):
        assert _time_reached("2020-01-01", "2026-08-01T00:00:00+00:00") is True

    assert "treating the validity interval as expired" in caplog.text


def test_time_reached_preserves_valid_iso_ordering(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="seam_runtime.knowledge_graph"):
        assert _time_reached(
            "2020-01-01T00:00:00+00:00",
            "2026-08-01T00:00:00+00:00",
        ) is True
        assert _time_reached(
            "2030-01-01T00:00:00+00:00",
            "2026-08-01T00:00:00+00:00",
        ) is False

    assert not caplog.records
