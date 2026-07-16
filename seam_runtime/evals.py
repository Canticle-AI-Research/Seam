from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dsl import compile_dsl
from .lossless import compress_text_lossless
from .models import EmbeddingModel, HashEmbeddingModel, cosine
from .pack import pack_records, score_pack
from .retrieval import raw_search, search_batch
from .vector import INDEXABLE_KINDS, SQLiteVectorIndex

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "docs" / "retrieval_gold_fixtures.json"


@dataclass(frozen=True)
class RetrievalFixture:
    name: str
    category: str
    format: str
    source: str
    query: str
    expected_ids: list[str]
    budget: int = 5
    pack_budget: int = 512


def default_retrieval_fixtures(path: str | Path | None = None) -> list[RetrievalFixture]:
    fixture_path = Path(path) if path is not None else FIXTURE_PATH
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        RetrievalFixture(
            name=item["name"],
            category=item["category"],
            format=item.get("format", "dsl"),
            source=item["source"],
            query=item["query"],
            expected_ids=list(item["expected_ids"]),
            budget=int(item.get("budget", 5)),
            pack_budget=int(item.get("pack_budget", 512)),
        )
        for item in payload
    ]


def run_retrieval_benchmark(fixtures: list[RetrievalFixture] | None = None, embedding_model: EmbeddingModel | None = None) -> dict[str, Any]:
    fixtures = fixtures or default_retrieval_fixtures()
    model = embedding_model or HashEmbeddingModel()
    results: list[dict[str, Any]] = []

    for fixture in fixtures:
        batch = _compile_fixture_batch(fixture)
        namespace = batch.records[0].ns if batch.records else None
        
        # Prepare natural and machine texts for records
        natural_texts = {}
        machine_texts = {}
        for record in batch.records:
            if record.kind in INDEXABLE_KINDS:
                nat = SQLiteVectorIndex.render_record_text(record)
                natural_texts[record.id] = nat
                machine_texts[record.id] = compress_text_lossless(nat).machine_text
                
        mac_query = compress_text_lossless(fixture.query).machine_text

        nat_scores = _vector_scores(batch.records, fixture.query, model, natural_texts)
        mac_doc_nat_query_scores = _vector_scores(batch.records, fixture.query, model, machine_texts)
        mac_scores = _vector_scores(batch.records, mac_query, model, machine_texts)

        raw_candidates = raw_search(batch.records, fixture.query, limit=fixture.budget).candidates
        mirl_candidates = search_batch(batch, fixture.query, limit=fixture.budget, vector_scores={}, namespace=namespace).candidates
        hybrid_candidates = search_batch(batch, fixture.query, limit=fixture.budget, vector_scores=nat_scores, namespace=namespace).candidates
        mac_hybrid_candidates = search_batch(batch, fixture.query, limit=fixture.budget, vector_scores=mac_scores, namespace=namespace).candidates
        vector_ranked_ids = _rank_vector_only(nat_scores, limit=fixture.budget)
        mac_nat_q_ranked_ids = _rank_vector_only(mac_doc_nat_query_scores, limit=fixture.budget)
        mac_ranked_ids = _rank_vector_only(mac_scores, limit=fixture.budget)

        packs = {}
        for mode in ("exact", "context", "narrative"):
            pack = pack_records(batch.records, lens=fixture.category, budget=fixture.pack_budget, mode=mode, namespace=namespace)
            packs[mode] = score_pack(pack, batch.records)

        results.append(
            {
                "name": fixture.name,
                "category": fixture.category,
                "query": fixture.query,
                "expected_ids": fixture.expected_ids,
                "tracks": {
                    "raw": _track_report([candidate.record.id for candidate in raw_candidates], fixture.expected_ids),
                    "vector": _track_report(vector_ranked_ids, fixture.expected_ids),
                    "mirl": _track_report([candidate.record.id for candidate in mirl_candidates], fixture.expected_ids),
                    "hybrid": _track_report([candidate.record.id for candidate in hybrid_candidates], fixture.expected_ids),
                    "machine_nat_query": _track_report(mac_nat_q_ranked_ids, fixture.expected_ids),
                    "machine_vector": _track_report(mac_ranked_ids, fixture.expected_ids),
                    "machine_hybrid": _track_report([candidate.record.id for candidate in mac_hybrid_candidates], fixture.expected_ids),
                },
                "packs": packs,
            }
        )

    return {
        "summary": {
            "fixture_count": len(results),
            "embedding_model": model.name,
            "tracks": {track: _aggregate_track(results, track) for track in ("raw", "vector", "mirl", "hybrid", "machine_nat_query", "machine_vector", "machine_hybrid")},
            "packs": {mode: _aggregate_pack(results, mode) for mode in ("exact", "context", "narrative")},
            "success_checks": {
                "mirl_beats_raw_on_fact_or_relation": any(_beats(result, "mirl", "raw") and result["category"] in {"fact", "relation"} for result in results),
                "hybrid_beats_vector_on_relation": any(_beats(result, "hybrid", "vector") and result["category"] == "relation" for result in results),
                "exact_packs_reversible": all(result["packs"]["exact"]["reversibility"] == 1.0 for result in results),
                "context_packs_traceable": all(result["packs"]["context"]["traceability"] >= 0.66 for result in results),
            },
        },
        "fixtures": results,
    }


