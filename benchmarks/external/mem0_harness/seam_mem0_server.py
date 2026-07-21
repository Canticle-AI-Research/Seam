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
import os
from datetime import datetime, timezone

from benchmarks.external.common.types import ConversationTurn
from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
from seam_runtime.derived_fact_context import (
    DERIVED_FACTS_OFF,
    DERIVED_FACTS_POLICIES,
    MULTI_SPEAKER_GROUNDED_V1,
    DerivedFact,
    grounded_spans_match_source,
    is_eligible_derived_claim,
    resolve_derived_facts_policy,
    splice_derived_facts,
)
from seam_runtime.event_count_context import (
    CountEvidence,
    build_count_context_projection,
)
from seam_runtime.multi_scope_pack import (
    POLICIES as MULTI_SCOPE_POLICIES,
)
from seam_runtime.multi_scope_pack import (
    POLICY_OFF as MULTI_SCOPE_OFF,
)
from seam_runtime.multi_scope_pack import (
    POLICY_V1 as MULTI_SCOPE_V1,
)
from seam_runtime.multi_scope_pack import (
    compose_reserved_multi_scope,
    select_date_diverse_rows,
)
from seam_runtime.multi_scope_pack import (
    resolve_policy as resolve_multi_scope_policy,
)
from seam_runtime.retrieval_orchestrator.orchestrator import RetrievalOrchestrator
from seam_runtime.second_hop_context import build_bridge_plan, splice_results
from seam_runtime.temporal_instance_context import (
    TemporalEvidence,
    build_temporal_context_projection,
)

GRAPH_CONTEXT_OFF = "off"
GRAPH_CONTEXT_FILL_V1 = "canonical-graph-fill/1"
GRAPH_CONTEXT_POLICIES = frozenset({GRAPH_CONTEXT_OFF, GRAPH_CONTEXT_FILL_V1})
GRAPH_CONTEXT_MAX_ROWS = 40
MULTI_SCOPE_PROBE_ROWS = 40


def _epoch_to_iso(timestamp: int | None, *, preserve_subday: bool = False) -> str:
    """Mem0's client sends observation dates as a unix epoch. SEAM turns want an
    ISO string for relative-date grounding; fall back to empty when absent."""
    if timestamp is None:
        return ""
    try:
        resolved = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        if preserve_subday:
            return resolved.isoformat(timespec="seconds").replace("+00:00", "Z")
        return resolved.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return ""


def _split_speaker(
    content: str,
) -> tuple[str, str, bool]:
    """Mem0 chunks a turn as ``"Speaker: text"``. Recover (speaker, text) so the
    SEAM turn carries the same ``[Speaker ts] text`` shape as the native adapter.
    The first two return values preserve the legacy facade behavior exactly.
    The third is a stricter, derived-facts-only trust signal."""
    if ": " in content:
        speaker, text = content.split(": ", 1)
        if speaker and len(speaker) <= 64 and "\n" not in speaker:
            explicit_for_facts = speaker == speaker.strip() and not any(
                char in speaker for char in "\r\n[]"
            )
            return speaker, text, explicit_for_facts
    return "user", content, False


