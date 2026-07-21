"""Free coverage/precision/closure gate for ``multi-speaker-grounded/1``.

The analogue of ``preflight_sentence_grounded_facts.py`` for the broadened
multi-speaker contract (``seam_runtime/multi_speaker_facts.py``). It answers the
one question the draft exists to test: does dropping the singular-first-person
restriction lift the 51/63 reach ceiling by capturing **third-person named
facts** on gold turns the live contract refuses — without wrecking precision?

Over the stored #429 cat1/cat3 miss set it measures, with zero provider calls
(local Ollama extraction + local BGE only):

  1. reach            -- misses with >=1 validated fact (compare to 51/63)
  2. third-person gain -- misses reached ONLY via gold turns that have no
                          first-person sentence (the specific upside the live
                          first-person contract cannot get)
  3. binding precision -- validated / model-emitted fact items
  4. safety acceptance -- validated / model-emitted (broadening's risk surface)
  5. wording closure   -- does the distilled fact embed closer to the query than
                          the raw gold turn (the #432 wall)

Output is aggregate + per-case NUMERIC only: question ids, categories, counts,
rounded cosines, and rejection-reason tallies. Never licensed text.
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
from seam_runtime.multi_speaker_facts import (
    MULTI_SPEAKER_FACT_SCHEMA,
    build_multi_speaker_fact_prompt,
    declarative_sentences,
    multi_speaker_fact_prompt_fingerprint,
    validate_multi_speaker_fact_with_reason,
)
from seam_runtime.multi_speaker_facts import (
    SentenceGroundedFact as MultiSpeakerFact,
)
from seam_runtime.sentence_grounded_facts import first_person_declarative_sentences

_PROMPT_VERSION = "multi-speaker-grounded/1"


def _normalized(value: str) -> str:
    return " ".join(value.strip().casefold().split())


class MultiSpeakerFactExtractor(Protocol):
    calls: int
    cache_hits: int
    model_fact_items: int
    validated_fact_items: int
    rejection_counts: dict[str, int]

    def extract(self, *, speaker: str, source_text: str) -> tuple[MultiSpeakerFact, ...]: ...


@dataclass
class OllamaMultiSpeakerFactExtractor:
    """Local, deterministic JSON extraction with a resumable private cache."""

    model: str = "qwen2.5-7b-1m:latest"
    host: str = "http://127.0.0.1:11434"
    timeout: float = 600.0
    cache_path: Path | None = None
    ground_scope: str = "sentence"
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 4096
    num_predict: int = 512
    calls: int = field(default=0, init=False)
    cache_hits: int = field(default=0, init=False)
    model_fact_items: int = field(default=0, init=False)
    validated_fact_items: int = field(default=0, init=False)
    rejection_counts: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.host = self._validated_host()
        if self.cache_path is not None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.cache_path) as connection:
                connection.execute(
                    """
                    create table if not exists multi_speaker_fact_cache (
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
            raise ValueError("multi-speaker preflight requires credential-free loopback Ollama")
        hostname = parsed.hostname.lower()
        display = f"[{hostname}]" if ":" in hostname else hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"http://{display}{port}"

    def _cache_key(self, *, speaker: str, source_text: str) -> str:
        body = "\0".join(
            (self.model, multi_speaker_fact_prompt_fingerprint(), speaker, source_text)
        )
        return hashlib.sha256(body.encode()).hexdigest()

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        if self.cache_path is None:
            return None
        with sqlite3.connect(self.cache_path) as connection:
            row = connection.execute(
                "select payload_json from multi_speaker_fact_cache where cache_key = ?",
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
                "insert or replace into multi_speaker_fact_cache(cache_key, payload_json) values (?, ?)",
                (cache_key, encoded),
            )

    def _generate(self, *, speaker: str, source_text: str) -> dict[str, Any]:
        prompt = build_multi_speaker_fact_prompt(speaker=speaker, source_text=source_text)
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": MULTI_SPEAKER_FACT_SCHEMA,
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
            raise RuntimeError("multi-speaker extractor returned non-object JSON")
        return decoded

    def extract(
        self,
        *,
        speaker: str,
        source_text: str,
    ) -> tuple[MultiSpeakerFact, ...]:
        if not declarative_sentences(source_text):
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
        facts: list[MultiSpeakerFact] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            validated, rejection = validate_multi_speaker_fact_with_reason(
                item,
                speaker=speaker,
                source_text=source_text,
                ground_scope=self.ground_scope,
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


@dataclass
class OpenAIMultiSpeakerFactExtractor:
    """GPT-4o research extractor for the contract-vs-model probe.

    The production policy remains local-first. This adapter intentionally lives
    in the benchmark lane and holds the prompt, validator, and cache contract
    fixed while changing only the model provider.
    """

    model: str = "gpt-4o"
    timeout: float = 120.0
    ground_scope: str = "turn"
    temperature: float = 0.0
    max_tokens: int = 512
    client: Any | None = field(default=None, repr=False)
    calls: int = field(default=0, init=False)
    cache_hits: int = field(default=0, init=False)
    model_fact_items: int = field(default=0, init=False)
    validated_fact_items: int = field(default=0, init=False)
    rejection_counts: dict[str, int] = field(default_factory=dict, init=False)
    input_tokens: int = field(default=0, init=False)
    output_tokens: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.ground_scope not in {"sentence", "turn"}:
            raise ValueError(f"unknown ground_scope {self.ground_scope!r}")
        if not self.model.strip():
            raise ValueError("OpenAI multi-speaker model must be nonempty")
        if self.client is None:
            if not str(os.environ.get("OPENAI_API_KEY") or "").strip():
                raise RuntimeError("OPENAI_API_KEY is required for the GPT-4o probe")
            from openai import OpenAI

            self.client = OpenAI(timeout=self.timeout, max_retries=6)

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "openai-multi-speaker-grounded-probe",
            "provider": "openai",
            "model": self.model,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "prompt_version": _PROMPT_VERSION,
            "prompt_fingerprint": multi_speaker_fact_prompt_fingerprint(),
            "schema": MULTI_SPEAKER_FACT_SCHEMA,
            "ground_scope": self.ground_scope,
            "response_format": "json_object",
            "safety_version": "multi-speaker-grounding/1",
        }

    def validate_for_derived_facts(self) -> None:
        if not self.model.startswith("gpt-4o"):
            raise ValueError(
                "the approved cloud probe requires a GPT-4o-family model"
            )
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured")

    def _generate(self, *, speaker: str, source_text: str) -> dict[str, Any]:
        assert self.client is not None
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": build_multi_speaker_fact_prompt(
                        speaker=speaker,
                        source_text=source_text,
                    ),
                }
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        self.calls += 1
        usage = getattr(response, "usage", None)
        self.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("GPT-4o multi-speaker extractor returned empty output")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise RuntimeError("GPT-4o multi-speaker extractor returned non-object JSON")
        return payload

    def extract(
        self,
        *,
        speaker: str,
        source_text: str,
    ) -> tuple[MultiSpeakerFact, ...]:
        if not declarative_sentences(source_text):
            return ()
        payload = self._generate(speaker=speaker, source_text=source_text)
        raw_items = payload.get("facts", [])
        if not isinstance(raw_items, list):
            raw_items = []
        self.model_fact_items += len(raw_items)
        facts: list[MultiSpeakerFact] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            validated, rejection = validate_multi_speaker_fact_with_reason(
                item,
                speaker=speaker,
                source_text=source_text,
                ground_scope=self.ground_scope,
            )
            if validated is None:
                reason = rejection or "unknown"
                self.rejection_counts[reason] = (
                    self.rejection_counts.get(reason, 0) + 1
                )
                continue
            self.validated_fact_items += 1
            key = (_normalized(validated.fact), validated.evidence_sentence)
            if key not in seen:
                seen.add(key)
                facts.append(validated)
        return tuple(facts)

    def extract_sentence_facts(
        self,
        text: str,
        *,
        speaker: str,
    ) -> tuple[MultiSpeakerFact, ...]:
        return self.extract(speaker=speaker, source_text=text)


