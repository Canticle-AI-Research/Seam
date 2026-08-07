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


class TestFirstSentenceCutsOnSentenceNotLine:
    """Part 5 of S2b: summaries used to cut at the first *line*
    (`.split("\n")[0]`). MCP descriptions are single physical lines but
    several sentences, so nothing was ever cut and the row wrapped; CLI/SDK
    docstrings can word-wrap their first sentence across source lines, so
    cutting at "\n" truncated mid-sentence. Collapsing whitespace and
    cutting at the first `.`/`!`/`?` fixes both."""

    def test_single_sentence_with_no_terminal_punctuation_is_unchanged(self) -> None:
        from seam_runtime.tui.commands import _first_sentence

        assert _first_sentence("Do the foo thing") == "Do the foo thing"

    def test_multi_sentence_text_is_cut_at_the_first_period(self) -> None:
        from seam_runtime.tui.commands import _first_sentence

        text = "Run a search and return matches. Useful for finding related concepts."
        assert _first_sentence(text) == "Run a search and return matches."

    def test_a_sentence_word_wrapped_across_source_lines_is_not_cut_mid_sentence(self) -> None:
        from seam_runtime.tui.commands import _first_sentence

        text = (
            "Do the foo thing across every namespace and every scope, returning a\n"
            "dict of results keyed by record id."
        )
        assert _first_sentence(text) == (
            "Do the foo thing across every namespace and every scope, returning a "
            "dict of results keyed by record id."
        )

    def test_trailing_sentence_with_no_following_text_is_kept_whole(self) -> None:
        from seam_runtime.tui.commands import _first_sentence

        assert _first_sentence("Do the thing.") == "Do the thing."

    def test_empty_and_blank_text_yield_empty(self) -> None:
        from seam_runtime.tui.commands import _first_sentence

        assert _first_sentence("") == ""
        assert _first_sentence("   \n  ") == ""


class TestMcpSummaryIsCutAtFirstSentence:
    """The MCP path specifically: `TOOL_METADATA` descriptions are already
    single-line, so the old `.split("\n")[0]` never truncated a
    multi-sentence one -- it passed through whole and wrapped the row."""

    def test_synthetic_multi_sentence_description_is_cut_to_one_sentence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from seam_runtime.tui import commands as commands_module

        fake_metadata = {
            "seam_fake_tool": {
                "description": (
                    "Do the thing well. It also does a second thing you "
                    "should know about."
                )
            }
        }
        monkeypatch.setattr("seam_runtime.mcp.TOOL_METADATA", fake_metadata, raising=False)

        specs = commands_module._mcp_specs()

        assert len(specs) == 1
        assert specs[0].summary == "Do the thing well."


