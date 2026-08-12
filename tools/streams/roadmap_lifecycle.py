"""Append-only three-stream roadmap workflow.

Future ideas, committed plans, and executed outcomes remain separate immutable
event logs. Stable item IDs and explicit origin/supersedes links provide the
join; ``roadmap_workflow_state.md`` is the disposable current-state view.
"""
from __future__ import annotations

import argparse
import os
import re
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from tools.streams.rebuild_cross_index import rebuild_cross_index
from tools.streams.rebuild_index import rebuild_index
from tools.streams.streams_lib import (
    REPO_ROOT,
    STREAMS_ROOT,
    StreamEvent,
    append_event,
    estimate_tokens,
    format_event,
    next_event_id,
    parse_events,
    read_log,
    write_log,
)

STREAM_KINDS = ("future-ideas", "plans", "executed")
STATE_PATH = STREAMS_ROOT / "roadmap_workflow_state.md"

ALLOWED_EVENTS = {
    "future-ideas": {"proposed", "revised", "deferred", "rejected"},
    "plans": {"planned", "replanned", "blocked", "cancelled"},
    "executed": {"completed", "partial", "failed", "abandoned"},
}

COMMON_REQUIRED = {"kind", "item", "event", "supersedes", "refs", "topics", "tokens"}
STREAM_REQUIRED = {
    "future-ideas": set(),
    "plans": {"origin", "depends-on", "gate"},
    "executed": {"origin", "outcome", "verification"},
}

_LIFECYCLE_REF_RE = re.compile(r"^(future-ideas|plans|executed):(\d+)$")
_EXTERNAL_ORIGIN_RE = re.compile(r"^(history|roadmap):\d+$")
_WORKFLOW_THREAD_LOCK = threading.Lock()