class SeamMem0Server:
    """Maps the three Mem0-OSS endpoints onto one shared ``SeamLocomoAdapter``.

    ``answerer=None``: the harness generates and judges its own answers; this
    server only supplies retrieved memories. All retrieval config comes from the
    environment (``SEAM_RETRIEVAL_*`` / ``SEAM_CONVERSATION_ADAPTER`` / etc.) via
    the adapter, so the exact validated stack is reproducible here.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        search_top_k: int = 100,
        context_budget: int = 8000,
        derived_facts_policy: str | None = None,
        graph_context_policy: str | None = None,
        multi_scope_pack_policy: str | None = None,
        nl_extractor=None,
        derived_facts_cache_path: str | None = None,
        derived_facts_max_facts: int = 40,
    ):
        resolved_graph_policy = graph_context_policy or os.environ.get(
            "SEAM_GRAPH_CONTEXT_POLICY", GRAPH_CONTEXT_OFF
        )
        if resolved_graph_policy not in GRAPH_CONTEXT_POLICIES:
            raise ValueError(f"unknown graph context policy {resolved_graph_policy!r}")
        resolved_multi_scope_policy = resolve_multi_scope_policy(
            multi_scope_pack_policy
            if multi_scope_pack_policy is not None
            else os.environ.get("SEAM_MULTI_SCOPE_PACK_POLICY", MULTI_SCOPE_OFF)
        )
        self._adapter = SeamLocomoAdapter(
            db_path=db_path,
            answerer=None,
            search_top_k=search_top_k,
            budget=context_budget,
            derived_facts_policy=derived_facts_policy,
            nl_extractor=nl_extractor,
            derived_facts_cache_path=derived_facts_cache_path,
        )
        self._derived_facts_policy = self._adapter._derived_facts.config.policy
        self._derived_fact_config_fingerprint = (
            self._adapter._derived_facts.config.fingerprint
        )
        if derived_facts_max_facts < 0:
            raise ValueError("derived_facts_max_facts must be nonnegative")
        self._derived_facts_max_facts = derived_facts_max_facts
        self._graph_context_policy = resolved_graph_policy
        self._multi_scope_pack_policy = resolved_multi_scope_policy

    # -- endpoint handlers (pure dict-in/dict-out; framework-agnostic) ------

    def add(self, payload: dict) -> dict:
        user_id = payload.get("user_id")
        messages = payload.get("messages") or []
        if not user_id or not isinstance(messages, list):
            raise ValueError("add requires user_id and a messages list")
        # The audited upstream ids identify contracts whose temporal questions
        # depend on hour/minute anchors. Keep the historical LoCoMo envelope
        # date-only while retaining full UTC time for LongMemEval and BEAM.
        preserve_subday = str(user_id).startswith(("longmemeval_", "beam_"))
        iso = _epoch_to_iso(payload.get("timestamp"), preserve_subday=preserve_subday)
        added = 0
        for msg in messages:
            content = (msg or {}).get("content") or ""
            if not content.strip():
                continue
            speaker, text, explicit_speaker = _split_speaker(content)
            self._adapter.ingest_turn(
                user_id,
                ConversationTurn(speaker=speaker, text=text, timestamp=iso),
                derive_facts=explicit_speaker,
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
        self._adapter.reset(user_id)
        cached_extractor = self._adapter._derived_facts.extractor
        if cached_extractor is not None:
            cached_extractor.purge_owner(f"locomo:{user_id}")
        return {"message": f"deleted memories for {user_id}"}

    def probe_stats(self) -> dict[str, object]:
        """Return numeric-only research extractor/cache counters."""

        cached = self._adapter._derived_facts.extractor
        if cached is None:
            return {
                "derived_facts_policy": self._derived_facts_policy,
                "enabled": False,
            }
        provider = cached.extractor
        rejection_counts = getattr(provider, "rejection_counts", {})
        return {
            "derived_facts_policy": self._derived_facts_policy,
            "enabled": True,
            "cache": cached.stats(),
            "provider_calls": int(getattr(provider, "calls", 0) or 0),
            "input_tokens": int(getattr(provider, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(provider, "output_tokens", 0) or 0),
            "model_fact_items": int(getattr(provider, "model_fact_items", 0) or 0),
            "validated_fact_items": int(
                getattr(provider, "validated_fact_items", 0) or 0
            ),
            "max_facts_per_query": self._derived_facts_max_facts,
            "rejection_counts": {
                str(key): int(value)
                for key, value in sorted(dict(rejection_counts).items())
            },
        }

    # -- retrieval ---------------------------------------------------------

    def _retrieve(self, user_id: str, query: str, limit: int) -> list[dict]:
        """Return ranked RAW turn memories as Mem0-shaped result dicts.

        Primary raw search, then the optional env-gated context policies in
        order: second-hop entity-bridge expansion (fills a reserved tail with
        evidence the primary query's wording cannot reach), then at most one
        disposable projection (count, else temporal)."""
        out = self._search_raw(user_id, query, limit)
        if (
            getattr(self, "_multi_scope_pack_policy", MULTI_SCOPE_OFF)
            != MULTI_SCOPE_OFF
        ):
            return self._apply_multi_scope_pack_policy(
                user_id,
                query,
                out,
                limit,
            )
        out = self._apply_second_hop_policy(user_id, query, out, limit)
        out = self._apply_graph_context_policy(user_id, query, out, limit)
        rt = self._adapter._runtime(user_id)
        projected = _apply_count_context_policy(rt, query, out, limit)
        if projected is not out:
            return projected
        projected = _apply_temporal_context_policy(query, out, limit)
        if projected is not out:
            return projected
        policy = getattr(
            self,
            "_derived_facts_policy",
            DERIVED_FACTS_OFF,
        )
        if policy == DERIVED_FACTS_OFF:
            return out
        facts = self._search_derived_facts(user_id, query, limit)
        return _pin_composed_order(
            splice_derived_facts(
                out,
                facts,
                limit=limit,
                policy=policy,
                max_facts=self._derived_facts_max_facts,
            )
        )

    def _apply_multi_scope_pack_policy(
        self,
        user_id: str,
        query: str,
        primary: list[dict],
        limit: int,
    ) -> list[dict]:
        """Compose independent representation lanes into one protected PACK.

        This is a standalone ratchet candidate: when enabled it does not stack
        the older second-hop, count, temporal-projection, graph-fill, or legacy
        fact splicers.  A deeper RAW probe must preserve the primary prefix;
        otherwise the candidate fails closed to the exact primary list.
        """

        policy = getattr(self, "_multi_scope_pack_policy", MULTI_SCOPE_OFF)
        if policy == MULTI_SCOPE_OFF:
            return primary
        if policy != MULTI_SCOPE_V1:
            raise ValueError(f"unknown multi-scope pack policy {policy!r}")
        deep_limit = max(limit, limit + MULTI_SCOPE_PROBE_ROWS)
        deep_raw = self._search_raw(user_id, query, deep_limit)
        if deep_raw[: len(primary)] != primary:
            return primary

        fact_rows: list[dict] = []
        if self._derived_facts_policy != DERIVED_FACTS_OFF:
            fact_rows = [
                fact.result()
                for fact in self._search_derived_facts(
                    user_id,
                    query,
                    MULTI_SCOPE_PROBE_ROWS,
                )
            ]
        graph_rows = self._search_graph_raw(
            user_id,
            query,
            MULTI_SCOPE_PROBE_ROWS,
        )
        temporal_rows = select_date_diverse_rows(
            deep_raw,
            exclude=primary,
            limit=MULTI_SCOPE_PROBE_ROWS,
        )
        return compose_reserved_multi_scope(
            primary,
            {
                "grounded_fact": fact_rows,
                "entity_relation": graph_rows,
                "temporal": temporal_rows,
                "raw_episode": deep_raw,
            },
            limit=limit,
            policy=policy,
        )

    def _apply_second_hop_policy(
        self, user_id: str, query: str, primary: list[dict], limit: int
    ) -> list[dict]:
        """Optional entity-bridge second hop (HISTORY#429 miss autopsy lever).

        Env-gated by ``SEAM_SECOND_HOP_POLICY``; off path returns ``primary``
        unchanged. Secondary searches reuse the exact raw search path, so the
        memory under test is unchanged — only the query set widens."""
        plan = build_bridge_plan(
            query,
            [str(item.get("memory") or "") for item in primary],
            policy=os.environ.get("SEAM_SECOND_HOP_POLICY", "off"),
        )
        if plan is None:
            return primary
        secondary: list[dict] = []
        for bridge_query in plan.queries:
            secondary.extend(
                self._search_raw(user_id, bridge_query, plan.reserve_slots)
            )
        return splice_results(
            primary, secondary, limit=limit, reserve_slots=plan.reserve_slots
        )

    def _apply_graph_context_policy(
        self,
        user_id: str,
        query: str,
        primary: list[dict],
        limit: int,
    ) -> list[dict]:
        """Fill unused result rows from the canonical graph without displacement."""

        policy = getattr(self, "_graph_context_policy", GRAPH_CONTEXT_OFF)
        if policy == GRAPH_CONTEXT_OFF:
            return primary
        if policy != GRAPH_CONTEXT_FILL_V1:
            raise ValueError(f"unknown graph context policy {policy!r}")
        available = max(0, limit - len(primary))
        if available == 0:
            return primary
        graph_rows = self._search_graph_raw(
            user_id,
            query,
            GRAPH_CONTEXT_MAX_ROWS,
        )
        return append_unique_graph_rows(primary, graph_rows, limit=limit)

    def _search_graph_raw(
        self,
        user_id: str,
        query: str,
        limit: int,
    ) -> list[dict]:
        """Resolve canonical ``knowledge_edges`` graph hits back to RAW turns."""

        if limit <= 0:
            return []
        runtime = self._adapter._runtime(user_id)
        graph = RetrievalOrchestrator(runtime).search(
            query,
            scope="thread",
            budget=limit,
            mode="graph",
        )
        out: list[dict] = []
        seen_content: set[str] = set()
        for candidate in graph.candidates:
            ids = _closure_ids(candidate)
            batch = runtime.store.load_ir(ids=ids)
            expanded_ids = list(ids)
            seen_ids = set(ids)
            for record in batch.records:
                if record.kind.value != "SPAN":
                    continue
                raw_id = record.attrs.get("raw_id")
                if isinstance(raw_id, str) and raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    expanded_ids.append(raw_id)
            if len(expanded_ids) != len(ids):
                batch = runtime.store.load_ir(ids=expanded_ids)
            for record in batch.records:
                if record.kind.value != "RAW":
                    continue
                content = record.attrs.get("content")
                if (
                    not isinstance(content, str)
                    or not content
                    or content in seen_content
                ):
                    continue
                seen_content.add(content)
                out.append(
                    {
                        "memory": content,
                        "score": float(candidate.score),
                        "id": record.id,
                        "created_at": _created_at(record),
                    }
                )
                if len(out) >= limit:
                    return out
        return out

    def _search_raw(self, user_id: str, query: str, limit: int) -> list[dict]:
        """The unexpanded ranked-RAW search (shared by primary + bridge hops).

        Uses the adapter's per-scope runtime + the same ``search_ir`` call the
        native benchmark uses, then maps each ranked candidate's closure to its
        RAW content so the harness sees individual memory strings (not SEAM's
        joined answer blob)."""
        rt = self._adapter._runtime(user_id)
        ns = f"locomo:{user_id}"
        temporal_window = self._adapter._build_temporal_window(query)
        temporal_reference = self._adapter._build_temporal_reference(user_id, query)
        result = rt.search_ir(
            query,
            scope="thread",
            budget=limit,
            include_raw=True,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            ns=ns,
        )
        out: list[dict] = []
        seen_content: set[str] = set()
        reached_limit = False
        for cand in result.candidates:
            ids = (
                self._adapter._collect_closure_ids_public(cand)
                if hasattr(self._adapter, "_collect_closure_ids_public")
                else _closure_ids(cand)
            )
            batch = rt.store.load_ir(ids=ids)
            expanded_ids = list(ids)
            seen_ids = set(ids)
            for record in batch.records:
                if record.kind.value != "SPAN":
                    continue
                raw_id = record.attrs.get("raw_id")
                if isinstance(raw_id, str) and raw_id and raw_id not in seen_ids:
                    seen_ids.add(raw_id)
                    expanded_ids.append(raw_id)
            if len(expanded_ids) != len(ids):
                batch = rt.store.load_ir(ids=expanded_ids)
            for record in batch.records:
                if record.kind.value != "RAW":
                    continue
                content = record.attrs.get("content")
                if (
                    not isinstance(content, str)
                    or not content
                    or content in seen_content
                ):
                    continue
                seen_content.add(content)
                out.append(
                    {
                        "memory": content,
                        "score": float(getattr(cand, "score", 0.0)),
                        "id": record.id,
                        "created_at": _created_at(record),
                    }
                )
                if len(out) >= limit:
                    reached_limit = True
                    break
            if reached_limit:
                break
        return out

    def _search_derived_facts(
        self,
        user_id: str,
        query: str,
        limit: int,
    ) -> list[DerivedFact]:
        """Retrieve explicit grounded CLMs with a complete live RAW backtrace."""

        rt = self._adapter._runtime(user_id)
        ns = f"locomo:{user_id}"
        temporal_window = self._adapter._build_temporal_window(query)
        temporal_reference = self._adapter._build_temporal_reference(
            user_id,
            query,
        )
        result = rt.search_ir(
            query,
            scope="thread",
            budget=limit,
            include_raw=False,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            ns=ns,
        )
        candidates = [
            candidate
            for candidate in result.candidates
            if candidate.record.ns == ns
            and candidate.record.scope == "thread"
            and is_eligible_derived_claim(
                candidate.record,
                policy=self._derived_facts_policy,
            )
            and candidate.record.ext.get("derived_fact_config_fingerprint")
            == self._derived_fact_config_fingerprint
        ]
        if not candidates:
            return []

        allowed = rt.store.assertable_record_ids(
            [candidate.record.id for candidate in candidates],
            namespace=ns,
            scope="thread",
        )
        candidates = [
            candidate for candidate in candidates if candidate.record.id in allowed
        ]
        if not candidates:
            return []

        initial_ids: list[str] = []
        seen_ids: set[str] = set()

        def add_id(record_id: object) -> None:
            if isinstance(record_id, str) and record_id and record_id not in seen_ids:
                seen_ids.add(record_id)
                initial_ids.append(record_id)

        for candidate in candidates:
            add_id(candidate.record.id)
            add_id(candidate.record.attrs.get("subject"))
            for evidence_id in candidate.record.evidence:
                add_id(evidence_id)

        initial_batch = rt.store.load_ir(ids=initial_ids)
        by_id = initial_batch.by_id()
        raw_ids: list[str] = []
        for record in initial_batch.records:
            if record.kind.value != "SPAN":
                continue
            raw_id = record.attrs.get("raw_id")
            if isinstance(raw_id, str) and raw_id not in raw_ids:
                raw_ids.append(raw_id)
        raw_batch = rt.store.load_ir(ids=raw_ids)
        by_id.update(raw_batch.by_id())
        live_chain_ids = rt.store.assertable_record_ids(
            list(by_id),
            namespace=ns,
            scope="thread",
        )

        facts: list[DerivedFact] = []
        for candidate in candidates:
            claim = candidate.record
            subject = by_id.get(str(claim.attrs.get("subject") or ""))
            if (
                subject is None
                or subject.kind.value != "ENT"
                or subject.ns != ns
                or subject.scope != "thread"
                or subject.id not in live_chain_ids
            ):
                continue
            subject_label = str(subject.attrs.get("label") or "").strip()
            recorded_label = str(claim.attrs.get("subject_label") or "").strip()
            if not subject_label or " ".join(subject_label.lower().split()) != " ".join(
                recorded_label.lower().split()
            ):
                continue

            source_raw = None
            source_span = None
            for evidence_id in claim.evidence:
                span = by_id.get(evidence_id)
                if (
                    span is None
                    or span.kind.value != "SPAN"
                    or span.ns != ns
                    or span.scope != "thread"
                    or span.id not in live_chain_ids
                ):
                    continue
                raw_id = span.attrs.get("raw_id")
                raw = by_id.get(str(raw_id or ""))
                if (
                    raw is not None
                    and raw.kind.value == "RAW"
                    and raw.ns == ns
                    and raw.scope == "thread"
                    and raw.id in live_chain_ids
                ):
                    source_raw = raw
                    source_span = span
                    break
            if source_raw is None or source_span is None:
                continue
            source_text = source_raw.attrs.get("content")
            source_metadata = source_raw.ext.get("source_metadata")
            if (
                not isinstance(source_metadata, dict)
                or source_metadata.get("format") != "locomo-turn/1"
            ):
                continue
            source_speaker = (
                source_metadata.get("speaker")
                if isinstance(source_metadata, dict)
                else None
            )
            source_timestamp = (
                source_metadata.get("timestamp")
                if isinstance(source_metadata, dict)
                else None
            )
            source_prefix_end = (
                source_metadata.get("prefix_end")
                if isinstance(source_metadata, dict)
                else None
            )
            if (
                not isinstance(source_text, str)
                or not source_text
                or not grounded_spans_match_source(
                    claim,
                    source_text,
                    evidence_start=source_span.attrs.get("start"),
                    evidence_end=source_span.attrs.get("end"),
                    source_speaker=source_speaker,
                    source_timestamp=source_timestamp,
                    source_prefix_end=source_prefix_end,
                    require_evidence_bounds=True,
                    require_source_metadata=True,
                )
            ):
                continue
            facts.append(
                DerivedFact(
                    claim_id=claim.id,
                    subject=subject_label,
                    predicate=str(claim.attrs["predicate"]).strip(),
                    obj=str(claim.attrs["object"]).strip(),
                    source_raw_id=source_raw.id,
                    source_text=source_text,
                    score=float(candidate.score),
                    created_at=_created_at(source_raw),
                )
            )
        return facts

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


def append_unique_graph_rows(
    primary: list[dict],
    graph_rows: list[dict],
    *,
    limit: int,
) -> list[dict]:
    """Fill unused rows only; never remove or reorder a primary result."""

    out = list(primary[:limit])
    seen = {str(item.get("memory") or "") for item in out}
    for row in graph_rows:
        content = str(row.get("memory") or "")
        if not content or content in seen:
            continue
        seen.add(content)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _apply_count_context_policy(
    runtime, query: str, results: list[dict], limit: int
) -> list[dict]:
    """Apply the optional count projection without changing the off path."""

    get_flags = getattr(runtime, "_retrieval_flags_cached", None)
    flags = get_flags() if callable(get_flags) else None
    policy = getattr(flags, "count_context_policy", "off")
    projection = build_count_context_projection(
        query,
        [
            CountEvidence(
                record_id=str(item["id"]),
                text=str(item["memory"]),
                score=float(item.get("score", 0.0)),
                created_at=str(item.get("created_at") or ""),
                original_rank=index,
            )
            for index, item in enumerate(results, 1)
        ],
        policy=policy,
    )
    if projection is None or limit < 2:
        return results

    by_id = {str(item["id"]): item for item in results}
    reranked_results = [
        by_id[row.evidence.record_id]
        for row in projection.ranked
        if row.evidence.record_id in by_id
    ]
    retained_results = reranked_results[: max(0, limit - 1)]
    retained_ids = {str(item["id"]) for item in retained_results}
    retained_evidence = [
        row.evidence
        for row in projection.ranked
        if row.evidence.record_id in retained_ids
    ]
    projection = build_count_context_projection(
        query,
        retained_evidence,
        policy=policy,
    )
    if projection is None:
        return results
    projected = {
        "memory": projection.render(),
        "score": max((float(item.get("score", 0.0)) for item in results), default=0.0),
        "id": projection.projection_id,
        "created_at": "",
    }
    return [projected, *retained_results]


def _apply_temporal_context_policy(
    query: str, results: list[dict], limit: int
) -> list[dict]:
    """Optional SEAM-TEMPORAL/1 projection (HISTORY#426 cat2 lever).

    Facade-scoped enablement via the ``SEAM_TEMPORAL_CONTEXT_POLICY`` env var
    (not a ``RetrievalFlags`` field yet: the flags module has in-flight
    concurrent edits and the lever is unvalidated; core productization follows
    a measured win). Off path returns ``results`` unchanged. Runs only when
    the count policy did not already project — the two intents are disjoint
    and only one disposable projection should spend context per query."""

    policy = os.environ.get("SEAM_TEMPORAL_CONTEXT_POLICY", "off")
    projection = build_temporal_context_projection(
        query,
        [
            TemporalEvidence(
                record_id=str(item["id"]),
                text=str(item["memory"]),
                score=float(item.get("score", 0.0)),
                original_rank=index,
            )
            for index, item in enumerate(results, 1)
        ],
        policy=policy,
    )
    if projection is None or limit < 2:
        return results
    retained = results[: max(0, limit - 1)]
    projected = {
        "memory": projection.render(),
        "score": max((float(item.get("score", 0.0)) for item in results), default=0.0),
        "id": projection.projection_id,
        "created_at": "",
    }
    return [projected, *retained]


def _created_at(record) -> str:
    """Prefer an explicit turn timestamp; the RAW content also carries the date
    inline (``[Speaker ts] text``), so an empty value never loses temporal info."""
    for key in ("timestamp", "observed_at", "valid_at"):
        val = record.attrs.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _pin_composed_order(results: list[dict]) -> list[dict]:
    """Keep a composed response stable through the pinned harness client.

    ``memory-benchmarks`` sorts every OSS response by ``score`` even when the
    facade has already composed a contract-bearing order. Replace only the
    transport score with a strictly descending value so RAW-prefix spacing and
    source-before-fact ordering survive that normalization step.
    """

    return [
        {**item, "score": 1.0 - (index * 1e-9)} for index, item in enumerate(results)
    ]


def build_asgi_app(server: SeamMem0Server):
    """Wrap a SeamMem0Server in a FastAPI app exposing the Mem0-OSS routes.

    Bodies are typed as ``dict`` (not a Pydantic model) so the app accepts the
    harness's exact JSON payloads verbatim without a schema to drift from.
    """
    from typing import Any

    from fastapi import Body, FastAPI

    app = FastAPI(title="SEAM Mem0-OSS facade")

    @app.post("/memories")
    def add_memories(payload: dict[str, Any] = Body(...)):
        return server.add(payload)

    @app.post("/search")
    def search_memories(payload: dict[str, Any] = Body(...)):
        return server.search(payload)

    @app.delete("/memories")
    def delete_memories(
        user_id: str | None = None,
        payload: dict[str, Any] | None = Body(default=None),
    ):
        uid = user_id or ((payload or {}).get("user_id"))
        return server.delete_user(uid)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/probe-stats")
    async def probe_stats():
        return server.probe_stats()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="SEAM as a Mem0-OSS memory server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--search-top-k", type=int, default=100)
    parser.add_argument("--context-budget", type=int, default=8000)
    parser.add_argument(
        "--derived-facts-policy",
        choices=sorted(DERIVED_FACTS_POLICIES),
        default=None,
        help=(
            "frozen ingest+retrieval policy; defaults to SEAM_DERIVED_FACTS_POLICY or off"
        ),
    )
    parser.add_argument(
        "--derived-facts-cache-path",
        default=None,
        help="optional content-addressed extraction-cache path",
    )
    parser.add_argument(
        "--derived-facts-max-facts",
        type=int,
        default=40,
        help="research cap for derived facts composed into one response",
    )
    parser.add_argument(
        "--multi-speaker-openai-model",
        default=None,
        help=(
            "research-probe-only OpenAI extractor model; required when derived-facts-policy is multi-speaker-grounded/1"
        ),
    )
    parser.add_argument(
        "--multi-speaker-ground-scope",
        choices=("sentence", "turn"),
        default="turn",
        help="name-grounding scope for the multi-speaker research probe",
    )
    parser.add_argument(
        "--graph-context-policy",
        choices=sorted(GRAPH_CONTEXT_POLICIES),
        default=None,
        help=(
            "default-off canonical graph composition; defaults to SEAM_GRAPH_CONTEXT_POLICY or off"
        ),
    )
    parser.add_argument(
        "--multi-scope-pack-policy",
        choices=sorted(MULTI_SCOPE_POLICIES),
        default=None,
        help=(
            "default-off direct-readable reserved context pack; defaults to SEAM_MULTI_SCOPE_PACK_POLICY or off"
        ),
    )
    args = parser.parse_args()

    import uvicorn

    resolved_derived_policy = resolve_derived_facts_policy(args.derived_facts_policy)
    nl_extractor = None
    if resolved_derived_policy == MULTI_SPEAKER_GROUNDED_V1:
        if not args.multi_speaker_openai_model:
            parser.error(
                "multi-speaker-grounded/1 requires --multi-speaker-openai-model"
            )
        from benchmarks.external.mem0_harness.preflight_multi_speaker_facts import (
            OpenAIMultiSpeakerFactExtractor,
        )

        nl_extractor = OpenAIMultiSpeakerFactExtractor(
            model=args.multi_speaker_openai_model,
            ground_scope=args.multi_speaker_ground_scope,
        )
    elif args.multi_speaker_openai_model:
        parser.error(
            "--multi-speaker-openai-model requires --derived-facts-policy multi-speaker-grounded/1"
        )

    server = SeamMem0Server(
        db_path=args.db_path,
        search_top_k=args.search_top_k,
        context_budget=args.context_budget,
        derived_facts_policy=args.derived_facts_policy,
        graph_context_policy=args.graph_context_policy,
        multi_scope_pack_policy=args.multi_scope_pack_policy,
        nl_extractor=nl_extractor,
        derived_facts_cache_path=args.derived_facts_cache_path,
        derived_facts_max_facts=args.derived_facts_max_facts,
    )
    uvicorn.run(build_asgi_app(server), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