def _compile_fixture_batch(fixture: RetrievalFixture):
    if fixture.format != "dsl":
        raise ValueError(f"Unsupported fixture format: {fixture.format}")
    return compile_dsl(fixture.source, scope="project")


def _vector_scores(records, query: str, model: EmbeddingModel, texts: dict[str, str]) -> dict[str, float]:
    query_vector = model.embed(query)
    scores: dict[str, float] = {}
    for record in records:
        if record.kind not in INDEXABLE_KINDS:
            continue
        text = texts.get(record.id)
        if not text:
            continue
        record_vector = model.embed(text)
        score = cosine(query_vector, record_vector)
        if score > 0:
            scores[record.id] = score
    return scores


def _rank_vector_only(scores: dict[str, float], limit: int) -> list[str]:
    return [record_id for record_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]]


def _track_report(ranked_ids: list[str], expected_ids: list[str]) -> dict[str, Any]:
    first_relevant_rank = next((index for index, record_id in enumerate(ranked_ids, start=1) if record_id in expected_ids), None)
    reciprocal_rank = 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
    relevant_hits = len([record_id for record_id in ranked_ids if record_id in expected_ids])
    recall_at_k = relevant_hits / max(len(expected_ids), 1)
    return {
        "ranked_ids": ranked_ids,
        "hit": first_relevant_rank is not None,
        "first_relevant_rank": first_relevant_rank,
        "relevant_hits": relevant_hits,
        "recall_at_k": round(recall_at_k, 6),
        "reciprocal_rank": round(reciprocal_rank, 6),
    }


def _aggregate_track(results: list[dict[str, Any]], track: str) -> dict[str, float]:
    if not results:
        return {"hit_rate": 0.0, "mrr": 0.0, "recall_at_k": 0.0}
    hits = [1.0 if item["tracks"][track]["hit"] else 0.0 for item in results]
    reciprocal_ranks = [item["tracks"][track]["reciprocal_rank"] for item in results]
    recall_scores = [item["tracks"][track]["recall_at_k"] for item in results]
    return {
        "hit_rate": round(sum(hits) / len(hits), 6),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 6),
        "recall_at_k": round(sum(recall_scores) / len(recall_scores), 6),
    }


def _aggregate_pack(results: list[dict[str, Any]], mode: str) -> dict[str, float]:
    if not results:
        return {"overall": 0.0, "compression_ratio": 0.0, "traceability": 0.0}
    overall = [item["packs"][mode]["overall"] for item in results]
    compression = [item["packs"][mode]["compression_ratio"] for item in results]
    traceability = [item["packs"][mode]["traceability"] for item in results]
    return {
        "overall": round(sum(overall) / len(overall), 6),
        "compression_ratio": round(sum(compression) / len(compression), 6),
        "traceability": round(sum(traceability) / len(traceability), 6),
    }


def _beats(result: dict[str, Any], winner: str, loser: str) -> bool:
    winner_track = result["tracks"][winner]
    loser_track = result["tracks"][loser]
    return (winner_track["recall_at_k"], winner_track["reciprocal_rank"]) > (loser_track["recall_at_k"], loser_track["reciprocal_rank"])
