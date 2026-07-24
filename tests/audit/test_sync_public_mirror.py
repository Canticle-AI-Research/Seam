"""The legacy Seam_Runtime mirror must fail closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.release.sync_public_mirror import (
    FROZEN_MESSAGE,
    PublicMirrorFrozenError,
    build_public_commit,
    build_public_tree,
    main,
)


def test_build_public_tree_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(PublicMirrorFrozenError, match="public mirror is frozen"):
        build_public_tree(tmp_path, "main")


def test_build_public_commit_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(PublicMirrorFrozenError, match="public mirror is frozen"):
        build_public_commit(tmp_path, "main", "must not publish")


@pytest.mark.parametrize("args", [[], ["--push"], ["--no-fetch"], ["--ref", "HEAD"]])
def test_cli_refuses_every_legacy_sync_mode(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(args) == 2
    captured = capsys.readouterr()
    assert FROZEN_MESSAGE in captured.err
    assert "separately reviewed public client/SDK" in captured.err
