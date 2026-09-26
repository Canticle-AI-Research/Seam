"""Installed-package CLI surface for the Skill Knowledge runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .kb import (
    ActivationPlan,
    ActivationPolicy,
    ActiveSkillWindow,
    FileSkillWindowHost,
    HostCapabilities,
    RegistrySnapshot,
    SkillSearchProjection,
    SkillSourceRoot,
    build_registry,
    build_skill_graph,
    plan_activation,
    render_skill_graph_html,
)


def add_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    skills = subparsers.add_parser(
        "skills", help="Index, find, plan, and visualize bounded skill packages"
    )
    commands = skills.add_subparsers(dest="skills_command", required=True)
    _add_skill_commands(commands)


def _add_skill_commands(commands: argparse._SubParsersAction) -> None:

    index = commands.add_parser("index", help="Build a deterministic portable SkillDB snapshot")
    index.add_argument("--root", action="append", default=[], metavar="LABEL=PATH")
    index.add_argument(
        "--markdown-root",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Recursively ingest only SKILL.md packages from this root",
    )
    index.add_argument("--output", required=True)
    index.add_argument("--max-file-bytes", type=int, default=1_048_576)

    find = commands.add_parser("find", help="Return compact ranked skill matches")
    find.add_argument("snapshot")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("--category")
    find.add_argument("--context")
    find.add_argument("--tag")
    find.add_argument("--capability")
    find.add_argument("--format", choices=("pretty", "json"), default="pretty")

    plan = commands.add_parser("plan", help="Build a fail-closed ActivationPlan and complete SkillFrame")
    plan.add_argument("snapshot")
    plan.add_argument("--skill", action="append", required=True)
    plan.add_argument("--task", required=True)
    plan.add_argument("--candidate", action="append", default=[])
    plan.add_argument("--capability", action="append", default=[])
    plan.add_argument("--tool", action="append", default=[])
    plan.add_argument("--permission", action="append", default=[])
    plan.add_argument("--max-skills", type=int, default=8)
    plan.add_argument("--token-budget", type=int, default=16_000)
    plan.add_argument("--window", help="Atomically persist a cooperating host's active window")
    plan.add_argument("--expected-revision", type=int)
    plan.add_argument("--pin", action="append", default=[])
    plan.add_argument("--output", help="Write the plan/frame JSON artifact")

    graph = commands.add_parser("graph", help="Write a Skill Knowledge Graph as JSON or standalone HTML")
    graph.add_argument("snapshot")
    graph.add_argument("--plan", help="Plan artifact emitted by `seam skills plan`")
    graph.add_argument("--format", choices=("json", "html"), default="html")
    graph.add_argument("--output", required=True)


def build_standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seam-skills",
        description="Portable SEAM Skill Knowledge resolver",
    )
    commands = parser.add_subparsers(dest="skills_command", required=True)
    _add_skill_commands(commands)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_standalone_parser().parse_args(sys.argv[1:] if argv is None else argv)
    run_skills_command(args)


def run_skills_command(args: argparse.Namespace) -> None:
    if args.skills_command == "index":
        roots = _parse_roots(args.root, args.markdown_root)
        snapshot = build_registry(roots, max_file_bytes=args.max_file_bytes)
        snapshot.write(args.output)
        _print_json(
            {
                "schema": snapshot.schema,
                "snapshot_fingerprint": snapshot.fingerprint,
                "package_count": len(snapshot.packages),
                "output": str(args.output),
                "index_output": str(Path(args.output).with_name(Path(args.output).name + ".index.json")),
            }
        )
        return

    if args.skills_command == "find":
        projection = SkillSearchProjection.read(args.snapshot)
        results = projection.search_index.search(
            args.query,
            limit=args.limit,
            category=args.category,
            context=args.context,
            tag=args.tag,
            capability=args.capability,
        )
        if args.format == "json":
            _print_json(
                {
                    "snapshot_fingerprint": projection.snapshot_fingerprint,
                    "query": args.query,
                    "results": [result.to_dict() for result in results],
                }
            )
        else:
            for result in results:
                print(
                    f"{result.score:>4}  {result.skill_id}  "
                    f"[{', '.join(result.matched_terms)}]"
                )
        return

    snapshot = RegistrySnapshot.read(args.snapshot)

    if args.skills_command == "plan":
        policy = ActivationPolicy(args.max_skills, args.token_budget)
        host = HostCapabilities(
            capabilities=tuple(args.capability),
            tools=tuple(args.tool),
            permissions=tuple(args.permission),
        )
        adapter = None
        current = None
        if args.window:
            if args.expected_revision is None:
                raise ValueError("--window requires --expected-revision")
            adapter = FileSkillWindowHost(args.window)
            if adapter.path.exists():
                current = adapter.load()
                if args.pin and set(args.pin) != {entry.skill_id for entry in current.pinned}:
                    raise ValueError("--pin cannot change an existing window's pinned core")
            elif args.expected_revision != 0:
                raise ValueError("a new window requires --expected-revision 0")
        requested = tuple(args.skill)
        if args.window and current is None:
            requested = tuple(dict.fromkeys((*requested, *args.pin)))
        plan, frame = plan_activation(
            snapshot,
            requested,
            task=args.task,
            policy=policy,
            host=host,
            candidate_ids=tuple(args.candidate),
            pinned=current.pinned if current else (),
        )
        receipt = None
        if args.window:
            assert adapter is not None
            assert args.expected_revision is not None
            if current is not None:
                receipt = adapter.replace(frame, expected_revision=args.expected_revision)
            else:
                by_id = {entry.skill_id: entry for entry in frame.entries}
                missing_pins = sorted(set(args.pin) - set(by_id))
                if missing_pins:
                    raise ValueError(f"pinned skills absent from frame: {', '.join(missing_pins)}")
                initial = ActiveSkillWindow(
                    revision=0,
                    pinned=tuple(by_id[skill_id] for skill_id in dict.fromkeys(args.pin)),
                    rotating=(),
                )
                updated, receipt = initial.replace(frame, expected_revision=0)
                adapter.initialize(updated)
        payload: dict[str, Any] = {
            "schema": "seam-skill-activation/v1",
            "plan": plan.to_dict(),
            "frame": frame.to_dict(),
            "receipt": receipt.to_dict() if receipt else None,
        }
        rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return

    if args.skills_command == "graph":
        plan = _read_plan(args.plan) if args.plan else None
        graph = build_skill_graph(snapshot, plan)
        output = Path(args.output)
        if args.format == "json":
            output.write_text(graph.to_json() + "\n", encoding="utf-8")
        else:
            output.write_text(render_skill_graph_html(graph), encoding="utf-8")
        _print_json(
            {
                "format": args.format,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "snapshot_fingerprint": graph.snapshot_fingerprint,
                "plan_fingerprint": graph.plan_fingerprint,
                "output": str(output),
            }
        )
        return

    raise ValueError(f"unknown skills command: {args.skills_command}")


def _parse_roots(
    hybrid_values: list[str], markdown_values: list[str]
) -> tuple[SkillSourceRoot, ...]:
    roots: list[SkillSourceRoot] = []
    labels: set[str] = set()
    for option, kind, value in (
        (option, kind, value)
        for option, kind, values in (
            ("--root", "hybrid", hybrid_values),
            ("--markdown-root", "markdown", markdown_values),
        )
        for value in values
    ):
        label, separator, path = value.partition("=")
        if not separator or not label or not path:
            raise ValueError(f"invalid {option} {value!r}; expected LABEL=PATH")
        if label in labels:
            raise ValueError(f"duplicate skill root label: {label}")
        labels.add(label)
        roots.append(SkillSourceRoot(label, Path(path), kind=kind))
    if not roots:
        raise ValueError("index requires at least one --root or --markdown-root")
    return tuple(roots)


def _read_plan(path: str) -> ActivationPlan:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("plan artifact must be a JSON object")
    plan_value = value.get("plan", value)
    if not isinstance(plan_value, dict):
        raise ValueError("plan artifact does not contain a plan object")
    return ActivationPlan.from_dict(plan_value)


def _print_json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
