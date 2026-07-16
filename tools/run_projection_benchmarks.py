"""
Run the projection benchmark with both HashEmbedding and SentenceTransformer models,
persist results to the DB, and export JSON bundles to benchmarks/runs/.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seam_runtime.evals import run_retrieval_benchmark
from seam_runtime.models import HashEmbeddingModel, SentenceTransformerModel

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmarks", "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

def run_and_save(model, label):
    print(f"\n{'='*60}")
    print(f"  Running: {model.name}")
    print(f"{'='*60}\n")

    result = run_retrieval_benchmark(embedding_model=model)
    tracks = result["summary"]["tracks"]

    # Print table
    header = f"{'Track':<25s}  {'hit_rate':>8s}  {'mrr':>8s}  {'recall@k':>8s}"
    print(header)
    print("-" * len(header))
    for name, data in tracks.items():
        print(f"{name:<25s}  {data['hit_rate']:8.3f}  {data['mrr']:8.3f}  {data['recall_at_k']:8.3f}")

    # Per-fixture
    print("\nPer-fixture:")
    for fix in result["fixtures"]:
        print(f"\n  {fix['name']} ({fix['category']})")
        for tname in ("raw", "vector", "mirl", "hybrid", "machine_nat_query", "machine_vector", "machine_hybrid"):
            t = fix["tracks"][tname]
            marker = "[+]" if t["hit"] else "[-]"
            print(f"    {marker} {tname:<25s}  recall@k={t['recall_at_k']:.3f}  mrr={t['reciprocal_rank']:.3f}")

    # Save bundle
    bundle = {
        "timestamp": timestamp,
        "model_name": model.name,
        "model_dimension": model.dimension,
        "summary": result["summary"],
        "fixtures": result["fixtures"],
    }
    filename = f"{timestamp}_{label}_projection.json"
    filepath = os.path.join(RUNS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    print(f"\n  -> Saved: benchmarks/runs/{filename}")
    return result


# --- Run both models ---
hash_result = run_and_save(HashEmbeddingModel(), "hash")
sbert_result = run_and_save(SentenceTransformerModel(), "sbert")

# --- Side-by-side comparison ---
print(f"\n{'='*70}")
print("  SIDE-BY-SIDE: Hash vs SBERT")
print(f"{'='*70}\n")

all_tracks = ("raw", "vector", "mirl", "hybrid", "machine_nat_query", "machine_vector", "machine_hybrid")
header = f"{'Track':<25s}  {'Hash recall':>12s}  {'SBERT recall':>13s}  {'Delta':>8s}"
print(header)
print("-" * len(header))
for track in all_tracks:
    h = hash_result["summary"]["tracks"][track]["recall_at_k"]
    s = sbert_result["summary"]["tracks"][track]["recall_at_k"]
    delta = s - h
    delta_str = f"+{delta:.3f}" if delta > 0 else f"{delta:.3f}" if delta < 0 else "  =  "
    print(f"{track:<25s}  {h:12.3f}  {s:13.3f}  {delta_str:>8s}")

print("\nAll bundles saved to: benchmarks/runs/")
