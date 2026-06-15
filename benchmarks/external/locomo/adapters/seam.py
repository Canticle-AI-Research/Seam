from __future__ import annotations

import hashlib
import json
import os
import re
import time as _time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.external.common.types import AdapterAnswer, ConversationTurn


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


_DEFAULT_SENTENCE_TRANSFORMER_MODEL = None


@dataclass(frozen=True)
class SemanticRecoveryPolicy:
    mode: str = "baseline"
    context_char_budget: int = 2000
    search_top_k: int = 20
    rerank_top_k: int = 20

    def to_dict(self) -> dict[str, int | str]:
        return {
            "mode": self.mode,
            "context_char_budget": self.context_char_budget,
            "search_top_k": self.search_top_k,
            "rerank_top_k": self.rerank_top_k,
        }


class SeamLocomoAdapter:
    """SEAM memory system adapter for LoCoMo benchmarks.

    Implements the MemorySystemAdapter protocol. Each scope_id maps to a
    dedicated SQLite database under ``{db_root}/{scope_id}.db``, providing
    per-scope storage isolation.

    Lazy imports of ``seam_runtime`` modules avoid import-time side effects
    (such as embedding model initialisation) during test discovery.
    """

    name = "seam"

    def __init__(
        self,
        db_path: str | None = None,
        # Measured knee (HISTORY#320): top_k=100 / context budget=8000 lifts paid
        # judge_score 0.40->0.52 vs the former starved 20/2000; the curve flattens
        # past here (200/20000 = +0.005 for ~2x answerer cost), so this is the
        # quality-per-token default, not "max it".
        budget: int = 8000,
        include_evidence_closure: bool = True,
        answerer: str | None = None,
        answerer_model: str | None = None,
        decomposer: str | None = None,
        decomposer_model: str | None = None,
        decomposer_max_subq: int = 3,
        abstain_threshold: float = 0.0,
        rerank: str | None = None,
        search_top_k: int = 100,
        rerank_top_k: int = 20,
        semantic_recovery_mode: str = "baseline",
        rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
        keep_db: bool = False,
        record_retrieval_events: bool | None = None,
        run_id: str | None = None,
        entity_aggregation: bool = False,
    ) -> None:
        # TODO: default db_path should be tmp_path, not a gitignored project dir
        self._db_root = Path(db_path) if db_path is not None else Path("test_seam/locomo")
        self.semantic_recovery_policy = SemanticRecoveryPolicy(
            mode=semantic_recovery_mode,
            context_char_budget=budget,
            search_top_k=search_top_k,
            rerank_top_k=rerank_top_k,
        )
        self.budget = self.semantic_recovery_policy.context_char_budget
        self.include_evidence_closure = include_evidence_closure
        self._answerer = answerer
        self._answerer_model = answerer_model
        self._decomposer = decomposer
        self._decomposer_model = decomposer_model
        self._decomposer_max_subq = decomposer_max_subq
        self._abstain_threshold = abstain_threshold
        self._rerank = rerank if rerank != "none" else None
        self._search_top_k = self.semantic_recovery_policy.search_top_k
        self._rerank_top_k = self.semantic_recovery_policy.rerank_top_k
        self._rerank_model = rerank_model
        self._keep_db = keep_db
        self._scope_anchor_by_id = {}
        self._runtime_by_scope = {}
        self._cached_scopes: set[str] = set()
        # H2 slice 2: opt-in retrieval_event writer hook.
        # Explicit ctor arg wins; env var is the operator/CI knob; default off.
        if record_retrieval_events is None:
            record_retrieval_events = _env_truthy(os.environ.get("SEAM_RECORD_RETRIEVAL_EVENTS"))
        self._record_events = bool(record_retrieval_events)
        self._run_id = run_id or os.environ.get("SEAM_RUN_ID") or None
        # HISTORY#322 prototype: entity-aggregation retrieval. Gathers every claim
        # SUBJECT-grounded to (or mentioning) the question's entity into a clean,
        # re-attributed list - the cross-turn coreference the per-turn ingest drops
        # (each turn's speaker is a fresh ent id with zero edges). Free cat1-recall
        # A/B (5 dev convs): cat1 +0.043, cat3 +0.075 (concentrated on the weak
        # categories, not uniform inflation). Subject ids resolve to labels so a
        # first-person utterance ("I researched X") is re-attributed to the named
        # entity - the coreference fix in the presented text. Ranked subject-first,
        # capped to bound the additive context.
        self._entity_aggregation = bool(entity_aggregation) or _env_truthy(os.environ.get("SEAM_BENCH_ENTITY_AGG"))
        self._entity_agg_max_claims = int(os.environ.get("SEAM_BENCH_ENTITY_AGG_MAX", "20"))

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def reset(self, scope_id: str) -> None:
        """Drop the per-scope database file (and any WAL artefacts).

        When ``keep_db`` is set and the scope's DB already holds ingested
        records, skip the delete and mark the scope as cached so subsequent
        ``ingest_turn`` calls become no-ops (anchor still updates).
        """
        self._cached_scopes.discard(scope_id)
        db = self._db_path(scope_id)
        if self._keep_db and db.exists() and self._scope_has_records(scope_id):
            self._scope_anchor_by_id.pop(scope_id, None)
            self._cached_scopes.add(scope_id)
            return
        runtime = self._runtime_by_scope.pop(scope_id, None)
        if runtime is not None:
            close = getattr(getattr(runtime, "store", None), "close", None)
            if callable(close):
                close()
        _remove_db_files(db)
        self._scope_anchor_by_id.pop(scope_id, None)

    def close(self) -> None:
        """Close every cached per-scope runtime so its SQLite file is unlocked.

        The adapter caches a runtime per scope for the duration of a run; callers
        must close the adapter when finished (or use it as a context manager) or
        Windows cannot delete the per-scope databases (WinError 32). Idempotent.
        """
        for runtime in self._runtime_by_scope.values():
            close = getattr(runtime, "close", None)
            if callable(close):
                close()
        self._runtime_by_scope.clear()

    def __enter__(self) -> "SeamLocomoAdapter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def ingest_turn(self, scope_id: str, turn: ConversationTurn) -> None:
        """Compile a conversation turn to MIRL and persist it in the
        scope's database. Skipped when the scope is already cached on disk."""
        from seam_runtime.runtime import SeamRuntime  # lazy
        from seam_runtime.temporal import parse_iso

        # anchor always updates so relative-date questions work on cached scopes
        turn_dt = parse_iso(turn.timestamp)
        if turn_dt is not None:
            current_anchor = self._scope_anchor_by_id.get(scope_id)
            if current_anchor is None or turn_dt < current_anchor:
                self._scope_anchor_by_id[scope_id] = turn_dt
        if scope_id in self._cached_scopes:
            return
        text = _format_turn(turn)
        turn_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        rt = self._runtime(scope_id)
        rt.ingest_conversation_turn(
            text=text,
            source_ref=f"locomo:{scope_id}:turn:{turn_hash}",
            ns=f"locomo:{scope_id}",
            scope="thread",
            persist=True,
        )

    def _scope_has_records(self, scope_id: str) -> bool:
        """Return True if the scope's DB already contains MIRL records."""
        try:
            rt = self._runtime(scope_id)
            batch = rt.store.load_ir(ns=f"locomo:{scope_id}")
            return len(batch.records) > 0
        except Exception:
            return False

    def answer(self, scope_id: str, question: str) -> AdapterAnswer:
        """Search the scope's memory and return source evidence text.

        Standard LoCoMo scoring uses token overlap against retrieved context.
        The default context pack is useful for SEAM graph inspection but elides
        natural-language evidence into symbolic records, so this adapter follows
        evidence/provenance and SPAN-to-RAW links before returning source text.
        """
        from seam_runtime.runtime import SeamRuntime  # lazy

        rt = self._runtime(scope_id)

        questions = [question]
        if self._decomposer:
            sub = self._decompose(question)
            if sub:
                questions = sub[: self._decomposer_max_subq] + [question]

        temporal_window = self._build_temporal_window(question)
        temporal_reference = self._build_temporal_reference(scope_id, question)

        # Substream isolation A/B toggle: when SEAM_RETRIEVAL_SCOPED_VECTORS is
        # set, confine retrieval to this conversation's namespace (matches the
        # ingest ns) so the shared pgvector pool returns only this scope's
        # vectors. Off -> prior global behavior (ns=None).
        from seam_runtime.retrieval import retrieval_flags_from_env  # lazy
        search_ns = f"locomo:{scope_id}" if retrieval_flags_from_env().scoped_vectors else None

        closures: list[list[str]] = []
        retrieval_latency_ms = 0.0
        top_score = 0.0
        candidate_count = 0
        # Track the result for the original question (always last in `questions`)
        # so the retrieval_event row reflects the question actually asked, not a
        # decomposed sub-query. Stays None if no candidates ever came back.
        primary_result = None
        for q in questions:
            t0 = _time.monotonic()
            result = rt.search_ir(
                q,
                scope="thread",
                budget=self._search_top_k,
                include_raw=True,
                temporal_window=temporal_window,
                temporal_reference=temporal_reference,
                ns=search_ns,
            )
            retrieval_latency_ms += (_time.monotonic() - t0) * 1000.0
            if q == question:
                primary_result = result
            if result.candidates:
                candidate_count += len(result.candidates)
                if self._rerank == "cross-encoder" and len(result.candidates) > 1:
                    result = self._rerank_candidates(q, result)
                if q == question:
                    primary_result = result
                closures.append(self._collect_closure_ids(result))
                top_score = max(top_score, result.candidates[0].score)

        merged: list[str] = []
        seen_merged: set[str] = set()
        for closure in closures:
            for record_id in closure:
                if record_id not in seen_merged:
                    seen_merged.add(record_id)
                    merged.append(record_id)

        if not merged:
            diag = self._retrieval_diagnostics(
                candidate_count=candidate_count,
                closure_id_count=0,
                sub_question_count=len(questions) - 1,
            )
            if self._record_events:
                self._record_retrieval_event(
                    rt=rt,
                    scope_id=scope_id,
                    question=question,
                    sub_questions=[q for q in questions if q != question],
                    primary_result=primary_result,
                    retrieved_context="",
                    retrieval_latency_ms=retrieval_latency_ms,
                    answer_latency_ms=None,
                    top_score=top_score,
                    generated=None,
                    answerer_diag=diag,
                )
            return AdapterAnswer(
                retrieved_context="",
                retrieval_latency_ms=retrieval_latency_ms,
                answerer_diagnostics=diag,
            )

        if self.include_evidence_closure:
            retrieved_context = self._build_evidence_context_from_ids(rt, merged)
        else:
            record_ids = sorted(merged)
            pack = rt.pack_ir(record_ids, lens="general", budget=self.budget)
            pack_dict = pack.to_dict() if hasattr(pack, "to_dict") else {}
            retrieved_context = json.dumps(pack_dict, sort_keys=True, indent=2)

        # HISTORY#322 prototype: append a re-attributed list of claims grounded to
        # (or mentioning) the question's entity - the cross-turn coreference the
        # per-turn ingest scatters across distinct ent ids.
        if self._entity_aggregation:
            agg = self._entity_aggregate(rt, question)
            if agg:
                # ADDITIVE: append AFTER the full semantic context so it can never
                # evict existing evidence (context_recall is set-based). The claim
                # cap bounds the blob so it doesn't dilute a real answerer's window.
                retrieved_context = retrieved_context + "\n\n" + _trim_context(agg, self.budget)

        generated = None
        answer_latency_ms = None
        answerer_diag: dict | None = None
        if self._answerer:
            if self._abstain_threshold > 0.0 and top_score < self._abstain_threshold:
                generated = "unknown"
                answerer_diag = {"abstained_by_threshold": True, "top_score": top_score}
            else:
                t1 = _time.monotonic()
                answerer_diag = {}
                generated = self._generate_answer(question, retrieved_context, diag_out=answerer_diag)
                answer_latency_ms = (_time.monotonic() - t1) * 1000.0

        diag = self._retrieval_diagnostics(
            candidate_count=candidate_count,
            closure_id_count=len(merged),
            sub_question_count=len(questions) - 1,
        )
        if answerer_diag:
            diag.update(answerer_diag)

        if self._record_events:
            self._record_retrieval_event(
                rt=rt,
                scope_id=scope_id,
                question=question,
                sub_questions=[q for q in questions if q != question],
                primary_result=primary_result,
                retrieved_context=retrieved_context,
                retrieval_latency_ms=retrieval_latency_ms,
                answer_latency_ms=answer_latency_ms,
                top_score=top_score,
                generated=generated,
                answerer_diag=diag,
            )

        return AdapterAnswer(
            retrieved_context=retrieved_context,
            generated_answer=generated,
            retrieval_latency_ms=retrieval_latency_ms,
            answer_latency_ms=answer_latency_ms,
            answerer_diagnostics=diag,
        )

    def _retrieval_diagnostics(
        self,
        *,
        candidate_count: int,
        closure_id_count: int,
        sub_question_count: int,
    ) -> dict:
        return {
            "retrieval_policy": self.semantic_recovery_policy.to_dict(),
            "retrieval": {
                "candidate_count": candidate_count,
                "closure_id_count": closure_id_count,
                "sub_question_count": sub_question_count,
            },
        }

    def _resolve_run_id(self) -> str:
        """Lazy-resolve and cache the run_id. Called only when recording is on."""
        if self._run_id:
            return self._run_id
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._run_id = f"seam-locomo-{ts}-{uuid.uuid4().hex[:8]}"
        return self._run_id

    def _record_retrieval_event(
        self,
        *,
        rt,
        scope_id: str,
        question: str,
        sub_questions: list[str],
        primary_result,
        retrieved_context: str,
        retrieval_latency_ms: float,
        answer_latency_ms: float | None,
        top_score: float,
        generated: str | None,
        answerer_diag: dict | None,
    ) -> None:
        """Append a retrieval_event row to the per-scope SQLite store.

        Diagnostic write: failures must never break the benchmark. The H2
        substrate is the canonical training-data source for the improvement
        loop; missing rows are acceptable, corrupting an answer pass is not.
        """
        try:
            candidates = list(primary_result.candidates) if primary_result is not None else []
            candidate_ids = [c.record.id for c in candidates]
            scores = [float(c.score) for c in candidates]
            ranks = list(range(1, len(candidates) + 1))
            reasons = [", ".join(c.reasons or []) for c in candidates]
            context_hash = (
                hashlib.sha256(retrieved_context.encode("utf-8")).hexdigest()
                if retrieved_context
                else None
            )
            extra: dict = {
                "top_score": float(top_score),
                "retrieval_latency_ms": float(retrieval_latency_ms),
            }
            if answer_latency_ms is not None:
                extra["answer_latency_ms"] = float(answer_latency_ms)
            if sub_questions:
                extra["sub_questions"] = sub_questions
            if answerer_diag:
                extra["answerer_diagnostics"] = answerer_diag
            rt.store.write_retrieval_event(
                run_id=self._resolve_run_id(),
                scope=f"locomo:{scope_id}",
                query=question,
                candidate_ids=candidate_ids,
                ranks=ranks if candidate_ids else None,
                scores=scores if candidate_ids else None,
                reasons=reasons if candidate_ids else None,
                context_hash=context_hash,
                answer=generated,
                source_kind="live",
                extra=extra,
            )
        except Exception:
            # Diagnostic write; swallow so the benchmark answer pass is never
            # invalidated by an instrumentation failure. The integrity hash of
            # the result bundle does not depend on retrieval_event rows.
            pass

    def _generate_answer(self, question: str, context: str, diag_out: dict | None = None) -> str:
        prompt = (
            "Answer the question using ONLY the context. "
            "Return the best supported answer found in the context, even when "
            "the context also contains unrelated snippets. "
            "Say 'unknown' only when the context contains no answer candidate. "
            "Reply with the shortest possible answer, no preamble.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
        )
        extra = {"diag_out": diag_out} if diag_out is not None else {}
        if self._answerer == "openai":
            return _openai_short_answer(self._answerer_model or "gpt-4o-mini", prompt, **extra)
        if self._answerer == "claude":
            return _claude_short_answer(self._answerer_model or "claude-haiku-4-5-20251001", prompt, **extra)
        if self._answerer == "ollama":
            return _ollama_short_answer(self._answerer_model or "qwen2.5:3b", prompt, **extra)
        raise ValueError(f"unknown answerer {self._answerer!r}")

    def _build_temporal_window(self, question: str):
        from datetime import timedelta

        from seam_runtime.temporal import detect_temporal_tokens, parse_iso

        tokens = detect_temporal_tokens(question)
        if not tokens:
            return None
        parsed = []
        for token in tokens:
            dt = parse_iso(token)
            if dt:
                parsed.append(dt)
        if not parsed:
            return None
        earliest = min(parsed) - timedelta(days=30)
        latest = max(parsed) + timedelta(days=30)
        return (earliest, latest)

    def _build_temporal_reference(self, scope_id: str, question: str):
        from seam_runtime.temporal import parse_temporal_reference

        return parse_temporal_reference(
            question,
            anchor=self._scope_anchor_by_id.get(scope_id),
        )

    def _decompose(self, question: str) -> list[str]:
        prompt = (
            "Decompose the question into 1-3 atomic sub-questions that each "
            "ask about a single fact, entity, or event. Reply with one "
            "sub-question per line and nothing else. If the question is "
            "already atomic, reply with the original question only.\n\n"
            f"Question: {question}\nSub-questions:"
        )
        if self._decomposer == "openai":
            text = _openai_short_answer(self._decomposer_model or "gpt-4o-mini", prompt, max_tokens=128)
        elif self._decomposer == "claude":
            text = _claude_short_answer(self._decomposer_model or "claude-haiku-4-5-20251001", prompt, max_tokens=128)
        else:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()][: self._decomposer_max_subq]

    def _collect_closure_ids(self, result) -> list[str]:
        """Collect record IDs from search result candidates and their evidence/prov."""
        closure_ids: list[str] = []
        seen: set[str] = set()

        def add(record_id: str) -> None:
            if record_id not in seen:
                seen.add(record_id)
                closure_ids.append(record_id)

        for candidate in result.candidates:
            add(candidate.record.id)
            for evidence_id in candidate.record.evidence or []:
                add(evidence_id)
            for prov_id in candidate.record.prov or []:
                add(prov_id)
        return closure_ids

    def _rerank_candidates(self, query: str, result):
        """Re-rank the top-K candidates with a cross-encoder and return a new
        SearchResult with re-scored, re-sorted candidates."""
        from seam_runtime.mirl import iter_textual_fields

        from benchmarks.external.locomo.rerank import cross_encoder_rerank

        top_k = result.candidates[: self._rerank_top_k]
        rest = result.candidates[self._rerank_top_k :]

        texts = [" ".join(iter_textual_fields(c.record)) for c in top_k]
        scores = cross_encoder_rerank(query, texts, model=self._rerank_model)

        for candidate, score in zip(top_k, scores):
            candidate.score = score

        top_k.sort(key=lambda c: c.score, reverse=True)
        result.candidates[:] = top_k + list(rest)
        return result

    # HISTORY#322 prototype: entity-aggregation retrieval.
    # Lowercased; matched case-insensitively. Question/pronoun words that get
    # capitalized at sentence start but are never the entity we aggregate on.
    _ENTITY_STOPWORDS = frozenset(
        w.lower()
        for w in (
            "What", "Where", "When", "Who", "How", "Why", "Which", "Whose", "Whom",
            "In", "On", "At", "By", "For", "From", "With", "About", "Into",
            "Has", "Have", "Had", "Is", "Are", "Was", "Were", "Does", "Did", "Do",
            "Will", "Would", "Can", "Could", "Should", "May", "Might",
            "The", "A", "An", "To", "Of", "And", "Or", "But", "If", "So",
            "This", "That", "These", "Those", "There", "Then", "Here",
            "He", "She", "They", "It", "We", "You", "His", "Her", "Their", "Its",
            "Him", "Them", "Your", "Our", "My", "Me", "Mr", "Mrs", "Ms", "Dr",
        )
    )

    # A proper-noun run (consecutive Capitalized words, e.g. "New York") or an
    # all-caps acronym (e.g. "LGBTQ"). Captures multi-word + acronym entities the
    # old single-token regex dropped.
    _ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*|[A-Z]{2,})\b")

    def _question_entities(self, question: str) -> list[str]:
        """Proper-noun entities in the question (capitalized runs + acronyms),
        stopwords stripped, deduped case-insensitively, order preserved."""
        out: list[str] = []
        seen: set[str] = set()
        for match in self._ENTITY_RE.findall(question):
            # Trim leading/trailing stopword tokens glued in by sentence-start
            # capitalization ("Did Caroline" -> "Caroline", "Mr Smith" -> "Smith").
            tokens = match.split()
            while tokens and tokens[0].lower() in self._ENTITY_STOPWORDS:
                tokens.pop(0)
            while tokens and tokens[-1].lower() in self._ENTITY_STOPWORDS:
                tokens.pop()
            ent = " ".join(tokens)
            if len(ent) < 3 or ent.lower() in self._ENTITY_STOPWORDS:
                continue
            key = ent.lower()
            if key not in seen:
                seen.add(key)
                out.append(ent)
        return out

    @staticmethod
    def _stem(word: str) -> str:
        """Crude English suffix-stripper so 'instruments'~'instrument' and
        'played'/'playing'/'plays'~'play' match during relevance ranking."""
        for suf in ("ing", "ed", "es", "s"):
            if word.endswith(suf) and len(word) - len(suf) >= 3:
                return word[: -len(suf)]
        return word

    def _query_terms(self, question: str, entities: list[str]) -> set[str]:
        """Stemmed content (non-stopword, non-entity) words from the question, used
        to rank an entity's claims by relevance to THIS question."""
        ent_words = {w for e in entities for w in e.lower().split()}
        terms: set[str] = set()
        for tok in re.findall(r"[a-z0-9]{3,}", question.lower()):
            if tok in self._ENTITY_STOPWORDS or tok in ent_words:
                continue
            terms.add(self._stem(tok))
        return terms

    def _entity_aggregate(self, rt, question: str) -> str:
        """Gather claims grounded to (subject) or mentioning (object) the question's
        entity into a clean, re-attributed, query-RANKED list. Subject ids resolve
        to labels so first-person utterances are re-attributed to the named entity
        (the coreference fix). Claims relevant to THIS question (lexical overlap
        with its content words) rank first so the answer needle survives the cap -
        the fix for the dilution that buried needles in a 40-claim blob. Capped at
        ``_entity_agg_max_claims`` to bound the additive context."""
        entities = self._question_entities(question)
        if not entities:
            return ""
        patterns = [
            re.compile(r"(?<![A-Za-z])" + re.escape(e) + r"(?![A-Za-z])", re.IGNORECASE)
            for e in entities
        ]
        qterms = self._query_terms(question, entities)
        records = rt.store.load_ir().records
        # ent id -> label, so a claim's subject id can be matched + displayed.
        labels = {
            r.id: str(r.attrs.get("label", "")).strip()
            for r in records
            if r.kind.value == "ENT"
        }
        scored: list[tuple[tuple[int, int, int, int], str]] = []
        seen: set[str] = set()
        for order, record in enumerate(records):
            if record.kind.value != "CLM":
                continue
            obj = str(record.attrs.get("object", "")).strip()
            if not obj:
                continue
            subj_id = str(record.attrs.get("subject", "")).strip()
            subj_label = labels.get(subj_id, "")
            subj_hit = bool(subj_label) and any(p.search(subj_label) for p in patterns)
            obj_hit = any(p.search(obj) for p in patterns)
            if not (subj_hit or obj_hit):
                continue
            line = f"- {subj_label}: {obj}" if subj_label else f"- {obj}"
            if line in seen:
                continue
            seen.add(line)
            needle_count = sum(
                1 for p in patterns if (subj_label and p.search(subj_label)) or p.search(obj)
            )
            hay_stems = {
                self._stem(t) for t in re.findall(r"[a-z0-9]{3,}", f"{subj_label} {obj}".lower())
            }
            query_overlap = len(qterms & hay_stems)
            # Question-relevant claims FIRST (needle survives the cap), then
            # subject-grounded, then more entities matched, then original order.
            scored.append(
                ((-query_overlap, 0 if subj_hit else 1, -needle_count, order), line)
            )
        if not scored:
            return ""
        scored.sort(key=lambda t: t[0])
        lines = [line for _, line in scored[: self._entity_agg_max_claims]]
        return f"Known statements about {', '.join(entities)}:\n" + "\n".join(lines)

    def _build_evidence_context_from_ids(self, rt, closure_ids: list[str]) -> str:
        """Build a bounded text context from a set of record IDs."""
        if closure_ids:
            first_batch = rt.store.load_ir(ids=list(closure_ids))
            expanded_ids: list[str] = []
            seen_expanded: set[str] = set()

            def add(record_id: str) -> None:
                if record_id not in seen_expanded:
                    seen_expanded.add(record_id)
                    expanded_ids.append(record_id)

            for record in first_batch.records:
                add(record.id)
                if record.kind.value == "SPAN":
                    raw_id = record.attrs.get("raw_id")
                    if isinstance(raw_id, str) and raw_id:
                        add(raw_id)

            closure_ids = expanded_ids

        if not closure_ids:
            return ""

        batch = rt.store.load_ir(ids=list(closure_ids))
        text_snippets: list[str] = []
        seen: set[str] = set()
        for record in batch.records:
            if record.kind.value != "RAW":
                continue
            content = record.attrs.get("content")
            if isinstance(content, str) and content and content not in seen:
                seen.add(content)
                text_snippets.append(content)

        if text_snippets:
            return _trim_context("\n".join(text_snippets), self.budget)

        try:
            pack = rt.pack_ir(list(closure_ids), lens="general", budget=self.budget, mode="exact")
        except ValueError:
            pack = rt.pack_ir(list(closure_ids), lens="general", budget=self.budget)
        pack_dict = pack.to_dict() if hasattr(pack, "to_dict") else {}
        return _trim_context(json.dumps(pack_dict, sort_keys=True, indent=2), self.budget)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _db_path(self, scope_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in scope_id)
        return self._db_root / f"{safe}.db"

    def _runtime(self, scope_id: str):
        runtime = self._runtime_by_scope.get(scope_id)
        if runtime is None:
            runtime = _open_runtime(self._db_path(scope_id))
            self._runtime_by_scope[scope_id] = runtime
        return runtime


