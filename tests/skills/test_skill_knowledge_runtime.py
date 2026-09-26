"""Public-seam tests for the portable Skill Knowledge runtime."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest


def _write_yaml_skill(root, name: str, *, extra: str = "", instructions: str = "Use this skill."):
    (root / f"{name}.yaml").write_text(
        f"""\
schema_version: "1.0"
name: {name}
title: {name.replace('-', ' ').title()}
description: {instructions}
short_description: {instructions}
purpose: {instructions}
{extra}""",
        encoding="utf-8",
    )


def test_registry_ingests_yaml_and_markdown_then_roundtrips_and_searches(tmp_path):
    from seam_runtime.skills.kb import RegistrySnapshot, build_registry

    yaml_root = tmp_path / "canonical"
    yaml_root.mkdir()
    (yaml_root / "closeout.yaml").write_text(
        """\
schema_version: "1.0"
name: session-end
title: Session Closeout
description: Verify continuity at the end of a session.
short_description: Close sessions safely
purpose: Preserve continuity.
categories: [operations]
contexts: [repository]
tags: [continuity, verification]
capabilities: [git-read]
safety_rules:
  - Never hide a failed check.
workflow:
  - number: 1
    title: Verify
    body: Run the required checks.
output_format: "Status: <result>"
""",
        encoding="utf-8",
    )
    markdown_root = tmp_path / "external"
    package_dir = markdown_root / "review"
    package_dir.mkdir(parents=True)
    markdown_text = """\
---
name: code-review
description: Review changes for correctness and security.
category: engineering
contexts: [pull-request]
tags: [review, security]
capabilities: [git-read]
---
# Code Review

Inspect every changed line. Do not omit mandatory security checks.
"""
    (package_dir / "SKILL.md").write_text(markdown_text, encoding="utf-8")

    snapshot = build_registry({"repo": yaml_root, "vendor": markdown_root})

    assert [package.skill_id for package in snapshot.packages] == [
        "repo:session-end",
        "vendor:code-review",
    ]
    review = snapshot.package("vendor:code-review")
    assert review.instructions == markdown_text
    assert review.declared.category == "engineering"
    assert review.derived.source_path == "review/SKILL.md"
    assert len(review.source_sha256) == 64
    assert snapshot.search("security pull request")[0].skill_id == "vendor:code-review"
    assert snapshot.search("pull request")[0].skill_id == "vendor:code-review"

    payload = snapshot.to_json()
    assert RegistrySnapshot.from_json(payload).to_json() == payload
    assert json.loads(payload)["schema"] == "seam-skilldb/v1"


def test_snapshot_write_uses_canonical_lf_under_windows_newline_translation(
    tmp_path, monkeypatch
):
    from seam_runtime.skills.kb import SkillSearchProjection, build_registry

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "portable")
    snapshot = build_registry({"repo": root})
    snapshot_path = tmp_path / "skilldb.json"
    original_write_text = Path.write_text

    def windows_write_text(path, data, *args, **kwargs):
        return original_write_text(path, data.replace("\n", "\r\n"), *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", windows_write_text)
    snapshot.write(snapshot_path)

    assert snapshot_path.read_bytes().endswith(b"}\n")
    assert not snapshot_path.read_bytes().endswith(b"}\r\n")
    assert SkillSearchProjection.read(snapshot_path).snapshot_fingerprint == snapshot.fingerprint


def test_crlf_markdown_frontmatter_preserves_source_and_enforces_policy(tmp_path):
    from seam_runtime.skills.kb import (
        HostCapabilities,
        PlanningError,
        build_registry,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "dependency")
    skill_dir = root / "crlf-skill"
    skill_dir.mkdir()
    source = (
        "---\r\n"
        "name: crlf-skill\r\n"
        "description: Preserve CRLF policy metadata.\r\n"
        "requires: [repo:dependency]\r\n"
        "permissions: [network]\r\n"
        "---\r\n"
        "# CRLF Skill\r\n"
    )
    (skill_dir / "SKILL.md").write_bytes(source.encode("utf-8"))

    snapshot = build_registry({"repo": root})
    package = snapshot.package("repo:crlf-skill")
    assert package.instructions == source
    assert package.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert package.declared.permissions == ("network",)
    assert [(relation.kind, relation.target) for relation in package.declared.relations] == [
        ("requires", "repo:dependency")
    ]
    with pytest.raises(PlanningError, match="missing permissions.*network"):
        plan_activation(snapshot, ("repo:crlf-skill",), task="enforce CRLF policy")
    plan, _ = plan_activation(
        snapshot,
        ("repo:crlf-skill",),
        task="enforce CRLF policy",
        host=HostCapabilities(permissions=("network",)),
    )
    assert [skill.skill_id for skill in plan.skills] == [
        "repo:dependency",
        "repo:crlf-skill",
    ]


def test_registry_rejects_duplicate_identity_and_unsafe_or_oversized_sources(tmp_path):
    from seam_runtime.skills.kb import SkillSourceError, build_registry

    root = tmp_path / "skills"
    root.mkdir()
    content = """\