class TestSdkRowsAreTrimmedButKeepTheFullSignature:
    """Part 5 of S2b: `sdk.knowledge(**query: 'Any') -> 'dict[str, object]'`
    was long enough to wrap the row's summary onto a second line. `name`
    now carries a trimmed call form for the row; `full_signature` keeps the
    untrimmed form for the reference card (`SeamTUI._show_reference`)."""

    def _knowledge_spec(self, tmp_path: Path):
        catalog = _catalog(tmp_path)
        return next(c for c in catalog if c.surface == "sdk" and c.name.startswith("knowledge("))

    def test_row_name_is_a_trimmed_call_form(self, tmp_path: Path) -> None:
        spec = self._knowledge_spec(tmp_path)
        assert spec.name == "knowledge(**query)"
        assert "Any" not in spec.name
        assert "->" not in spec.name
        assert "self" not in spec.name

    def test_full_signature_keeps_the_untrimmed_form(self, tmp_path: Path) -> None:
        spec = self._knowledge_spec(tmp_path)
        assert spec.full_signature.startswith("knowledge(")
        assert "query" in spec.full_signature

    def test_full_signature_is_empty_for_every_non_sdk_surface(self, tmp_path: Path) -> None:
        catalog = _catalog(tmp_path)
        non_sdk = [c for c in catalog if c.surface != "sdk"]
        assert non_sdk, "expected non-sdk rows to exist"
        assert all(c.full_signature == "" for c in non_sdk)

    def test_sdk_summary_is_still_derived_and_sentence_cut(self, tmp_path: Path) -> None:
        spec = self._knowledge_spec(tmp_path)
        assert spec.summary
        assert spec.summary.count(". ") == 0  # a real second sentence would show up as ". "


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

    def test_sdk_row_shows_the_trimmed_call_form_not_the_full_signature(
        self, tmp_path: Path
    ) -> None:
        """The rendered row text itself, not just the underlying
        `CommandSpec.name` -- confirms `_render_options` (app.py) puts the
        trimmed form on screen."""
        import asyncio

        from textual.app import App
        from textual.widgets import OptionList

        from seam_runtime.tui.app import CommandPalette

        catalog = _catalog(tmp_path)

        class _PaletteHarness(App[None]):
            async def on_mount(self) -> None:
                await self.push_screen(CommandPalette(catalog, initial="knowledge(**"))

        async def _check() -> None:
            app = _PaletteHarness()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                option_list = app.screen.query_one("#palette-list", OptionList)
                rows = [
                    str(option_list.get_option_at_index(i)._prompt)
                    for i in range(option_list.option_count)
                ]
                knowledge_rows = [row for row in rows if "sdk.knowledge(" in row]
                assert knowledge_rows, rows
                assert all("Any" not in row for row in knowledge_rows)
                assert all("->" not in row for row in knowledge_rows)

        asyncio.run(_check())


@textual_required
class TestModesGroupIsDiscoverableFromTheMenu:
    """Part 5 of S2b: `!shell`, `?chat`, `/seam` are listed in the Run
    section so the modes are discoverable from the menu, not just from
    documentation."""

    def test_modes_group_and_all_three_rows_render(self, tmp_path: Path) -> None:
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
                assert any("Modes" in label for label in labels)
                assert any("!shell" in label for label in labels)
                assert any("?chat" in label for label in labels)
                assert any("/seam" in label for label in labels)

        asyncio.run(_check())

    def test_selecting_a_mode_row_dismisses_with_a_mode_id(self, tmp_path: Path) -> None:
        import asyncio

        from textual.app import App
        from textual.widgets import OptionList

        from seam_runtime.tui.app import CommandPalette

        catalog = _catalog(tmp_path)
        dismissed: list[str] = []

        class _PaletteHarness(App[None]):
            async def on_mount(self) -> None:
                self.push_screen(CommandPalette(catalog), dismissed.append)

        async def _check() -> None:
            app = _PaletteHarness()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                option_list = app.screen.query_one("#palette-list", OptionList)
                shell_index = next(
                    i for i in range(option_list.option_count)
                    if "!shell" in str(option_list.get_option_at_index(i)._prompt)
                )
                option_list.highlighted = shell_index
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

        asyncio.run(_check())
        assert dismissed == ["mode:shell"]


@textual_required
class TestReferenceCardCarriesTheFullSdkSignature:
    """`SeamTUI._show_reference`: the row shows a trimmed call form, but
    selecting an SDK reference entry must still print the untrimmed
    signature -- nothing is actually lost, it just moved off the row."""

    def test_selecting_an_sdk_entry_prints_the_full_signature(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from textual.widgets import RichLog

        from seam_runtime.tui.app import SeamTUI

        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
        backend = DashboardApp(SeamRuntime(str(tmp_path / "seam.db")))
        app = SeamTUI(backend)
        spec = next(
            c for c in app.catalog if c.surface == "sdk" and c.name.startswith("knowledge(")
        )

        async def _check() -> None:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._palette_result(f"sdk:{spec.name}")
                await pilot.pause()
                text = "\n".join(
                    strip.text for strip in app.query_one("#log-memory", RichLog).lines
                )
                assert spec.full_signature in text
                # The row's trimmed form must not be what's mistaken for
                # completeness -- the annotation text that trimming removed
                # has to actually show up somewhere.
                assert "Any" in text or "dict" in text

        asyncio.run(_check())
