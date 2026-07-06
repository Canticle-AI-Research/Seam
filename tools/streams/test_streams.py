"""Smoke tests for the Context Streams substrate."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.history.history_lib import HISTORY_PATH, INDEX_PATH
from tools.streams.history_adapter import sync_history_mirror, verify_history_mirror
from tools.streams.rebuild_cross_index import ARCHIVE_DIR, collect_all_events, rebuild_cross_index
from tools.streams.rebuild_index import rebuild_index
from tools.streams.roadmap_parser import (
    ROADMAP_PATH,
    items_to_events,
    parse_roadmap_markers,
    render_state_md,
)
from tools.streams.streams_lib import (
    CROSS_INDEX_PATH,
    STREAMS_ROOT,
    format_event,
    parse_events,
)
from tools.streams.verify_streams import verify_all


class StreamsLibTests(unittest.TestCase):
    def test_format_then_parse_roundtrip(self) -> None:
        block = format_event(
            kind="roadmap",
            id=1,
            date="2026-05-15T00:00:00Z",
            agent="test",
            fields={
                "kind": "status-change",
                "item": "roadmap:track:X1",
                "event": "bootstrap",
                "from": "(initial)",
                "to": "now",
                "supersedes": "none",
                "refs": "ROADMAP.md:1",
                "topics": "roadmap, plan",
                "tokens": "10",
            },
            body="Test body.",
        )
        events = parse_events(block.encode("utf-8"), "roadmap")
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt.id, 1)
        self.assertEqual(evt.kind, "roadmap")
        self.assertEqual(evt.fields["item"], "roadmap:track:X1")
        self.assertEqual(evt.fields["to"], "now")
        self.assertEqual(evt.body, "Test body.")

    def test_history_kind_uses_entry_delim(self) -> None:
        block = format_event(
            kind="history",
            id=1,
            date="2026-05-15T00:00:00Z",
            agent="test",
            fields={"status": "done", "topics": "history", "supersedes": "none", "tokens": "5", "commits": "none", "refs": "none"},
            body="x",
            history_compat=True,
        )
        self.assertIn("---BEGIN-ENTRY-#001---", block)
        self.assertIn("---END-ENTRY-#001---", block)


class HistoryAdapterTests(unittest.TestCase):
    def test_mirror_matches_root_bytes(self) -> None:
        sync_history_mirror()
        log = STREAMS_ROOT / "history" / "log.md"
        idx = STREAMS_ROOT / "history" / "index.md"
        self.assertEqual(log.read_bytes(), HISTORY_PATH.read_bytes())
        self.assertEqual(idx.read_bytes(), INDEX_PATH.read_bytes())
        self.assertEqual(verify_history_mirror(), [])


class RoadmapParserTests(unittest.TestCase):
    def test_extracts_track_h_items(self) -> None:
        items = parse_roadmap_markers(ROADMAP_PATH.read_text(encoding="utf-8"))
        ids = {it.item_id for it in items}
        self.assertIn("roadmap:track:H1", ids)
        self.assertIn("roadmap:track:H2", ids)
        self.assertIn("roadmap:track:H3", ids)
        self.assertIn("roadmap:track:H4", ids)

    def test_extracts_tracks_i_j_k_l_items(self) -> None:
        items = parse_roadmap_markers(ROADMAP_PATH.read_text(encoding="utf-8"))
        ids = {it.item_id for it in items}
        self.assertIn("roadmap:track:I", ids)
        self.assertIn("roadmap:track:J", ids)
        self.assertIn("roadmap:track:K", ids)
        self.assertIn("roadmap:track:L", ids)

    def test_agent_compiler_is_not_labeled_as_track_h(self) -> None:
        text = ROADMAP_PATH.read_text(encoding="utf-8")
        self.assertNotIn("Track H: Agent / Skills Compiler", text)

    def test_events_have_sequential_ids_and_required_fields(self) -> None:
        items = parse_roadmap_markers(ROADMAP_PATH.read_text(encoding="utf-8"))
        events = items_to_events(items)
        self.assertEqual(len(events), len(items))
        for evt in events:
            self.assertIn("item", evt["fields"])
            self.assertIn("to", evt["fields"])

    def test_state_md_buckets_by_status(self) -> None:
        items = parse_roadmap_markers(ROADMAP_PATH.read_text(encoding="utf-8"))
        text = render_state_md(items)
        # At least one status bucket is rendered.
        self.assertTrue(any(h in text for h in ("## now", "## in-progress", "## planned", "## later", "## done")))
        self.assertIn("roadmap:track:H1", text)


class CrossIndexTests(unittest.TestCase):
    def test_cross_index_includes_both_streams(self) -> None:
        rebuild_index("history")
        rebuild_index("roadmap")
        rebuild_index("experience")
        rebuild_cross_index()
        items = collect_all_events()
        kinds = {it["ref"].split(":", 1)[0] for it in items}
        self.assertIn("history", kinds)
        self.assertIn("roadmap", kinds)
        self.assertTrue(CROSS_INDEX_PATH.exists())

    def test_rebuild_cross_index_removes_stale_archive_chunks(self) -> None:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stale = ARCHIVE_DIR / "9999-9999.cross.md"
        stale.write_text("# stale\n", encoding="utf-8")

        rebuild_cross_index()

        self.assertFalse(stale.exists())


    def test_rebuild_cross_index_atomic_on_write_failure(self) -> None:
        from unittest.mock import patch

        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stale = ARCHIVE_DIR / "0001-0010.cross.md"
        stale.write_text("# stale chunk\n", encoding="utf-8")
        self.addCleanup(lambda: stale.unlink() if stale.exists() else None)

        original_cross = (
            CROSS_INDEX_PATH.read_text(encoding="utf-8")
            if CROSS_INDEX_PATH.exists()
            else ""
        )
        if not original_cross:
            original_cross = "# original cross-index\n"
            CROSS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            CROSS_INDEX_PATH.write_text(original_cross, encoding="utf-8")
        self.addCleanup(
            lambda: CROSS_INDEX_PATH.write_text(original_cross, encoding="utf-8")
        )

        # 250 events -> 50 cold (triggers archive chunk write), 200 hot
        fake_events: list[dict[str, object]] = []
        for i in range(250):
            fake_events.append({
                "utc": f"2026-01-{i+1:02d}T00:00:00Z",
                "ref": f"history:{i+1:03d}:abc12345",
                "kind": "session-event",
                "event": "done",
                "topics": "test",
                "refs": "",
                "_sort": (f"2026-01-{i+1:02d}T00:00:00Z", "history", i + 1),
            })

        error_raised = False
        try:
            with patch(
                "tools.streams.rebuild_cross_index.collect_all_events",
                return_value=fake_events,
            ):
                with patch.object(
                    Path, "write_text", side_effect=OSError("Simulated write failure")
                ):
                    rebuild_cross_index()
        except OSError:
            error_raised = True

        self.assertTrue(error_raised, "Expected OSError was not raised")
        self.assertTrue(
            stale.exists(),
            "Stale archive chunk was deleted despite write failure",
        )
        self.assertEqual(CROSS_INDEX_PATH.read_text(encoding="utf-8"), original_cross)


class RebuildIndexTests(unittest.TestCase):
    def test_rebuild_index_atomic_on_write_failure(self) -> None:
        import shutil
        import tempfile
        from unittest.mock import patch

        tmp_root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp_root, ignore_errors=True))

        test_stream = tmp_root / "testkind"
        test_stream.mkdir(parents=True)
        log_content = """---BEGIN-TESTKIND-EVENT-#001---
