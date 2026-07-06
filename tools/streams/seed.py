"""One-shot Context Streams bootstrap.

Runs the history adapter, bootstraps the roadmap stream from ROADMAP.md
markers, initializes the experience stream skeleton, rebuilds per-stream
indexes, and regenerates the derived cross-index. Idempotent — safe to
re-run after pulling roadmap or history changes.
"""
from __future__ import annotations

from tools.streams.history_adapter import sync_history_mirror
from tools.streams.rebuild_cross_index import rebuild_cross_index
from tools.streams.rebuild_index import rebuild_index
from tools.streams.roadmap_parser import bootstrap_roadmap_stream
from tools.streams.streams_lib import STREAMS_ROOT


def init_experience_stream() -> dict[str, object]:
    exp_dir = STREAMS_ROOT / "experience"
    exp_dir.mkdir(parents=True, exist_ok=True)
    log = exp_dir / "log.md"
    if not log.exists():
        log.write_bytes(b"")
    readme = exp_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            (
                "# Experience Stream\n\n"
                "Append-only log of lessons, constraints, patterns, anti-patterns,\n"
                "and decisions discovered during work. Each event uses the universal\n"
                "stream schema (see docs/roadmap/CONTEXT_STREAMS.md §4) with\n"
                "`kind` from {constraint, pattern, anti-pattern, decision}.\n\n"
                "Empty until the first lesson is recorded.\n"
            ),
            encoding="utf-8",
        )
    return {"kind": "experience", "log": str(log)}


def seed_all() -> dict[str, object]:
    STREAMS_ROOT.mkdir(parents=True, exist_ok=True)
    history_result = sync_history_mirror()
    roadmap_result = bootstrap_roadmap_stream()
    experience_result = init_experience_stream()
    index_results = {
        "history": rebuild_index("history"),
        "roadmap": rebuild_index("roadmap"),
        "experience": rebuild_index("experience"),
    }
    cross = rebuild_cross_index()
    return {
        "history": history_result,
        "roadmap": roadmap_result,
        "experience": experience_result,
        "indexes": index_results,
        "cross_index": cross,
    }


def main() -> int:
    result = seed_all()
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