def _workflow_lock_path() -> Path:
    git_path = REPO_ROOT / ".git"
    if git_path.is_dir():
        return git_path / "seam-roadmap-lifecycle.lock"
    if git_path.is_file():
        try:
            pointer = git_path.read_text(encoding="utf-8").strip()
        except OSError:
            pointer = ""
        if pointer.startswith("gitdir:"):
            git_dir = Path(pointer.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = (REPO_ROOT / git_dir).resolve()
            if git_dir.is_dir():
                return git_dir / "seam-roadmap-lifecycle.lock"
    return STREAMS_ROOT / ".roadmap-lifecycle.lock"


@contextmanager
def _workflow_lock() -> Iterator[None]:
    """Serialize lifecycle validation, append, and derived rebuilds."""
    _WORKFLOW_THREAD_LOCK.acquire()
    fd = -1
    try:
        lock_path = _workflow_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        if os.name == "nt":
            import msvcrt

            if os.path.getsize(lock_path) == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd >= 0:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        _WORKFLOW_THREAD_LOCK.release()


def load_events() -> dict[str, list[StreamEvent]]:
    result: dict[str, list[StreamEvent]] = {}
    for stream in STREAM_KINDS:
        data = read_log(stream)
        result[stream] = parse_events(data, stream) if data else []
    return result


def _event_ref(event: StreamEvent) -> str:
    return f"{event.kind}:{event.id:03d}"


def _lifecycle_target(
    value: str,
    all_events: dict[str, StreamEvent],
) -> StreamEvent | None:
    match = _LIFECYCLE_REF_RE.fullmatch(value)
    if match is None:
        return None
    return all_events.get(f"{match.group(1)}:{int(match.group(2)):03d}")


def validate_events(events_by_stream: dict[str, list[StreamEvent]]) -> list[str]:
    """Validate schema, linear supersession, and cross-stream promotion."""
    errors: list[str] = []
    all_events = {
        _event_ref(event): event
        for stream in STREAM_KINDS
        for event in events_by_stream.get(stream, [])
    }
    known_items = {
        event.fields.get("item", "")
        for stream in STREAM_KINDS
        for event in events_by_stream.get(stream, [])
    }
    superseded_by: dict[str, list[str]] = defaultdict(list)

    for stream in STREAM_KINDS:
        for event in events_by_stream.get(stream, []):
            ref = _event_ref(event)
            fields = event.fields
            missing = sorted((COMMON_REQUIRED | STREAM_REQUIRED[stream]) - fields.keys())
            if missing:
                errors.append(f"[{ref}] missing fields: {', '.join(missing)}")
                continue
            if fields["kind"] != "roadmap-item":
                errors.append(f"[{ref}] kind must be roadmap-item")
            if not fields["item"].startswith("roadmap:"):
                errors.append(f"[{ref}] item must be a stable roadmap:* id")
            if fields["event"] not in ALLOWED_EVENTS[stream]:
                errors.append(
                    f"[{ref}] event {fields['event']!r} is invalid for {stream}"
                )
            if not event.body.strip():
                errors.append(f"[{ref}] body must not be empty")
            if fields.get("topics") in (None, "", "none"):
                errors.append(f"[{ref}] topics must not be empty or none")
            if fields.get("tokens", "").isdigit() is False:
                errors.append(f"[{ref}] tokens must be a non-negative integer")
            if stream == "plans" and fields.get("gate") in (None, "", "none"):
                errors.append(f"[{ref}] plan gate must not be empty or none")
            if stream == "executed":
                if fields.get("outcome") in (None, "", "none"):
                    errors.append(f"[{ref}] executed outcome must not be empty or none")
                if fields.get("verification") in (None, "", "none"):
                    errors.append(
                        f"[{ref}] executed verification must not be empty or none"
                    )

            supersedes = fields["supersedes"]
            if supersedes != "none":
                target = _lifecycle_target(supersedes, all_events)
                if target is None:
                    errors.append(f"[{ref}] supersedes missing lifecycle event {supersedes}")
                else:
                    if target.kind != stream:
                        errors.append(f"[{ref}] supersedes must stay within {stream}")
                    if target.fields.get("item") != fields["item"]:
                        errors.append(f"[{ref}] supersedes a different item")
                    if target.id >= event.id:
                        errors.append(f"[{ref}] supersedes must point backward")
                    superseded_by[supersedes].append(ref)

            origin = fields.get("origin", "none")
            if stream == "plans" and origin != "none":
                target = _lifecycle_target(origin, all_events)
                if target is None:
                    errors.append(f"[{ref}] plan origin must be a future-ideas event or none")
                elif target.kind != "future-ideas" or target.fields.get("item") != fields["item"]:
                    errors.append(f"[{ref}] plan origin must reference the same future idea")
            elif stream == "executed":
                target = _lifecycle_target(origin, all_events)
                if target is None:
                    if not _EXTERNAL_ORIGIN_RE.fullmatch(origin):
                        errors.append(
                            f"[{ref}] executed origin must be a plans event or imported history/roadmap ref"
                        )
                elif target.kind != "plans" or target.fields.get("item") != fields["item"]:
                    errors.append(f"[{ref}] executed origin must reference the same plan")

    for target, children in sorted(superseded_by.items()):
        if len(children) > 1:
            errors.append(f"[{target}] supersession fork: {', '.join(sorted(children))}")

    for stream in STREAM_KINDS:
        by_item: dict[str, list[StreamEvent]] = defaultdict(list)
        for event in events_by_stream.get(stream, []):
            by_item[event.fields.get("item", "")].append(event)
        for item, item_events in by_item.items():
            refs = {_event_ref(event) for event in item_events}
            heads = sorted(refs - set(superseded_by))
            if item and len(heads) != 1:
                errors.append(
                    f"[{stream}] item {item} must have one live head; found {', '.join(heads)}"
                )

    current = current_heads(events_by_stream)
    dependencies: dict[str, set[str]] = defaultdict(set)
    for event in current["plans"]:
        ref = _event_ref(event)
        item = event.fields.get("item", "")
        for dependency in event.fields.get("depends-on", "none").split(","):
            dependency = dependency.strip()
            if dependency == "none":
                continue
            if dependency not in known_items:
                errors.append(f"[{ref}] depends on unknown item {dependency}")
            elif dependency == item:
                errors.append(f"[{ref}] cannot depend on itself")
            else:
                dependencies[item].add(dependency)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item: str, path: list[str]) -> None:
        if item in visiting:
            cycle_start = path.index(item) if item in path else 0
            errors.append(f"[plans] dependency cycle: {' -> '.join(path[cycle_start:] + [item])}")
            return
        if item in visited:
            return
        visiting.add(item)
        for dependency in sorted(dependencies.get(item, set())):
            if dependency in dependencies:
                visit(dependency, path + [item])
        visiting.remove(item)
        visited.add(item)

    for item in sorted(dependencies):
        visit(item, [])
    return errors


def _validate_external_origins(events_by_stream: dict[str, list[StreamEvent]]) -> list[str]:
    errors: list[str] = []
    available: dict[str, set[int]] = {}
    for stream in ("history", "roadmap"):
        data = read_log(stream)
        available[stream] = {
            event.id for event in (parse_events(data, stream) if data else [])
        }
    for event in events_by_stream.get("executed", []):
        origin = event.fields.get("origin", "")
        match = _EXTERNAL_ORIGIN_RE.fullmatch(origin)
        if match and int(origin.split(":", 1)[1]) not in available[match.group(1)]:
            errors.append(f"[{_event_ref(event)}] imported origin does not exist: {origin}")
    return errors


