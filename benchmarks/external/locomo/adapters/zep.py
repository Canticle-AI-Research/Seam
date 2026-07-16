from __future__ import annotations

import os
import threading
import time

from benchmarks.external.common.provider_retry import provider_retry
from benchmarks.external.common.types import AdapterAnswer, ConversationTurn

_INGEST_PACE_LOCK = threading.Lock()
_LAST_INGEST_AT = 0.0


class ZepLocomoAdapter:
    """Zep (Graphiti) comparator adapter for LoCoMo, using the v3 SDK API.

    zep-cloud >= 3.x removed the legacy ``client.memory`` session API this
    adapter was originally written against; the v3 surface is ``user`` /
    ``thread`` / ``graph``. One Zep ``user_id`` + one ``thread_id`` per
    scope_id. Conversation turns are added as thread messages; ``answer``
    runs ``graph.search`` over the user's knowledge graph (edge facts plus
    entity summaries) and returns them joined as ``retrieved_context``.

    Like the SEAM and Mem0 adapters, this adapter does NOT generate an answer;
    LLM-judge scoring is layered separately.

    Zep ingestion is asynchronous on the server side (graph extraction runs in
    a background job), so a naive ``add then immediately search`` can return
    zero hits. The first ``answer`` call for a scope therefore blocks until
    every ingested episode reports ``processed`` (or raises after
    ``SEAM_BENCH_ZEP_PROCESSING_TIMEOUT_SECONDS``, default 1800) -- failing
    loudly instead of silently benchmarking an empty graph.
    """

    name = "zep"

    def __init__(
        self,
        *,
        search_limit: int = 8,
        _client: object | None = None,
    ):
        self.search_limit = search_limit
        self._threads: dict[str, str] = {}
        self._pending: dict[str, int] = {}
        self._settled: set[str] = set()

        if _client is not None:
            self._client = _client
            self._is_stub = True
            return

        self._is_stub = False
        try:
            from zep_cloud.client import Zep
        except ImportError as exc:
            raise RuntimeError(
                "--adapter zep requires the zep-cloud package (v3+). "
                "Install with: pip install seam[bench-zep]"
            ) from exc

        api_key = os.environ.get("ZEP_API_KEY")
        base_url = os.environ.get("ZEP_API_URL")
        if not api_key and not base_url:
            raise RuntimeError(
                "Zep requires ZEP_API_KEY (Zep Cloud) or ZEP_API_URL "
                "(self-hosted, API-compatible) in the environment."
            )
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Zep(**kwargs)

    # -- Protocol methods -------------------------------------------------

    def reset(self, scope_id: str) -> None:
        user_id = _user_id(scope_id)
        thread_id = f"{user_id}-thread"
        try:
            self._client.user.delete(user_id=user_id)
        except Exception:
            pass
        provider_retry(
            lambda: self._client.user.add(user_id=user_id), label="zep.user.add"
        )
        provider_retry(
            lambda: self._client.thread.create(thread_id=thread_id, user_id=user_id),
            label="zep.thread.create",
        )
        self._threads[scope_id] = thread_id
        self._pending[scope_id] = 0
        self._settled.discard(scope_id)

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        thread_id = self._threads[scope_id]
        role = (
            "user"
            if turn.speaker.lower().startswith(("speaker_a", "alice", "user"))
            else "assistant"
        )
        ts = turn.timestamp or ""
        prefix = f"[{turn.speaker} {ts}] ".rstrip() + " " if ts else f"[{turn.speaker}] "
        message = self._build_message(
            role=role, name=turn.speaker, content=prefix + turn.text
        )
        self._pace_ingest()
        provider_retry(
            lambda: self._client.thread.add_messages(thread_id, messages=[message]),
            label="zep.thread.add_messages",
        )
        self._pending[scope_id] = self._pending.get(scope_id, 0) + 1
        self._settled.discard(scope_id)

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        user_id = _user_id(scope_id)
        self._await_processing(scope_id, user_id)

        t0 = time.perf_counter()
        edge_results = provider_retry(
            lambda: self._client.graph.search(
                query=question,
                user_id=user_id,
                scope="edges",
                limit=self.search_limit,
            ),
            label="zep.graph.search.edges",
        )
        node_results = provider_retry(
            lambda: self._client.graph.search(
                query=question,
                user_id=user_id,
                scope="nodes",
                limit=max(1, self.search_limit // 2),
            ),
            label="zep.graph.search.nodes",
        )
        retrieval_ms = (time.perf_counter() - t0) * 1000.0

        lines: list[str] = []
        for edge in getattr(edge_results, "edges", None) or []:
            fact = getattr(edge, "fact", None)
            if not fact:
                continue
            valid_at = getattr(edge, "valid_at", None)
            invalid_at = getattr(edge, "invalid_at", None)
            dates = ""
            if valid_at or invalid_at:
                dates = f" (valid: {valid_at or '?'} - {invalid_at or 'present'})"
            lines.append(f"{fact}{dates}")
        for node in getattr(node_results, "nodes", None) or []:
            name = getattr(node, "name", None)
            summary = getattr(node, "summary", None)
            if name and summary:
                lines.append(f"{name}: {summary}")

        return AdapterAnswer(
            retrieved_context="\n".join(lines),
            generated_answer=None,
            retrieval_latency_ms=retrieval_ms,
            answer_latency_ms=0.0,
        )

    def close(self) -> None:
        if not self._is_stub:
            for scope_id in list(self._threads.keys()):
                try:
                    self._client.user.delete(user_id=_user_id(scope_id))
                except Exception:
                    pass
        self._threads.clear()
        self._pending.clear()
        self._settled.clear()

    # -- Internals ---------------------------------------------------------

    @staticmethod
    def _build_message(*, role: str, name: str, content: str):
        try:
            from zep_cloud.types.message import Message

            return Message(role=role, name=name, content=content)
        except ImportError:
            # Stub/test path without the SDK installed.
            return {"role": role, "name": name, "content": content}

    def _await_processing(self, scope_id: str, user_id: str) -> None:
        """Block until every episode ingested for this scope is processed.

        Zep's graph extraction is an async server-side job; searching before it
        finishes measures an empty graph, not Zep. Polls ``processed`` on the
        scope's episodes and fails loudly on timeout rather than proceeding.
        """
        if scope_id in self._settled:
            return
        count = self._pending.get(scope_id, 0)
        if count <= 0:
            self._settled.add(scope_id)
            return
        timeout = float(
            os.environ.get("SEAM_BENCH_ZEP_PROCESSING_TIMEOUT_SECONDS", "1800")
        )
        interval = float(
            os.environ.get("SEAM_BENCH_ZEP_PROCESSING_POLL_SECONDS", "5")
        )
        deadline = time.monotonic() + timeout
        while True:
            response = provider_retry(
                lambda: self._client.graph.episode.get_by_user_id(
                    user_id, lastn=count
                ),
                label="zep.episode.get_by_user_id",
            )
            episodes = getattr(response, "episodes", None) or []
            if episodes and all(
                getattr(e, "processed", False) for e in episodes
            ):
                self._settled.add(scope_id)
                return
            if time.monotonic() >= deadline:
                unprocessed = sum(
                    1 for e in episodes if not getattr(e, "processed", False)
                )
                raise RuntimeError(
                    f"Zep did not finish processing scope {scope_id!r} within "
                    f"{timeout:.0f}s ({unprocessed}/{len(episodes)} episodes "
                    "unprocessed); refusing to benchmark an incomplete graph. "
                    "Raise SEAM_BENCH_ZEP_PROCESSING_TIMEOUT_SECONDS if the "
                    "server is just slow."
                )
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def _pace_ingest(self) -> None:
        if self._is_stub:
            return
        interval = float(
            os.environ.get("SEAM_BENCH_ZEP_INGEST_MIN_INTERVAL_SECONDS", "0.25")
        )
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


def _user_id(scope_id: str) -> str:
    return f"seam-bench-{scope_id}"