# ------------------------------------------------------------------
# Module-level helpers (avoid cluttering the class)
# ------------------------------------------------------------------

def _format_turn(turn: ConversationTurn) -> str:
    """Format a conversation turn into the canonical SEAM ingest string."""
    ts = turn.timestamp or ""
    return f"[{turn.speaker} {ts}] {turn.text}".strip()


def _open_runtime(db_path: Path):
    """Open (or reopen) a SeamRuntime for a per-scope SQLite database."""
    from seam_runtime.models import SentenceTransformerModel, embedding_settings_from_env
    from seam_runtime.runtime import SeamRuntime  # lazy

    db_path.parent.mkdir(parents=True, exist_ok=True)

    settings = embedding_settings_from_env()
    if settings.provider in {"hash", "local", "deterministic"}:
        global _DEFAULT_SENTENCE_TRANSFORMER_MODEL
        try:
            if _DEFAULT_SENTENCE_TRANSFORMER_MODEL is None:
                _DEFAULT_SENTENCE_TRANSFORMER_MODEL = SentenceTransformerModel(model_name="BAAI/bge-small-en-v1.5")
            model = _DEFAULT_SENTENCE_TRANSFORMER_MODEL
        except Exception as exc:
            raise RuntimeError(
                "LoCoMo benchmark requires a real embedding model. "
                "Install with `pip install sentence-transformers`, "
                "or set SEAM_EMBEDDING_PROVIDER=openai with a valid "
                "SEAM_EMBEDDING_API_KEY_ENV. "
                f"Default-model load failed: {exc}"
            ) from exc
        return SeamRuntime(str(db_path), embedding_model=model)

    return SeamRuntime(str(db_path))