class Similarity(Protocol):
    def cos(self, a: str, b: str) -> float: ...


# Compared to sentence-grounded-clm/1's frozen 51/63 reach on this same set.
_SENTENCE_GROUNDED_REACH = 51
_MIN_REACHED_MISSES = 30
_MIN_BINDING_PRECISION = 0.90
_MIN_THIRD_PERSON_GAIN = 1
_MIN_CLOSURE_CASES = 15
_MIN_MEAN_CLOSURE = 0.02


def summarize_record(
    payload: dict[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
    *,
    extractor: MultiSpeakerFactExtractor,
    embedder: Similarity,
    categories: frozenset[int] = frozenset({1, 3}),
    limit: int | None = None,
) -> dict[str, Any]:
    """Measure the broadened contract over stored matched-run misses."""

    misses = [
        evaluation
        for evaluation in payload.get("evaluations", [])
        if int(evaluation.get("category") or 0) in categories
        and float(
            (evaluation.get("cutoff_results") or {}).get("top_200", {}).get("score") or 0.0
        )
        < 1.0
    ]
    if limit is not None:
        misses = misses[:limit]

    totals = {
        "misses": len(misses),
        "candidate_misses": 0,
        "model_fact_items": 0,
        "validated_fact_items": 0,
        "misses_with_fact": 0,
        "misses_reached_third_person_only": 0,
        "misses_fact_beats_raw_gold": 0,
    }
    cases: list[dict[str, Any]] = []
    turn_cache: dict[tuple[int, str], tuple[MultiSpeakerFact, ...]] = {}
    closure_deltas: list[float] = []

    for evaluation in misses:
        conv_idx = int(evaluation.get("conversation_idx") or 0)
        turns = turn_index[conv_idx] if 0 <= conv_idx < len(turn_index) else {}
        query = str((evaluation.get("retrieval") or {}).get("search_query") or "")
        raw_scores: list[float] = []
        fact_scores: list[float] = []
        case_fact_count = 0
        candidate_turns = 0
        reached_via_first_person = False
        reached_via_third_person = False

        for dia_id in evaluation.get("evidence") or []:
            turn = turns.get(str(dia_id))
            if turn is None:
                continue
            if query:
                raw_scores.append(embedder.cos(query, turn["envelope"]))
            if not declarative_sentences(turn["text"]):
                continue
            candidate_turns += 1
            turn_is_first_person = bool(first_person_declarative_sentences(turn["text"]))
            cache_key = (conv_idx, str(dia_id))
            facts = turn_cache.get(cache_key)
            if facts is None:
                facts = extractor.extract(speaker=turn["speaker"], source_text=turn["text"])
                turn_cache[cache_key] = facts
            case_fact_count += len(facts)
            if facts:
                if turn_is_first_person:
                    reached_via_first_person = True
                else:
                    reached_via_third_person = True
            for fact in facts:
                if query:
                    fact_scores.append(embedder.cos(query, fact.fact))

        if candidate_turns:
            totals["candidate_misses"] += 1
        if case_fact_count:
            totals["misses_with_fact"] += 1
        # Reached, and every reaching turn was third-person: the upside the live
        # first-person contract structurally cannot capture.
        if reached_via_third_person and not reached_via_first_person:
            totals["misses_reached_third_person_only"] += 1

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
                "facts": case_fact_count,
                "reached_third_person_only": bool(
                    reached_via_third_person and not reached_via_first_person
                ),
                "best_raw_gold_cos": round(best_raw, 4) if best_raw is not None else None,
                "best_fact_cos": round(best_fact, 4) if best_fact is not None else None,
                "wording_closure_delta": round(delta, 4) if delta is not None else None,
            }
        )

    totals["validated_fact_items"] = extractor.validated_fact_items
    totals["model_fact_items"] = extractor.model_fact_items
    precision = (
        extractor.validated_fact_items / extractor.model_fact_items
        if extractor.model_fact_items
        else None
    )
    mean_closure = sum(closure_deltas) / len(closure_deltas) if closure_deltas else None
    gates = {
        "reached_misses": totals["misses_with_fact"] >= _MIN_REACHED_MISSES,
        "binding_precision": precision is not None and precision >= _MIN_BINDING_PRECISION,
        "third_person_gain": totals["misses_reached_third_person_only"] >= _MIN_THIRD_PERSON_GAIN,
        "closure_cases": totals["misses_fact_beats_raw_gold"] >= _MIN_CLOSURE_CASES,
        "mean_closure": mean_closure is not None and mean_closure >= _MIN_MEAN_CLOSURE,
    }
    return {
        "dry_run": True,
        "paid_provider_calls": 0,
        "preflight": _PROMPT_VERSION,
        "ground_scope": getattr(extractor, "ground_scope", "sentence"),
        "sentence_grounded_reach_baseline": _SENTENCE_GROUNDED_REACH,
        "categories": sorted(categories),
        "limit": limit,
        "thresholds": {
            "min_reached_misses": _MIN_REACHED_MISSES,
            "min_binding_precision": _MIN_BINDING_PRECISION,
            "min_third_person_gain": _MIN_THIRD_PERSON_GAIN,
            "min_closure_cases": _MIN_CLOSURE_CASES,
            "min_mean_wording_closure_delta": _MIN_MEAN_CLOSURE,
        },
        "totals": totals,
        "reach_delta_vs_sentence_grounded": totals["misses_with_fact"] - _SENTENCE_GROUNDED_REACH,
        "binding_precision": round(precision, 4) if precision is not None else None,
        "mean_wording_closure_delta": round(mean_closure, 4) if mean_closure is not None else None,
        "unique_candidate_turns": len(turn_cache),
        "ollama_generation_calls": extractor.calls,
        "ollama_cache_hits": extractor.cache_hits,
        "rejection_counts": dict(sorted(extractor.rejection_counts.items())),
        "gates": gates,
        "gate_passed": all(gates.values()),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free multi-speaker-grounded fact coverage and closure gate"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness matched JSON artifact")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--categories", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default="qwen2.5-7b-1m:latest")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--ground-scope",
        choices=("sentence", "turn"),
        default="sentence",
        help="proper-noun grounding scope: cited sentence (strict) or whole turn",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("test_seam/mem0/multi-speaker-preflight.sqlite3"),
    )
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    with args.record.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    with args.dataset.open(encoding="utf-8") as handle:
        dataset = json.load(handle)

    extractor = OllamaMultiSpeakerFactExtractor(
        model=args.model,
        host=args.host,
        timeout=float(os.environ.get("SEAM_OLLAMA_TIMEOUT_S", "600")),
        cache_path=args.cache,
        ground_scope=args.ground_scope,
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