schema_version: "1.0"
name: duplicate
title: Duplicate
description: Duplicate identity.
short_description: Duplicate
purpose: Exercise validation.
"""
    (root / "a.yaml").write_text(content, encoding="utf-8")
    (root / "b.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(SkillSourceError, match="duplicate skill identity"):
        build_registry({"repo": root})
    (root / "b.yaml").unlink()

    outside = tmp_path / "outside.yaml"
    outside.write_text(content.replace("duplicate", "outside"), encoding="utf-8")
    (root / "linked.yaml").symlink_to(outside)
    with pytest.raises(SkillSourceError, match="unsafe source path"):
        build_registry({"safe": root})

    huge_root = tmp_path / "huge"
    huge_root.mkdir()
    (huge_root / "huge.yaml").write_text(content + ("x" * 500), encoding="utf-8")
    with pytest.raises(SkillSourceError, match="exceeds"):
        build_registry({"repo": huge_root}, max_file_bytes=128)


def test_registry_ignores_nested_yaml_and_tolerates_minimal_malformed_frontmatter(tmp_path):
    from seam_runtime.skills.kb import build_registry

    root = tmp_path / "catalog"
    root.mkdir()
    _write_yaml_skill(root, "canonical", instructions="Canonical manifest.")
    nested = root / "nested"
    nested.mkdir()
    (nested / "config.yaml").write_text("ordinary:\n  nested: config\n", encoding="utf-8")
    skill_dir = nested / "fallback-skill"
    skill_dir.mkdir()
    source = """\
---
name: fallback-skill
title: Fallback Skill
description: Review code: preserve the complete source
requires: [catalog:missing]
permissions: [network]
---
# Fallback Skill

