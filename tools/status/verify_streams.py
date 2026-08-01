"""Verify the status-stream decomposition stays honest.

Checks, in order of what would actually bite:

1. Every stream listed in the index exists, and every stream file is indexed.
2. `PROJECT_STATUS.md` links every stream, and stays small enough to read in one
   pass (it is step 1 of the mandatory session-start read order).
3. No stream has started stacking `Current update:` blocks — the exact drift that
   made the old status file unreadable.
4. The archived prior status file is present, and every `HISTORY#` entry it cited
   still resolves in `HISTORY.md`, so the restructure lost no chronology.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STREAM_DIR = REPO / "docs" / "status"
INDEX = STREAM_DIR / "index.md"
STATUS = REPO / "PROJECT_STATUS.md"
ARCHIVE = REPO / "docs" / "status_archive" / "2026-07-30-project-status-full.md"
HISTORY = REPO / "HISTORY.md"

# The old file was 348 KB. Anything approaching that is the drift returning.
STATUS_MAX_BYTES = 32_768

_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]]+\]\(\s*<?([^>\s)]+)>?(?:\s+[^)]*)?\)"
)


def _markdown_link_targets(text: str) -> set[str]:
    """Return inline Markdown link destinations, excluding images."""

    return {match.group(1) for match in _MARKDOWN_LINK.finditer(text)}


def check() -> list[str]:
    problems: list[str] = []

    if not INDEX.exists():
        return [f"missing stream index: {INDEX}"]

    index_text = INDEX.read_text()
    indexed = set(re.findall(r"\|\s*`([a-z-]+)`\s*\|", index_text))
    on_disk = {p.stem for p in STREAM_DIR.glob("*.md") if p.name != "index.md"}

    for name in sorted(indexed - on_disk):
        problems.append(f"index lists '{name}' but {name}.md does not exist")
    for name in sorted(on_disk - indexed):
        problems.append(f"{name}.md exists but is not listed in index.md")

    if not STATUS.exists():
        problems.append("PROJECT_STATUS.md missing")
        return problems

    status_text = STATUS.read_text()
    status_links = _markdown_link_targets(status_text)
    size = len(status_text.encode("utf-8"))
    if size > STATUS_MAX_BYTES:
        problems.append(
            f"PROJECT_STATUS.md is {size} bytes (> {STATUS_MAX_BYTES}); "
            "it must stay a router, not an archive"
        )

    for name in sorted(on_disk):
        if f"docs/status/{name}.md" not in status_links:
            problems.append(f"PROJECT_STATUS.md does not link stream '{name}'")

    for path in sorted(STREAM_DIR.glob("*.md")):
        stacked = len(re.findall(r"^Current update:", path.read_text(), re.M))
        if stacked:
            problems.append(
                f"{path.name} has {stacked} stacked 'Current update:' block(s); "
                "streams supersede in place and never stack"
            )

    if not HISTORY.exists():
        problems.append("HISTORY.md missing")

    if not ARCHIVE.exists():
        problems.append(f"status archive missing: {ARCHIVE}")
    elif HISTORY.exists():
        history_text = HISTORY.read_text()
        cited = {int(n) for n in re.findall(r"HISTORY#(\d+)", ARCHIVE.read_text())}
        missing = sorted(
            n for n in cited if f"---BEGIN-ENTRY-#{n:03d}---" not in history_text
        )
        if missing:
            problems.append(
                f"{len(missing)} HISTORY entries cited by the archive are absent "
                f"from HISTORY.md: {missing[:10]}"
            )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("status-stream verification FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    streams = sorted(p.stem for p in STREAM_DIR.glob("*.md") if p.name != "index.md")
    print(
        f"status streams OK: {len(streams)} streams "
        f"({', '.join(streams)}); PROJECT_STATUS.md "
        f"{len(STATUS.read_text().encode('utf-8'))} bytes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
