# Canonical graph fill preflight

Date: 2026-07-21

Status: corrected broad-profile free evidence gate failed; paid score gate canceled

Scope: LoCoMo cat1/cat3 matched-facade retrieval composition

## Decision

Keep canonical graph context default-off and do not advance it to a paid score
gate. Under the frozen capable-answerer `broad` retrieval profile, the
non-displacing `canonical-graph-fill/1` policy gained zero exact evidence
references across the full cat1/cat3 slice. It therefore failed the declared
free gate before any provider call.

The earlier +5 result used an unintended compact 8,000-character retrieval
budget. That baseline was not the frozen matched `gpt-4o` contract and the
result is retracted. The policy implementation remains a valid default-off
investigation path, but it has no matched-harness gain claim.

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
- Retrieval: frozen capable-answerer `broad` profile (search depth 300, context
  budget 60,000) with the facade response truncated to top-200; graph candidate
  uses the canonical retrieval orchestrator in `mode="graph"` and resolves
  graph records back to exact RAW provenance.

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

During the operator-authorized paid-gate dry run, an exact fresh-checkpoint
comparison stopped before provider initialization: the preflight baseline had
193 rows where the frozen predict-only checkpoint had 200. The cause was that
the preflight explicitly replaced the broad profile with an 8,000-character
context budget. Pinning 300/60,000 restored exact checkpoint parity and changed
the evidence result from +5 to zero. The runner now requires that parity and a
currently passing broad-profile gain list before it can accept `--allow-paid`.

## Corrected broad-profile results

| Measure | RAW baseline | graph standalone | fill-only candidate |
| --- | ---: | ---: | ---: |
| Cases with any gold evidence | 353 | 228 | 353 |
| Cases with all gold evidence | 252 | 42 | 252 |
| Exact gold-reference hits | 887 | 364 | 887 |
| Result rows | 75,490 | 14,513 | 75,522 |

Fill-only added 32 unique graph-reached RAW rows across the slice. It gained
zero exact gold references and lost zero. The declared free gate required at
least one gained reference and zero lost references, so it failed.

For auditability, the rejected compact-budget run reported 349 any-evidence
cases, 240 complete cases, and 859 exact hits at baseline versus 349, 241, and
864 for fill-only. Those values describe an unmatched 8,000-character
baseline and must not be quoted as matched `gpt-4o` evidence. The reserved-tail
result from that same invalid baseline is likewise not a promotion result.

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

The paid microgate is canceled. No answerer or judge call was made and no
private paid record was created. A future graph-composition proposal must first
produce a new non-displacing evidence gain under the pinned 300/60,000 broad
profile; only then may it request a separate paid authorization.
