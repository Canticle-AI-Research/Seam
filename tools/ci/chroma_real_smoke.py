from __future__ import annotations

import json
import tempfile
from pathlib import Path

from seam import SeamRuntime
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.retrieval_orchestrator import ChromaSemanticAdapter
from seam_runtime.retrieval_orchestrator.planner import build_plan


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="seam-chroma-smoke-") as tmp:
        root = Path(tmp)
        runtime = SeamRuntime(root / "seam.db", embedding_model=HashEmbeddingModel())
        batch = runtime.compile_nl(
            "SEAM real Chroma smoke indexes durable memory retrieval workflows.",
            source_ref="ci://chroma-real-smoke",
            ns="ci.smoke",
            scope="thread",
        )
        runtime.persist_ir(batch)

        adapter = ChromaSemanticAdapter(
            runtime.store,
            runtime.embedding_model,
            persist_directory=str(root / "chroma"),
            collection_name="seam_ci_smoke",
        )
        indexed = adapter.sync_records()
        hits = adapter.search(build_plan("durable memory retrieval workflows", scope="thread"), limit=3)

        payload = {
            "status": "PASS" if indexed > 0 and hits else "FAIL",
            "indexed": indexed,
            "hit_ids": [hit.record.id for hit in hits],
            "legs": [hit.leg for hit in hits],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
