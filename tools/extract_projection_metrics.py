"""Extract and display the projection comparison metrics from the retrieval benchmark."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seam_runtime.evals import run_retrieval_benchmark
from seam_runtime.models import HashEmbeddingModel

result = run_retrieval_benchmark(embedding_model=HashEmbeddingModel())
tracks = result["summary"]["tracks"]

print("=== PROJECTION COMPARISON (Aggregated) ===")
print()
header = f"{'Track':<25s}  {'hit_rate':>8s}  {'mrr':>8s}  {'recall@k':>8s}"
print(header)
print("-" * len(header))
for name, data in tracks.items():
    print(f"{name:<25s}  {data['hit_rate']:8.3f}  {data['mrr']:8.3f}  {data['recall_at_k']:8.3f}")

print()
print("=== PER-FIXTURE BREAKDOWN ===")
for fix in result["fixtures"]:
    print(f"\n--- {fix['name']} (category={fix['category']}) ---")
    for tname in ("raw", "vector", "mirl", "hybrid", "machine_nat_query", "machine_vector", "machine_hybrid"):
        t = fix["tracks"][tname]
        print(f"  {tname:<25s}  hit={str(t['hit']):<5s}  recall@k={t['recall_at_k']:.3f}  mrr={t['reciprocal_rank']:.3f}")