These complete instructions must remain intact.
"""
    (skill_dir / "SKILL.md").write_text(source, encoding="utf-8")

    snapshot = build_registry({"catalog": root})

    assert [package.skill_id for package in snapshot.packages] == [
        "catalog:canonical",
        "catalog:fallback-skill",
    ]
    fallback = snapshot.package("catalog:fallback-skill")
    assert fallback.instructions == source
    assert fallback.declared.description == "Review code: preserve the complete source"
    assert fallback.declared.title == "Fallback Skill"
    assert fallback.declared.summary == ""
    assert fallback.derived.inferred_title == ""
    assert fallback.derived.inferred_summary == "Review code: preserve the complete source"
    assert fallback.title == "Fallback Skill"
    assert fallback.declared.relations == ()
    assert fallback.declared.permissions == ()
    assert fallback.derived.parser_policy == "minimal-scalar-fallback"
    assert fallback.derived.parser_version == "1"


def test_omitted_display_text_is_derived_with_field_provenance_for_yaml_and_markdown(
    tmp_path,
):
    from seam_runtime.skills.kb import build_registry, build_skill_graph

    root = tmp_path / "catalog"
    root.mkdir()
    (root / "yaml-skill.yaml").write_text(
        "name: yaml-skill\ndescription: Authored YAML description.\n",
        encoding="utf-8",
    )
    markdown = root / "markdown-skill"
    markdown.mkdir()
    (markdown / "SKILL.md").write_text(
        "---\nname: markdown-skill\n---\n# Markdown Heading\n\nComplete instructions.\n",
        encoding="utf-8",
    )

    snapshot = build_registry({"catalog": root})
    yaml_skill = snapshot.package("catalog:yaml-skill")
    assert yaml_skill.declared.title == ""
    assert yaml_skill.declared.summary == ""
    assert yaml_skill.derived.inferred_title == "yaml-skill"
    assert yaml_skill.derived.inferred_summary == "Authored YAML description."
    assert yaml_skill.title == "yaml-skill"
    assert yaml_skill.summary == "Authored YAML description."

    markdown_skill = snapshot.package("catalog:markdown-skill")
    assert markdown_skill.declared.title == ""
    assert markdown_skill.declared.description == ""
    assert markdown_skill.declared.summary == ""
    assert markdown_skill.derived.inferred_title == "Markdown Heading"
    assert markdown_skill.derived.inferred_description == "Markdown Heading"
    assert markdown_skill.derived.inferred_summary == "Markdown Heading"
    assert snapshot.search("markdown heading")[0].skill_id == "catalog:markdown-skill"
    graph = build_skill_graph(snapshot)
    node = next(node for node in graph.nodes if node.node_id == "skill:catalog:markdown-skill")
    assert node.label == "Markdown Heading"
    assert dict(node.details)["description"] == "Markdown Heading"


def test_planner_rejects_policy_incomplete_frontmatter_fallback(tmp_path):
    from seam_runtime.skills.kb import PlanningError, build_registry, plan_activation

    root = tmp_path / "catalog"
    skill_dir = root / "fallback-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fallback-skill\ndescription: Review code: preserve provenance\n"
        "permissions: [network]\nrequires: [catalog:missing]\n---\n# Fallback\n",
        encoding="utf-8",
    )
    snapshot = build_registry({"catalog": root})

    assert snapshot.search("preserve provenance")[0].skill_id == "catalog:fallback-skill"
    with pytest.raises(PlanningError, match="policy metadata is incomplete"):
        plan_activation(snapshot, ("catalog:fallback-skill",), task="fail closed")


def test_explicit_markdown_root_ignores_sibling_yaml_in_api_and_cli(tmp_path, capsys):
    from seam_runtime.skills.cli import main
    from seam_runtime.skills.kb import SkillSourceRoot, build_registry

    root = tmp_path / "page-monitor"
    root.mkdir()
    (root / "config.yml").write_text("monitor:\n  interval: 30\n", encoding="utf-8")
    source = "---\nname: page-monitor\ndescription: Monitor a page.\n---\n# Page Monitor\n"
    (root / "SKILL.md").write_text(source, encoding="utf-8")

    snapshot = build_registry((SkillSourceRoot("agents", root, kind="markdown"),))
    assert [package.skill_id for package in snapshot.packages] == ["agents:page-monitor"]
    assert snapshot.packages[0].instructions == source

    output = tmp_path / "skilldb.json"
    main(
        [
            "index",
            "--markdown-root",
            f"agents={root}",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["package_count"] == 1


def test_relation_kinds_are_closed_on_construction_and_snapshot_load(tmp_path):
    from seam_runtime.skills.kb import RegistrySnapshot, SkillRelation, build_registry

    with pytest.raises(ValueError, match="unsupported skill relation"):
        SkillRelation("executes", "repo:target")

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "one", extra="related: [repo:two]\n")
    _write_yaml_skill(root, "two")
    payload = build_registry({"repo": root}).to_dict()
    payload["packages"][0]["declared"]["relations"][0]["kind"] = "executes"
    with pytest.raises(ValueError, match="unsupported skill relation"):
        RegistrySnapshot.from_dict(payload)


def test_search_uses_precomputed_metadata_only_and_never_instruction_tokens(tmp_path):
    from seam_runtime.skills.kb import build_registry

    root = tmp_path / "skills"
    root.mkdir()
    (root / "metadata-search.yaml").write_text(
        """\
schema_version: "1.0"
name: metadata-search
title: Metadata Search
description: Search compact declared metadata.
short_description: Compact metadata
purpose: Prove metadata-only discovery.
tags: [discoverable]
contexts: [pull-request]
workflow:
  - number: 1
    title: Hidden instruction term
    body: instruction-only-needle
