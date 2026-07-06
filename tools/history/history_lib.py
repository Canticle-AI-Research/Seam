"""Shared library for HISTORY.md + HISTORY_INDEX.md tooling.

Canonical invariants:
    - HISTORY.md is append-only
    - Entries are delimited by ---BEGIN-ENTRY-#NNN--- and ---END-ENTRY-#NNN--- markers
    - Entry hash = SHA-256 of the complete byte range from BEGIN through END marker inclusive
    - HISTORY_INDEX.md is derived state, regenerable at any time from HISTORY.md
    - Byte ranges in the index are canonical; line ranges are a derived convenience column
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = REPO_ROOT / "HISTORY.md"
INDEX_PATH = REPO_ROOT / "HISTORY_INDEX.md"
SNAPSHOTS_DIR = REPO_ROOT / ".seam" / "snapshots"

VALID_STATUS = {"planned", "in-progress", "done", "changed", "deferred", "abandoned"}

BEGIN_RE = re.compile(rb"^---BEGIN-ENTRY-#(\d+)---\r?$", re.MULTILINE)
END_RE = re.compile(rb"^---END-ENTRY-#(\d+)---\r?$", re.MULTILINE)


@dataclass
class Entry:
    """Parsed entry with byte range + hash."""
    id: int
    date: str
    agent: str
    status: str
    topics: list[str]
    commits: str
    refs: str
    supersedes: str
    tokens: int
    body: str
    byte_start: int     # byte offset of ---BEGIN marker (inclusive)
    byte_end: int       # byte offset of end of ---END marker (inclusive, last char)
    line_start: int     # 1-indexed line of BEGIN marker
    line_end: int       # 1-indexed line of END marker
    hash: str           # full SHA-256 hex
    raw: bytes          # raw bytes of the entry (BEGIN through END inclusive)

    @property
    def hash_short(self) -> str:
        return self.hash[:16]


def read_history_bytes(path: Path | None = None) -> bytes:
    """Read HISTORY.md bytes. Resolves default path at call time so patching works."""
    if path is None:
        path = HISTORY_PATH
    if not path.exists():
        return b""
    return path.read_bytes()


def parse_entries(data: bytes) -> list[Entry]:
    """Parse HISTORY.md bytes into entries. Validates BEGIN/END pairing.

    Raises ValueError on malformed structure.
    """
    begin_matches = list(BEGIN_RE.finditer(data))
    end_matches = list(END_RE.finditer(data))

    if len(begin_matches) != len(end_matches):
        raise ValueError(
            f"Marker count mismatch: {len(begin_matches)} BEGINs vs {len(end_matches)} ENDs"
        )

    entries: list[Entry] = []
    for bm, em in zip(begin_matches, end_matches):
        begin_id = int(bm.group(1))
        end_id = int(em.group(1))
        if begin_id != end_id:
            raise ValueError(f"Marker pair mismatch: BEGIN #{begin_id} / END #{end_id}")

        byte_start = bm.start()
        byte_end = em.end() - 1  # inclusive last byte of END marker line
        raw = data[byte_start : em.end()]

        # Line numbers (1-indexed)
        line_start = data.count(b"\n", 0, byte_start) + 1
        line_end = data.count(b"\n", 0, em.end()) + 1
        # em.end() points one past the last char of the marker; line_end counts
        # newlines up to that point. Subtract 1 if the marker isn't followed by \n.
        # Simpler: count newlines up to the start of the END marker + 1
        line_end = data.count(b"\n", 0, em.start()) + 1

        h = hashlib.sha256(raw).hexdigest()

        entry = _parse_entry_body(raw.decode("utf-8", errors="replace"), begin_id)
        entry.byte_start = byte_start
        entry.byte_end = byte_end
        entry.line_start = line_start
        entry.line_end = line_end
        entry.hash = h
        entry.raw = raw
        entries.append(entry)

    # Sanity: ids should be strictly increasing
    for i in range(1, len(entries)):
        if entries[i].id <= entries[i - 1].id:
            raise ValueError(
                f"Entry IDs not strictly increasing: #{entries[i - 1].id} then #{entries[i].id}"
            )
    return entries


def _parse_entry_body(text: str, expected_id: int) -> Entry:
    """Parse a single entry string into an Entry (without byte offsets)."""
    lines = text.splitlines()
    # lines[0] = BEGIN marker, lines[-1] = END marker
    # Header block runs from line 1 until the first '---' separator line
    header_lines: list[str] = []
    sep_idx = None
    for i in range(1, len(lines) - 1):
        if lines[i].strip() == "---":
            sep_idx = i
            break
        header_lines.append(lines[i])
    if sep_idx is None:
        raise ValueError(f"Entry #{expected_id}: no header/body separator found")

    body_lines = lines[sep_idx + 1 : -1]
    body = "\n".join(body_lines).strip("\n")

    fields: dict[str, str] = {}
    for hl in header_lines:
        if ":" not in hl:
            continue
        k, v = hl.split(":", 1)
        fields[k.strip()] = v.strip()

    required = ["id", "date", "agent", "status", "topics", "commits", "refs", "supersedes", "tokens"]
    for r in required:
        if r not in fields:
            raise ValueError(f"Entry #{expected_id}: missing required field '{r}'")

    parsed_id = int(fields["id"])
    if parsed_id != expected_id:
        raise ValueError(
            f"Entry id field ({parsed_id}) does not match marker (#{expected_id})"
        )
    if fields["status"] not in VALID_STATUS:
        raise ValueError(
            f"Entry #{expected_id}: invalid status '{fields['status']}'"
        )

    topics = [t.strip() for t in fields["topics"].split(",") if t.strip()]

    try:
        tokens = int(fields["tokens"])
    except ValueError:
        raise ValueError(f"Entry #{expected_id}: tokens must be int")

    return Entry(
        id=parsed_id,
        date=fields["date"],
        agent=fields["agent"],
        status=fields["status"],
        topics=topics,
        commits=fields["commits"],
        refs=fields["refs"],
        supersedes=fields["supersedes"],
        tokens=tokens,
        body=body,
        byte_start=0,
        byte_end=0,
        line_start=0,
        line_end=0,
        hash="",
        raw=b"",
    )


def format_entry(
    *,
    id: int,
    date: str,
    agent: str,
    status: str,
    topics: Iterable[str],
    commits: str,
    refs: str,
    supersedes: str,
    tokens: int,
    body: str,
) -> str:
    """Format an entry as a string suitable for appending to HISTORY.md."""
    if status not in VALID_STATUS:
        raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUS}")
    id_str = f"{id:03d}"
    topics_str = ", ".join(topics)
    body_trimmed = body.rstrip("\n")
    return (
        f"---BEGIN-ENTRY-#{id_str}---\n"
        f"id: {id_str}\n"
        f"date: {date}\n"
        f"agent: {agent}\n"
        f"status: {status}\n"
        f"topics: {topics_str}\n"
        f"commits: {commits}\n"
        f"refs: {refs}\n"
        f"supersedes: {supersedes}\n"
        f"tokens: {tokens}\n"
        f"---\n"
        f"{body_trimmed}\n"
        f"---END-ENTRY-#{id_str}---\n"
    )


def estimate_tokens(text: str) -> int:
    from tools.tokenization import count_tokens
    return count_tokens(text)


def compute_entry_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def next_entry_id(entries: list[Entry]) -> int:
    if not entries:
        return 1
    return entries[-1].id + 1


def resolve_supersedes_chain(entries: list[Entry]) -> dict[int, tuple[list[int], str]]:
    """For each root entry id, return (chain_of_ids, latest_status).

    A "root" is an entry with supersedes == 'none'. A chain walks forward
    through entries whose supersedes points back to the previous link.
    """
    by_id = {e.id: e for e in entries}
    # Build forward map: prev_id -> [next_ids]
    forward: dict[int, list[int]] = {}
    for e in entries:
        if e.supersedes == "none":
            continue
        try:
            prev = int(e.supersedes.lstrip("#"))
        except ValueError:
            continue
        forward.setdefault(prev, []).append(e.id)

    rollup: dict[int, tuple[list[int], str]] = {}
    for e in entries:
        if e.supersedes != "none":
            continue
        chain = [e.id]
        current = e.id
        while current in forward and forward[current]:
            # Take the latest (highest id) child
            next_id = max(forward[current])
            chain.append(next_id)
            current = next_id
        latest_status = by_id[chain[-1]].status
        rollup[e.id] = (chain, latest_status)
    return rollup
