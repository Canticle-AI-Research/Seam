"""Reproducible ranking-parity probe for batched embedding (HISTORY#613).

HISTORY#610 claimed batched and per-record embedding produce identical
vectors. That was false. HISTORY#612 replaced it with a measured claim -- that
the drift sits far below the smallest ranking margin -- but recorded no way to
re-run it. This probe is that way.

It embeds the same corpus per-record and batched, then compares the resulting
top-k orderings for a query set, and reports drift against the smallest
adjacent score gap. A claim of retrieval parity is only meaningful if drift is
compared to margin, so both are reported.

    python -m tools.ranking_parity_probe --text-dir <dir> --queries q.txt
    python -m tools.ranking_parity_probe --synthetic 80 --json

Exit code is non-zero if any top-k ordering differs, so this can gate a claim.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from seam_runtime.models import default_embedding_model, embed_texts

DEFAULT_QUERIES = [
    "desire and persistence",
    "the subconscious mind",
    "organized planning",
    "concentration of mental force",
    "habit and routine",
    "influence of the stars",
]


def _device(model) -> str:
    inner = getattr(model, "_model", None)
    try:
        return str(next(inner.parameters()).device)  # type: ignore[union-attr]
    except Exception:
        return "cpu/unknown"


def _synthetic(count: int) -> list[str]:
    seeds = [
        "The mind concentrates its force upon one sustained purpose.",
        "A habit forms through cue, routine, and reward repeated.",
        "The planets were held to incline rather than compel.",
        "Persistence transmutes desire into its physical equivalent.",
    ]
    return [f"Passage {i}. {seeds[i % len(seeds)]} " * 4 for i in range(count)]


def _from_dir(root: Path, count: int) -> list[str]:
    chunks: list[str] = []
    for path in sorted(root.rglob("*.txt")):
        text = path.read_text(errors="ignore")
        for start in range(0, len(text), 1200):
            piece = text[start : start + 1200].strip()
            if len(piece) > 400:
                chunks.append(piece)
            if len(chunks) >= count:
                return chunks
    return chunks


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text-dir", type=Path)
    source.add_argument("--synthetic", type=int, metavar="N")
    parser.add_argument("--chunks", type=int, default=80)
    parser.add_argument("--queries", type=Path, help="one query per line")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.synthetic is not None:
        if args.synthetic < 2:
            parser.error("--synthetic needs at least 2 chunks to rank")
        chunks = _synthetic(args.synthetic)
    else:
        chunks = _from_dir(args.text_dir, args.chunks)
    if len(chunks) < 2:
        parser.error("need at least 2 chunks to compare orderings")

    queries = (
        [q.strip() for q in args.queries.read_text().splitlines() if q.strip()]
        if args.queries
        else DEFAULT_QUERIES
    )

    model = default_embedding_model()
    model.embed("warm up")

    per_record = [model.embed(c) for c in chunks]
    batched = embed_texts(model, chunks)

    drift = max(
        abs(a - b)
        for left, right in zip(per_record, batched)
        for a, b in zip(left, right)
    )

    top_k = min(args.top_k, len(chunks))
    flips = {1: 0, 5: 0, top_k: 0}
    margins: list[float] = []
    for query in queries:
        qv = model.embed(query)
        scored_per = sorted(range(len(chunks)), key=lambda i: -_dot(qv, per_record[i]))
        scored_bat = sorted(range(len(chunks)), key=lambda i: -_dot(qv, batched[i]))
        for k in flips:
            if scored_per[:k] != scored_bat[:k]:
                flips[k] += 1
        ordered = sorted((_dot(qv, v) for v in per_record), reverse=True)
        gaps = [ordered[i] - ordered[i + 1] for i in range(min(top_k, len(ordered)) - 1)]
        if gaps:
            margins.append(min(gaps))

    smallest_margin = min(margins) if margins else 0.0
    result = {
        "chunks": len(chunks),
        "queries": len(queries),
        "model": getattr(model, "name", "?"),
        "device": _device(model),
        "python": platform.python_version(),
        "max_component_drift": drift,
        "smallest_topk_margin": smallest_margin,
        "margin_over_drift": (smallest_margin / drift) if drift else float("inf"),
        "orderings_changed": {str(k): v for k, v in sorted(flips.items())},
        "parity_holds": all(v == 0 for v in flips.values()),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key:24} {value}")
    return 0 if result["parity_holds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
