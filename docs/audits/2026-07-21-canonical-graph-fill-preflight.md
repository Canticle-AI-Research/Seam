# Canonical graph fill preflight

Date: 2026-07-21

Status: free evidence gate passed; paid score gate not run

Scope: LoCoMo cat1/cat3 matched-facade retrieval composition

## Decision

Keep canonical graph context default-off and advance only the non-displacing
`canonical-graph-fill/1` policy. It appends unique RAW evidence reached through
SEAM's existing `knowledge_edges` retriever only when the primary top-k result
has vacant rows. It never removes or reorders a primary row.

Do not advance the aggressive reserved-tail composition. It found the same five
additional exact evidence references but displaced one exact reference already
present in the baseline.

This is an evidence-presence result, not an answer score, benchmark win, or
production-policy promotion. A paired paid microgate still requires explicit
operator approval.

## Matched corpus and execution contract

- Dataset: committed `benchmarks/external/locomo/data/locomo10.json`.
- Upstream harness: clean `/tmp/memory-benchmarks` checkout at audited revision
  `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`.
- Ingest/search run: upstream predict-only mode, all 1,540 questions, top-k 200,
  loopback SEAM facade, run id `4a959f93`.
- Provider boundary: zero provider calls. The upstream predict-only client still
  constructs an OpenAI client before doing local work, so a visibly
  non-credential placeholder satisfied that constructor; an accidental request
  would have failed.
- Store validation: each copied per-conversation SQLite store's RAW envelopes
  had to equal the committed dataset turn set before measurement.
- Categories measured: cat1 and cat3, 378 questions, 1,076 resolved gold
  references plus seven unresolved dataset references.
- Retrieval: frozen matched facade RAW baseline at top-200; graph candidate uses
  the canonical retrieval orchestrator in `mode="graph"` and resolves graph
  records back to exact RAW provenance.

Older preserved replay stores were rejected rather than reused: conversations
1 and 2 were each missing two canonical RAW turns. Fresh exact stores were
generated through the pinned upstream predict-only route.

## Reproducibility repair

The first repeated reserved-tail probe exposed process-dependent score ties in
`SQLiteGraphAdapter.search()`. Graph-expanded ids were held in a set and
iterated without ordering, so equal-score candidates could change across
process hash seeds. The adapter now sorts seed ids and orders final ties by
`(-score, record.id)`. Focused regression coverage pins that order.

The initial prototype also incorrectly shortened the baseline to 160 rows even
when graph retrieval supplied fewer than 40 unique rows. That result was
discarded. The audited reserved-tail implementation displaces exactly the
number of unique graph rows it actually adds.

## Results

| Measure | RAW baseline | graph standalone | fill-only candidate |
| --- | ---: | ---: | ---: |
| Cases with any gold evidence | 349 | 228 | 349 |
| Cases with all gold evidence | 240 | 42 | 241 |
| Exact gold-reference hits | 859 | 364 | 864 |
| Result rows | 66,250 | 14,513 | 69,654 |

Fill-only added 3,404 unique graph-reached RAW rows across the slice. It gained
five exact gold references across four questions, made one question newly
complete, and lost zero exact references, any-evidence cases, or complete
cases. The declared free gate required at least one gained reference and zero
lost references, so it passed.

The aggressive 40-row reserved-tail candidate added 3,730 unique graph rows.
It gained five exact references and one complete case but lost one exact
reference and one complete case. It therefore failed the same zero-displacement
gate and remains unshipped.

## Runtime policy

The real Mem0-compatible facade now accepts
`SEAM_GRAPH_CONTEXT_POLICY=canonical-graph-fill/1` or the equivalent CLI flag.
The default remains `off`. When enabled, graph search is skipped entirely at
top-k capacity; otherwise it probes at most 40 graph-reached RAW rows so a
baseline duplicate cannot hide a later unique row, then appends only
content-unique rows up to the actual number of vacancies.

The free preflight copies source stores to a temporary directory before current
graph schema/backfill code opens them, rejects pgvector or remote embedding
configuration, validates exact RAW corpus parity, and emits only ids/counts --
never licensed conversation, question, answer, or memory text.

Reproduction command for already matched local stores:

```bash
unset SEAM_PGVECTOR_DSN PGVECTOR_TEST_DSN SEAM_EMBEDDING_PROVIDER
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m benchmarks.external.mem0_harness.preflight_graph_memory \
  /path/to/matched-store-root --run-id <run-id> \
  --composition fill-only --summary-only
```

## Promotion boundary

The next step is an operator-approved same-day paired paid microgate under the
frozen `gpt-4o` answerer/judge contract. Baseline and candidate must use the
same fresh ingest and harness revision. Promotion still requires a real net
answer-score improvement with no candidate-caused sentinel regression; the
free evidence result alone does not authorize a full paid run or default-on
policy.