""",
        encoding="utf-8",
    )
    snapshot = build_registry({"repo": root})

    assert snapshot.search("discoverable")[0].skill_id == "repo:metadata-search"
    assert snapshot.search("instruction-only-needle") == ()
    index_payload = snapshot.search_index.to_dict()
    assert "instructions" not in json.dumps(index_payload)
    assert snapshot.search_index == type(snapshot.search_index).from_dict(index_payload)


def test_planner_closes_dependency_builds_complete_frame_and_rotates_window_atomically(tmp_path):
    from seam_runtime.skills.kb import (
        ActivationPolicy,
        ActiveSkillWindow,
        FileSkillWindowHost,
        HostCapabilities,
        build_registry,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "foundation", instructions="Always preserve provenance.")
    _write_yaml_skill(
        root,
        "review",
        extra="requires: [repo:foundation]\nruns_after: [repo:foundation]\ncapabilities: [git-read]\ntools: [git]\npermissions: [workspace-read]\n",
        instructions="Review every changed line and report security findings.",
    )
    _write_yaml_skill(root, "docs", instructions="Update operator documentation.")
    snapshot = build_registry({"repo": root})
    policy = ActivationPolicy(max_skills=3, token_budget=20_000)
    host = HostCapabilities(
        capabilities=("git-read",), tools=("git",), permissions=("workspace-read",)
    )

    plan, frame = plan_activation(
        snapshot,
        ("repo:review",),
        task="review the patch",
        policy=policy,
        host=host,
        candidate_ids=("repo:review", "repo:docs"),
    )

    assert [skill.skill_id for skill in plan.skills] == ["repo:foundation", "repo:review"]
    assert plan.exclusions[0].skill_id == "repo:docs"
    assert plan.exclusions[0].reason == "not selected"
    assert [entry.skill_id for entry in frame.entries] == ["repo:foundation", "repo:review"]
    assert frame.entries[1].instructions == snapshot.package("repo:review").instructions
    assert frame.snapshot_fingerprint == snapshot.fingerprint
    assert all(
        len(value) == 64
        for value in (
            frame.task_fingerprint,
            frame.policy_fingerprint,
            frame.capabilities_fingerprint,
            frame.tokenizer_fingerprint,
            frame.snapshot_fingerprint,
        )
    )

    pinned = (frame.entries[0],)
    window = ActiveSkillWindow(revision=0, pinned=pinned, rotating=())
    updated, receipt = window.replace(frame, expected_revision=0)
    assert receipt.activated_ids == ("repo:review",)
    assert receipt.retained_ids == ("repo:foundation",)
    assert receipt.evicted_ids == ()
    assert updated.revision == 1
    with pytest.raises(ValueError, match="revision mismatch"):
        updated.replace(frame, expected_revision=0)

    path = tmp_path / "active-window.json"
    host_adapter = FileSkillWindowHost(path)
    host_adapter.initialize(window)
    persisted_receipt = host_adapter.replace(frame, expected_revision=0)
    assert persisted_receipt.new_revision == 1
    assert host_adapter.load() == updated


def test_window_preserves_topological_frame_order_when_retaining_pin(tmp_path):
    from seam_runtime.skills.kb import ActiveSkillWindow, build_registry, plan_activation

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "helper")
    _write_yaml_skill(root, "pinned-base", extra="requires: [repo:helper]\n")
    _write_yaml_skill(root, "z-other")
    snapshot = build_registry({"repo": root})
    _, pinned_frame = plan_activation(snapshot, ("repo:pinned-base",), task="pin")
    pinned_entry = next(
        entry for entry in pinned_frame.entries if entry.skill_id == "repo:pinned-base"
    )
    _, frame = plan_activation(
        snapshot,
        ("repo:z-other",),
        task="retain",
        pinned=(pinned_entry,),
    )

    assert [entry.skill_id for entry in frame.entries] == [
        "repo:helper",
        "repo:pinned-base",
        "repo:z-other",
    ]
    updated, _ = ActiveSkillWindow(0, (pinned_entry,), ()).replace(
        frame, expected_revision=0
    )
    assert [entry.skill_id for entry in updated.entries] == [
        "repo:helper",
        "repo:pinned-base",
        "repo:z-other",
    ]
    assert updated.to_dict()["activation_order"] == [
        "repo:helper",
        "repo:pinned-base",
        "repo:z-other",
    ]


def test_planner_fails_closed_on_constraints_cycles_conflicts_and_budgets(tmp_path):
    from seam_runtime.skills.kb import (
        ActivationPolicy,
        HostCapabilities,
        PlanningError,
        build_registry,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "a", extra="requires: [repo:b]\n", instructions="A " + ("word " * 30))
    _write_yaml_skill(root, "b", extra="requires: [repo:a]\n", instructions="B")
    _write_yaml_skill(root, "locked", extra="permissions: [network]\n", instructions="Locked")
    _write_yaml_skill(root, "left", extra="conflicts_with: [repo:right]\n", instructions="Left")
    _write_yaml_skill(root, "right", instructions="Right")
    _write_yaml_skill(root, "big", instructions="Big " + ("word " * 30))
    snapshot = build_registry({"repo": root})

    with pytest.raises(PlanningError, match="dependency cycle"):
        plan_activation(snapshot, ("repo:a",), task="cycle")
    with pytest.raises(PlanningError, match="missing permissions.*network"):
        plan_activation(snapshot, ("repo:locked",), task="locked", host=HostCapabilities())
    with pytest.raises(PlanningError, match="conflict"):
        plan_activation(snapshot, ("repo:left", "repo:right"), task="conflict")
    with pytest.raises(PlanningError, match="skill-count budget"):
        plan_activation(
            snapshot,
            ("repo:left", "repo:locked"),
            task="too many",
            host=HostCapabilities(permissions=("network",)),
            policy=ActivationPolicy(max_skills=1, token_budget=10_000),
        )
    with pytest.raises(PlanningError, match="token budget"):
        plan_activation(
            snapshot,
            ("repo:big",),
            task="too large",
            policy=ActivationPolicy(max_skills=3, token_budget=5),
        )


def test_exact_tokenizer_rejects_large_unspaced_cjk_frame(tmp_path):
    from seam_runtime.skills.kb import ActivationPolicy, PlanningError, build_registry, plan_activation

    root = tmp_path / "skills"
    root.mkdir()
    skill_dir = root / "cjk"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: cjk\ndescription: Exact CJK token counting.\n---\n" + ("界" * 200_000),
        encoding="utf-8",
    )
    snapshot = build_registry({"repo": root})

    with pytest.raises(PlanningError, match="token budget"):
        plan_activation(
            snapshot,
            ("repo:cjk",),
            task="count exact CJK tokens",
            policy=ActivationPolicy(max_skills=2, token_budget=50),
        )

    _, frame = plan_activation(
        snapshot,
        ("repo:cjk",),
        task="count exact CJK tokens",
        policy=ActivationPolicy(max_skills=2, token_budget=1_000_000),
    )
    assert frame.token_count > 1
    assert frame.tokenizer_name
    assert frame.tokenizer_implementation == "tiktoken"
    assert frame.tokenizer_version


def test_retained_pins_participate_in_closure_conflicts_host_checks_and_revision(tmp_path):
    from seam_runtime.skills.kb import (
        HostCapabilities,
        PlanningError,
        build_registry,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "dependency")
    _write_yaml_skill(
        root,
        "pinned",
        extra="requires: [repo:dependency]\ncapabilities: [git-read]\n",
    )
    _write_yaml_skill(root, "neutral")
    _write_yaml_skill(root, "conflict", extra="conflicts_with: [repo:pinned]\n")
    snapshot = build_registry({"repo": root})
    host = HostCapabilities(capabilities=("git-read",))
    _, pinned_frame = plan_activation(snapshot, ("repo:pinned",), task="pin", host=host)
    pinned_entry = next(entry for entry in pinned_frame.entries if entry.skill_id == "repo:pinned")

    plan, _ = plan_activation(
        snapshot,
        ("repo:neutral",),
        task="retain pin",
        host=host,
        pinned=(pinned_entry,),
    )
    assert [skill.skill_id for skill in plan.skills] == [
        "repo:dependency",
        "repo:neutral",
        "repo:pinned",
    ]
    with pytest.raises(PlanningError, match="missing capabilities.*git-read"):
        plan_activation(snapshot, ("repo:neutral",), task="host", pinned=(pinned_entry,))
    with pytest.raises(PlanningError, match="conflict"):
        plan_activation(
            snapshot,
            ("repo:conflict",),
            task="conflict",
            host=host,
            pinned=(pinned_entry,),
        )
    with pytest.raises(PlanningError, match="pinned revision mismatch"):
        plan_activation(
            snapshot,
            ("repo:neutral",),
            task="revision",
            host=host,
            pinned=(replace(pinned_entry, revision="0" * 64),),
        )


def test_file_window_host_serializes_competing_replacements_and_uses_private_mode(tmp_path, monkeypatch):
    from seam_runtime.skills.kb import (
        ActiveSkillWindow,
        FileSkillWindowHost,
        build_registry,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "one")
    snapshot = build_registry({"repo": root})
    _, frame = plan_activation(snapshot, ("repo:one",), task="race")
    path = tmp_path / "window.json"
    FileSkillWindowHost(path).initialize(ActiveSkillWindow(0, (), ()))
    original_write = FileSkillWindowHost._atomic_write

    def slow_write(self, window):
        time.sleep(0.1)
        return original_write(self, window)

    monkeypatch.setattr(FileSkillWindowHost, "_atomic_write", slow_write)
    start = threading.Barrier(3)
    outcomes = []

    def replace_from_competing_host():
        start.wait()
        try:
            outcomes.append(FileSkillWindowHost(path).replace(frame, expected_revision=0))
        except ValueError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=replace_from_competing_host) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert sum("revision mismatch" in str(outcome) for outcome in outcomes) == 1
    assert FileSkillWindowHost(path).load().revision == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_name(path.name + ".lock").exists()


def test_graph_uses_snapshot_and_plan_for_typed_nodes_edges_and_safe_standalone_html(tmp_path):
    from seam_runtime.skills.kb import (
        HostCapabilities,
        build_registry,
        build_skill_graph,
        plan_activation,
        render_skill_graph_html,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(
        root,
        "foundation",
        extra="category: core\ncontexts: [repository]\ntags: [provenance]\n",
        instructions="Always preserve provenance.",
    )
    _write_yaml_skill(
        root,
        "review",
        extra=(
            "category: engineering\ncontexts: [pull-request]\ntags: [security]\n"
            "capabilities: [git-read]\ntools: [git]\npermissions: [workspace-read]\n"
            "requires: [repo:foundation]\nrelated: [repo:foundation]\n"
        ),
        instructions="Inspect <script>alert(1)</script> without executing markup.",
    )
    snapshot = build_registry({"repo": root})
    plan, _ = plan_activation(
        snapshot,
        ("repo:review",),
        task="review",
        host=HostCapabilities(
            capabilities=("git-read",), tools=("git",), permissions=("workspace-read",)
        ),
    )

    graph = build_skill_graph(snapshot, plan)

    node_types = {node.kind for node in graph.nodes}
    edge_types = {edge.kind for edge in graph.edges}
    assert {"skill", "capability", "context", "category", "tool", "permission"} <= node_types
    assert {"requires", "related", "has_capability", "has_context", "has_category", "needs_tool", "needs_permission"} <= edge_types
    assert all(
        edge.declared
        for edge in graph.edges
        if edge.kind in {"has_capability", "has_context", "has_category", "needs_tool", "needs_permission"}
    )
    assert {node.node_id for node in graph.nodes if node.active} >= {
        "skill:repo:foundation",
        "skill:repo:review",
    }
    assert graph.snapshot_fingerprint == snapshot.fingerprint
    assert graph.plan_fingerprint == plan.fingerprint

    html = render_skill_graph_html(graph)
    assert "<!doctype html>" in html.lower()
    assert 'id="graph-filter"' in html
    assert 'id="node-inspector"' in html
    assert 'src="http' not in html and 'href="http' not in html
    assert "<script>alert(1)</script>" not in html
    assert "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e" in html


def test_graph_rejects_stale_missing_and_revision_drifted_plans(tmp_path):
    from seam_runtime.skills.kb import (
        SkillReference,
        build_registry,
        build_skill_graph,
        plan_activation,
    )

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "one")
    snapshot = build_registry({"repo": root})
    plan, _ = plan_activation(snapshot, ("repo:one",), task="graph")

    with pytest.raises(ValueError, match="snapshot fingerprint mismatch"):
        build_skill_graph(snapshot, replace(plan, snapshot_fingerprint="0" * 64))
    with pytest.raises(ValueError, match="missing skill"):
        build_skill_graph(
            snapshot,
            replace(plan, skills=(SkillReference("repo:missing", "0" * 64),)),
        )
    with pytest.raises(ValueError, match="revision mismatch"):
        build_skill_graph(
            snapshot,
            replace(plan, skills=(SkillReference("repo:one", "0" * 64),)),
        )


def test_large_graph_html_has_dynamic_extents_and_local_navigation(tmp_path):
    from seam_runtime.skills.kb import build_registry, build_skill_graph, render_skill_graph_html

    root = tmp_path / "skills"
    root.mkdir()
    for index in range(80):
        _write_yaml_skill(root, f"skill-{index:03d}")
    html = render_skill_graph_html(build_skill_graph(build_registry({"repo": root})))

    match = re.search(r'<svg[^>]+viewBox="0 0 (\d+) (\d+)"', html)
    assert match
    width, height = (int(value) for value in match.groups())
    assert width > 1_000 and height > 1_000
    assert "fitGraph" in html
    assert 'addEventListener("wheel"' in html
    assert 'id="zoom-in"' in html and 'id="zoom-out"' in html


def test_graph_projects_source_hierarchy_as_derived_provenance(tmp_path):
    from seam_runtime.skills.kb import build_registry, build_skill_graph

    root = tmp_path / "catalog"
    skill_dir = root / "providers" / "acme" / "plugins" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code.\n---\n# Review\n",
        encoding="utf-8",
    )

    graph = build_skill_graph(build_registry({"codex": root}))

    assert any(node.kind == "source_root" and node.label == "codex" for node in graph.nodes)
    assert {
        node.label for node in graph.nodes if node.kind == "source_group"
    } >= {"providers", "acme", "plugins", "review"}
    derived = [edge for edge in graph.edges if edge.kind in {"contains", "contains_skill"}]
    assert derived
    assert all(not edge.declared for edge in derived)


def test_fresh_kb_import_is_portable_and_existing_root_exports_remain_lazy():
    script = """
