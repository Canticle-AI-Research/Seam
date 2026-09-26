"""Public-seam tests for the Codex native-skill host adapter."""

from __future__ import annotations

import hashlib
import json
import queue
import shlex
import stat
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


class _QueueStream:
    def __init__(self, on_read=None):
        self.items: queue.Queue[str | None] = queue.Queue()
        self.on_read = on_read

    def __iter__(self):
        return self

    def __next__(self):
        item = self.items.get(timeout=2)
        if item is None:
            raise StopIteration
        if self.on_read is not None:
            self.on_read(item)
        return item


class _ScriptedInput:
    def __init__(self, process):
        self.process = process

    def write(self, value: str) -> int:
        for line in value.splitlines():
            self.process.receive(json.loads(line))
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _ScriptedAppServer:
    def __init__(self, skill_path: Path):
        self.stdout = _QueueStream(self.mark_read)
        self.stderr = _QueueStream()
        self.stdin = _ScriptedInput(self)
        self.requests: list[dict] = []
        self.initialize_read = False
        self.returncode = None
        self.skill_path = skill_path

    def receive(self, message: dict) -> None:
        self.requests.append(message)
        if message.get("method") == "initialize":
            self.stdout.items.put(json.dumps({"id": 1, "result": {}}) + "\n")
        elif message.get("method") == "skills/list":
            assert self.initialize_read
            self.stdout.items.put(
                json.dumps(
                    {
                        "id": 2,
                        "result": {
                            "data": [
                                {
                                    "cwd": message["params"]["cwds"][0],
                                    "skills": [
                                        {
                                            "name": "review",
                                            "description": "Review changes.",
                                            "path": str(self.skill_path),
                                            "scope": "user",
                                            "enabled": True,
                                            "pluginId": None,
                                        }
                                    ],
                                    "errors": [],
                                }
                            ]
                        },
                    }
                )
                + "\n"
            )

    def mark_read(self, line: str) -> None:
        message = json.loads(line)
        if message.get("id") == 1:
            self.initialize_read = True

    def terminate(self) -> None:
        self.returncode = 0
        self.stdout.items.put(None)
        self.stderr.items.put(None)

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.terminate()


def test_app_server_inventory_rejects_loose_types_errors_and_duplicate_cwd(tmp_path):
    from seam_runtime.skills.adapters.codex import AppServerInventoryClient, CodexAdapterError

    cwd = tmp_path.resolve()
    skill = {
        "name": "review",
        "description": "Review changes.",
        "path": str(tmp_path / "review" / "SKILL.md"),
        "scope": "user",
        "enabled": True,
        "pluginId": None,
    }

    with pytest.raises(CodexAdapterError, match="enabled must be a boolean"):
        AppServerInventoryClient._parse_inventory(
            {"data": [{"cwd": str(cwd), "skills": [{**skill, "enabled": "false"}], "errors": []}]},
            cwd,
        )
    with pytest.raises(CodexAdapterError, match="error must be an object"):
        AppServerInventoryClient._parse_inventory(
            {"data": [{"cwd": str(cwd), "skills": [skill], "errors": ["bad"]}]},
            cwd,
        )
    with pytest.raises(CodexAdapterError, match="exactly one"):
        AppServerInventoryClient._parse_inventory(
            {
                "data": [
                    {"cwd": str(cwd), "skills": [skill], "errors": []},
                    {"cwd": str(cwd), "skills": [skill], "errors": []},
                ]
            },
            cwd,
        )


def test_app_server_client_stages_initialize_then_skills_list(tmp_path):
    from seam_runtime.skills.adapters.codex import AppServerInventoryClient

    skill_path = tmp_path / "review" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text("---\nname: review\ndescription: Review changes.\n---\n", encoding="utf-8")
    process = _ScriptedAppServer(skill_path)
    client = AppServerInventoryClient(
        process_factory=lambda *args, **kwargs: process,
        timeout=2,
    )

    inventory = client.list_skills(tmp_path)

    assert [request["method"] for request in process.requests] == [
        "initialize",
        "initialized",
        "skills/list",
    ]
    assert inventory.skills[0].name == "review"
    assert inventory.skills[0].path == skill_path
    assert inventory.errors == ()


class _StaticInventoryClient:
    def __init__(self, inventory):
        self.inventory = inventory

    def list_skills(self, _cwd):
        return self.inventory


