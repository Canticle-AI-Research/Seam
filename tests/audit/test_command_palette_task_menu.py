"""The `/` command palette: every command described, grouped by shared task.

Two failures the previous catalog shipped with, both invisible unless you
build the catalog and look:

* 104 of 153 commands (cli, api, most of sdk) carried an empty `summary` --
  descriptions must be derived from each surface's own source (argparse
  `help=`, FastAPI route `summary=`, SDK docstrings), never hand-transcribed
  into `commands.py`.
* the menu grouped by "where the code lives" (surface, then a per-surface
  sub-group) rather than "what an operator wants to do". Every surface now
  shares one task vocabulary (`TASK_GROUPS`), and the palette renders two
  sections -- Run (executable dash verbs) then Reference (cli/mcp/api/sdk) --
  grouped by that shared vocabulary within each section.

`textual` is an optional extra (`seam[dash]`); only the one test that mounts
the real `CommandPalette` needs it, guarded the same way as
`test_tui_supersedes_dashboard.py` so a module-level import never aborts the
whole suite on an installation without the extra.
"""

from __future__ import annotations

import argparse
from importlib.util import find_spec
from pathlib import Path

import pytest

from seam_runtime.dashboard import DashboardApp
from seam_runtime.runtime import SeamRuntime
from seam_runtime.tui.commands import (
    _ROUTE_RE,
    _subparser_help,
    _walk_parser,
    build_catalog,
)
from seam_runtime.tui.commands import TASK_GROUPS as _TASK_GROUPS

textual_required = pytest.mark.skipif(
    find_spec("textual") is None, reason="textual is not installed"
)


def _catalog(tmp_path: Path):
    backend = DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))
    return build_catalog(backend.command_parser)


class TestEveryCommandIsDescribed:
    """The census gate: this must fail the moment a new command ships bare."""

    def test_every_spec_has_a_nonempty_summary(self, tmp_path: Path) -> None:
        catalog = _catalog(tmp_path)
        assert catalog, "catalog must not be empty"
        missing = [f"{c.surface}:{c.name}" for c in catalog if not c.summary]
        assert missing == [], (
            f"{len(missing)}/{len(catalog)} commands carry no description: "
            f"{missing[:15]}"
        )


class TestEveryCommandIsGrouped:
    """Every command lands in exactly one member of the shared vocabulary."""

    def test_every_spec_group_is_in_the_task_vocabulary(self, tmp_path: Path) -> None:
        catalog = _catalog(tmp_path)
        ungrouped = [f"{c.surface}:{c.name}" for c in catalog if not c.group]
        assert ungrouped == [], f"ungrouped commands: {ungrouped[:15]}"
        bad = [
            (f"{c.surface}:{c.name}", c.group)
            for c in catalog
            if c.group not in _TASK_GROUPS
        ]
        assert bad == [], f"groups outside the task vocabulary: {bad[:15]}"

    def test_no_real_bucket_is_a_quiet_catch_all(self, tmp_path: Path) -> None:
        """Sanity check on the design, not just the mechanism: a fallback
        bucket silently absorbing more than a handful of commands would mean
        the compact rule set missed real structure, and should have been
        reported rather than dumped. None of the fallback defaults in
        commands.py (`_cli_task_group`, `_mcp_task_group`, `_api_task_group`,
        `_SDK_TASK_NAMES.get(..., "Lifecycle & admin")`) are ever exercised
        by the current 153 commands, so this stays trivially true today and
        catches the day that stops being so.
        """
        catalog = _catalog(tmp_path)
        from collections import Counter

        counts = Counter(c.group for c in catalog)
        # "Lifecycle & admin" is a real, named task (tenant lifecycle ops,
        # doctor, transpile, ...), not a dumping ground -- but if it balloons
        # past a generous ceiling, something is being quietly dumped there.
        assert counts["Lifecycle & admin"] <= 16, dict(counts)