import json
import sys
import seam_runtime.skills.kb
forbidden = [name for name in (
    'seam_runtime.runtime', 'seam_runtime.storage', 'seam_runtime.agent_memory'
) if name in sys.modules]
from seam_runtime import MIRLRecord, SeamRuntime
print(json.dumps({
    'forbidden': forbidden,
    'exports': [MIRLRecord.__name__, SeamRuntime.__name__],
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["forbidden"] == []
    assert payload["exports"] == ["MIRLRecord", "SeamRuntime"]


def test_dedicated_seam_skills_entrypoint_uses_portable_command_parser(tmp_path, capsys):
    from seam_runtime.skills.cli import main

    document = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert document["project"]["scripts"]["seam-skills"] == "seam_runtime.skills.cli:main"

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "portable")
    output = tmp_path / "skilldb.json"
    main(["index", "--root", f"repo={root}", "--output", str(output)])
    payload = json.loads(capsys.readouterr().out)
    assert payload["package_count"] == 1
    assert output.is_file()


def test_cli_find_reads_compact_projection_without_loading_skilldb_packages(tmp_path, capsys, monkeypatch):
    from seam_runtime.skills.cli import main
    from seam_runtime.skills.kb import RegistrySnapshot

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "portable", extra="tags: [compact-search]\n")
    snapshot_path = tmp_path / "skilldb.json"
    main(["index", "--root", f"repo={root}", "--output", str(snapshot_path)])
    capsys.readouterr()
    projection_path = snapshot_path.with_name(snapshot_path.name + ".index.json")
    assert projection_path.is_file()

    def forbidden_snapshot_read(_cls, _path):
        raise AssertionError("find must not load complete SkillDB packages")

    monkeypatch.setattr(RegistrySnapshot, "read", classmethod(forbidden_snapshot_read))
    main(["find", str(snapshot_path), "compact-search", "--format", "json"])
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["skill_id"] == "repo:portable"


def test_search_projection_rejects_stale_snapshot_association(tmp_path):
    from seam_runtime.skills.kb import SkillSearchProjection, SkillSourceError, build_registry

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "portable", instructions="First revision.")
    snapshot_path = tmp_path / "skilldb.json"
    build_registry({"repo": root}).write(snapshot_path)
    projection_path = snapshot_path.with_name(snapshot_path.name + ".index.json")
    stale_projection = projection_path.read_bytes()

    _write_yaml_skill(root, "portable", instructions="Second revision.")
    build_registry({"repo": root}).write(snapshot_path)
    projection_path.write_bytes(stale_projection)

    with pytest.raises(SkillSourceError, match="snapshot fingerprint mismatch"):
        SkillSearchProjection.read(snapshot_path)


