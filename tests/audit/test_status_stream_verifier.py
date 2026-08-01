"""Focused fail-closed checks for the status-stream verifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.status import verify_streams


def _configure_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_text: str,
    include_history: bool = True,
) -> None:
    stream_dir = tmp_path / "docs" / "status"
    archive = (
        tmp_path
        / "docs"
        / "status_archive"
        / "2026-07-30-project-status-full.md"
    )
    stream_dir.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    (stream_dir / "index.md").write_text(
        "| stream | file |\n|---|---|\n| `alpha` | [alpha.md](alpha.md) |\n"
    )
    (stream_dir / "alpha.md").write_text("# Alpha\n")
    (tmp_path / "PROJECT_STATUS.md").write_text(status_text)
    archive.write_text("# Preserved prior status\n")
    if include_history:
        (tmp_path / "HISTORY.md").write_text("# History\n")

    monkeypatch.setattr(verify_streams, "REPO", tmp_path)
    monkeypatch.setattr(verify_streams, "STREAM_DIR", stream_dir)
    monkeypatch.setattr(verify_streams, "INDEX", stream_dir / "index.md")
    monkeypatch.setattr(verify_streams, "STATUS", tmp_path / "PROJECT_STATUS.md")
    monkeypatch.setattr(verify_streams, "ARCHIVE", archive)
    monkeypatch.setattr(verify_streams, "HISTORY", tmp_path / "HISTORY.md")


def test_missing_history_is_a_verification_failure(tmp_path, monkeypatch):
    _configure_layout(
        tmp_path,
        monkeypatch,
        status_text="[alpha](docs/status/alpha.md)\n",
        include_history=False,
    )

    assert verify_streams.check() == ["HISTORY.md missing"]


@pytest.mark.parametrize(
    "status_text",
    [
        "Plain filename mention: alpha.md\n",
        "`docs/status/alpha.md`\n",
        "[wrong host](https://example.com/docs/status/alpha.md)\n",
        "[wrong path](docs/status/not-alpha.md) alpha.md\n",
    ],
)
def test_stream_requires_an_exact_markdown_link_target(
    tmp_path, monkeypatch, status_text
):
    _configure_layout(tmp_path, monkeypatch, status_text=status_text)

    assert verify_streams.check() == [
        "PROJECT_STATUS.md does not link stream 'alpha'"
    ]


def test_exact_markdown_stream_link_passes(tmp_path, monkeypatch):
    _configure_layout(
        tmp_path,
        monkeypatch,
        status_text="Read [the alpha stream](docs/status/alpha.md).\n",
    )

    assert verify_streams.check() == []
