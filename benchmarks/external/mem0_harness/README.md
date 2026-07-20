# Running SEAM inside mem0's own benchmark harness

SEAM answers **mem0's own harness** (`mem0ai/memory-benchmarks`) as a drop-in
memory server. This is the reverse of the in-harness head-to-head (HISTORY#384,
where mem0/Zep ran inside SEAM's harness) and the basis for a number directly
comparable to mem0's published tables.

## Why an HTTP server (and not an in-process adapter)

mem0's harness is hardwired to Mem0: its `--backend oss` mode is an HTTP client
(`benchmarks/common/mem0_client.py`) that talks to a Mem0 server over three REST
endpoints. There is no in-process third-party injection point. So the shim is a
server that implements those endpoints; the harness runs **unmodified** against
it.

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /memories` | `{messages:[{role,content}], user_id, timestamp?}` | `{"results":[...]}` |
| `POST /search` | `{query, user_id, limit}` | `{"results":[{memory, score, id, created_at}]}` |
| `DELETE /memories?user_id=` | (or JSON body `{user_id}`) | `{"message":...}` |

`seam_mem0_server.py` implements these on top of the real `SeamLocomoAdapter`:
one SEAM namespace per `user_id`, ingest via the adapter's exact conversation-
turn path, and search returning the ranked RAW turn strings (`[Speaker date]
text` — the shape their `format_search_results` + answerer read). Retrieval
honors `RetrievalFlags` from the environment, so the validated
conversation/temporal/profile stack applies identically.

The default-off `grounded-clm/1` policy can additionally serve explicit,
speaker-grounded MIRL facts beside those RAW turns. It does not change the
default response.

> The earlier in-process `adapter.py` targeted an interface the current harness
> does not expose and was never runnable against the real harness; it was
> retired in favor of this server (HISTORY#394).

## Run it

1. **Start SEAM as the memory server** (this repo), matching a validated stack:

   ```bash
   export SEAM_CONVERSATION_ADAPTER=conversation/2
   export SEAM_INFERENCE_POLICY=inference/high-confidence/1
   export SEAM_TEMPORAL_POLICY=temporal/1
   export SEAM_RETRIEVAL_PROFILE=broad
   python -m benchmarks.external.mem0_harness.seam_mem0_server --port 8900
   ```

2. **Point their harness at it** (in a clone of `mem0ai/memory-benchmarks`):

   ```bash
   pip install -r requirements.txt
   # FREE structural smoke first — stops after retrieval, no answerer/judge spend:
   python -m benchmarks.locomo.run --project-name seam-smoke \
       --backend oss --mem0-host http://127.0.0.1:8900 --predict-only

   # Full run (PAID: their default answerer+judge are gpt-4o, top_k up to 200):
   python -m benchmarks.locomo.run --project-name seam \
       --backend oss --mem0-host http://127.0.0.1:8900
   ```

## Grounded derived-facts lever (default off)

`grounded-clm/1` is one frozen benchmark ingest-and-retrieval policy. It runs
SEAM's local grounded extractor and serves only singular first-person facts
that resolve to the explicit turn speaker. Unresolved pronouns and contractions
fail closed in v1. It stores readable rich CLMs with exact field spans and
CLM→SPAN→RAW provenance, and serves only gap-free S-R-O partitions that do not
drop clause qualifiers or recombine text across clauses. It reserves at most
20% of the rows actually returned for `SEAM-FACT/1` rows.
At least 80% of a full response remains RAW, and every served fact's source
RAW appears before that fact. The same ceiling holds for every response
prefix, including the harness's scored 10/20/50/200 cutoffs.

Enable it only against a new, isolated candidate database root:

```bash
unset SEAM_PGVECTOR_DSN SEAM_PGVECTOR_TABLE SEAM_EMBEDDING_PROVIDER
export SEAM_DERIVED_FACTS_POLICY=grounded-clm/1
export SEAM_OLLAMA_MODEL=qwen2.5:14b  # choose a locally installed model
python -m benchmarks.external.mem0_harness.seam_mem0_server \
    --db-path /tmp/seam-grounded-clm-candidate --port 8900
```

For this candidate, run the upstream harness with `--max-workers 1`. The
facade dispatches blocking ingest/search work through FastAPI's worker
threadpool, but v1 deliberately does not claim concurrent extraction
reproducibility, and local Ollama commonly serializes generation internally.

The first enablement writes an immutable configuration manifest and a
content-addressed extraction cache inside that root. A pre-existing database
without the manifest, or a later model-digest/prompt/policy fingerprint
mismatch, fails closed. The configured Ollama tag is resolved to its installed
content digest; an optional configured digest is verified rather than trusted,
and the installed digest is checked again before every uncached generation.
V1 accepts only a credential-free loopback Ollama origin. Extraction errors
also fail closed instead of silently becoming empty facts. The candidate is
pinned to its own SQLite vector index and the exact local
`BAAI/bge-small-en-v1.5` revision recorded in its manifest. It refuses a leaked
`SEAM_PGVECTOR_DSN` or remote embedding provider; run the separate floor
baseline with those variables unset as well.
Use a separate fresh floor-only store for the baseline: rich CLMs participate
in retrieval as well as presentation, so toggling presentation on one shared
enriched store is rejected rather than treated as a valid A/B.

Count and temporal projections take precedence when co-enabled; derived facts
run only when neither specialized projection fires. The policy uses local
Ollama only and makes no provider call, but a paid answerer/judge run remains
operator-gated. `DELETE /memories` drops the user's candidate database and its
cache ownership; an extraction cache row is removed once no remaining user
owns it.

This is the auditable LoCoMo/Mem0 evaluation slice of the derived-facts
architecture, not yet a general SEAM product surface. Core chat/MCP ingestion
and serving remain a separate productization step.

## Distinct-count context preflight (default off)

`event-count/distinct/1` is the original opt-in query-time context policy for
questions such as "how many" and "how many times." `event-count/distinct/2`
keeps the same default-off, disposable boundary and adds explicit same-event
groups inside the rendered `SEAM-COUNT/2` block. Every group retains all member
RAW ids and texts, marks whether the question-specific action/object is
an explicit direct match, distinguishes occurrence counts from item/event
counts, and carries ordinal hints without turning them into an answer or
durable truth. Repeated
descriptions in one group are counted once. Plans or mentions qualify only when
the question asks about plans or mentions.

Neither policy generates the answer or mutates stored MIRL. Flag-off and v1
behavior remain unchanged.

Enable it on the facade with:

```bash
export SEAM_COUNT_CONTEXT_POLICY=event-count/distinct/2
```

Before any answerer or judge call, run the free structural preflight against a
private saved Mem0-harness result:

```bash
python -m benchmarks.external.mem0_harness.preflight_event_count_context \
    /path/to/mem0-harness-cat13.json \
    --policy event-count/distinct/2 --summary-only
```

The command makes zero provider calls, writes no files, and prints aggregate
projection/grouping diagnostics without reproducing licensed questions or
memory text. It is a structural gate only; it does not claim a score
improvement. The committed microgate runner remains pinned to the historical
v1 experiment; any v2 answerer microgate or full harness run requires separate
operator authorization.

## Comparability notes (read before quoting a number)

- **Their judge is far more lenient than ours** — a binary CORRECT/WRONG
  "J-score" that credits partial lists, paraphrases, extra detail, and ±14-day
  dates. SEAM's number here reads *higher* than its judge/1 number and is the
  fair basis for a mem0-table comparison.
- **Their defaults differ**: gpt-4o answerer+judge (vs our gpt-4o-mini), top_k
  200, categories 1–4. Match these deliberately.
- **`--predict-only` is free** and proves the round-trip before any gpt-4o spend.
- Pin a commit of `mem0ai/memory-benchmarks`; it is actively developed.

The endpoint contract is regression-pinned by
`tests/audit/test_seam_mem0_server.py`.