def test_snapshot_deserialization_rejects_instruction_and_revision_digest_drift(tmp_path):
    from seam_runtime.skills.kb import RegistrySnapshot, build_registry

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "portable", instructions="Trusted instructions.")
    payload = build_registry({"repo": root}).to_dict()
    payload["packages"][0]["instructions"] = "Mutated instructions."
    with pytest.raises(ValueError, match="instruction digest mismatch"):
        RegistrySnapshot.from_dict(payload)

    payload = build_registry({"repo": root}).to_dict()
    payload["packages"][0]["revision"] = "0" * 64
    with pytest.raises(ValueError, match="revision and source SHA-256 must match"):
        RegistrySnapshot.from_dict(payload)


def test_cli_indexes_finds_plans_updates_window_and_writes_graph(tmp_path, capsys):
    from seam_runtime.cli import run_cli

    root = tmp_path / "skills"
    root.mkdir()
    _write_yaml_skill(root, "foundation", instructions="Preserve provenance.")
    _write_yaml_skill(
        root,
        "review",
        extra=(
            "requires: [repo:foundation]\ncontexts: [pull-request]\ntags: [security]\n"
            "capabilities: [git-read]\ntools: [git]\npermissions: [workspace-read]\n"
        ),
        instructions="Review every change.",
    )
    snapshot_path = tmp_path / "skilldb.json"
    window_path = tmp_path / "window.json"
    plan_path = tmp_path / "activation.json"
    graph_path = tmp_path / "graph.html"
    graph_json_path = tmp_path / "graph.json"

    run_cli(
        [
            "skills",
            "index",
            "--root",
            f"repo={root}",
            "--output",
            str(snapshot_path),
        ]
    )
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["package_count"] == 2
    assert snapshot_path.is_file()

    run_cli(["skills", "find", str(snapshot_path), "security pull-request", "--format", "json"])
    found = json.loads(capsys.readouterr().out)
    assert found["results"][0]["skill_id"] == "repo:review"
    assert "instructions" not in found["results"][0]

    run_cli(
        [
            "skills",
            "plan",
            str(snapshot_path),
            "--skill",
            "repo:review",
            "--task",
            "review the patch",
            "--capability",
            "git-read",
            "--tool",
            "git",
            "--permission",
            "workspace-read",
            "--pin",
            "repo:foundation",
            "--window",
            str(window_path),
            "--expected-revision",
            "0",
            "--output",
            str(plan_path),
        ]
    )
    planned = json.loads(capsys.readouterr().out)
    assert [item["skill_id"] for item in planned["plan"]["skills"]] == [
        "repo:foundation",
        "repo:review",
    ]
    assert planned["receipt"]["new_revision"] == 1
    assert window_path.is_file() and plan_path.is_file()

    run_cli(
        [
            "skills",
            "plan",
            str(snapshot_path),
            "--skill",
            "repo:review",
            "--task",
            "review the next patch",
            "--capability",
            "git-read",
            "--tool",
            "git",
            "--permission",
            "workspace-read",
            "--window",
            str(window_path),
            "--expected-revision",
            "1",
        ]
    )
    replanned = json.loads(capsys.readouterr().out)
    assert replanned["receipt"]["new_revision"] == 2
    assert {item["skill_id"] for item in replanned["plan"]["skills"]} >= {
        "repo:foundation",
        "repo:review",
    }

    run_cli(
        [
            "skills",
            "graph",
            str(snapshot_path),
            "--plan",
            str(plan_path),
            "--format",
            "html",
            "--output",
            str(graph_path),
        ]
    )
    graphed = json.loads(capsys.readouterr().out)
    assert graphed["format"] == "html"
    assert graphed["output"] == str(graph_path)
    assert "Skill Knowledge Graph" in graph_path.read_text(encoding="utf-8")
    assert Path(graphed["output"]).stat().st_size > 1000

    run_cli(
        [
            "skills",
            "graph",
            str(snapshot_path),
            "--plan",
            str(plan_path),
            "--format",
            "json",
            "--output",
            str(graph_json_path),
        ]
    )
    capsys.readouterr()
    graph_json = json.loads(graph_json_path.read_text(encoding="utf-8"))
    assert graph_json["schema"] == "seam-skill-graph/v1"
    assert any(node["active"] for node in graph_json["nodes"])
