from __future__ import annotations

import os
import shutil
import tempfile
import time
import threading

from benchmarks.external.common.provider_retry import provider_retry
from benchmarks.external.common.types import AdapterAnswer, ConversationTurn


_INGEST_PACE_LOCK = threading.Lock()
_LAST_INGEST_AT = 0.0


class Mem0LocomoAdapter:
    """Mem0 (mem0ai) comparator adapter for LoCoMo.

    One Mem0 ``user_id`` per scope_id. Conversation turns are added as
    user/assistant messages with metadata. ``answer`` runs Mem0 search and
    returns the joined retrieved memories as ``retrieved_context``.

    Like the SEAM adapter, this adapter does NOT generate an answer;
    LLM-judge scoring is layered separately.
    """

    name = "mem0"

    def __init__(
        self,
        *,
        search_limit: int | None = None,
        config_overrides: dict | None = None,
        _memory: object | None = None,
    ):
        self.search_limit = _resolve_search_limit(search_limit)

        if _memory is not None:
            self._memory = _memory
            self._store_dir = None
            self._seen_user_ids: set[str] = set()
            self._pace_real_ingest = False
            return

        try:
            from mem0 import Memory
        except ImportError as exc:
            raise RuntimeError(
                "--adapter mem0 requires the mem0ai package. "
                "Install with: pip install seam[bench-mem0]"
            ) from exc

        if not os.environ.get("OPENAI_API_KEY") and not (config_overrides or {}).get(
            "llm"
        ):
            raise RuntimeError(
                "Mem0 requires an LLM provider. Set OPENAI_API_KEY or pass config_overrides."
            )

        self._store_dir = tempfile.mkdtemp(prefix="seam-bench-mem0-")
        config = self._build_config(self._store_dir, config_overrides)
        self._memory = Memory.from_config(config)
        self._seen_user_ids: set[str] = set()
        self._pace_real_ingest = True

    @staticmethod
    def _build_config(store_dir: str, overrides: dict | None) -> dict:
        cfg = {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": os.environ.get("SEAM_BENCH_MEM0_LLM_MODEL", "gpt-4o-mini"),
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "path": store_dir,
                    "collection_name": "seam_bench_mem0",
                },
            },
        }
        if overrides:
            cfg.update(overrides)
        return cfg

    # -- Protocol methods -------------------------------------------------

    def reset(self, scope_id: str) -> None:
        try:
            self._memory.delete_all(user_id=scope_id)
        except Exception:
            pass
        self._seen_user_ids.add(scope_id)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        role = (
            "user"
            if turn.speaker.lower().startswith(("speaker_a", "alice", "user"))
            else "assistant"
        )
        ts = turn.timestamp or ""
        prefix = f"[{turn.speaker} {ts}] ".rstrip() + " " if ts else f"[{turn.speaker}] "
        messages = [{"role": role, "content": prefix + turn.text}]
        self._pace_ingest()
        provider_retry(
            lambda: self._memory.add(messages, user_id=scope_id),
            label="mem0.add",
        )

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        t0 = time.perf_counter()
        # mem0 2.x: user_id moved into filters, and limit was renamed top_k.
        results = provider_retry(
            lambda: self._memory.search(
                query=question, filters={"user_id": scope_id}, top_k=self.search_limit
            ),
            label="mem0.search",
        )
        retrieval_ms = (time.perf_counter() - t0) * 1000.0
        items = (
            results.get("results", results)
            if isinstance(results, dict)
            else results
        )
        joined = "\n".join(
            item.get("memory", "") if isinstance(item, dict) else str(item)
            for item in items
        )
        return AdapterAnswer(
            retrieved_context=joined,
            generated_answer=None,
            retrieval_latency_ms=retrieval_ms,
            answer_latency_ms=0.0,
        )

    def close(self) -> None:
        if self._store_dir is not None:
            shutil.rmtree(self._store_dir, ignore_errors=True)

    def _pace_ingest(self) -> None:
        if not self._pace_real_ingest:
            return
        interval = float(os.environ.get("SEAM_BENCH_MEM0_INGEST_MIN_INTERVAL_SECONDS", "0.75"))
        if interval <= 0:
            return
        global _LAST_INGEST_AT
        with _INGEST_PACE_LOCK:
            now = time.monotonic()
            wait = interval - (now - _LAST_INGEST_AT)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            _LAST_INGEST_AT = now


def _resolve_search_limit(search_limit: int | None) -> int:
    if search_limit is not None:
        return max(1, int(search_limit))
    value = os.environ.get("SEAM_BENCH_MEM0_SEARCH_LIMIT")
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            pass
    return 8
