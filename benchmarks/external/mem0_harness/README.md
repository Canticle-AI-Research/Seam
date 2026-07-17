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

## Distinct-count context preflight (default off)

`event-count/distinct/1` is an opt-in query-time context policy for questions
such as "how many" and "how many times." It prepends a disposable
`SEAM-COUNT/1` projection that organizes retrieved RAW turns by likely observed,
planned, negated, or reference-only status; asks the downstream harness
answerer to count distinct occurrences/items rather than mentions; and retains
RAW ids as provenance. It does not generate the answer or mutate stored MIRL.
All defaults remain unchanged.

Enable it on the facade with:

```bash
export SEAM_COUNT_CONTEXT_POLICY=event-count/distinct/1
```

Before any answerer or judge call, run the free structural preflight against a
private saved Mem0-harness result:

```bash
python -m benchmarks.external.mem0_harness.preflight_event_count_context \
    /path/to/mem0-harness-cat13.json --summary-only
```

The command makes zero provider calls, writes no files, and prints aggregate
projection diagnostics without reproducing licensed questions or memory text.
It is a structural gate only; it does not claim a score improvement. A scored
answerer microgate and any full harness run remain operator-gated.

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