def current_heads(
    events_by_stream: dict[str, list[StreamEvent]],
) -> dict[str, list[StreamEvent]]:
    superseded = {
        event.fields["supersedes"]
        for stream in STREAM_KINDS
        for event in events_by_stream.get(stream, [])
        if event.fields.get("supersedes", "none") != "none"
    }
    heads = {
        stream: [
            event
            for event in events_by_stream.get(stream, [])
            if _event_ref(event) not in superseded
        ]
        for stream in STREAM_KINDS
    }

    # A promoted item remains in its source log but leaves the active source
    # bucket. The exact immutable source event stays reachable by origin.
    consumed = {
        event.fields.get("origin", "none")
        for stream in ("plans", "executed")
        for event in heads[stream]
    }
    for stream in ("future-ideas", "plans"):
        heads[stream] = [event for event in heads[stream] if _event_ref(event) not in consumed]
    return heads


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    )


def _ordered_bucket(stream: str, bucket: list[StreamEvent]) -> list[StreamEvent]:
    if stream != "plans":
        return sorted(bucket, key=lambda event: _natural_key(event.fields.get("item", "")))

    by_item = {event.fields.get("item", ""): event for event in bucket}
    dependencies = {
        item: {
            dependency.strip()
            for dependency in event.fields.get("depends-on", "none").split(",")
            if dependency.strip() in by_item
        }
        for item, event in by_item.items()
    }
    remaining = set(by_item)
    ordered: list[StreamEvent] = []
    status_rank = {"planned": 0, "replanned": 0, "blocked": 1, "cancelled": 2}
    while remaining:
        ready = [item for item in remaining if not (dependencies[item] & remaining)]
        if not ready:  # Validation reports the cycle; keep state rendering total.
            ready = list(remaining)
        ready.sort(
            key=lambda item: (
                status_rank.get(by_item[item].fields.get("event", ""), 9),
                _natural_key(item),
            )
        )
        for item in ready:
            ordered.append(by_item[item])
            remaining.remove(item)
    ordered.sort(
        key=lambda event: status_rank.get(event.fields.get("event", ""), 9)
    )
    return ordered


def render_state(events_by_stream: dict[str, list[StreamEvent]]) -> str:
    heads = current_heads(events_by_stream)
    titles = {
        "future-ideas": "Future Ideas",
        "plans": "Plans",
        "executed": "Executed / Finished",
    }
    lines = [
        "# Append-Only Roadmap State (derived)",
        "",
        "Source: `.seam/streams/{future-ideas,plans,executed}/log.md`.",
        "Regenerate: `python -m tools.streams.roadmap_lifecycle rebuild-state`.",
        "Do not hand-edit this file.",
        "",
    ]
    for stream in STREAM_KINDS:
        bucket = _ordered_bucket(stream, heads[stream])
        lines.extend([f"## {titles[stream]} ({len(bucket)})", ""])
        for event in bucket:
            fields = event.fields
            if stream == "plans" and fields.get("gate") not in (None, "none"):
                detail = fields["gate"]
            elif stream == "executed" and fields.get("outcome") not in (None, "none"):
                detail = fields["outcome"]
            else:
                detail = event.body.splitlines()[0]
            lines.append(
                f"- `{fields.get('item', '?')}` — **{fields.get('event', '?')}** "
                f"via `{_event_ref(event)}` — {detail}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_state(events_by_stream: dict[str, list[StreamEvent]] | None = None) -> Path:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
    tmp.write_text(render_state(events_by_stream or load_events()), encoding="utf-8")
    os.replace(tmp, STATE_PATH)
    return STATE_PATH


def _verify_workflow_unlocked() -> list[str]:
    errors: list[str] = []
    for stream in STREAM_KINDS:
        stream_dir = STREAMS_ROOT / stream
        for name in ("log.md", "index.md", "README.md"):
            if not (stream_dir / name).exists():
                errors.append(f"[{stream}] {name} missing; run roadmap_lifecycle init")
    events = load_events()
    errors.extend(validate_events(events))
    errors.extend(_validate_external_origins(events))
    expected = render_state(events)
    if not STATE_PATH.exists():
        errors.append("roadmap workflow state missing; run roadmap_lifecycle rebuild-state")
    elif STATE_PATH.read_text(encoding="utf-8") != expected:
        errors.append("roadmap workflow state is stale; run roadmap_lifecycle rebuild-state")
    return errors


def verify_workflow() -> list[str]:
    with _workflow_lock():
        return _verify_workflow_unlocked()


def _initialize_unlocked() -> None:
    readme = (
        "# Append-only roadmap stream\n\n"
        "Managed by `python -m tools.streams.roadmap_lifecycle`; see "
        "`docs/roadmap/APPEND_ONLY_ROADMAP.md`.\n"
    )
    existing_logs = {
        stream: (STREAMS_ROOT / stream / "log.md").exists() for stream in STREAM_KINDS
    }
    if any(existing_logs.values()) and not all(existing_logs.values()):
        missing = ", ".join(stream for stream, exists in existing_logs.items() if not exists)
        raise RuntimeError(
            f"refusing partial lifecycle initialization; restore missing canonical logs: {missing}"
        )
    for stream in STREAM_KINDS:
        stream_dir = STREAMS_ROOT / stream
        stream_dir.mkdir(parents=True, exist_ok=True)
        if not (stream_dir / "log.md").exists():
            write_log(stream, b"")
        if not (stream_dir / "README.md").exists():
            (stream_dir / "README.md").write_text(readme, encoding="utf-8")
        rebuild_index(stream)
    write_state()
    rebuild_cross_index()


def initialize() -> None:
    with _workflow_lock():
        _initialize_unlocked()


def _candidate_event(
    stream: str,
    fields: dict[str, str],
    body: str,
    *,
    agent: str,
    date: str,
    existing: list[StreamEvent],
) -> StreamEvent:
    event_id = next_event_id(existing)
    block = format_event(
        kind=stream,
        id=event_id,
        date=date,
        agent=agent,
        fields=fields,
        body=body,
    )
    return parse_events(block.encode("utf-8"), stream)[0]


def append_roadmap_item(args: argparse.Namespace) -> StreamEvent:
    with _workflow_lock():
        missing_logs = [
            stream
            for stream in STREAM_KINDS
            if not (STREAMS_ROOT / stream / "log.md").exists()
        ]
        if missing_logs:
            raise RuntimeError(
                "canonical lifecycle logs are missing; run init only for a new workflow or "
                f"restore deleted logs: {', '.join(missing_logs)}"
            )
        body = args.body.strip()
        fields = {
            "kind": "roadmap-item",
            "item": args.item,
            "event": args.event,
            "supersedes": args.supersedes,
            "origin": args.origin,
            "depends-on": args.depends_on,
            "gate": args.gate,
            "outcome": args.outcome,
            "verification": args.verification,
            "refs": args.refs,
            "topics": args.topics,
            "tokens": str(estimate_tokens(body)),
        }
        date = args.date or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        events = load_events()
        events[args.stream].append(
            _candidate_event(
                args.stream,
                fields,
                body,
                agent=args.agent,
                date=date,
                existing=events[args.stream],
            )
        )
        errors = validate_events(events)
        errors.extend(_validate_external_origins(events))
        if errors:
            raise ValueError("; ".join(errors))

        event = append_event(args.stream, fields, body, agent=args.agent, date=date)
        rebuild_index(args.stream)
        write_state()
        rebuild_cross_index()
        errors = _verify_workflow_unlocked()
        if errors:
            raise RuntimeError("; ".join(errors))
        return event


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("verify")
    sub.add_parser("rebuild-state")

    append = sub.add_parser("append")
    append.add_argument("--stream", required=True, choices=STREAM_KINDS)
    append.add_argument("--item", required=True)
    append.add_argument("--event", required=True)
    append.add_argument("--body", required=True)
    append.add_argument("--agent", default="codex")
    append.add_argument("--date")
    append.add_argument("--supersedes", default="none")
    append.add_argument("--origin", default="none")
    append.add_argument("--depends-on", default="none")
    append.add_argument("--gate", default="none")
    append.add_argument("--outcome", default="none")
    append.add_argument("--verification", default="none")
    append.add_argument("--refs", default="none")
    append.add_argument("--topics", default="roadmap")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "init":
        initialize()
        print(f"roadmap lifecycle initialized: {', '.join(STREAM_KINDS)}")
        return 0
    if args.command == "rebuild-state":
        with _workflow_lock():
            print(f"roadmap lifecycle state rebuilt: {write_state()}")
        return 0
    if args.command == "verify":
        errors = verify_workflow()
        if errors:
            for error in errors:
                print(f"roadmap lifecycle: {error}")
            return 1
        print("roadmap lifecycle OK")
        return 0
    try:
        event = append_roadmap_item(args)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"appended {_event_ref(event)} for {event.fields['item']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
