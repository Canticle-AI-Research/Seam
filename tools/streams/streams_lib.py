"""Generic event parser/writer for SEAM Context Streams.

Each stream is a markdown file at .seam/streams/<kind>/log.md containing
events delimited by ---BEGIN-<DELIM>-#NNN--- / ---END-<DELIM>-#NNN---.
For the history stream the delimiter is ENTRY (so the derived mirror is
byte-equivalent to root HISTORY.md). For all other streams the delimiter
is <STREAM>-EVENT where STREAM is the upper-cased kind.

The event header is a sequence of "key: value" lines terminated by a "---"
separator. Required fields per event: id, date, agent. Other universal
fields (kind, item, event, from, to, caused-by, triggers, supersedes,
refs, topics, tokens) are optional but recommended.

Events are addressable by stable IDs of the form "<stream>:NNN" with an
optional ":sha8" integrity suffix.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STREAMS_ROOT = REPO_ROOT / ".seam" / "streams"
CROSS_INDEX_PATH = REPO_ROOT / ".seam" / "cross_index.md"
_STREAM_APPEND_THREAD_LOCK = threading.Lock()


def delim_for(kind: str) -> str:
    """Return the marker delimiter for a stream kind."""
    if kind == "history":
        return "ENTRY"
    return f"{kind.upper()}-EVENT"


def log_path(kind: str) -> Path:
    return STREAMS_ROOT / kind / "log.md"


def index_path(kind: str) -> Path:
    return STREAMS_ROOT / kind / "index.md"


@dataclass
class StreamEvent:
    id: int
    kind: str
    date: str
    agent: str
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""
    byte_start: int = 0
    byte_end: int = 0
    line_start: int = 0
    line_end: int = 0
    hash: str = ""
    raw: bytes = b""

    @property
    def hash_short(self) -> str:
        return self.hash[:16]

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.id:03d}"

    def topics_list(self) -> list[str]:
        return [t.strip() for t in self.fields.get("topics", "").split(",") if t.strip()]


def _markers(kind: str) -> tuple[re.Pattern[bytes], re.Pattern[bytes]]:
    delim = re.escape(delim_for(kind))
    begin = re.compile(rb"^---BEGIN-" + delim.encode() + rb"-#(\d+)---\r?$", re.MULTILINE)
    end = re.compile(rb"^---END-" + delim.encode() + rb"-#(\d+)---\r?$", re.MULTILINE)
    return begin, end


def parse_events(data: bytes, kind: str) -> list[StreamEvent]:
    """Parse a stream log into events. Raises ValueError on malformed structure."""
    begin_re, end_re = _markers(kind)
    begin_matches = list(begin_re.finditer(data))
    end_matches = list(end_re.finditer(data))
    if len(begin_matches) != len(end_matches):
        raise ValueError(
            f"[{kind}] marker count mismatch: {len(begin_matches)} BEGIN vs {len(end_matches)} END"
        )
    events: list[StreamEvent] = []
    for bm, em in zip(begin_matches, end_matches):
        begin_id = int(bm.group(1))
        end_id = int(em.group(1))
        if begin_id != end_id:
            raise ValueError(f"[{kind}] marker pair mismatch BEGIN #{begin_id} / END #{end_id}")
        byte_start = bm.start()
        byte_end = em.end() - 1
        raw = data[byte_start : em.end()]
        line_start = data.count(b"\n", 0, byte_start) + 1
        line_end = data.count(b"\n", 0, em.start()) + 1
        evt = _parse_event_body(raw.decode("utf-8"), kind, begin_id)
        evt.byte_start = byte_start
        evt.byte_end = byte_end
        evt.line_start = line_start
        evt.line_end = line_end
        evt.hash = hashlib.sha256(raw).hexdigest()
        evt.raw = raw
        events.append(evt)
    for i in range(1, len(events)):
        if events[i].id <= events[i - 1].id:
            raise ValueError(
                f"[{kind}] event IDs not strictly increasing: #{events[i-1].id} then #{events[i].id}"
            )
    return events


def _parse_event_body(text: str, kind: str, expected_id: int) -> StreamEvent:
    lines = text.splitlines()
    header_lines: list[str] = []
    sep_idx = None
    for i in range(1, len(lines) - 1):
        if lines[i].strip() == "---":
            sep_idx = i
            break
        header_lines.append(lines[i])
    if sep_idx is None:
        raise ValueError(f"[{kind}] event #{expected_id}: no header/body separator")
    body = "\n".join(lines[sep_idx + 1 : -1]).strip("\n")

    fields: dict[str, str] = {}
    for hl in header_lines:
        if ":" not in hl:
            continue
        k, v = hl.split(":", 1)
        fields[k.strip()] = v.strip()
    for required in ("id", "date", "agent"):
        if required not in fields:
            raise ValueError(f"[{kind}] event #{expected_id}: missing '{required}'")

    raw_id = fields["id"]
    # Accept either "<kind>:NNN" or bare "NNN" (history's existing format).
    if ":" in raw_id:
        scope, num = raw_id.split(":", 1)
        if scope != kind and not (kind == "history" and scope.isdigit()):
            # Allow kind mismatch only if the parser is reading a foreign stream by mistake; warn via error.
            try:
                parsed_id = int(num)
            except ValueError:
                raise ValueError(f"[{kind}] event #{expected_id}: bad id '{raw_id}'")
        else:
            parsed_id = int(num)
    else:
        parsed_id = int(raw_id)

    if parsed_id != expected_id:
        raise ValueError(
            f"[{kind}] event id field ({parsed_id}) does not match marker (#{expected_id})"
        )

    return StreamEvent(
        id=parsed_id,
        kind=kind,
        date=fields["date"],
        agent=fields["agent"],
        fields={k: v for k, v in fields.items() if k not in ("id", "date", "agent")},
        body=body,
    )


def format_event(
    *,
    kind: str,
    id: int,
    date: str,
    agent: str,
    fields: dict[str, str],
    body: str,
    history_compat: bool = False,
) -> str:
    """Render an event as a markdown block ready to append to log.md.

    history_compat=True writes the legacy ENTRY format using bare numeric ids
    so the derived history mirror stays byte-equivalent to root HISTORY.md.
    """
    delim = delim_for(kind)
    id_str = f"{id:03d}"
    id_value = id_str if history_compat else f"{kind}:{id_str}"
    header_lines = [
        f"id: {id_value}",
        f"date: {date}",
        f"agent: {agent}",
    ]
    for key, value in fields.items():
        if key in ("id", "date", "agent"):
            continue
        header_lines.append(f"{key}: {value}")
    body_trimmed = body.rstrip("\n")
    return (
        f"---BEGIN-{delim}-#{id_str}---\n"
        + "\n".join(header_lines)
        + f"\n---\n{body_trimmed}\n---END-{delim}-#{id_str}---\n"
    )


def estimate_tokens(text: str) -> int:
    from tools.tokenization import count_tokens
    return count_tokens(text)


def next_event_id(events: list[StreamEvent]) -> int:
    return events[-1].id + 1 if events else 1


def read_log(kind: str) -> bytes:
    p = log_path(kind)
    return p.read_bytes() if p.exists() else b""


def write_log(kind: str, data: bytes) -> None:
    p = log_path(kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Best-effort parent-dir fsync (POSIX; Windows raises — swallow there)
    try:
        dir_fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def append_log(kind: str, data: bytes) -> None:
    p = log_path(kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        dir_fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def list_stream_kinds() -> list[str]:
    if not STREAMS_ROOT.exists():
        return []
    return sorted(p.name for p in STREAMS_ROOT.iterdir() if p.is_dir())


def _acquire_stream_lock(kind: str):
    """Acquire an exclusive advisory lock for a stream log.

    Returns a (lock_fd, release_fn) pair. Callers must invoke release_fn in a
    ``finally`` block.
    """
    stream_dir = STREAMS_ROOT / kind
    stream_dir.mkdir(parents=True, exist_ok=True)
    lock_path = stream_dir / "log.lock"
    _STREAM_APPEND_THREAD_LOCK.acquire()
    fd = -1
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        if os.name == "nt":
            import msvcrt
            if os.path.getsize(lock_path) == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

            def _release():
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                finally:
                    try:
                        os.close(fd)
                    finally:
                        _STREAM_APPEND_THREAD_LOCK.release()

        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)

            def _release():
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    try:
                        os.close(fd)
                    finally:
                        _STREAM_APPEND_THREAD_LOCK.release()

        return fd, _release
    except Exception:
        if fd >= 0:
            os.close(fd)
        _STREAM_APPEND_THREAD_LOCK.release()
        raise


def append_event(kind: str, header_fields: dict[str, str], body: str, *, agent: str, date: str) -> StreamEvent:
    """Append a new event to <kind>/log.md and return the parsed event."""
    _lock_fd, _release = _acquire_stream_lock(kind)
    try:
        data = read_log(kind)
        events = parse_events(data, kind) if data else []
        new_id = next_event_id(events)
        block = format_event(
            kind=kind,
            id=new_id,
            date=date,
            agent=agent,
            fields=header_fields,
            body=body,
        )
        append_bytes = b""
        if data and not data.endswith(b"\n"):
            append_bytes += b"\n"
        if data:
            append_bytes += b"\n"
        append_bytes += block.encode("utf-8")
        append_log(kind, append_bytes)
        events = parse_events(read_log(kind), kind)
        return events[-1]
    finally:
        _release()
