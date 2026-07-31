"""Free coverage/precision/retrieval-lift preflight for ``grounded-clm/1``.

The derived-facts analogue of ``preflight_event_count_context.py``, called for in
the 2026-07-20 derived-facts handoff. It reads a saved Mem0-harness matched result
artifact plus the LoCoMo source dataset, extracts derived facts from the GOLD
evidence turns of the cat1/cat3 misses using the same runtime ingest path the
facade uses (``compile_nl`` with ``derived_fact_policy='grounded-clm/1'``), and
measures the three things the handoff asks for:

  1. per-turn fact YIELD    -- eligible derived facts per gold turn
  2. grounding PRECISION    -- eligible / total CLM candidates emitted
  3. retrieval LIFT         -- does distilling a gold turn into a fact make the
                               evidence look more like the query? (the #432 wall:
                               raw turns lose on query<->evidence wording distance)

No paid provider call. It DOES run a local Ollama extractor (slow: ~138 s/turn for
qwen2.5:14b) and a local sentence-transformer embedder, so use ``--limit`` for a
smoke. Output is aggregate + per-case NUMERIC only (question_id, category, counts,
rounded cosines) -- no licensed question/answer/memory text.

Why everything is measured in bge-small cosine space
----------------------------------------------------
The artifact's stored ``score`` is SEAM's retrieval-PIPELINE score from the baseline
run (``seam_mem0_server`` returns ``candidate.score``), in an embedding space that
is NOT reproducible from the artifact (empirically Pearson ~0.1 vs a plain
bge-small cosine, and the run records no embedder). Comparing a fact's cosine to
that pipeline score would mix two scales.

So this tool measures ENTIRELY in ``BAAI/bge-small-en-v1.5`` cosine space -- which
is exactly the store embedder ``grounded-clm/1`` forces on
(``adapters/seam.py:_open_runtime(force_derived_facts_embedding=True)``), so it is
the space the lever actually operates in. The HEADLINE is relative and
self-consistent:

    wording_closure_delta = cos(query, "subject predicate object")
                          - cos(query, "[speaker date] raw gold turn")

A positive delta is direct evidence the distilled fact closes the query<->evidence
wording gap the raw turn could not. The secondary ``bge_floor`` is the min
bge-cosine over the 200 baseline-retrieved memories: a LOOSE reachability proxy
(those 200 were picked by the baseline's own embedder, not bge), reported for
context, not as a top-200 guarantee.

Env (facade parity): HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1. Do NOT set
HF_HUB_CACHE -- the default ~/.cache/huggingface holds bge-small-en-v1.5 and
loads offline; the old /media/terrabyte/T7 path is dead (T7 mounts at /mnt/t7)
and pointing HF at it silently creates an empty cache that fails every case.
Extractor: a local Ollama model that FITS the GPU fully.
On the 8 GB RTX 2070, qwen2.5:14b spills 69% to CPU (>300 s/turn); the imported
qwen2.5-7b-1m (Q4, 4.7 GB, 100% GPU) runs ~6 s/turn -- use ``--model
qwen2.5-7b-1m:latest`` and raise ``SEAM_OLLAMA_TIMEOUT_S`` above the 300 s default
if you fall back to a CPU-spilling model.

Example:

    SEAM_OLLAMA_TIMEOUT_S=600 python -m \
      benchmarks.external.mem0_harness.preflight_derived_facts \
      /media/.../20260719-161639-mem0-harness-cat13-matched-final.json \
      --model qwen2.5-7b-1m:latest --limit 5
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATASET = _REPO_ROOT / "benchmarks" / "external" / "locomo" / "data" / "locomo10.json"
_SESSION_KEY = re.compile(r"session_(\d+)$")
# LoCoMo session date_time, e.g. "8:56 pm on 20 July, 2023"; the mem0 harness
# normalizes this to YYYY-MM-DD in the ingested turn envelope.
_LOCOMO_DT = re.compile(r"\bon\s+(\d{1,2}\s+[A-Za-z]+,\s+\d{4})\s*$")


def normalize_timestamp(raw: str) -> str:
    """Reproduce the harness's ``YYYY-MM-DD`` turn-envelope date from a session
    date_time string. Returns ``""`` when the value cannot be parsed."""

    match = _LOCOMO_DT.search(raw or "")
    if not match:
        return ""
    try:
        return datetime.strptime(match.group(1), "%d %B, %Y").date().isoformat()
    except ValueError:
        return ""


def _turn_body(dialog: dict[str, Any]) -> str:
    """Reproduce the mem0 harness turn text incl. photo tag
    (``memory-benchmarks/benchmarks/locomo/run.py:session_to_chunks``)."""

    text = str(dialog.get("text") or "")
    blip = str(dialog.get("blip_caption") or "")
    query = str(dialog.get("query") or "")
    if query and blip:
        photo_tag = f"[Sharing image - query: {query}. The image shows: {blip}]"
    elif query:
        photo_tag = f"[Sharing image - query for: {query}]"
    elif blip:
        photo_tag = f"[Sharing image that shows: {blip}]"
    else:
        photo_tag = ""
    if photo_tag:
        text = f"{text} {photo_tag}" if text else photo_tag
    return text


def build_turn_index(dataset: list[dict[str, Any]]) -> list[dict[str, dict[str, str]]]:
    """Return, per conversation index, ``dia_id -> {speaker,text,timestamp,envelope}``.

    The envelope reproduces ``adapters/seam.py:_format_turn`` with the harness's
    normalized date and photo tags, so extraction grounding and raw-turn embedding
    match the run byte-for-byte.
    """

    index: list[dict[str, dict[str, str]]] = []
    for conv in dataset:
        conversation = conv.get("conversation") or {}
        turns: dict[str, dict[str, str]] = {}
        for key, dialogs in conversation.items():
            match = _SESSION_KEY.fullmatch(key)
            if not match or not isinstance(dialogs, list):
                continue
            n = match.group(1)
            timestamp = normalize_timestamp(conversation.get(f"session_{n}_date_time") or "")
            for dialog in dialogs:
                if not isinstance(dialog, dict):
                    continue
                dia_id = dialog.get("dia_id")
                speaker = dialog.get("speaker")
                if not (isinstance(dia_id, str) and isinstance(speaker, str)):
                    continue
                text = _turn_body(dialog)
                if not text:
                    continue
                envelope = f"[{speaker} {timestamp}] {text}".strip()
                turns[dia_id] = {
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                    "envelope": envelope,
                }
        index.append(turns)
    return index


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> list[float]:
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag else v


class _Embedder:
    """bge-small (the grounded-clm/1 store embedder), with a text->vector cache."""

    def __init__(self) -> None:
        from seam_runtime.derived_fact_context import (
            DERIVED_FACTS_EMBEDDING_MODEL,
            DERIVED_FACTS_EMBEDDING_REVISION,
        )
        from seam_runtime.models import SentenceTransformerModel

        self._model = SentenceTransformerModel(
            model_name=DERIVED_FACTS_EMBEDDING_MODEL,
            revision=DERIVED_FACTS_EMBEDDING_REVISION,
            local_files_only=True,
        )
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        cached = self._cache.get(text)
        if cached is None:
            cached = _norm(self._model.embed(text))
            self._cache[text] = cached
        return cached

    def cos(self, a: str, b: str) -> float:
        return _cosine(self.embed(a), self.embed(b))


def summarize_record(
    payload: dict[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
    *,
    categories: frozenset[int],
    limit: int | None,
    compute_floor: bool,
    model: str,
    policy: str = "grounded-clm/1",
) -> dict[str, Any]:
    from seam_runtime.derived_fact_context import is_eligible_derived_claim
    from seam_runtime.nl import compile_nl
    from seam_runtime.nl_extract import OllamaExtractor
    from seam_runtime.vector import SQLiteVectorIndex

    embedder = _Embedder()
    extractor = OllamaExtractor(model=model, strict=True)
    if hasattr(extractor, "validate_for_derived_facts"):
        extractor.validate_for_derived_facts()

    misses = [
        e
        for e in payload.get("evaluations", [])
        if int(e.get("category") or 0) in categories
        and float((e.get("cutoff_results") or {}).get("top_200", {}).get("score") or 0.0) < 1.0
    ]
    if limit is not None:
        misses = misses[:limit]

    cases: list[dict[str, Any]] = []
    totals = {
        "misses": 0,
        "gold_turns_resolved": 0,
        "gold_turns_unresolved": 0,
        "clm_candidates": 0,
        "eligible_facts": 0,
        "misses_with_eligible_fact": 0,
        "misses_fact_beats_raw_gold": 0,
        "misses_fact_clears_bge_floor": 0,
    }
    closure_deltas: list[float] = []

    for evaluation in misses:
        totals["misses"] += 1
        conv_idx = int(evaluation.get("conversation_idx") or 0)
        turns = turn_index[conv_idx] if 0 <= conv_idx < len(turn_index) else {}
        retrieval = evaluation.get("retrieval") or {}
        query = str(retrieval.get("search_query") or "")

        bge_floor: float | None = None
        if compute_floor and query:
            floor_vals = [
                embedder.cos(query, str(s.get("memory") or ""))
                for s in (retrieval.get("search_results") or [])
                if str(s.get("memory") or "").strip()
            ]
            bge_floor = min(floor_vals) if floor_vals else None

        fact_scores: list[float] = []
        raw_gold_scores: list[float] = []
        clm_candidates = 0
        eligible = 0
        resolved = 0
        for dia_id in evaluation.get("evidence") or []:
            turn = turns.get(str(dia_id))
            if turn is None:
                totals["gold_turns_unresolved"] += 1
                continue
            resolved += 1
            totals["gold_turns_resolved"] += 1
            envelope = turn["envelope"]
            if query:
                raw_gold_scores.append(embedder.cos(query, envelope))
            batch = compile_nl(
                envelope,
                source_ref=f"preflight:{conv_idx}:{dia_id}",
                ns=f"locomo:preflight_{conv_idx}",
                scope="thread",
                extractor=extractor,
                speaker=turn["speaker"],
                source_timestamp=turn["timestamp"],
                derived_fact_policy=policy,
                allow_env_extractor=False,
            )
            for record in batch.records:
                if str(record.ext.get("derived_fact_policy") or "") != policy:
                    continue
                clm_candidates += 1
                if is_eligible_derived_claim(record, policy=policy):
                    eligible += 1
                    fact_text = SQLiteVectorIndex.render_record_text(record)
                    if query:
                        fact_scores.append(embedder.cos(query, fact_text))

        totals["clm_candidates"] += clm_candidates
        totals["eligible_facts"] += eligible
        best_fact = max(fact_scores) if fact_scores else None
        best_raw = max(raw_gold_scores) if raw_gold_scores else None
        beats_raw = best_fact is not None and best_raw is not None and best_fact > best_raw
        clears_floor = (
            best_fact is not None and bge_floor is not None and best_fact > bge_floor
        )
        if eligible:
            totals["misses_with_eligible_fact"] += 1
        if beats_raw:
            totals["misses_fact_beats_raw_gold"] += 1
        if clears_floor:
            totals["misses_fact_clears_bge_floor"] += 1
        if best_fact is not None and best_raw is not None:
            closure_deltas.append(best_fact - best_raw)

        cases.append(
            {
                "question_id": evaluation.get("question_id"),
                "category": int(evaluation.get("category") or 0),
                "gold_turns_resolved": resolved,
                "clm_candidates": clm_candidates,
                "eligible_facts": eligible,
                "bge_floor_over_baseline_retrieved": round(bge_floor, 4) if bge_floor is not None else None,
                "best_fact_cos": round(best_fact, 4) if best_fact is not None else None,
                "best_raw_gold_cos": round(best_raw, 4) if best_raw is not None else None,
                "wording_closure_delta": (
                    round(best_fact - best_raw, 4)
                    if best_fact is not None and best_raw is not None
                    else None
                ),
                "fact_beats_raw_gold": beats_raw,
                "fact_clears_bge_floor": clears_floor,
            }
        )

    grounded_precision = (
        totals["eligible_facts"] / totals["clm_candidates"] if totals["clm_candidates"] else None
    )
    yield_per_turn = (
        totals["eligible_facts"] / totals["gold_turns_resolved"] if totals["gold_turns_resolved"] else None
    )
    return {
        "dry_run": True,
        "paid_provider_calls": 0,
        "policy": policy,
        "embedding_space": "bge-small-en-v1.5 cosine (grounded-clm/1 store embedder)",
        "floor_note": (
            "bge_floor = min bge-cosine over the 200 baseline-retrieved memories; "
            "a loose reachability proxy, NOT the run's pipeline score."
        ),
        "categories": sorted(categories),
        "limit": limit,
        "totals": totals,
        "grounding_precision": round(grounded_precision, 4) if grounded_precision is not None else None,
        "eligible_fact_yield_per_gold_turn": round(yield_per_turn, 4) if yield_per_turn is not None else None,
        "mean_wording_closure_delta": (
            round(sum(closure_deltas) / len(closure_deltas), 4) if closure_deltas else None
        ),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free derived-facts (grounded-clm/1) coverage/precision/lift preflight"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness matched JSON artifact")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET, help="LoCoMo source dataset (locomo10.json)")
    parser.add_argument("--categories", type=int, nargs="+", default=[1, 3], help="miss categories to inspect (default 1 3)")
    parser.add_argument("--limit", type=int, default=None, help="cap misses processed (smoke; extraction is slow)")
    parser.add_argument("--model", default="qwen2.5-7b-1m:latest", help="local Ollama extractor model (default qwen2.5-7b-1m:latest; must fit GPU)")
    parser.add_argument("--policy", default="grounded-clm/1", help="derived-facts policy (grounded-clm/1 strict, grounded-clm/2 clause-scoped)")
    parser.add_argument("--no-floor", action="store_true", help="skip the bge floor (200 embeds/miss); keep only the closure metric")
    parser.add_argument("--summary-only", action="store_true", help="omit per-case rows")
    args = parser.parse_args()

    with args.record.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    with args.dataset.open(encoding="utf-8") as handle:
        dataset = json.load(handle)

    report = summarize_record(
        payload,
        build_turn_index(dataset),
        categories=frozenset(args.categories),
        limit=args.limit,
        compute_floor=not args.no_floor,
        model=args.model,
        policy=args.policy,
    )
    if args.summary_only:
        report.pop("cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