def _write_skill(
    path: Path,
    *,
    name: str,
    description: str,
    extra: str = "",
    body: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n# {name}\n\n{body or description}\n",
        encoding="utf-8",
    )


def test_refresh_converts_enabled_duplicate_names_and_never_publishes_failures(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        CodexInventoryError,
        NativeCodexSkill,
        refresh_catalog,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    first_path = tmp_path / "catalog-a" / "SKILL.md"
    second_path = tmp_path / "catalog-b" / "SKILL.md"
    _write_skill(first_path, name="review", description="First duplicate review marker.")
    _write_skill(second_path, name="review", description="Second duplicate review marker.")
    disabled_path = tmp_path / "disabled-does-not-exist" / "SKILL.md"
    inventory = CodexInventory(
        skills=(
            NativeCodexSkill("review", "First", first_path, "user", True, None),
            NativeCodexSkill("review", "Second", second_path, "user", True, "vendor@plugin"),
            NativeCodexSkill("disabled", "Disabled", disabled_path, "user", False, None),
        ),
        errors=(),
    )
    state_dir = tmp_path / "state"

    receipt = refresh_catalog(cwd, state_dir, client=_StaticInventoryClient(inventory))

    assert receipt.total_count == 3
    assert receipt.enabled_count == 2
    assert receipt.package_count == 2
    assert [skill.native_name for skill in receipt.skills] == ["review", "review"]
    assert len({skill.skill_id for skill in receipt.skills}) == 2
    assert all(skill.path in {first_path, second_path} for skill in receipt.skills)
    assert "duplicate review marker" not in json.dumps(receipt.to_dict()).lower()
    current_path = Path(receipt.current_path)
    original_current = current_path.read_bytes()
    assert stat.S_IMODE(current_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(current_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(receipt.snapshot_path).stat().st_mode) == 0o600

    inventory_error = CodexInventory(
        skills=inventory.skills,
        errors=(CodexInventoryError(str(first_path), "host parse error"),),
    )
    with pytest.raises(CodexAdapterError, match="inventory reported 1 error"):
        refresh_catalog(cwd, state_dir, client=_StaticInventoryClient(inventory_error))
    assert current_path.read_bytes() == original_current

    missing_source = CodexInventory(
        skills=(NativeCodexSkill("missing", "Missing", disabled_path, "user", True, None),),
        errors=(),
    )
    with pytest.raises(CodexAdapterError, match="unsafe or missing skill source"):
        refresh_catalog(cwd, state_dir, client=_StaticInventoryClient(missing_source))
    assert current_path.read_bytes() == original_current


def test_refresh_rejects_symlinked_adapter_owned_ancestor(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        NativeCodexSkill,
        refresh_catalog,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "review" / "SKILL.md"
    _write_skill(skill_path, name="review", description="Review changes.")
    inventory = CodexInventory(
        skills=(NativeCodexSkill("review", "Review", skill_path, "user", True),),
        errors=(),
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    cwd_digest = hashlib.sha256(str(cwd.resolve()).encode()).hexdigest()
    (state_dir / cwd_digest).symlink_to(escaped, target_is_directory=True)

    with pytest.raises(CodexAdapterError, match="symlinked state directory"):
        refresh_catalog(cwd, state_dir, client=_StaticInventoryClient(inventory))
    assert list(escaped.iterdir()) == []


def test_refresh_has_no_fallible_post_commit_mode_change_and_preserves_current_on_precommit_failure(
    tmp_path, monkeypatch
):
    import seam_runtime.skills.adapters.codex as adapter

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "review" / "SKILL.md"
    _write_skill(skill_path, name="review", description="First revision.")
    client = _StaticInventoryClient(
        adapter.CodexInventory(
            (adapter.NativeCodexSkill("review", "Review", skill_path, "user", True),),
            (),
        )
    )
    state_dir = tmp_path / "state"
    first = adapter.refresh_catalog(cwd, state_dir, client=client)
    current_path = Path(first.current_path)
    first_current = current_path.read_bytes()

    _write_skill(skill_path, name="review", description="Second revision.")
    original_chmod = adapter.os.chmod

    def reject_final_file_chmod(path, mode):
        if Path(path) == current_path:
            raise OSError("injected post-commit chmod failure")
        return original_chmod(path, mode)

    monkeypatch.setattr(adapter.os, "chmod", reject_final_file_chmod)
    second = adapter.refresh_catalog(cwd, state_dir, client=client)
    second_current = current_path.read_bytes()
    assert second_current != first_current
    assert json.loads(second_current)["snapshot_fingerprint"] == second.snapshot_fingerprint

    monkeypatch.setattr(adapter.os, "chmod", original_chmod)
    _write_skill(skill_path, name="review", description="Third revision.")

    def reject_precommit_mode(_descriptor, _mode):
        raise OSError("injected pre-commit mode failure")

    monkeypatch.setattr(adapter.os, "fchmod", reject_precommit_mode)
    with pytest.raises(OSError, match="pre-commit"):
        adapter.refresh_catalog(cwd, state_dir, client=client)
    assert current_path.read_bytes() == second_current


def test_refresh_uses_stable_source_ids_and_resolves_relations_fail_closed(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        NativeCodexSkill,
        discover,
        refresh_catalog,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    first_path = tmp_path / "first" / "SKILL.md"
    duplicate_path = tmp_path / "duplicate" / "SKILL.md"
    _write_skill(first_path, name="same-package", description="Stable first package.")
    _write_skill(duplicate_path, name="same-package", description="Stable duplicate package.")
    first = NativeCodexSkill("first-native", "First", first_path, "user", True)
    first_only = CodexInventory((first,), ())
    first_receipt = refresh_catalog(
        cwd,
        tmp_path / "state-stable",
        client=_StaticInventoryClient(first_only),
    )
    duplicate_receipt = refresh_catalog(
        cwd,
        tmp_path / "state-stable",
        client=_StaticInventoryClient(
            CodexInventory(
                (first, NativeCodexSkill("second-native", "Second", duplicate_path, "user", True)),
                (),
            )
        ),
    )
    assert duplicate_receipt.skills[0].skill_id == first_receipt.skills[0].skill_id

    foundation_path = tmp_path / "foundation" / "SKILL.md"
    review_path = tmp_path / "relation-review" / "SKILL.md"
    _write_skill(foundation_path, name="base-package", description="Foundation dependency.")
    _write_skill(
        review_path,
        name="relation-review",
        description="Relation review workflow.",
        extra="requires: [native-foundation]\n",
    )
    relation_inventory = CodexInventory(
        (
            NativeCodexSkill("native-foundation", "Foundation", foundation_path, "user", True),
            NativeCodexSkill("native-review", "Review", review_path, "user", True),
        ),
        (),
    )
    discovered = discover(
        cwd,
        "relation review workflow",
        tmp_path / "state-relations",
        client=_StaticInventoryClient(relation_inventory),
    )
    assert [skill.native_name for skill in discovered.active_skills] == [
        "native-foundation",
        "native-review",
    ]

    ambiguous_path = tmp_path / "ambiguous" / "SKILL.md"
    _write_skill(
        ambiguous_path,
        name="ambiguous-review",
        description="Ambiguous review workflow.",
        extra="requires: [shared-native]\n",
    )
    with pytest.raises(CodexAdapterError, match="ambiguous relation target"):
        refresh_catalog(
            cwd,
            tmp_path / "state-ambiguous",
            client=_StaticInventoryClient(
                CodexInventory(
                    (
                        NativeCodexSkill("shared-native", "One", first_path, "user", True),
                        NativeCodexSkill("shared-native", "Two", foundation_path, "plugin", True),
                        NativeCodexSkill("review", "Review", ambiguous_path, "user", True),
                    ),
                    (),
                )
            ),
        )


def test_refresh_ingests_only_inventory_listed_skill_file(tmp_path):
    from seam_runtime.skills.adapters.codex import CodexInventory, NativeCodexSkill, refresh_catalog

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "package" / "SKILL.md"
    _write_skill(skill_path, name="listed", description="Listed skill.")
    nested = skill_path.parent / "nested" / "SKILL.md"
    nested.parent.mkdir()
    nested.write_text("---\nname: [not-a-scalar]\n---\nunsafe descendant", encoding="utf-8")

    receipt = refresh_catalog(
        cwd,
        tmp_path / "state",
        client=_StaticInventoryClient(
            CodexInventory((NativeCodexSkill("listed", "Listed", skill_path, "user", True),), ())
        ),
    )

    assert receipt.package_count == 1


def test_discover_selects_bounded_ranked_skill_and_closes_dependency(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexInventory,
        DiscoveryConstraints,
        NativeCodexSkill,
        discover,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    foundation_path = tmp_path / "foundation" / "SKILL.md"
    review_path = tmp_path / "review" / "SKILL.md"
    docs_path = tmp_path / "docs" / "SKILL.md"
    _write_skill(
        foundation_path,
        name="foundation",
        description="Base provenance layer.",
        body="Foundation instructions are complete.",
    )
    _write_skill(
        review_path,
        name="security-review",
        description="Security review for code changes.",
        extra="requires: [foundation]\n",
        body="Security review instructions are complete.",
    )
    _write_skill(
        docs_path,
        name="docs",
        description="Write release documentation.",
        body="Documentation instructions are complete.",
    )
    inventory = CodexInventory(
        skills=(
            NativeCodexSkill("foundation", "Base", foundation_path, "user", True),
            NativeCodexSkill("security-review", "Security", review_path, "user", True),
            NativeCodexSkill("docs", "Docs", docs_path, "user", True),
        ),
        errors=(),
    )

    receipt = discover(
        cwd,
        "perform a security review",
        tmp_path / "state",
        constraints=DiscoveryConstraints(max_skills=3, token_budget=4_000, max_selected=1),
        client=_StaticInventoryClient(inventory),
    )

    assert [skill.native_name for skill in receipt.selected] == ["security-review"]
    assert [skill.native_name for skill in receipt.active_skills] == [
        "foundation",
        "security-review",
    ]
    assert "Foundation instructions are complete." in receipt.frame_text
    assert "Security review instructions are complete." in receipt.frame_text
    assert "Documentation instructions are complete." not in receipt.frame_text
    assert receipt.skill_count == 2
    assert receipt.token_count <= receipt.token_budget
    assert receipt.window_id
    with pytest.raises(ValueError, match="max_selected must be at most 3"):
        DiscoveryConstraints(max_selected=4)


def test_discover_skips_denied_candidate_and_keeps_windows_private_and_separate(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexInventory,
        DiscoveryConstraints,
        NativeCodexSkill,
        discover,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    denied_path = tmp_path / "denied" / "SKILL.md"
    allowed_path = tmp_path / "allowed" / "SKILL.md"
    _write_skill(
        denied_path,
        name="security-audit-network",
        description="Security audit network specialist.",
        extra="tags: [priority]\npermissions: [network]\n",
    )
    _write_skill(
        allowed_path,
        name="security-audit",
        description="Security audit changes safely.",
    )
    inventory = CodexInventory(
        skills=(
            NativeCodexSkill("security-audit-network", "Denied", denied_path, "user", True),
            NativeCodexSkill("security-audit", "Allowed", allowed_path, "user", True),
        ),
        errors=(),
    )
    client = _StaticInventoryClient(inventory)
    state_dir = tmp_path / "state"
    task = "priority security audit unique-task-marker-927"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            discover,
            cwd,
            task,
            state_dir,
            window_id="first",
            constraints=DiscoveryConstraints(max_selected=1, permissions=()),
            client=client,
        )
        second_future = executor.submit(
            discover,
            cwd,
            "priority security audit second-window-marker",
            state_dir,
            window_id="second",
            constraints=DiscoveryConstraints(max_selected=1, permissions=()),
            client=client,
        )
        first = first_future.result()
        second = second_future.result()

    assert [skill.native_name for skill in first.selected] == ["security-audit"]
    assert first.skipped[0].native_name == "security-audit-network"
    assert "permission" in first.skipped[0].reason.lower()
    assert Path(first.receipt_path).parent != Path(second.receipt_path).parent
    assert stat.S_IMODE(Path(first.receipt_path).parent.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in Path(first.receipt_path).parent.iterdir())
    cwd_state = Path(first.receipt_path).parents[2]
    persisted = b"\n".join(path.read_bytes() for path in cwd_state.rglob("*") if path.is_file())
    assert task.encode() not in persisted


def test_inspect_validates_frame_graph_receipt_and_rejects_stale_source(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        NativeCodexSkill,
        discover,
        inspect_window,
        refresh_catalog,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "review" / "SKILL.md"
    _write_skill(
        skill_path,
        name="source-review",
        description="Review source changes.",
        body="Complete source review instructions.",
    )
    inventory = CodexInventory(
        skills=(NativeCodexSkill("source-review", "Review", skill_path, "user", True),),
        errors=(),
    )
    client = _StaticInventoryClient(inventory)
    state_dir = tmp_path / "state"
    created = discover(
        cwd,
        "review source changes",
        state_dir,
        window_id="review-window",
        client=client,
    )

    inspected = inspect_window(cwd, "review-window", state_dir)

    assert inspected.frame_text == created.frame_text == Path(created.frame_path).read_text()
    activation = json.loads(Path(created.activation_path).read_text())
    graph = json.loads(Path(created.graph_json_path).read_text())
    persisted_receipt = json.loads(Path(created.receipt_path).read_text())
    assert activation["plan"]["snapshot_fingerprint"] == created.snapshot_fingerprint
    assert activation["frame"]["plan_fingerprint"] == created.plan_fingerprint
    assert graph["plan_fingerprint"] == created.plan_fingerprint
    assert persisted_receipt["artifact_sha256"] == dict(created.artifact_sha256)

    persisted_receipt["active_skills"][0]["revision"] = "0" * 64
    Path(created.receipt_path).write_text(json.dumps(persisted_receipt, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(CodexAdapterError, match="receipt skill set does not match plan"):
        inspect_window(cwd, "review-window", state_dir)
    persisted_receipt["active_skills"][0]["revision"] = created.active_skills[0].revision
    Path(created.receipt_path).write_text(json.dumps(persisted_receipt, sort_keys=True, separators=(",", ":")) + "\n")

    _write_skill(
        skill_path,
        name="source-review",
        description="Review source changes.",
        body="Edited source review instructions.",
    )
    with pytest.raises(CodexAdapterError, match="live source drift"):
        inspect_window(cwd, "review-window", state_dir)
    refresh_catalog(cwd, state_dir, client=client)
    with pytest.raises(CodexAdapterError, match="stale window snapshot"):
        inspect_window(cwd, "review-window", state_dir)


def test_inspect_rebuilds_graph_json_and_html_semantics(tmp_path):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        NativeCodexSkill,
        discover,
        inspect_window,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "graph" / "SKILL.md"
    _write_skill(skill_path, name="graph-review", description="Graph review workflow.")
    client = _StaticInventoryClient(
        CodexInventory(
            (NativeCodexSkill("graph-review", "Graph", skill_path, "user", True),),
            (),
        )
    )
    receipt = discover(
        cwd,
        "graph review workflow",
        tmp_path / "state",
        window_id="graph-window",
        client=client,
    )
    receipt_path = Path(receipt.receipt_path)
    original_receipt = receipt_path.read_bytes()
    graph_path = Path(receipt.graph_json_path)
    original_graph = graph_path.read_bytes()
    graph = json.loads(original_graph)
    graph["nodes"][0]["label"] = "tampered semantic label"
    tampered_graph = (json.dumps(graph, sort_keys=True, separators=(",", ":")) + "\n").encode()
    graph_path.write_bytes(tampered_graph)
    persisted = json.loads(original_receipt)
    persisted["artifact_sha256"]["graph.json"] = hashlib.sha256(tampered_graph).hexdigest()
    receipt_path.write_text(json.dumps(persisted, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(CodexAdapterError, match="graph JSON semantic drift"):
        inspect_window(cwd, "graph-window", tmp_path / "state")

    graph_path.write_bytes(original_graph)
    html_path = Path(receipt.graph_html_path)
    original_html = html_path.read_bytes()
    tampered_html = original_html + b"<!-- semantic drift -->"
    html_path.write_bytes(tampered_html)
    persisted = json.loads(original_receipt)
    persisted["artifact_sha256"]["graph.html"] = hashlib.sha256(tampered_html).hexdigest()
    receipt_path.write_text(json.dumps(persisted, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(CodexAdapterError, match="graph HTML semantic drift"):
        inspect_window(cwd, "graph-window", tmp_path / "state")


def test_inspect_recomputes_exact_frame_tokens_and_rejects_coordinated_budget_tamper(
    tmp_path,
):
    from seam_runtime.skills.adapters.codex import (
        CodexAdapterError,
        CodexInventory,
        NativeCodexSkill,
        discover,
        inspect_window,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "token" / "SKILL.md"
    _write_skill(
        skill_path,
        name="token-review",
        description="Token review workflow.",
        body="This complete frame has substantially more than one token.",
    )
    client = _StaticInventoryClient(
        CodexInventory(
            (NativeCodexSkill("token-review", "Token", skill_path, "user", True),),
            (),
        )
    )
    state_dir = tmp_path / "state"
    receipt = discover(
        cwd,
        "token review workflow",
        state_dir,
        window_id="token-window",
        client=client,
    )
    activation_path = Path(receipt.activation_path)
    receipt_path = Path(receipt.receipt_path)
    activation = json.loads(activation_path.read_bytes())
    persisted = json.loads(receipt_path.read_bytes())
    activation["frame"]["token_count"] = 0
    activation["frame"]["token_budget"] = 1
    tampered_activation = (json.dumps(activation, sort_keys=True, separators=(",", ":")) + "\n").encode()
    activation_path.write_bytes(tampered_activation)
    persisted["token_count"] = 0
    persisted["token_budget"] = 1
    persisted["artifact_sha256"]["activation.json"] = hashlib.sha256(tampered_activation).hexdigest()
    receipt_path.write_text(json.dumps(persisted, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(CodexAdapterError, match="frame token|frame policy"):
        inspect_window(cwd, "token-window", state_dir)


def test_cli_bootstrap_discover_inspect_and_installed_entrypoint(tmp_path, capsys):
    from seam_runtime.skills.adapters.codex import (
        CodexInventory,
        NativeCodexSkill,
        main,
    )

    cwd = tmp_path / "repo"
    cwd.mkdir()
    skill_path = tmp_path / "review" / "SKILL.md"
    _write_skill(
        skill_path,
        name="cli-review",
        description="CLI review workflow.",
        body="Complete CLI review instructions.",
    )
    client = _StaticInventoryClient(
        CodexInventory(
            skills=(NativeCodexSkill("cli-review", "Review", skill_path, "user", True),),
            errors=(),
        )
    )
    state_dir = tmp_path / "state"

    bootstrap_state = tmp_path / "state with spaces"
    executable = tmp_path / "installed seam skills codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    assert (
        main(
            [
                "bootstrap",
                "--state-dir",
                str(bootstrap_state),
                "--executable",
                str(executable),
            ]
        )
        == 0
    )
    bootstrap = capsys.readouterr().out
    profile = tomllib.loads(bootstrap)
    assert profile["skills"]["include_instructions"] is False
    instructions = profile["developer_instructions"]
    assert "SKILLDB_BOOTSTRAP_BEGIN" in instructions
    assert f"{shlex.quote(str(executable.resolve()))} discover" in instructions
    assert '--cwd "$PWD"' in instructions
    assert "seam-skills-codex discover" not in instructions
    assert repr(str(bootstrap_state)) in instructions
    assert "does not mutate privileged" in instructions

    assert (
        main(
            [
                "discover",
                "--cwd",
                str(cwd),
                "--task",
                "CLI review workflow",
                "--state-dir",
                str(state_dir),
                "--window",
                "cli-window",
                "--max-skills",
                "2",
                "--token-budget",
                "4000",
                "--max-selected",
                "1",
            ],
            client=client,
        )
        == 0
    )
    discovered = json.loads(capsys.readouterr().out)
    assert "Complete CLI review instructions." in discovered["frame_text"]
    assert (
        main(
            [
                "inspect",
                "--cwd",
                str(cwd),
                "--state-dir",
                str(state_dir),
                "--window",
                "cli-window",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["frame_text"] == discovered["frame_text"]

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    assert 'seam-skills-codex = "seam_runtime.skills.adapters.codex:main"' in pyproject.read_text()
    installed = subprocess.run(
        ["seam-skills-codex", "bootstrap"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "SKILLDB_BOOTSTRAP_END" in installed.stdout
    assert tomllib.loads(installed.stdout)["skills"]["include_instructions"] is False

    docs = (Path(__file__).parents[2] / "docs" / "skills" / "CODEX_ADAPTER.md").read_text()
    assert "$CODEX_HOME/skilldb.config.toml" in docs
    assert "[profiles.skilldb]" not in docs


def test_adapter_import_keeps_portable_core_boundary():
    script = """
import json
import sys
import seam_runtime.skills.adapters.codex
print(json.dumps(sorted(name for name in sys.modules if name in {
    'seam_runtime.runtime', 'seam_runtime.storage', 'seam_runtime.agent_memory',
    'seam_runtime.server', 'seam_runtime.knowledge_graph'})))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == []
