from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tools.history.history_lib import format_entry
from tools.history.verify_handoffs import SCHEMA, HandoffRow, verify_handoffs


def _write_history(root: Path, ids: tuple[int, ...] = (1, 2)) -> Path:
    history = root / "HISTORY.md"
    entries = [
        format_entry(
            id=entry_id,
            date="2026-07-11T00:00:00Z",
            agent="test",
            status="done",
            topics=["handoff"],
            commits="none",
            refs="docs/handoffs/INDEX.md",
            supersedes="none" if entry_id == ids[0] else str(ids[ids.index(entry_id) - 1]),
            tokens=10,
            body=f"Test entry {entry_id}.",
        )
        for entry_id in ids
    ]
    history.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    return history


def _write_doc(handoffs: Path, row: HandoffRow) -> None:
    (handoffs / row.path).write_text(
        "\n".join(
            [
                "---",
                f"handoff_id: {row.handoff_id}",
                f"supersedes: {row.supersedes or 'none'}",
                f"handoff_status: {row.status}",
                f"history: {row.history}",
                "---",
                "",
                f"# {row.handoff_id}",
                "",
                "Test handoff.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_registry(root: Path, rows: list[HandoffRow], *, latest: str | None = None) -> tuple[Path, Path]:
    handoffs = root / "docs" / "handoffs"
    handoffs.mkdir(parents=True)
    for row in rows:
        _write_doc(handoffs, row)

    latest = latest or rows[0].handoff_id
    table = [
        "---",
        f"schema: {SCHEMA}",
        f"latest: {latest}",
        "---",
        "",
        "# Handoff Registry",
        "",
        "| handoff_id | path | supersedes | history | status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        table.append(
            f"| `{row.handoff_id}` | [{row.path}]({row.path}) | "
            f"`{row.supersedes or 'none'}` | `{row.history}` | `{row.status}` |"
        )
    index = handoffs / "INDEX.md"
    index.write_text("\n".join(table) + "\n", encoding="utf-8")
    history = _write_history(root)
    return index, history


def _valid_rows() -> list[HandoffRow]:
    return [
        HandoffRow("handoff-two", "handoff-two.md", "handoff-one", "HISTORY#2", "current"),
        HandoffRow("handoff-one", "handoff-one.md", None, "HISTORY#1", "superseded"),
    ]


def _verify(root: Path, index: Path, history: Path) -> tuple[bool, list[str]]:
    return verify_handoffs(index, repo_root=root, history_path=history)


def test_valid_linear_registry_passes(tmp_path: Path) -> None:
    index, history = _write_registry(tmp_path, _valid_rows())

    ok, errors = _verify(tmp_path, index, history)

    assert ok, errors


def test_missing_supersedes_target_fails(tmp_path: Path) -> None:
    rows = _valid_rows()
    rows[0] = replace(rows[0], supersedes="missing-handoff")
    index, history = _write_registry(tmp_path, rows)

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("supersedes missing target missing-handoff" in error for error in errors)


def test_cycle_fails(tmp_path: Path) -> None:
    rows = _valid_rows()
    rows[1] = replace(rows[1], supersedes="handoff-two")
    index, history = _write_registry(tmp_path, rows)

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("contains a cycle" in error for error in errors)


def test_fork_and_multiple_live_heads_fail(tmp_path: Path) -> None:
    rows = _valid_rows()
    third = HandoffRow("handoff-three", "handoff-three.md", "handoff-one", "HISTORY#2", "superseded")
    rows.append(third)
    index, history = _write_registry(tmp_path, rows)

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("forks at handoff-one" in error for error in errors)
    assert any("exactly one live head" in error for error in errors)


def test_latest_must_match_head_and_current_status(tmp_path: Path) -> None:
    index, history = _write_registry(tmp_path, _valid_rows(), latest="handoff-one")

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("does not match live head handoff-two" in error for error in errors)
    assert any("does not match current handoff handoff-two" in error for error in errors)


def test_document_metadata_must_match_index(tmp_path: Path) -> None:
    rows = _valid_rows()
    index, history = _write_registry(tmp_path, rows)
    doc = tmp_path / "docs" / "handoffs" / rows[0].path
    doc.write_text(doc.read_text(encoding="utf-8").replace("handoff_status: current", "handoff_status: superseded"), encoding="utf-8")

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("metadata handoff_status='superseded'" in error for error in errors)


def test_unregistered_handoff_document_fails(tmp_path: Path) -> None:
    index, history = _write_registry(tmp_path, _valid_rows())
    extra = tmp_path / "docs" / "handoffs" / "forgotten.md"
    extra.write_text("# Forgotten\n", encoding="utf-8")

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("unregistered handoff document" in error for error in errors)


def test_missing_history_reference_fails(tmp_path: Path) -> None:
    rows = _valid_rows()
    rows[0] = replace(rows[0], history="HISTORY#99")
    index, history = _write_registry(tmp_path, rows)

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("references missing HISTORY#99" in error for error in errors)


def test_newest_first_table_order_is_enforced(tmp_path: Path) -> None:
    rows = list(reversed(_valid_rows()))
    index, history = _write_registry(tmp_path, rows, latest="handoff-two")

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("newest-first chain must start" in error for error in errors)


def test_handoff_history_references_must_follow_chronological_chain(
    tmp_path: Path,
) -> None:
    rows = _valid_rows()
    rows[0] = replace(rows[0], history="HISTORY#1")
    index, history = _write_registry(tmp_path, rows)

    ok, errors = _verify(tmp_path, index, history)

    assert not ok
    assert any("handoff history order broken" in error for error in errors)