class TestWalkParserReadsArgparseHelp:
    """`_walk_parser` must read `help=`, which argparse keeps on the parent
    subparsers action, not on the child parser's `description`."""

    def _tree(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="throwaway")
        sub = parser.add_subparsers(dest="command", required=True)
        sub.add_parser("foo", help="Do the foo thing")
        sub.add_parser("bar", description="Bar description, no help kwarg")
        sub.add_parser("baz")  # neither help nor description
        return parser

    def test_help_kwarg_is_picked_up(self) -> None:
        specs = _walk_parser(self._tree(), "cli")
        by_name = {s.name: s for s in specs}
        assert by_name["foo"].summary == "Do the foo thing"

    def test_falls_back_to_description_when_no_help(self) -> None:
        specs = _walk_parser(self._tree(), "cli")
        by_name = {s.name: s for s in specs}
        assert by_name["bar"].summary == "Bar description, no help kwarg"

    def test_neither_help_nor_description_yields_empty_not_a_crash(self) -> None:
        specs = _walk_parser(self._tree(), "cli")
        by_name = {s.name: s for s in specs}
        assert by_name["baz"].summary == ""

    def test_subparser_help_degrades_without_choices_actions(self) -> None:
        """A future argparse without the private `_choices_actions`
        attribute must degrade to an empty map, not raise."""

        class BareAction:
            pass

        assert _subparser_help(BareAction()) == {}


class TestRouteRegexCapturesOptionalSummary:
    """`_ROUTE_RE` must keep matching a decorator with no `summary=`."""

    def test_captures_summary_when_present(self) -> None:
        source = (
            '@app.get("/stats", summary="Return runtime and store statistics", '
            "dependencies=[Depends(guard)])"
        )
        assert _ROUTE_RE.findall(source) == [
            ("get", "/stats", "Return runtime and store statistics")
        ]

    def test_still_yields_the_route_when_summary_is_absent(self) -> None:
        source = '@app.post("/persist", dependencies=[Depends(guard)])'
        assert _ROUTE_RE.findall(source) == [("post", "/persist", "")]

    def test_multiple_routes_in_one_source_blob(self) -> None:
        source = (
            '@app.get("/a", summary="A")\n'
            'def a(): ...\n'
            '@app.post("/b")\n'
            'def b(): ...\n'
        )
        assert _ROUTE_RE.findall(source) == [("get", "/a", "A"), ("post", "/b", "")]


class TestRunSectionSortsAheadOfReference:
    """The palette's Run/Reference split is a property of catalog order:
    every executable (dash) row precedes every non-executable (reference)
    row, so the unfiltered palette renders Run, then Reference, never
    interleaved."""

    def test_executable_rows_form_one_contiguous_leading_block(
        self, tmp_path: Path
    ) -> None:
        catalog = _catalog(tmp_path)
        flags = [c.executable for c in catalog]
        assert any(flags), "expected at least one executable (Run) row"
        assert not all(flags), "expected at least one reference row"
        first_reference = flags.index(False)
        assert all(flags[:first_reference]), "a reference row sorted before a Run row"
        assert not any(flags[first_reference:]), "a Run row sorted after the first reference row"

    def test_run_rows_are_exactly_the_executable_dash_verbs(self, tmp_path: Path) -> None:
        catalog = _catalog(tmp_path)
        run_rows = [c for c in catalog if c.executable]
        assert {c.surface for c in run_rows} == {"dash"}
        assert len(run_rows) == 20


@textual_required
class TestPaletteRendersTwoSections:
    """End-to-end confirmation that the rendered palette shows Run before
    Reference, with a dim surface tag on reference rows."""

    def test_run_header_precedes_reference_header(self, tmp_path: Path) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import OptionList

        from seam_runtime.tui.app import CommandPalette

        catalog = _catalog(tmp_path)

        class _PaletteHarness(App[None]):
            async def on_mount(self) -> None:
                await self.push_screen(CommandPalette(catalog))

        async def _check() -> None:
            app = _PaletteHarness()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                option_list = app.screen.query_one("#palette-list", OptionList)
                labels = [
                    str(option_list.get_option_at_index(i)._prompt)
                    for i in range(option_list.option_count)
                ]
                run_index = next(i for i, label in enumerate(labels) if "Run" in label)
                reference_index = next(
                    i for i, label in enumerate(labels) if "Reference" in label
                )
                assert run_index < reference_index
                # A reference row (after the Reference header) carries a
                # surface tag; "rest" for the api surface specifically.
                assert any("rest" in label for label in labels[reference_index:])

        asyncio.run(_check())