def _remove_db_files(db_path: Path) -> None:
    """Remove a SQLite database file and any WAL / SHM sidecars."""
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def _trim_context(text: str, budget: int) -> str:
    if budget <= 0 or len(text) <= budget:
        return text
    return text[:budget]


def _uses_completion_token_budget(model: str) -> bool:
    model_id = model.lower()
    return model_id.startswith(("gpt-5", "o1", "o3", "o4"))


def _openai_short_answer(model: str, prompt: str, max_tokens: int = 64, diag_out: dict | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai answerer requires the openai package. "
            "Install with: pip install openai"
        ) from exc
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("openai answerer requires OPENAI_API_KEY in the environment")
    client = OpenAI(api_key=api_key)
    request: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _uses_completion_token_budget(model):
        # gpt-5 / o-series reasoning models reject temperature=0 and burn
        # hidden reasoning tokens against the completion budget. Mirror the
        # judge's handling at judge.py:148-150: floor the budget so the
        # actual answer text has room to emit, and minimize reasoning.
        # Reasoning tokens count against max_completion_tokens, so a small floor
        # (256) is exhausted by medium/high effort before the answer emits. Floor
        # generously (env-configurable) so the short answer has room after reasoning.
        _floor = int(os.environ.get("SEAM_BENCH_MAX_COMPLETION_TOKENS", "2048"))
        request["max_completion_tokens"] = max(max_tokens, _floor)
        # reasoning_effort is env-configurable (SEAM_BENCH_REASONING_EFFORT).
        # Default "low": the former hardcoded "minimal" is rejected by some
        # reasoning models (o4-mini supports low/medium/high/xhigh, not minimal),
        # and "low" is the broadly-supported minimum. Raise it (medium/high) to
        # actually engage reasoning for hard-category measurement.
        request["reasoning_effort"] = os.environ.get("SEAM_BENCH_REASONING_EFFORT", "low")
    else:
        request["max_tokens"] = max_tokens
        request["temperature"] = 0
    response = client.chat.completions.create(**request)
    raw = response.choices[0].message.content or ""
    if diag_out is not None:
        diag_out["provider"] = "openai"
        diag_out["model"] = model
        diag_out["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
        diag_out["content_len"] = len(raw)
        diag_out["content_preview"] = raw[:120]
        usage = getattr(response, "usage", None)
        if usage is not None:
            details = getattr(usage, "completion_tokens_details", None)
            diag_out["completion_tokens"] = getattr(usage, "completion_tokens", None)
            diag_out["reasoning_tokens"] = getattr(details, "reasoning_tokens", None) if details is not None else None
        diag_out["max_completion_tokens"] = request.get("max_completion_tokens")
        diag_out["reasoning_effort"] = request.get("reasoning_effort")
    return raw.strip()


def _claude_short_answer(model: str, prompt: str, max_tokens: int = 64, diag_out: dict | None = None) -> str:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError(
            "claude answerer requires the anthropic package. "
            "Install with: pip install anthropic"
        ) from exc
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("claude answerer requires ANTHROPIC_API_KEY in the environment")
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text if response.content else ""
    if diag_out is not None:
        diag_out["provider"] = "anthropic"
        diag_out["model"] = model
        diag_out["finish_reason"] = getattr(response, "stop_reason", None)
        diag_out["content_len"] = len(raw)
        diag_out["content_preview"] = raw[:120]
        usage = getattr(response, "usage", None)
        if usage is not None:
            diag_out["output_tokens"] = getattr(usage, "output_tokens", None)
        diag_out["max_tokens"] = max_tokens
    return raw.strip()


def _ollama_short_answer(model: str, prompt: str, max_tokens: int = 64, diag_out: dict | None = None) -> str:
    """FREE local answerer via an Ollama HTTP endpoint - no API cost, no new dep
    (urllib, mirroring nl_extract.py). Lets answer-quality be measured locally
    before any operator-gated paid run. Endpoint from SEAM_BENCH_OLLAMA_URL
    (default http://localhost:11434); model overridable via --answerer-model."""
    import json as _json
    import urllib.request

    base = os.environ.get("SEAM_BENCH_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    # Greedy + fixed seed + top_k=1 for the most deterministic decode this
    # backend allows (Ollama can still vary at temp=0 via batching; the seed
    # narrows it). Reproducibility matters for free A/B deltas.
    payload = _json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "top_k": 1,
                "top_p": 1.0,
                "seed": int(os.environ.get("SEAM_BENCH_OLLAMA_SEED", "42")),
                "num_predict": max_tokens,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    raw = (data.get("response") or "").strip()
    if diag_out is not None:
        diag_out["provider"] = "ollama"
        diag_out["model"] = model
        diag_out["endpoint"] = base
        diag_out["content_len"] = len(raw)
        diag_out["content_preview"] = raw[:120]
    return raw
