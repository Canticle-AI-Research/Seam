"""Free gate for sentence-grounded derived facts.

This is deliberately a preflight, not a runtime policy.  It tests the direction
selected after HISTORY#438 before adding any ``grounded-clm`` policy plumbing:

* fact text may be a model paraphrase;
* every fact must cite one exact source sentence from the canonical turn;
* first-person source claims must be rebased to the canonical turn speaker;
* all model work is local Ollama and all scoring is local BGE.

The report contains only aggregate and per-case numeric data.  It never prints
licensed question, answer, turn, or fact text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    _Embedder,
    build_turn_index,
)
from seam_runtime.sentence_grounded_facts import (
    SENTENCE_FACT_PROMPT_VERSION,
    SENTENCE_FACT_SCHEMA,
    SentenceGroundedFact,
    build_sentence_fact_prompt,
    first_person_declarative_sentences,
    has_exact_evidence_binding,
    sentence_fact_prompt_fingerprint,
    validate_sentence_grounded_fact_with_reason,
)
from seam_runtime.sentence_grounded_facts import (
    validate_sentence_grounded_fact as _validate_sentence_grounded_fact,
)

_PROMPT_VERSION = SENTENCE_FACT_PROMPT_VERSION


def _normalized(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def validate_sentence_grounded_fact(
    item: object,
    *,
    speaker: str,
    source_text: str,
) -> SentenceGroundedFact | None:
    """Compatibility export for focused preflight tests and callers."""

    return _validate_sentence_grounded_fact(
        item,
        speaker=speaker,
        source_text=source_text,
    )


class SentenceFactExtractor(Protocol):
    calls: int
    cache_hits: int
    model_fact_items: int
    bound_fact_items: int
    validated_fact_items: int
    rejection_counts: dict[str, int]

    def extract(self, *, speaker: str, source_text: str) -> tuple[SentenceGroundedFact, ...]: ...


@dataclass
class OllamaSentenceFactExtractor:
    """Local, deterministic JSON extraction with a resumable private cache."""

    model: str = "qwen2.5-7b-1m:latest"
    host: str = "http://127.0.0.1:11434"
    timeout: float = 600.0
    cache_path: Path | None = None
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 4096
    num_predict: int = 512
    calls: int = field(default=0, init=False)
    cache_hits: int = field(default=0, init=False)
    model_fact_items: int = field(default=0, init=False)
    bound_fact_items: int = field(default=0, init=False)
    validated_fact_items: int = field(default=0, init=False)
    rejection_counts: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.host = self._validated_host()
        if self.cache_path is not None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.cache_path) as connection:
                connection.execute(
                    """
                    create table if not exists sentence_fact_cache (
                        cache_key text primary key,
                        payload_json text not null
                    )
                    """
                )

    def _validated_host(self) -> str:
        parsed = urllib.parse.urlsplit(self.host)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("sentence-grounded preflight requires credential-free loopback Ollama")
        hostname = parsed.hostname.lower()
        display = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"http://{display}{port}"

    def _cache_key(self, *, speaker: str, source_text: str) -> str:
        body = "\0".join(
            (self.model, sentence_fact_prompt_fingerprint(), speaker, source_text)
        )
        return hashlib.sha256(body.encode()).hexdigest()

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        if self.cache_path is None:
            return None
        with sqlite3.connect(self.cache_path) as connection:
            row = connection.execute(
                "select payload_json from sentence_fact_cache where cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        self.cache_hits += 1
        return json.loads(row[0])

    def _write_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        if self.cache_path is None:
            return
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                "insert or replace into sentence_fact_cache(cache_key, payload_json) values (?, ?)",
                (cache_key, encoded),
            )

    def _generate(self, *, speaker: str, source_text: str) -> dict[str, Any]:
        prompt = build_sentence_fact_prompt(
            speaker=speaker,
            source_text=source_text,
        )
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": SENTENCE_FACT_SCHEMA,
                "options": {
                    "temperature": self.temperature,
                    "seed": self.seed,
                    "num_ctx": self.num_ctx,
                    "num_predict": self.num_predict,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            envelope = json.loads(response.read())
        decoded = json.loads(envelope["response"])
        if not isinstance(decoded, dict):
            raise RuntimeError("sentence-grounded extractor returned non-object JSON")
        return decoded

    def extract(
        self,
        *,
        speaker: str,
        source_text: str,
    ) -> tuple[SentenceGroundedFact, ...]:
        if not first_person_declarative_sentences(source_text):
            return ()
        cache_key = self._cache_key(speaker=speaker, source_text=source_text)
        payload = self._read_cache(cache_key)
        if payload is None:
            self.calls += 1
            payload = self._generate(speaker=speaker, source_text=source_text)
            self._write_cache(cache_key, payload)
        raw_items = payload.get("facts", []) if isinstance(payload, dict) else []
        if not isinstance(raw_items, list):
            raw_items = []
        self.model_fact_items += len(raw_items)
        facts: list[SentenceGroundedFact] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            if has_exact_evidence_binding(item, source_text=source_text):
                self.bound_fact_items += 1
            validated, rejection = validate_sentence_grounded_fact_with_reason(
                item,
                speaker=speaker,
                source_text=source_text,
            )
            if validated is None:
                reason = rejection or "unknown"
                self.rejection_counts[reason] = self.rejection_counts.get(reason, 0) + 1
                continue
            self.validated_fact_items += 1
            key = (_normalized(validated.fact), validated.evidence_sentence)
            if key not in seen:
                seen.add(key)
                facts.append(validated)
        return tuple(facts)
class Similarity(Protocol):
    def cos(self, a: str, b: str) -> float: ...


_MIN_REACHED_MISSES = 30
_MIN_BINDING_PRECISION = 0.95
_MIN_CLOSURE_CASES = 15
_MIN_MEAN_CLOSURE = 0.02
_MIN_MEAN_SUPPORT_COS = 0.50


def summarize_record(
    payload: dict[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
    *,
    extractor: SentenceFactExtractor,
    embedder: Similarity,
    categories: frozenset[int] = frozenset({1, 3}),
    limit: int | None = None,
) -> dict[str, Any]:
    """Measure the predeclared free ratchet over stored matched-run misses."""

    misses = [
        evaluation
        for evaluation in payload.get("evaluations", [])
        if int(evaluation.get("category") or 0) in categories
        and float(
            (evaluation.get("cutoff_results") or {})
            .get("top_200", {})
            .get("score")
            or 0.0
        )
        < 1.0
    ]
    if limit is not None:
        misses = misses[:limit]

    totals = {
        "misses": len(misses),
        "candidate_misses": 0,
        "candidate_turns": 0,
        "unique_candidate_turns": 0,
        "model_fact_items": 0,
        "bound_fact_items": 0,
        "validated_fact_items": 0,
        "provenance_bound_facts": 0,
        "misses_with_bound_fact": 0,
        "misses_fact_beats_raw_gold": 0,
    }
    cases: list[dict[str, Any]] = []
    turn_cache: dict[
        tuple[int, str], tuple[tuple[SentenceGroundedFact, ...], int, int, int]
    ] = {}
    closure_deltas: list[float] = []
    support_cosines: list[float] = []

    for evaluation in misses:
        conv_idx = int(evaluation.get("conversation_idx") or 0)
        turns = turn_index[conv_idx] if 0 <= conv_idx < len(turn_index) else {}
        retrieval = evaluation.get("retrieval") or {}
        query = str(retrieval.get("search_query") or "")
        raw_scores: list[float] = []
        fact_scores: list[float] = []
        case_support: list[float] = []
        case_fact_count = 0
        case_model_fact_items = 0
        case_bound_fact_items = 0
        case_validated_fact_items = 0
        candidate_turns = 0

        for dia_id in evaluation.get("evidence") or []:
            turn = turns.get(str(dia_id))
            if turn is None:
                continue
            if query:
                raw_scores.append(embedder.cos(query, turn["envelope"]))
            if not first_person_declarative_sentences(turn["text"]):
                continue
            candidate_turns += 1
            cache_key = (conv_idx, str(dia_id))
            cached = turn_cache.get(cache_key)
            if cached is None:
                model_items_before = extractor.model_fact_items
                bound_items_before = extractor.bound_fact_items
                validated_items_before = extractor.validated_fact_items
                facts = extractor.extract(
                    speaker=turn["speaker"],
                    source_text=turn["text"],
                )
                model_item_count = extractor.model_fact_items - model_items_before
                bound_item_count = extractor.bound_fact_items - bound_items_before
                validated_item_count = (
                    extractor.validated_fact_items - validated_items_before
                )
                cached = (
                    facts,
                    model_item_count,
                    bound_item_count,
                    validated_item_count,
                )
                turn_cache[cache_key] = cached
            facts, model_item_count, bound_item_count, validated_item_count = cached
            case_fact_count += len(facts)
            case_model_fact_items += model_item_count
            case_bound_fact_items += bound_item_count
            case_validated_fact_items += validated_item_count
            for fact in facts:
                support = embedder.cos(fact.fact, fact.evidence_sentence)
                support_cosines.append(support)
                case_support.append(support)
                if query:
                    fact_scores.append(embedder.cos(query, fact.fact))

        if candidate_turns:
            totals["candidate_misses"] += 1
        totals["candidate_turns"] += candidate_turns
        totals["provenance_bound_facts"] += case_fact_count
        totals["model_fact_items"] += case_model_fact_items
        totals["bound_fact_items"] += case_bound_fact_items
        totals["validated_fact_items"] += case_validated_fact_items
        if case_fact_count:
            totals["misses_with_bound_fact"] += 1

        best_raw = max(raw_scores) if raw_scores else None
        best_fact = max(fact_scores) if fact_scores else None
        delta = (
            best_fact - best_raw
            if best_fact is not None and best_raw is not None
            else None
        )
        if delta is not None:
            closure_deltas.append(delta)
        if delta is not None and delta > 0:
            totals["misses_fact_beats_raw_gold"] += 1

        cases.append(
            {
                "question_id": evaluation.get("question_id"),
                "category": int(evaluation.get("category") or 0),
                "candidate_turns": candidate_turns,
                "provenance_bound_facts": case_fact_count,
                "best_raw_gold_cos": round(best_raw, 4) if best_raw is not None else None,
                "best_fact_cos": round(best_fact, 4) if best_fact is not None else None,
                "wording_closure_delta": round(delta, 4) if delta is not None else None,
                "best_fact_beats_raw_gold": bool(delta is not None and delta > 0),
                "mean_fact_evidence_cos": (
                    round(sum(case_support) / len(case_support), 4)
                    if case_support
                    else None
                ),
            }
        )

    totals["unique_candidate_turns"] = len(turn_cache)
    precision = (
        totals["bound_fact_items"] / totals["model_fact_items"]
        if totals["model_fact_items"]
        else None
    )
    safety_acceptance = (
        totals["validated_fact_items"] / totals["model_fact_items"]
        if totals["model_fact_items"]
        else None
    )
    mean_closure = (
        sum(closure_deltas) / len(closure_deltas) if closure_deltas else None
    )
    mean_support = (
        sum(support_cosines) / len(support_cosines) if support_cosines else None
    )
    gates = {
        "reached_misses": totals["misses_with_bound_fact"] >= _MIN_REACHED_MISSES,
        "binding_precision": precision is not None and precision >= _MIN_BINDING_PRECISION,
        "closure_cases": totals["misses_fact_beats_raw_gold"] >= _MIN_CLOSURE_CASES,
        "mean_closure": mean_closure is not None and mean_closure >= _MIN_MEAN_CLOSURE,
        "semantic_support_proxy": mean_support is not None and mean_support >= _MIN_MEAN_SUPPORT_COS,
    }
    return {
        "dry_run": True,
        "paid_provider_calls": 0,
        "policy_plumbing_changed": False,
        "preflight": _PROMPT_VERSION,
        "categories": sorted(categories),
        "limit": limit,
        "thresholds": {
            "min_reached_misses": _MIN_REACHED_MISSES,
            "min_binding_precision": _MIN_BINDING_PRECISION,
            "min_closure_cases": _MIN_CLOSURE_CASES,
            "min_mean_wording_closure_delta": _MIN_MEAN_CLOSURE,
            "min_mean_fact_evidence_cos": _MIN_MEAN_SUPPORT_COS,
        },
        "totals": totals,
        "provenance_binding_precision": round(precision, 4) if precision is not None else None,
        "safety_acceptance_rate": (
            round(safety_acceptance, 4) if safety_acceptance is not None else None
        ),
        "mean_wording_closure_delta": round(mean_closure, 4) if mean_closure is not None else None,
        "mean_fact_evidence_cos": round(mean_support, 4) if mean_support is not None else None,
        "ollama_generation_calls": extractor.calls,
        "ollama_cache_hits": extractor.cache_hits,
        "unique_turn_rejection_counts": dict(sorted(extractor.rejection_counts.items())),
        "gates": gates,
        "gate_passed": all(gates.values()),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free sentence-grounded fact coverage and wording-closure gate"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness matched JSON artifact")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--categories", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default="qwen2.5-7b-1m:latest")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("test_seam/mem0/sentence-grounded-preflight.sqlite3"),
    )
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    with args.record.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    with args.dataset.open(encoding="utf-8") as handle:
        dataset = json.load(handle)

    extractor = OllamaSentenceFactExtractor(
        model=args.model,
        host=args.host,
        timeout=float(os.environ.get("SEAM_OLLAMA_TIMEOUT_S", "600")),
        cache_path=args.cache,
    )
    report = summarize_record(
        payload,
        build_turn_index(dataset),
        extractor=extractor,
        embedder=_Embedder(),
        categories=frozenset(args.categories),
        limit=args.limit,
    )
    if args.summary_only:
        report.pop("cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