id: testkind:001
date: 2026-05-18T00:00:00Z
agent: test
kind: test
item: test:item
event: test
supersedes: none
refs: none
topics: test
tokens: 1
---
test body
---END-TESTKIND-EVENT-#001---
"""
        (test_stream / "log.md").write_text(log_content, encoding="utf-8")

        original_index = "# original index\n"
        index_md = test_stream / "index.md"
        index_md.write_text(original_index, encoding="utf-8")

        error_raised = False
        try:
            # streams_lib owns STREAMS_ROOT; index_path() and read_log()
            # both resolve against streams_lib's module-level constant, so
            # the patch must target streams_lib — not rebuild_index, which
            # only imports the symbol but never references it directly.
            with patch("tools.streams.streams_lib.STREAMS_ROOT", tmp_root):
                with patch("os.replace", side_effect=OSError("Simulated replace failure")):
                    rebuild_index("testkind")
        except OSError:
            error_raised = True

        self.assertTrue(error_raised, "Expected OSError was not raised")
        self.assertEqual(
            index_md.read_text(encoding="utf-8"),
            original_index,
            "Index was overwritten despite write failure",
        )


class BuildContextPackTests(unittest.TestCase):
    def test_roadmap_pack_returns_latest_events(self) -> None:
        from tools.streams.build_context_pack import build_stream_pack
        result = build_stream_pack("roadmap", latest=3, budget=10_000)
        self.assertEqual(result["stream"], "roadmap")
        self.assertLessEqual(len(result["included_ids"]), 3)
        self.assertIn("BEGIN-ROADMAP-EVENT", result["pack"])

    def test_roadmap_pack_budget_skips_oldest(self) -> None:
        from tools.streams.build_context_pack import build_stream_pack
        result = build_stream_pack("roadmap", latest=10, budget=50)
        self.assertGreaterEqual(len(result["included_ids"]), 1)
        self.assertLessEqual(result["tokens_used"], 200)

    def test_history_delegation_via_module(self) -> None:
        import io
        from contextlib import redirect_stdout

        from tools.streams import build_context_pack as wrapper
        buf = io.StringIO()
        with redirect_stdout(buf):
            # This wrapper always reads the real repo HISTORY.md (no
            # --repo-root/--history override exists), so the budget must
            # stay well above the largest entry actually written, not just
            # above whatever the largest entry was when this test was
            # written -- entries have already reached ~1200 tokens.
            wrapper.main(["--stream", "history", "--latest", "1", "--token-budget", "4000"])
        out = buf.getvalue()
        # Output should contain a history entry block (legacy ENTRY delim).
        self.assertIn("BEGIN-ENTRY-#", out)


class AppendEventLockTests(unittest.TestCase):
    def test_concurrent_append_event_no_interleaving(self) -> None:
        import shutil
        import tempfile
        import threading
        from unittest.mock import patch

        from tools.streams.streams_lib import append_event

        tmp_root = Path(tempfile.mkdtemp(prefix=f"{self._testMethodName}-"))
        self.addCleanup(lambda: shutil.rmtree(tmp_root, ignore_errors=True))

        results = [None, None]

        def _append(result_idx, body):
            results[result_idx] = append_event(
                kind="test",
                header_fields={"status": "done", "topics": "test", "supersedes": "none",
                               "tokens": "1", "commits": "none", "refs": "none"},
                body=body,
                agent="test-agent",
                date="2026-05-18T00:00:00Z",
            )

        barrier = threading.Barrier(2)

        def _append_with_barrier(result_idx, body):
            barrier.wait()
            _append(result_idx, body)

        with patch("tools.streams.streams_lib.STREAMS_ROOT", tmp_root):
            t0 = threading.Thread(target=_append_with_barrier, args=(0, "Body from thread 0"), daemon=True)
            t1 = threading.Thread(target=_append_with_barrier, args=(1, "Body from thread 1"), daemon=True)
            t0.start()
            t1.start()
            t0.join(timeout=30)
            t1.join(timeout=30)
            self.assertFalse(t0.is_alive(), "Thread 0 did not complete")
            self.assertFalse(t1.is_alive(), "Thread 1 did not complete")

        self.assertIsNotNone(results[0], "Thread 0 did not complete")
        self.assertIsNotNone(results[1], "Thread 1 did not complete")

        # Both events must have distinct, sequential ids.
        ids = {results[0].id, results[1].id}
        self.assertEqual(ids, {1, 2}, f"Expected ids {{1, 2}}, got {ids}")

        # Read the log directly from tmp_root (patch has exited, so
        # read_log would use the real repo path).
        log_data = (tmp_root / "test" / "log.md").read_bytes()
        from tools.streams.streams_lib import parse_events
        events = parse_events(log_data, "test")
        self.assertEqual(len(events), 2)
        text = log_data.decode("utf-8")
        self.assertIn("Body from thread 0", text)
        self.assertIn("Body from thread 1", text)

    def tearDown(self):
        import shutil
        path = Path(self._testMethodName)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


class VerifyStreamsTests(unittest.TestCase):
    def test_verify_returns_no_errors_after_seed(self) -> None:
        sync_history_mirror()
        rebuild_index("history")
        rebuild_index("roadmap")
        rebuild_index("experience")
        rebuild_cross_index()
        self.assertEqual(verify_all(), [])

    def test_verify_detects_stale_cross_index(self) -> None:
        sync_history_mirror()
        rebuild_index("history")
        rebuild_index("roadmap")
        rebuild_index("experience")
        rebuild_cross_index()
        original = CROSS_INDEX_PATH.read_text(encoding="utf-8")
        try:
            stale = original.replace("total_events:", "total_events: 0 # stale", 1)
            CROSS_INDEX_PATH.write_text(stale, encoding="utf-8")
            self.assertTrue(any("cross_index.md is stale" in err for err in verify_all()))
        finally:
            CROSS_INDEX_PATH.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
