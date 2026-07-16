"""Measure the H1 context-bloat reduction.

Reports byte and approximate-token counts for canonical (pre-H1) reads vs
their H1 bounded equivalents. Token estimate matches tools.history.history_lib
(word_count * 1.3) so numbers line up with what the existing context pack tool
reports.
"""
from __future__ import annotations

from pathlib import Path

from tools.streams.streams_lib import CROSS_INDEX_PATH, REPO_ROOT, STREAMS_ROOT


def tokens(text: str) -> int:
    from tools.tokenization import count_tokens
    return count_tokens(text)


def measure(label: str, path: Path) -> dict[str, object]:
    if not path.exists():
        return {"label": label, "path": str(path), "missing": True}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "label": label,
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
        "tokens": tokens(text),
    }


def pct(before: int, after: int) -> str:
    if before == 0:
        return "n/a"
    return f"{100 * (1 - after / before):.1f}%"


def main() -> int:
    rows: list[tuple[str, dict[str, object], dict[str, object]]] = []

    rows.append((
        "Roadmap status read",
        measure("full ROADMAP.md", REPO_ROOT / "ROADMAP.md"),
        measure("derived state.md", STREAMS_ROOT / "roadmap" / "state.md"),
    ))
    rows.append((
        "History map read",
        measure("full HISTORY.md", REPO_ROOT / "HISTORY.md"),
        measure("HISTORY_INDEX.md", REPO_ROOT / "HISTORY_INDEX.md"),
    ))
    rows.append((
        "Cross-stream recent",
        measure("HISTORY.md + ROADMAP.md", REPO_ROOT / "HISTORY.md"),  # before lower-bound: just history
        measure("cross_index.md hot zone", CROSS_INDEX_PATH),
    ))

    # Special case: combined-before for cross-stream recent
    history = REPO_ROOT / "HISTORY.md"
    roadmap = REPO_ROOT / "ROADMAP.md"
    combined_text = ""
    for p in (history, roadmap):
        if p.exists():
            combined_text += p.read_text(encoding="utf-8", errors="replace")
    combined_before = {
        "label": "HISTORY.md + ROADMAP.md combined",
        "path": "HISTORY.md + ROADMAP.md",
        "bytes": (history.stat().st_size if history.exists() else 0)
                 + (roadmap.stat().st_size if roadmap.exists() else 0),
        "tokens": tokens(combined_text),
    }
    rows[2] = (rows[2][0], combined_before, rows[2][2])

    print("# SEAM H1 Context-Bloat Report\n")
    print("| Use case | Pre-H1 read | Tokens | H1 bounded read | Tokens | Reduction |")
    print("|---|---|---:|---|---:|---:|")
    for label, before, after in rows:
        b_tokens = int(before.get("tokens", 0))
        a_tokens = int(after.get("tokens", 0))
        print(
            f"| {label} | `{before.get('path')}` | {b_tokens:,} | "
            f"`{after.get('path')}` | {a_tokens:,} | **{pct(b_tokens, a_tokens)}** |"
        )

    print("\n## Detail\n")
    for label, before, after in rows:
        print(f"### {label}")
        for k, v in before.items():
            print(f"- before.{k}: {v}")
        for k, v in after.items():
            print(f"- after.{k}: {v}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
