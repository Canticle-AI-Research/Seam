"""SEAM as a drop-in Mem0-OSS memory server for mem0ai/memory-benchmarks.

The mem0 benchmark harness (``mem0ai/memory-benchmarks``) is hardwired to Mem0:
its OSS backend is an HTTP client (``benchmarks/common/mem0_client.py``) that
talks to a Mem0 server over three REST endpoints. This module implements those
three endpoints on top of the real SEAM retrieval path, so the harness runs
UNMODIFIED against SEAM:

    python -m benchmarks.locomo.run --project-name seam --backend oss \\
        --mem0-host http://localhost:8900

Contract (from the harness's own client, pinned 2026-07-15):

    POST /memories   {messages:[{role,content}], user_id, timestamp?}
                     -> {"results": [ ... ]}
    POST /search     {query, user_id, limit}
                     -> {"results": [{memory, score, id, created_at}]}
    DELETE /memories ?user_id=<id>            (also accepts JSON body)
                     -> {"message": ...}

Design: one SEAM namespace per ``user_id`` (``locomo:<user_id>``), reusing
``SeamLocomoAdapter``'s exact ingest path so the memory under test is byte-for-
byte the SEAM the in-harness benchmarks measure. Retrieval returns the ranked
RAW turn strings (``[Speaker timestamp] text``) as individual ``memory`` items
— the shape the harness's ``format_search_results`` + answerer expect — rather
than SEAM's joined answer context.

This is a fair-comparison FACADE, not new memory behavior: it changes no
retrieval logic and honors ``RetrievalFlags`` from the environment (so the
validated conversation/temporal/profile stack applies exactly as in-harness).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter


def _epoch_to_iso(timestamp: int | None) -> str:
    """Mem0's client sends observation dates as a unix epoch. SEAM turns want an
    ISO string for relative-date grounding; fall back to empty when absent."""
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return ""


def _split_speaker(content: str) -> tuple[str, str]:
    """Mem0 chunks a turn as ``"Speaker: text"``. Recover (speaker, text) so the
    SEAM turn carries the same ``[Speaker ts] text`` shape as the native adapter.
    Falls back to a generic speaker when the colon convention is absent."""
    if ": " in content:
        speaker, text = content.split(": ", 1)
        if speaker and len(speaker) <= 64 and "\n" not in speaker:
            return speaker, text
    return "user", content


class SeamMem0Server:
    """Maps the three Mem0-OSS endpoints onto one shared ``SeamLocomoAdapter``.

    ``answerer=None``: the harness generates and judges its own answers; this
    server only supplies retrieved memories. All retrieval config comes from the
    environment (``SEAM_RETRIEVAL_*`` / ``SEAM_CONVERSATION_ADAPTER`` / etc.) via
    the adapter, so the exact validated stack is reproducible here.
    """

    def __init__(self, *, db_path: str | None = None, search_top_k: int = 100,
                 context_budget: int = 8000):
        self._adapter = SeamLocomoAdapter(
            db_path=db_path,
            answerer=None,
            search_top_k=search_top_k,
            budget=context_budget,
        )
        self._seen_users: set[str] = set()

    # -- endpoint handlers (pure dict-in/dict-out; framework-agnostic) ------

    def add(self, payload: dict) -> dict:
        user_id = payload.get("user_id")
        messages = payload.get("messages") or []
        if not user_id or not isinstance(messages, list):
            raise ValueError("add requires user_id and a messages list")
        iso = _epoch_to_iso(payload.get("timestamp"))
        if user_id not in self._seen_users:
            self._adapter.reset(user_id)
            self._seen_users.add(user_id)
        added = 0
        for msg in messages:
            content = (msg or {}).get("content") or ""
            if not content.strip():
                continue
            speaker, text = _split_speaker(content)
            self._adapter.ingest_turn(
                user_id,
                ConversationTurn(speaker=speaker, text=text, timestamp=iso),
            )
            added += 1
        # Mem0 returns the extracted-memory list; the harness only needs a
        # well-formed envelope, so report the count of ingested turns.
        return {"results": [{"event": "ADD"} for _ in range(added)]}

    def search(self, payload: dict) -> dict:
        user_id = payload.get("user_id")
        query = payload.get("query") or ""
        limit = int(payload.get("limit") or payload.get("top_k") or 100)
        if not user_id or not query.strip():
            raise ValueError("search requires user_id and query")
        results = self._retrieve(user_id, query, limit)
        return {"results": results}

    def delete_user(self, user_id: str) -> dict:
        if not user_id:
            raise ValueError("delete requires user_id")
        try:
            self._adapter.reset(user_id)
        finally:
            self._seen_users.discard(user_id)
        return {"message": f"deleted memories for {user_id}"}

    # -- retrieval ---------------------------------------------------------

    def _retrieve(self, user_id: str, query: str, limit: int) -> list[dict]:
        """Return ranked RAW turn memories as Mem0-shaped result dicts.

        Uses the adapter's per-scope runtime + the same ``search_ir`` call the
        native benchmark uses, then maps each ranked candidate's closure to its
        RAW content so the harness sees individual memory strings (not SEAM's
        joined answer blob)."""
        rt = self._adapter._runtime(user_id)
        ns = f"locomo:{user_id}"
        result = rt.search_ir(query, scope="thread", budget=limit, include_raw=True, ns=ns)
        out: list[dict] = []
        seen_content: set[str] = set()
        for cand in result.candidates:
            ids = self._adapter._collect_closure_ids_public(cand) \
                if hasattr(self._adapter, "_collect_closure_ids_public") \
                else _closure_ids(cand)
            batch = rt.store.load_ir(ids=ids)
            for record in batch.records:
                if record.kind.value != "RAW":
                    continue
                content = record.attrs.get("content")
                if not isinstance(content, str) or not content or content in seen_content:
                    continue
                seen_content.add(content)
                out.append({
                    "memory": content,
                    "score": float(getattr(cand, "score", 0.0)),
                    "id": record.id,
                    "created_at": _created_at(record),
                })
                if len(out) >= limit:
                    return out
        return out

    def close(self) -> None:
        self._adapter.close()


def _closure_ids(candidate) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(rid: str) -> None:
        if rid and rid not in seen:
            seen.add(rid)
            ids.append(rid)

    add(candidate.record.id)
    for rid in candidate.record.evidence or []:
        add(rid)
    for rid in candidate.record.prov or []:
        add(rid)
    return ids


def _created_at(record) -> str:
    """Prefer an explicit turn timestamp; the RAW content also carries the date
    inline (``[Speaker ts] text``), so an empty value never loses temporal info."""
    for key in ("timestamp", "observed_at", "valid_at"):
        val = record.attrs.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def build_asgi_app(server: SeamMem0Server):
    """Wrap a SeamMem0Server in a FastAPI app exposing the Mem0-OSS routes.

    Bodies are typed as ``dict`` (not a Pydantic model) so the app accepts the
    harness's exact JSON payloads verbatim without a schema to drift from.
    """
    from typing import Any

    from fastapi import Body, FastAPI

    app = FastAPI(title="SEAM Mem0-OSS facade")

    @app.post("/memories")
    async def add_memories(payload: dict[str, Any] = Body(...)):
        return server.add(payload)

    @app.post("/search")
    async def search_memories(payload: dict[str, Any] = Body(...)):
        return server.search(payload)

    @app.delete("/memories")
    async def delete_memories(
        user_id: str | None = None,
        payload: dict[str, Any] | None = Body(default=None),
    ):
        uid = user_id or ((payload or {}).get("user_id"))
        return server.delete_user(uid)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="SEAM as a Mem0-OSS memory server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--search-top-k", type=int, default=100)
    parser.add_argument("--context-budget", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    server = SeamMem0Server(
        db_path=args.db_path,
        search_top_k=args.search_top_k,
        context_budget=args.context_budget,
    )
    uvicorn.run(build_asgi_app(server), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
