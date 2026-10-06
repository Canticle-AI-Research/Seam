"""Offline rename/link-change acceptance tests; no SEAM commands or stores."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.docs import sync_references as sync


def parser(command="load", flag="--output"):
    root = argparse.ArgumentParser(prog="seam", description="Fixture CLI")
    root.add_argument("--db", default="fixture.db", help="Database")
    parents = root.add_subparsers(dest="command", required=True)
    parent = parents.add_parser(command, aliases=["remember"], help="Capture")
    parent.add_argument("--mode", choices=["safe", "fast"], default="safe")
    children = parent.add_subparsers(dest="operation", required=True)
    child = children.add_parser("file", aliases=["document"], help="Capture a file")
    child.add_argument("source", nargs="?")
    child.add_argument("-o", flag, nargs="+", required=True, help="Destination")
    child.add_argument("--verbose", action="store_true")
    return root


def catalog(command="load", flag="--output"):
    return {
        "schema": "seam-command-reference/1",
        "sources": {"fixture.py": {"sha256": hashlib.sha256(b"fixture").hexdigest(),
                                   "git_blob_sha1": hashlib.sha1(b"blob 7\0fixture").hexdigest()}},
        "source_revision_kind": "fixture content identities",
        "commands": sync.describe_parser(parser(command, flag)),
    }


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tools/docs").mkdir(parents=True)
    (tmp_path / "docs/archive").mkdir(parents=True)
    config = {
        "schema": "seam-doc-references/1",
        "links": {"setup": "docs/setup.md"},
        "managed_pages": ["README.md", "docs/README.md"],
        "command_pages": ["docs/reference/CLI_REFERENCE.md", "docs/reference/SECOND.md"],
    }
    (tmp_path / "tools/docs/reference_config.json").write_text(json.dumps(config))
    for path in ("README.md", "docs/README.md"):
        (tmp_path / path).write_text(
            "# Home\n\n[Setup][seam:setup]\n\n"
            "<!-- seam-docs:links:start -->\n<!-- seam-docs:links:end -->\n"
        )
    (tmp_path / "docs/setup.md").write_text("# Setup\n")
    (tmp_path / "docs/manual.md").write_text("# Example\n\n`seam load file --output example`\n")
    (tmp_path / "HISTORY.md").write_text("Historical command: seam load file\n")
    (tmp_path / "docs/archive/old.md").write_text("[Old](../setup.md)\nseam load file\n")
    return tmp_path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_full_parser_contract_includes_global_parent_arguments_and_aliases():
    rows = sync.describe_parser(parser())
    leaf = next(row for row in rows if row["path"] == "seam load file")
    assert set(leaf["aliases"]) == {"seam load document", "seam remember file", "seam remember document"}
    assert [(a["scope"], a["flags"]) for a in leaf["inherited_arguments"] if a["dest"] != "help"] == [
        ("seam", ["--db"]), ("seam load", ["--mode"]),
    ]
    option = next(a for a in leaf["arguments"] if a["dest"] == "output")
    assert option["flags"] == ["-o", "--output"]
    assert option["nargs"] == "+" and option["required"] is True
    assert next(a for a in leaf["inherited_arguments"] if a["dest"] == "mode")["default"] == "safe"
    assert next(a for a in leaf["arguments"] if a["dest"] == "verbose")["default"] is False


def test_initial_check_fails_then_generation_is_idempotent_and_read_only_check(repo):
    assert not sync.run(repo, catalog=catalog()).ok
    assert sync.run(repo, catalog=catalog(), update=True).ok
    first = snapshot(repo)
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == first
    assert sync.run(repo, catalog=catalog()).ok
    assert snapshot(repo) == first


def test_failed_multi_file_update_restores_bytes_and_review_queue(repo, monkeypatch):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    before = snapshot(repo)
    replace = sync.os.replace
    def fail_state(source, destination):
        if Path(destination) == repo / sync.STATE:
            raise OSError("fixture state write failure")
        return replace(source, destination)
    with monkeypatch.context() as context:
        context.setattr(sync.os, "replace", fail_state)
        result = sync.run(repo, catalog=catalog("capture"), update=True)
    assert not result.ok
    assert snapshot(repo) == before
    retry = sync.run(repo, catalog=catalog("capture"), update=True)
    assert not retry.ok and "docs/manual.md" in retry.pending


@pytest.mark.parametrize("field", ["pending_reviews", "documents", "links", "review_acknowledgements",
                                   "command_contract_sha256", "catalog_sha256", "baseline_is_identity_not_semantic_approval"])
def test_missing_saved_metadata_cannot_reset_review(repo, field):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert not sync.run(repo, catalog=catalog("capture"), update=True).ok
    path = repo / sync.STATE
    state = json.loads(path.read_text())
    del state[field]
    path.write_text(json.dumps(state))
    before = snapshot(repo)
    result = sync.run(repo, catalog=catalog("capture"), update=True)
    assert not result.ok and result.errors
    assert snapshot(repo) == before


def test_interrupted_source_only_catalog_advance_cannot_reset_review(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    changed = catalog()
    changed["sources"]["fixture.py"]["sha256"] = hashlib.sha256(b"source-only drift").hexdigest()
    (repo / sync.CATALOG).write_text(sync._json(changed))
    before = snapshot(repo)
    result = sync.run(repo, catalog=changed, update=True)
    assert not result.ok and result.errors
    assert snapshot(repo) == before


def test_update_preserves_existing_file_permissions(repo):
    (repo / "README.md").chmod(0o640)
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert (repo / "README.md").stat().st_mode & 0o777 == 0o640


def test_nested_registered_command_page_has_correct_catalog_link(repo):
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    name = "docs/reference/nested/CLI.md"
    config["command_pages"].append(name)
    path.write_text(json.dumps(config))
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert "[command_catalog.json](../command_catalog.json)" in (repo / name).read_text()


def test_authored_removal_requires_explicit_change_review(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    (repo / "docs/manual.md").unlink()
    result = sync.run(repo, catalog=catalog(), update=True)
    assert not result.ok and "docs/manual.md" in result.pending
    assert not sync.run(repo, catalog=catalog()).ok
    assert sync.run(repo, catalog=catalog(), update=True, acknowledge=["docs/manual.md"]).ok


def test_unregistered_marker_blocks_remain_authored_content_and_queue_changes(repo):
    path = repo / "docs/unmanaged.md"
    path.write_text(f"# Authored\n{sync.START}\nOriginal prose.\n{sync.END}\n")
    assert sync.run(repo, catalog=catalog(), update=True).ok
    changed = f"# Authored\n{sync.START}\n`seam obsolete --bad`\n{sync.END}\n"
    path.write_text(changed)
    result = sync.run(repo, catalog=catalog(), update=True)
    assert not result.ok and "docs/unmanaged.md" in result.pending
    assert path.read_text() == changed
    assert not sync.run(repo, catalog=catalog()).ok


@pytest.mark.parametrize("name", ["./README.md", "docs/reference/./CLI_REFERENCE.md",
                                 "docs/reference//CLI_REFERENCE.md", "docs/reference/../CLI_REFERENCE.md"])
def test_noncanonical_registry_paths_fail_without_writes(repo, name):
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["command_pages"].append(name)
    path.write_text(json.dumps(config))
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


@pytest.mark.parametrize("url", ["https://example.test/docs\n# Injected", "https://example.test/%0aheading",
                                "https://example.test:broken/docs", "https://example.test/docs?token=private"])
def test_unsafe_external_registry_links_fail_without_writes(repo, url):
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["links"]["setup"] = url
    path.write_text(json.dumps(config))
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


def test_all_new_or_changed_authored_prose_queues_even_without_cli_mentions(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    (repo / "docs/setup.md").write_text("# Setup\nChanged installation instructions.\n")
    (repo / "docs/new.md").write_text("# New explanation\nReview this new page.\n")
    result = sync.run(repo, catalog=catalog(), update=True)
    assert set(result.pending) == {"docs/setup.md", "docs/new.md"}
    assert not sync.run(repo, catalog=catalog()).ok
    assert sync.run(repo, catalog=catalog(), update=True,
                    acknowledge=["docs/setup.md", "docs/new.md"]).ok


def test_removing_unused_link_id_regenerates_blocks_without_false_unknown(repo):
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["links"]["unused"] = "docs/setup.md"
    path.write_text(json.dumps(config))
    assert sync.run(repo, catalog=catalog(), update=True).ok
    del config["links"]["unused"]
    path.write_text(json.dumps(config))
    result = sync.run(repo, catalog=catalog(), update=True)
    assert result.ok
    for page in config["managed_pages"]:
        assert "seam:unused" not in (repo / page).read_text()


def test_canonical_consumers_queue_when_target_changes(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    (repo / "docs/installation.md").write_text("# Installation\n")
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["links"]["setup"] = "docs/installation.md"
    path.write_text(json.dumps(config))
    result = sync.run(repo, catalog=catalog(), update=True)
    assert {"README.md", "docs/README.md"} <= set(result.pending)
    assert "[seam:setup]: docs/installation.md" in (repo / "README.md").read_text()


def test_unregistered_canonical_consumer_cannot_pass_with_no_definition(repo):
    (repo / "docs/manual.md").write_text("# Manual\n[Setup][seam:setup]\n")
    before = snapshot(repo)
    result = sync.run(repo, catalog=catalog(), update=True)
    assert not result.ok and result.errors
    assert snapshot(repo) == before


def test_private_metadata_and_exception_contents_are_never_written_or_echoed(repo, monkeypatch):
    secret = "sk-" + "x" * 24
    meta = catalog()
    meta["commands"][0]["arguments"][0]["default"] = secret
    before = snapshot(repo)
    result = sync.run(repo, catalog=meta, update=True)
    assert not result.ok and result.errors
    assert secret not in repr(result)
    assert snapshot(repo) == before
    def broken(root):
        raise RuntimeError(secret)
    monkeypatch.setattr(sync, "build_catalog", broken)
    result = sync.run(repo, update=True)
    assert not result.ok and secret not in repr(result)


def test_command_and_flag_rename_updates_every_registered_copy_and_queues_prose(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    before = snapshot(repo)
    renamed = catalog("capture", "--destination")
    assert not sync.run(repo, catalog=renamed).ok
    assert snapshot(repo) == before
    result = sync.run(repo, catalog=renamed, update=True)
    assert not result.ok and "docs/manual.md" in result.pending
    for path in ("docs/reference/CLI_REFERENCE.md", "docs/reference/SECOND.md"):
        text = (repo / path).read_text()
        assert "seam capture file" in text and "--destination" in text
        assert "seam load file" not in text and "--output" not in text
    assert (repo / "docs/manual.md").read_bytes() == before["docs/manual.md"]
    assert (repo / "HISTORY.md").read_bytes() == before["HISTORY.md"]
    assert (repo / "docs/archive/old.md").read_bytes() == before["docs/archive/old.md"]
    assert not sync.run(repo, catalog=renamed).ok
    (repo / "docs/manual.md").write_text("# Example\n`seam capture file --destination example`\n")
    assert sync.run(repo, catalog=renamed, update=True, acknowledge=["docs/manual.md"]).ok
    assert sync.run(repo, catalog=renamed).ok


def test_canonical_link_rename_changes_definitions_not_hand_written_links(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    (repo / "docs/link-example.md").write_text("# Manual\n[Setup](setup.md)\n")
    assert sync.run(repo, catalog=catalog(), update=True, acknowledge=["docs/link-example.md"]).ok
    (repo / "docs/setup.md").rename(repo / "docs/installation.md")
    config_path = repo / "tools/docs/reference_config.json"
    config = json.loads(config_path.read_text())
    config["links"]["setup"] = "docs/installation.md"
    config_path.write_text(json.dumps(config))
    assert not sync.run(repo, catalog=catalog()).ok
    result = sync.run(repo, catalog=catalog(), update=True)
    assert "docs/link-example.md" in result.pending
    assert "[seam:setup]: docs/installation.md" in (repo / "README.md").read_text()
    assert "[seam:setup]: installation.md" in (repo / "docs/README.md").read_text()
    assert (repo / "docs/link-example.md").read_text() == "# Manual\n[Setup](setup.md)\n"


@pytest.mark.parametrize("problem", ["unknown_id", "missing_target", "missing_metadata", "missing_marker"])
def test_missing_inputs_fail_closed_without_writing(repo, problem):
    meta = catalog()
    if problem == "unknown_id":
        (repo / "docs/manual.md").write_text("[Missing][seam:unknown]\n")
    elif problem == "missing_target":
        (repo / "docs/setup.md").unlink()
    elif problem == "missing_metadata":
        meta["commands"] = []
    else:
        (repo / "README.md").write_text("# Home without a managed marker\n")
    before = snapshot(repo)
    result = sync.run(repo, catalog=meta, update=True)
    assert not result.ok and result.errors
    assert snapshot(repo) == before


def test_active_unmanaged_documents_are_reported_and_historical_writes_rejected(repo):
    result = sync.run(repo, catalog=catalog(), update=True)
    assert "docs/manual.md" in result.unmanaged
    assert "docs/archive/old.md" not in result.unmanaged
    config_path = repo / "tools/docs/reference_config.json"
    config = json.loads(config_path.read_text())
    config["command_pages"] = ["HISTORY.md"]
    config_path.write_text(json.dumps(config))
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


def test_symlink_output_cannot_escape_repository(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (repo / "docs/reference").symlink_to(outside, target_is_directory=True)
    result = sync.run(repo, catalog=catalog(), update=True)
    assert not result.ok
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("target", ["README.md", "docs/reference/MANUAL.md", "LICENSE.md"])
def test_whole_page_generation_cannot_overwrite_prose_or_licensing(repo, target):
    path = repo / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Authored contract\nDo not replace this prose.\n")
    config_path = repo / sync.CONFIG
    config = json.loads(config_path.read_text())
    config["command_pages"] = [target]
    config_path.write_text(json.dumps(config))
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


def test_legal_page_cannot_be_registered_for_even_marked_link_updates(repo):
    legal = repo / "COMMERCIAL_LICENSE.md"
    legal.write_text(f"# Legal\n{sync.START}\n{sync.END}\n")
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["managed_pages"].append(legal.name)
    path.write_text(json.dumps(config))
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


def test_rendered_contract_explains_suppression_constants_and_metavars():
    cli = parser()
    cli.add_argument("--optional", nargs="?", const="automatic", default=argparse.SUPPRESS, metavar="VALUE")
    meta = catalog()
    meta["commands"] = sync.describe_parser(cli)
    root = next(row for row in meta["commands"] if row["path"] == "seam")
    arg = next(arg for arg in root["arguments"] if arg["dest"] == "optional")
    assert arg["default_kind"] == "suppressed"
    text = sync._render_commands(meta)
    assert "Const" in text and "Metavar" in text and "automatic" in text and "VALUE" in text
    assert "omitted unless supplied" in text


def test_root_only_catalog_is_not_accepted_as_complete_commands(repo):
    meta = catalog()
    meta["commands"] = [row for row in meta["commands"] if row["path"] == "seam"]
    before = snapshot(repo)
    assert not sync.run(repo, catalog=meta, update=True).ok
    assert snapshot(repo) == before


def test_factory_failure_is_a_failed_gate_without_outputs(repo, monkeypatch):
    def broken(root):
        raise RuntimeError("fixture factory failed")
    monkeypatch.setattr(sync, "build_catalog", broken)
    before = snapshot(repo)
    result = sync.run(repo, update=True)
    assert not result.ok and result.errors
    assert snapshot(repo) == before


def test_pending_reviews_cannot_be_reset_by_deleting_one_baseline_file(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert not sync.run(repo, catalog=catalog("capture"), update=True).ok
    (repo / sync.CATALOG).unlink()
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog("capture"), update=True).ok
    assert snapshot(repo) == before


def test_source_revision_change_queues_prose_even_when_parser_contract_is_identical(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    changed = catalog()
    changed["sources"]["fixture.py"]["sha256"] = hashlib.sha256(b"changed implementation").hexdigest()
    result = sync.run(repo, catalog=changed, update=True)
    assert not result.ok and "docs/manual.md" in result.pending


def test_deleting_both_indexed_baseline_files_cannot_discard_pending_reviews(repo):
    assert sync.run(repo, catalog=catalog(), update=True).ok
    assert not sync.run(repo, catalog=catalog("capture"), update=True).ok
    assert subprocess.run(["git", "init", "-q"], cwd=repo, check=False).returncode == 0
    assert subprocess.run(["git", "add", sync.CATALOG, sync.STATE], cwd=repo, check=False).returncode == 0
    (repo / sync.CATALOG).unlink()
    (repo / sync.STATE).unlink()
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog("capture"), update=True).ok
    assert snapshot(repo) == before


def test_link_rename_queues_authored_dot_relative_links_with_fragments(repo):
    (repo / "docs/setup.md").write_text("# Setup\n## Detail\n")
    (repo / "docs/link-example.md").write_text("# Example\n[Detail](./setup.md#detail)\n")
    assert sync.run(repo, catalog=catalog(), update=True).ok
    (repo / "docs/setup.md").rename(repo / "docs/installation.md")
    path = repo / sync.CONFIG
    config = json.loads(path.read_text())
    config["links"]["setup"] = "docs/installation.md"
    path.write_text(json.dumps(config))
    result = sync.run(repo, catalog=catalog(), update=True)
    assert not result.ok and "docs/link-example.md" in result.pending


def test_duplicate_configuration_keys_fail_before_outputs(repo):
    (repo / sync.CONFIG).write_text('{"schema": "seam-doc-references/1", "schema": "other"}')
    before = snapshot(repo)
    assert not sync.run(repo, catalog=catalog(), update=True).ok
    assert snapshot(repo) == before


def test_watch_uses_fresh_subprocesses_and_never_acknowledges(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(sync.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    def stop_after_two(interval):
        if len(calls) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(sync.time, "sleep", stop_after_two)
    assert sync.main(["--watch", "--root", str(repo), "--interval", "1"]) == 130
    assert len(calls) == 2
    assert all("--update" in args and "--acknowledge" not in args for args, _ in calls)
    assert all(kw["cwd"] == repo for _, kw in calls)


@pytest.mark.parametrize("args", [["--watch", "--interval", "nan"], ["--watch", "--interval", "0"],
                                  ["--watch", "--acknowledge", "README.md"]])
def test_watch_rejects_unsafe_modes(args):
    with pytest.raises(SystemExit):
        sync.main(args)


def test_gate_rejects_stale_staged_reference_despite_unstaged_repair(repo):
    source = Path(sync.__file__).resolve().parents[2]
    (repo / "tools/security").mkdir()
    for name in ("tools/docs/sync_references.py", "tools/docs/verify_wiki.py", "tools/security/secret_scan.py"):
        shutil.copyfile(source / name, repo / name)
    for name in ("tools/__init__.py", "tools/docs/__init__.py", "tools/security/__init__.py", "seam_runtime/__init__.py",
                 "seam_runtime/tui/__init__.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    (repo / "seam_runtime/tui/commands.py").write_text(
        'import argparse\n'
        'def _subparser_action(p):\n'
        '    return next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)\n'
        'def _subparser_help(a):\n'
        '    return {c.dest: c.help for c in a._choices_actions}\n'
    )
    cli = repo / "seam_runtime/cli.py"
    cli.write_text(
        'import argparse\n'
        'def default_runtime_db_path():\n'
        '    raise AssertionError("must not read local installation defaults")\n'
        'def build_parser():\n'
        '    p = argparse.ArgumentParser(prog="seam")\n'
        '    p.add_argument("--db", default=default_runtime_db_path())\n'
        '    s = p.add_subparsers(dest="command", required=True)\n'
        '    s.add_parser("load").add_argument("--output")\n'
        '    return p\n'
    )
    for name in ("installer", "lossless", "holographic", "benchmarks", "context_views", "retrieval"):
        (repo / f"seam_runtime/{name}.py").write_text("# Metadata source fixture\n")
    (repo / "pyproject.toml").write_text("# Metadata source fixture\n")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0"}
    environment.pop("PYTHONPATH", None)
    def command(args):
        return subprocess.run(args, cwd=repo, env=environment, capture_output=True, text=True, check=False)
    def gate(*args):
        return command([sys.executable, "-m", "tools.docs.sync_references", *args])
    assert command(["git", "init", "-q"]).returncode == 0
    assert gate("--update").returncode == 0
    assert command(["git", "add", "."]).returncode == 0
    assert gate("--check", "--staged").returncode == 0
    cli.write_text(cli.read_text().replace("--output", "--destination"))
    assert command(["git", "add", "seam_runtime/cli.py"]).returncode == 0
    assert gate("--update").returncode == 1  # prose review remains required
    (repo / "docs/manual.md").write_text("# Example\n`seam load --destination example`\n")
    assert gate("--update", "--acknowledge", "docs/manual.md").returncode == 0
    assert gate("--check").returncode == 0
    before = snapshot(repo)
    result = gate("--check", "--staged")
    assert result.returncode == 1 and "stale/missing managed reference" in result.stdout
    assert snapshot(repo) == before
