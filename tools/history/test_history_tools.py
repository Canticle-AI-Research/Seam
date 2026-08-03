"""Unit tests for history tools."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.history import history_lib
from tools.history import new_entry as new_entry_module
from tools.history.build_context_pack import build_context_pack
from tools.history.history_lib import (
    compute_entry_hash,
    estimate_tokens,
    format_entry,
    next_entry_id,
    parse_entries,
    resolve_supersedes_chain,
)
from tools.history.load_snapshot import find_latest, load_and_verify
from tools.history.rebuild_index import rebuild
from tools.history.recorded_fact_audit import audit_recorded_facts
from tools.history.test_count_audit import audit_test_count_claims
from tools.history.verify_continuity import verify_continuity
from tools.history.verify_integrity import verify
from tools.history.verify_routing import verify_routing
from tools.history.write_snapshot import write_snapshot


class TempRepoBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.history = self.root / "HISTORY.md"
        self.index = self.root / "HISTORY_INDEX.md"
        self.snaps = self.root / ".seam" / "snapshots"
        self.snaps.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_entries(self, entries: list[str]) -> None:
        # Write raw bytes with LF line endings — HISTORY.md is canonical LF
        self.history.write_bytes(("\n\n".join(entries) + "\n").encode("utf-8"))

    def patch_paths(self):
        # Patch module constants for both history_lib AND the tools that
        # from-imported those constants at import time.
        from tools.history import load_snapshot as ls
        from tools.history import rebuild_index as ri
        from tools.history import verify_continuity as vc
        from tools.history import write_snapshot as ws
        return _MultiPatch(
            [
                (history_lib, "HISTORY_PATH", self.history),
                (history_lib, "INDEX_PATH", self.index),
                (history_lib, "SNAPSHOTS_DIR", self.snaps),
                (ws, "HISTORY_PATH", self.history),
                (ws, "INDEX_PATH", self.index),
                (ws, "SNAPSHOTS_DIR", self.snaps),
                (ls, "SNAPSHOTS_DIR", self.snaps),
                (ri, "HISTORY_PATH", self.history),
                (ri, "INDEX_PATH", self.index),
                (new_entry_module, "HISTORY_PATH", self.history),
                (new_entry_module, "INDEX_PATH", self.index),
                (vc, "HISTORY_PATH", self.history),
                (vc, "INDEX_PATH", self.index),
                (vc, "SNAPSHOTS_DIR", self.snaps),
            ]
        )


class _MultiPatch:
    """Context manager that patches multiple module attributes at once."""
    def __init__(self, targets):
        self.targets = targets
        self._original: list = []

    def __enter__(self):
        for mod, name, value in self.targets:
            self._original.append((mod, name, getattr(mod, name)))
            setattr(mod, name, value)
        return self

    def __exit__(self, *a):
        for mod, name, value in reversed(self._original):
            setattr(mod, name, value)


def sample_entry(
    id: int,
    *,
    status: str = "done",
    supersedes: str = "none",
    topics: str = "meta",
    refs: str = "none",
) -> str:
    return format_entry(
        id=id,
        date="2026-04-18T12:00:00Z",
        agent="claude-sonnet-4-6",
        status=status,
        topics=topics.split(","),
        commits="none",
        refs=refs,
        supersedes=supersedes,
        tokens=10,
        body=f"Body of entry {id}.",
    )


class TestFormatAndParse(unittest.TestCase):
    def test_format_roundtrip(self):
        text = sample_entry(1)
        entries = parse_entries(text.encode("utf-8"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, 1)
        self.assertEqual(entries[0].status, "done")
        self.assertEqual(entries[0].topics, ["meta"])

    def test_parse_three_entries(self):
        combined = "\n\n".join(sample_entry(i) for i in (1, 2, 3)) + "\n"
        entries = parse_entries(combined.encode("utf-8"))
        self.assertEqual([e.id for e in entries], [1, 2, 3])

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            format_entry(
                id=1, date="2026-04-18T12:00:00Z", agent="a", status="invalid",
                topics=["x"], commits="none", refs="none", supersedes="none",
                tokens=1, body="b",
            )

    def test_ids_must_increase(self):
        text = sample_entry(2) + "\n\n" + sample_entry(1)
        with self.assertRaises(ValueError):
            parse_entries(text.encode("utf-8"))

    def test_marker_mismatch_raises(self):
        bad = "---BEGIN-ENTRY-#001---\nid: 001\n---\nbody\n---END-ENTRY-#002---\n"
        with self.assertRaises(ValueError):
            parse_entries(bad.encode("utf-8"))

    def test_hash_is_deterministic(self):
        text = sample_entry(1)
        entries = parse_entries(text.encode("utf-8"))
        self.assertEqual(entries[0].hash, compute_entry_hash(entries[0].raw))
        self.assertEqual(len(entries[0].hash), 64)

    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens("one two three four five"), 5)

    def test_next_entry_id(self):
        self.assertEqual(next_entry_id([]), 1)
        text = sample_entry(5)
        entries = parse_entries(text.encode("utf-8"))
        self.assertEqual(next_entry_id(entries), 6)


class TestSupersedesChain(unittest.TestCase):
    def test_simple_chain(self):
        text = sample_entry(1, status="planned") + "\n\n" + sample_entry(2, status="done", supersedes="001")
        entries = parse_entries(text.encode("utf-8"))
        rollup = resolve_supersedes_chain(entries)
        self.assertEqual(rollup[1][0], [1, 2])
        self.assertEqual(rollup[1][1], "done")

    def test_no_supersedes(self):
        text = sample_entry(1) + "\n\n" + sample_entry(2)
        entries = parse_entries(text.encode("utf-8"))
        rollup = resolve_supersedes_chain(entries)
        self.assertEqual(rollup[1][1], "done")
        self.assertEqual(rollup[2][1], "done")


class TestRebuildIndexIdempotent(TempRepoBase):
    def test_rebuild_twice_identical(self):
        self.write_entries([sample_entry(1), sample_entry(2), sample_entry(3)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            first = self.index.read_text(encoding="utf-8")
            rebuild(self.history, self.index)
            second = self.index.read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertIn("total_entries: 3", first)
        self.assertIn("latest_id: 003", first)

    def test_empty_history(self):
        self.history.write_text("", encoding="utf-8")
        with self.patch_paths():
            rebuild(self.history, self.index)
        text = self.index.read_text(encoding="utf-8")
        self.assertIn("total_entries: 0", text)


class TestHistoryLockPath(TempRepoBase):
    """The advisory lock must never land inside a working tree.

    A linked git worktree has `.git` as a FILE holding `gitdir: <path>`, not a
    directory. The original `is_dir()`-only check fell through to a
    `HISTORY_INDEX.md.lock` beside the index, where `git add -A` picked it up.
    """

    def test_lock_lives_in_git_dir_for_an_ordinary_clone(self):
        git_dir = self.root / ".git"
        git_dir.mkdir()
        with self.patch_paths():
            self.assertEqual(
                new_entry_module.history_lock_path(),
                git_dir / "seam-history.lock",
            )

    def test_lock_lives_in_the_real_git_dir_for_a_worktree(self):
        real_git_dir = self.root / "main-clone" / ".git" / "worktrees" / "wt"
        real_git_dir.mkdir(parents=True)
        (self.root / ".git").write_text(f"gitdir: {real_git_dir}\n", encoding="utf-8")
        with self.patch_paths():
            resolved = new_entry_module.history_lock_path()
        self.assertEqual(resolved, real_git_dir / "seam-history.lock")
        self.assertNotEqual(resolved.parent, self.root)

    def test_lock_resolves_a_relative_worktree_gitdir_pointer(self):
        real_git_dir = self.root / "elsewhere" / "worktrees" / "wt"
        real_git_dir.mkdir(parents=True)
        (self.root / ".git").write_text(
            "gitdir: elsewhere/worktrees/wt\n", encoding="utf-8"
        )
        with self.patch_paths():
            resolved = new_entry_module.history_lock_path()
        self.assertEqual(resolved, real_git_dir.resolve() / "seam-history.lock")

    def test_lock_falls_back_beside_the_index_without_any_git_dir(self):
        with self.patch_paths():
            self.assertEqual(
                new_entry_module.history_lock_path(),
                self.index.with_name(f"{self.index.name}.lock"),
            )

    def test_new_entry_in_a_worktree_leaves_no_lock_file_in_the_tree(self):
        real_git_dir = self.root / "main-clone" / ".git" / "worktrees" / "wt"
        real_git_dir.mkdir(parents=True)
        (self.root / ".git").write_text(f"gitdir: {real_git_dir}\n", encoding="utf-8")
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            new_entry_module.main([
                "--agent", "test",
                "--status", "done",
                "--topics", "meta",
                "--body", "Entry written from a linked worktree",
            ])
        self.assertFalse((self.root / "HISTORY_INDEX.md.lock").exists())
        self.assertTrue((real_git_dir / "seam-history.lock").exists())


class TestNewEntryLock(TempRepoBase):
    def test_new_entry_releases_process_lock_when_file_lock_fails(self):
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            with patch.object(new_entry_module, "_acquire_history_lock", side_effect=OSError("lock failed")):
                with self.assertRaises(OSError):
                    new_entry_module.main([
                        "--agent", "test",
                        "--status", "done",
                        "--topics", "meta",
                        "--body", "Entry that cannot acquire the file lock",
                    ])

        acquired = new_entry_module._PROCESS_LOCK.acquire(blocking=False)
        try:
            self.assertTrue(acquired, "new_entry left the process lock held after file-lock failure")
        finally:
            if acquired:
                new_entry_module._PROCESS_LOCK.release()
            else:
                new_entry_module._PROCESS_LOCK.release()

    def test_new_entry_lock_serializes_concurrent_writes(self):
        import concurrent.futures
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)

            def write_entry(worker_id: int) -> int:
                return new_entry_module.main([
                    "--agent", "test",
                    "--status", "done",
                    "--topics", "meta",
                    "--body", f"Concurrent entry from worker {worker_id}",
                ])

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(write_entry, i) for i in range(4)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            self.assertTrue(all(r == 0 for r in results),
                            f"One or more workers returned non-zero: {results}")

            entries = parse_entries(self.history.read_bytes())
            ids = [e.id for e in entries]
            self.assertEqual(len(ids), len(set(ids)),
                             f"Duplicate ids detected: {ids}")
            self.assertEqual(len(ids), 5, f"Expected 5 entries (1 base + 4 concurrent), got {len(ids)}")


class TestVerifyIntegrity(TempRepoBase):
    def test_verify_ok(self):
        self.write_entries([sample_entry(1), sample_entry(2)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            ok, errs = verify(self.history, self.index)
        self.assertTrue(ok, f"Errors: {errs}")

    def test_verify_detects_tampering(self):
        self.write_entries([sample_entry(1), sample_entry(2)])
        with self.patch_paths():
            rebuild(self.history, self.index)
        # Tamper: modify body content (not a marker line)
        raw = self.history.read_bytes()
        tampered = raw.replace(b"Body of entry 1.", b"Body of entry X.")
        self.assertNotEqual(raw, tampered)
        self.history.write_bytes(tampered)
        with self.patch_paths():
            ok, errs = verify(self.history, self.index)
        self.assertFalse(ok)
        self.assertTrue(any("#001" in e for e in errs))

    def test_verify_rejects_partial_index_hash_match(self):
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)
        text = self.index.read_text(encoding="utf-8")
        entries = parse_entries(self.history.read_bytes())
        partial = entries[0].hash_short[:8]
        self.index.write_text(text.replace(entries[0].hash_short, partial), encoding="utf-8")

        with self.patch_paths():
            ok, errs = verify(self.history, self.index)
        self.assertFalse(ok)
        self.assertTrue(any("does not match" in e for e in errs))


class TestSnapshots(TempRepoBase):
    def test_write_and_load_roundtrip(self):
        self.write_entries([sample_entry(1), sample_entry(2), sample_entry(3)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            snap_path = write_snapshot(
                agent="claude-test",
                entry_ids=[1, 2, 3],
                token_budget=9999,
                snapshots_dir=self.snaps,
            )
            ok, payload, errs = load_and_verify(snap_path)
        self.assertTrue(ok, f"Errors: {errs}")
        self.assertEqual(len(payload["selected_entries"]), 3)
        self.assertEqual(payload["latest_entry_id"], 3)
        self.assertIn("Body of entry 1.", payload["pack"])
        self.assertIn("Body of entry 3.", payload["pack"])

    def test_write_snapshot_uses_atomic_replace(self):
        self.write_entries([sample_entry(1)])
        from tools.history import write_snapshot as ws
        if not hasattr(ws, "os"):
            ws.os = __import__("os")  # type: ignore[attr-defined]
        with self.patch_paths():
            rebuild(self.history, self.index)
            with patch("tools.history.write_snapshot.os.replace", wraps=__import__("os").replace) as replace:
                snap_path = write_snapshot(
                    agent="claude-test",
                    entry_ids=[1],
                    token_budget=9999,
                    snapshots_dir=self.snaps,
                )

        self.assertTrue(snap_path.exists())
        replace.assert_called_once()

    def test_snapshot_records_pack_entries_skipped_by_token_budget(self):
        self.write_entries([sample_entry(1), sample_entry(2), sample_entry(3)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            snap_path = write_snapshot(
                agent="claude-test",
                entry_ids=[1, 2, 3],
                token_budget=20,
                snapshots_dir=self.snaps,
            )
            ok, payload, errs = load_and_verify(snap_path)
        self.assertTrue(ok, f"Errors: {errs}")
        self.assertEqual([item["id"] for item in payload["selected_entries"]], [1, 2, 3])
        self.assertEqual(payload["pack_entry_ids"], [1, 2])
        self.assertEqual(payload["skipped_entry_ids"], [3])

    def test_find_latest_accepts_repo_root_path(self):
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            snap_path = write_snapshot(
                agent="claude-test",
                entry_ids=[1],
                token_budget=9999,
                snapshots_dir=self.snaps,
            )
        self.assertEqual(find_latest(self.root), snap_path)

    def test_tampered_history_invalidates_snapshot(self):
        self.write_entries([sample_entry(1), sample_entry(2)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            snap_path = write_snapshot(
                agent="claude-test",
                entry_ids=[1, 2],
                token_budget=9999,
                snapshots_dir=self.snaps,
            )
        # Tamper: corrupt entry #1 body by one byte
        raw = self.history.read_bytes()
        self.history.write_bytes(raw.replace(b"Body of entry 1.", b"Body of entry 9."))
        with self.patch_paths():
            ok, payload, errs = load_and_verify(snap_path)
        self.assertFalse(ok)
        self.assertTrue(any("#001" in e for e in errs))

    def test_tampered_snapshot_itself_detected(self):
        self.write_entries([sample_entry(1)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            snap_path = write_snapshot(
                agent="claude-test",
                entry_ids=[1],
                token_budget=9999,
                snapshots_dir=self.snaps,
            )
        # Tamper the JSON payload
        data = json.loads(snap_path.read_text(encoding="utf-8"))
        data["agent"] = "claude-imposter"
        snap_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        with self.patch_paths():
            ok, _, errs = load_and_verify(snap_path)
        self.assertFalse(ok)
        self.assertTrue(any("integrity_hash" in e for e in errs))


class TestSurgicalRead(TempRepoBase):
    def test_byte_range_matches_hash(self):
        self.write_entries([sample_entry(1), sample_entry(2), sample_entry(3)])
        with self.patch_paths():
            rebuild(self.history, self.index)
        from tools.history.history_lib import parse_entries, read_history_bytes
        data = read_history_bytes(self.history)
        entries = parse_entries(data)
        # Pull entry #2 by byte range and verify it hashes the same
        target = entries[1]
        slice_bytes = data[target.byte_start : target.byte_end + 1]
        self.assertEqual(compute_entry_hash(slice_bytes), target.hash)


class TestContextPack(TempRepoBase):
    def test_builds_latest_topic_pack_with_chain(self):
        self.write_entries(
            [
                sample_entry(1, status="planned", topics="dashboard"),
                sample_entry(2, status="done", supersedes="001", topics="dashboard,verify"),
                sample_entry(3, status="done", topics="installer"),
                sample_entry(4, status="done", supersedes="002", topics="dashboard,history"),
            ]
        )
        entries = parse_entries(self.history.read_bytes())
        pack = build_context_pack(
            entries,
            latest=1,
            topics={"dashboard"},
            topic_limit=1,
            token_budget=999,
        )
        self.assertEqual(pack.included_ids, [4, 2, 1])
        self.assertIn("---BEGIN-ENTRY-#004---", pack.pack)
        self.assertIn("---BEGIN-ENTRY-#001---", pack.pack)
        self.assertNotIn("---BEGIN-ENTRY-#003---", pack.pack)

    def test_respects_token_budget(self):
        self.write_entries([sample_entry(1), sample_entry(2), sample_entry(3)])
        entries = parse_entries(self.history.read_bytes())
        pack = build_context_pack(entries, latest=3, token_budget=15)
        self.assertEqual(pack.included_ids, [3])
        self.assertEqual(pack.skipped_ids, [2, 1])

    def test_invalid_utf8_survives_decode_replace(self):
        entry = (
            b"---BEGIN-ENTRY-#001---\n"
            b"id: 001\n"
            b"date: 2026-04-18T12:00:00Z\n"
            b"agent: test\n"
            b"status: done\n"
            b"topics: meta\n"
            b"commits: none\n"
            b"refs: none\n"
            b"supersedes: none\n"
            b"tokens: 5\n"
            b"hash: 0000000000000000000000000000000000000000000000000000000000000001\n"
            b"---\n"
            b"Body with \xff\xfe invalid bytes.\n"
            b"---END-ENTRY-#001---\n"
        )
        self.history.write_bytes(entry)
        entries = parse_entries(self.history.read_bytes())
        pack = build_context_pack(entries, latest=1, token_budget=999)
        self.assertIn("invalid bytes", pack.pack)

    def test_refs_pattern_is_literal_not_regex(self):
        self.write_entries(
            [
                sample_entry(1, refs="docs/(literal).md"),
                sample_entry(2, refs="docs/other.md"),
            ]
        )
        entries = parse_entries(self.history.read_bytes())

        pack = build_context_pack(entries, latest=0, refs_pattern="docs/(literal).md", token_budget=999)

        self.assertEqual(pack.included_ids, [1])


class TestVerifyContinuity(TempRepoBase):
    def test_continuity_ok_with_latest_snapshot(self):
        self.write_entries([sample_entry(1), sample_entry(2, supersedes="001")])
        with self.patch_paths():
            rebuild(self.history, self.index)
            write_snapshot(
                agent="claude-test",
                entry_ids=[2, 1],
                token_budget=999,
                snapshots_dir=self.snaps,
            )
            ok, errs = verify_continuity(
                history_path=self.history,
                index_path=self.index,
                snapshots_dir=self.snaps,
                scan_secrets=False,
                verify_routes=False,
            )
        self.assertTrue(ok, f"Errors: {errs}")

    def test_continuity_fails_when_latest_snapshot_missing(self):
        self.write_entries([sample_entry(1), sample_entry(2)])
        with self.patch_paths():
            rebuild(self.history, self.index)
            write_snapshot(
                agent="claude-test",
                entry_ids=[1],
                token_budget=999,
                snapshots_dir=self.snaps,
            )
            ok, errs = verify_continuity(
                history_path=self.history,
                index_path=self.index,
                snapshots_dir=self.snaps,
                scan_secrets=False,
                verify_routes=False,
            )
        self.assertFalse(ok)
        self.assertTrue(any("latest entry #002" in err for err in errs))

    def test_continuity_fails_on_broken_supersedes(self):
        self.write_entries([sample_entry(1), sample_entry(2, supersedes="999")])
        with self.patch_paths():
            rebuild(self.history, self.index)
            write_snapshot(
                agent="claude-test",
                entry_ids=[2],
                token_budget=999,
                snapshots_dir=self.snaps,
            )
            ok, errs = verify_continuity(
                history_path=self.history,
                index_path=self.index,
                snapshots_dir=self.snaps,
                scan_secrets=False,
                verify_routes=False,
            )
        self.assertFalse(ok)
        self.assertTrue(any("supersedes missing entry #999" in err for err in errs))


class TestTestCountAudit(TempRepoBase):
    def _write_test_file(self, relative: str, count: int) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(
            f"def test_case_{idx}():\n    assert True" for idx in range(count)
        )
        path.write_text(body + "\n", encoding="utf-8")
        return path

    def test_audit_flags_stale_scoped_count(self):
        self._write_test_file("tests/test_demo.py", 3)
        doc = self.root / "ROADMAP.md"
        doc.write_text(
            "python -m pytest tests/test_demo.py -q passed with 2 passed\n",
            encoding="utf-8",
        )

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(len(issues), 1)
        self.assertIn("claims 2", issues[0])
        self.assertIn("actual static count is 3", issues[0])

    def test_audit_flags_ambiguous_bare_count(self):
        doc = self.root / "ROADMAP.md"
        doc.write_text("All existing tests pass (177+).\n", encoding="utf-8")

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(len(issues), 1)
        self.assertIn("lacks pytest path scope", issues[0])

    def test_audit_flags_split_line_bare_count(self):
        doc = self.root / "ROADMAP.md"
        doc.write_text("existing 177+\ntests pass\n", encoding="utf-8")

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(len(issues), 1)
        self.assertIn("lacks pytest path scope", issues[0])

    def test_audit_ignores_non_pytest_fraction_count(self):
        doc = self.root / "HISTORY.md"
        doc.write_text(
            "npm test in experimental/webui passed with 11/11 tests.\n",
            encoding="utf-8",
        )

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(issues, [])

    def test_audit_ignores_non_pytest_fraction_on_shared_line(self):
        self._write_test_file("tests/test_demo.py", 1)
        doc = self.root / "HISTORY.md"
        doc.write_text(
            "npm test in experimental/webui passed with 11/11 tests. "
            "python -m pytest tests/test_demo.py -q passed with 1 passed.\n",
            encoding="utf-8",
        )

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(issues, [])

    def test_audit_flags_stale_pytest_count_after_non_pytest_sentence(self):
        self._write_test_file("tests/test_demo.py", 3)
        doc = self.root / "HISTORY.md"
        doc.write_text(
            "npm test in experimental/webui passed with 11/11 tests. "
            "python -m pytest tests/test_demo.py -q passed with 2 passed.\n",
            encoding="utf-8",
        )

        issues = audit_test_count_claims(self.root, doc_paths=[doc], latest_history_only=False)

        self.assertEqual(len(issues), 1)
        self.assertIn("claims 2", issues[0])
        self.assertIn("actual static count is 3", issues[0])


class TestRecordedFactAudit(TempRepoBase):
    def test_audit_flags_stale_handoff_pointer(self):
        self.write_entries([sample_entry(1), sample_entry(2)])
        status = self.root / "PROJECT_STATUS.md"
        status.write_text(
            "Latest continuity handoff is `HISTORY#001`.\n",
            encoding="utf-8",
        )

        issues = audit_recorded_facts(
            self.root,
            history_path=self.history,
            doc_paths=[status],
        )

        self.assertTrue(any(issue.kind == "handoff" for issue in issues))
        self.assertTrue(any("latest HISTORY#002" in issue.message for issue in issues))

    def test_audit_flags_missing_latest_entry_ref(self):
        entry = format_entry(
            id=1,
            date="2026-04-18T12:00:00Z",
            agent="claude-sonnet-4-6",
            status="done",
            topics=["history"],
            commits="none",
            refs="missing/file.md",
            supersedes="none",
            tokens=10,
            body="Changed a missing file.",
        )
        self.write_entries([entry])
        status = self.root / "PROJECT_STATUS.md"
        status.write_text("", encoding="utf-8")

        issues = audit_recorded_facts(
            self.root,
            history_path=self.history,
            doc_paths=[status],
        )

        self.assertTrue(any(issue.kind == "history-ref" for issue in issues))
        self.assertTrue(any("missing/file.md" in issue.message for issue in issues))

    def test_audit_flags_precedence_drop_for_same_test_scope(self):
        test_file = self.root / "tests" / "test_demo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "\n\n".join(f"def test_case_{idx}():\n    assert True" for idx in range(150)),
            encoding="utf-8",
        )
        first = format_entry(
            id=1,
            date="2026-04-18T12:00:00Z",
            agent="codex",
            status="done",
            topics=["verify"],
            commits="none",
            refs="tests/test_demo.py",
            supersedes="none",
            tokens=10,
            body="python -m pytest tests/test_demo.py -q passed with 180 passed",
        )
        second = format_entry(
            id=2,
            date="2026-04-19T12:00:00Z",
            agent="codex",
            status="done",
            topics=["verify"],
            commits="none",
            refs="tests/test_demo.py",
            supersedes="001",
            tokens=10,
            body="python -m pytest tests/test_demo.py -q passed with 150 passed",
        )
        self.write_entries([first, second])
        status = self.root / "PROJECT_STATUS.md"
        status.write_text("", encoding="utf-8")

        issues = audit_recorded_facts(
            self.root,
            history_path=self.history,
            doc_paths=[status],
        )

        self.assertTrue(any(issue.kind == "test-count-precedence" for issue in issues))
        self.assertTrue(any("180 to 150" in issue.message for issue in issues))

    def test_audit_accepts_relative_repo_root(self):
        self._write_test_file = lambda relative, count: None  # type: ignore[attr-defined]
        test_file = self.root / "tests" / "test_demo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_case_1():\n    assert True\n", encoding="utf-8")
        status = self.root / "PROJECT_STATUS.md"
        status.write_text(
            "python -m pytest tests/test_demo.py -q passed with 1 passed\n",
            encoding="utf-8",
        )
        cwd = Path.cwd()
        try:
            import os
            os.chdir(self.root)
            issues = audit_recorded_facts(
                Path("."),
                history_path=Path("HISTORY.md"),
                doc_paths=[Path("PROJECT_STATUS.md")],
            )
        finally:
            os.chdir(cwd)

        self.assertEqual(issues, [])

    def test_precedence_handles_pytest_after_non_pytest_sentence(self):
        test_file = self.root / "tests" / "test_demo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "\n\n".join(f"def test_case_{idx}():\n    assert True" for idx in range(150)),
            encoding="utf-8",
        )
        first = format_entry(
            id=1,
            date="2026-04-18T12:00:00Z",
            agent="codex",
            status="done",
            topics=["verify"],
            commits="none",
            refs="tests/test_demo.py",
            supersedes="none",
            tokens=10,
            body=(
                "npm test passed with 11/11 tests. "
                "python -m pytest tests/test_demo.py -q passed with 180 passed"
            ),
        )
        second = format_entry(
            id=2,
            date="2026-04-19T12:00:00Z",
            agent="codex",
            status="done",
            topics=["verify"],
            commits="none",
            refs="tests/test_demo.py",
            supersedes="001",
            tokens=10,
            body=(
                "npm test passed with 11/11 tests. "
                "python -m pytest tests/test_demo.py -q passed with 150 passed"
            ),
        )
        self.write_entries([first, second])
        status = self.root / "PROJECT_STATUS.md"
        status.write_text("", encoding="utf-8")

        issues = audit_recorded_facts(
            self.root,
            history_path=self.history,
            doc_paths=[status],
        )

        self.assertTrue(any(issue.kind == "test-count-precedence" for issue in issues))


class TestVerifyRouting(TempRepoBase):
    def _write_manifest(self, manifest: dict) -> Path:
        path = self.root / "routing_manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def _manifest(self) -> dict:
        ledger = self.root / "docs" / "ledgers" / "maintenance" / "docker.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# Docker\n", encoding="utf-8")
        return {
            "schema": "seam-history-routing/v1",
            "version": 1,
            "updated": "2026-04-26",
            "routes": [
                {
                    "id": "maintenance",
                    "parent": None,
                    "status": "active",
                    "description": "Maintenance",
                    "match_topics": ["verify"],
                    "match_refs": [],
                    "ledger": None,
                    "introduced": "001",
                    "supersedes": "none",
                    "moved_to": None,
                    "retired_reason": None,
                },
                {
                    "id": "maintenance/docker",
                    "parent": "maintenance",
                    "status": "active",
                    "description": "Docker maintenance",
                    "match_topics": ["docker"],
                    "match_refs": ["docker"],
                    "ledger": "docs/ledgers/maintenance/docker.md",
                    "introduced": "001",
                    "supersedes": "none",
                    "moved_to": None,
                    "retired_reason": None,
                },
            ],
        }

    def test_verify_routing_ok(self):
        self.write_entries([sample_entry(1, topics="verify")])
        manifest = self._write_manifest(self._manifest())
        ok, errs = verify_routing(manifest, repo_root=self.root, history_path=self.history)
        self.assertTrue(ok, f"Errors: {errs}")

    def test_verify_routing_detects_missing_parent(self):
        self.write_entries([sample_entry(1, topics="verify")])
        data = self._manifest()
        data["routes"][1]["parent"] = "missing"
        manifest = self._write_manifest(data)
        ok, errs = verify_routing(manifest, repo_root=self.root, history_path=self.history)
        self.assertFalse(ok)
        self.assertTrue(any("parent missing" in err or "does not match path" in err for err in errs))

    def test_verify_routing_detects_missing_history_ref(self):
        self.write_entries([sample_entry(1, topics="verify")])
        data = self._manifest()
        data["routes"][0]["introduced"] = "999"
        manifest = self._write_manifest(data)
        ok, errs = verify_routing(manifest, repo_root=self.root, history_path=self.history)
        self.assertFalse(ok)
        self.assertTrue(any("missing HISTORY#999" in err for err in errs))


if __name__ == "__main__":
    unittest.main()
