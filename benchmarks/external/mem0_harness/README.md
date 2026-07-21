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

The facade preserves the historical date-only timestamp envelope for upstream
LoCoMo ids. Audited LongMemEval and BEAM ids retain the full UTC second-level
timestamp because those contracts include sub-day temporal anchors.

The endpoint contract is shared by the upstream LoCoMo, LongMemEval, and BEAM
runners. SEAM's local LongMemEval/BEAM modules validate dataset structure but
do not reimplement their task-specific prompts or judges. Competitive and
predict-only execution goes through the pinned upstream checkout via
`upstream_runner.py`; revision drift, non-loopback facade URLs, missing BEAM
dependencies, a missing BEAM cache without download approval, paid execution
without approval, and accidental BEAM-10M runs all fail closed. Targeted
`--plan` prints these gates and never launches the harness.

The default-off `grounded-clm/1`, `grounded-clm/2`, and
`sentence-grounded-clm/1` policies can additionally serve explicit,
speaker-grounded MIRL facts beside those RAW turns. They do not change the
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

LongMemEval and BEAM commands are documented in their respective runner
READMEs. The harness source is sufficient for SEAM-side evaluation; installing
or launching Mem0 itself is not required because SEAM supplies the OSS HTTP
contract.

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

### Sentence-grounded facts (default off)

`sentence-grounded-clm/1` is the higher-coverage successor candidate. The local
model writes a concise indexing paraphrase and selects an eligible source
sentence by integer index; SEAM itself attaches the exact canonical sentence,
offsets, sentence hash, fact hash, speaker resolution, and CLM→SPAN→RAW chain.
Paraphrases that drop source numbers or sentence-level negation, retain first
person, or fail to name the canonical speaker are rejected. Accepted facts use
the same source-before-fact ordering and 20% prefix ceiling as strict
`grounded-clm/*` facts.

The free preflight passed on the 63 stored cat1/cat3 matched-run misses with
the shared runtime prompt: 51 misses reached, 46 facts closer to the query than
RAW, mean closure +0.1138, exact binding 0.9956, and local fact/evidence cosine
0.7147. This is a direction/build gate, not a judged score claim.

Run or resume that provider-free gate:

```bash
HF_HUB_CACHE=/media/terrabyte/T7/hf-cache \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 SEAM_OLLAMA_TIMEOUT_S=600 \
python -m benchmarks.external.mem0_harness.preflight_sentence_grounded_facts \
  /path/to/matched-cat13-final.json \
  --model qwen2.5-7b-1m:latest --summary-only
```

Enable the runtime candidate only on a fresh shadow store:

```bash
unset SEAM_PGVECTOR_DSN SEAM_PGVECTOR_TABLE SEAM_EMBEDDING_PROVIDER
export SEAM_DERIVED_FACTS_POLICY=sentence-grounded-clm/1
export SEAM_SENTENCE_FACT_MODEL=qwen2.5-7b-1m:latest
python -m benchmarks.external.mem0_harness.seam_mem0_server \
  --db-path /tmp/seam-sentence-grounded-candidate --port 8900
```

The default model/config matches the passed free gate (4096 context, 512 output)
and is frozen with its installed Ollama digest in the store manifest. A paid
paired answerer/judge microgate is still operator-gated.

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

## Canonical graph evidence/displacement preflight

Before enabling graph-composed context in the facade, measure the existing
`knowledge_edges` retriever against preserved matched-harness SQLite stores:

```bash
unset SEAM_PGVECTOR_DSN PGVECTOR_TEST_DSN SEAM_EMBEDDING_PROVIDER
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m benchmarks.external.mem0_harness.preflight_graph_memory \
  /path/to/matched-store-root --run-id <run-id> --summary-only
```

The command copies the stores to a temporary directory before current graph
schema/backfill code opens them, validates every stored RAW turn against the
canonical LoCoMo dataset, and runs the matched facade RAW baseline at top-200.
The baseline pins the frozen capable-answerer `broad` profile (retrieval depth
300, context budget 60,000) before the harness truncates the returned surface
to 200 rows. Substituting the compact 8,000-character budget is not matched and
can create false evidence gains.
The default candidate fills only unused top-200 rows with genuinely new RAW
evidence reached through the canonical graph retriever, so it cannot displace a
baseline row. Pass `--composition reserved-tail` to separately test the more
aggressive policy that reserves up to 40 graph rows and measures the resulting
displacement. The command never emits licensed text and makes zero provider
calls. Promotion requires at least one newly present exact gold turn and zero
displaced exact gold turns; this is not an answer score.

Only a composition that passes this broad-profile free gate may advance to a
paid microgate. A provider-free dry run of the paired runner additionally
requires explicit gain-case ids from that passing report and revalidates them
before accepting `--allow-paid`:

```bash
python -m benchmarks.external.mem0_harness.microgate_graph_memory \
  /path/to/matched-store-root --run-id <run-id> \
  --predicted-dir /path/to/fresh-predict-only \
  --sentinel-record /path/to/prior-matched-gpt4o-record.json \
  --harness-root /path/to/pinned-memory-benchmarks \
  --gain-ids convN_qN,...
```

The current broad-profile result has zero gained references, so there are no
valid gain ids and no paid graph-fill microgate is authorized.

The policy can still be enabled for controlled local investigation with:

```bash
export SEAM_GRAPH_CONTEXT_POLICY=canonical-graph-fill/1
python -m benchmarks.external.mem0_harness.seam_mem0_server \
  --db-path /tmp/seam-graph-fill-candidate --port 8900
```

The policy is default-off. It uses the same canonical `knowledge_edges` graph
retriever as the dashboard and appends only into vacant result rows; it never
removes or reorders a primary RAW result.
