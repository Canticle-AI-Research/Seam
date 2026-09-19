# M1: memory formation audit

Date: 2026-09-13. Scope: the M1 investigation in
[the memory-formation roadmap](../roadmap/MEMORY_FORMATION.md), following
HISTORY#645. Recorded by HISTORY#649 in this publication-preparation branch.

**Result:** the current default path preserves the supplied RAW text and its
admitted proposition spans, but can lose structured speaker attribution, source
event identity, and separately supplied caption metadata. The speaker error
propagates into graph products. Unicode-only prose can produce no proposition
records while ingestion reports a compiled chunk. These are reproducible
formation gaps; this audit does not establish a benchmark-score improvement.

Status: local audit evidence and an M2 proposal, awaiting independent review and
protected-branch qualification. Runtime behavior is unchanged. This document
is the canonical audit, not a website edition. Publication was on hold when
the audit ran. The later publication authorization is held on the separate
reports-site branch (PR #264) and is deliberately not cited as a repository
path here, so this audit stands independently of the website publisher.

## Evidence boundary and reproduction

Audited runtime, adapters, and existing tests at
`614141c5aa96fd51d4dee2e09c186bb4035c0377` (merged roadmap PR #261).
The new observation helper is identified separately by its SHA-256 below.
Its runtime/adapter diff check passed before the probe. Inputs are deliberately
small synthetic examples, never benchmark answers or operator transcripts.

Run from a checkout with the project dependencies and the pinned embedding
model already cached:

```bash
python -m tools.memory_formation_m1 --output test_seam/formation-audit/new-observations.json
```

The helper refuses to overwrite an existing result, uses temporary SQLite
stores, disables model downloads, and supplies no answerer or extraction
provider. The real `SeamLocomoAdapter` uses
`st:BAAI/bge-small-en-v1.5@5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.
A separately labelled direct-ingest control uses `hash-bow-v1`; it provides no
retrieval-quality evidence. Generated store IDs and timestamps may change on a
rerun. Compare behavior and source links, not those incidental values.

The recorded invocation used the project virtual environment's Python and
`--output docs/audits/evidence/2026-09-13-memory-formation-m1/observations.json`.
It exited successfully with: `M1 synthetic compiler, loader, real-adapter,
storage and retrieval observations saved.`

## Path and metadata matrix

All source references below describe the audited revision, not a proposed
replacement. File paths are relative to the repository root.

| Boundary and source | Available input | Consumed or preserved | Gap or limitation |
| --- | --- | --- | --- |
| Native loader: `benchmarks/external/common/dataset.py::load_locomo_cases`, `_iter_locomo_sessions`; `common/types.py::ConversationTurn` | Session order/date, speaker, text, dialogue ID, separately supplied caption | Ordered turns containing speaker, text, session timestamp | Turn type has no dialogue/session identity or caption field. Synthetic distinct `dia_id` values become equal turns; separate caption text is absent. |
| Ingest runner: `benchmarks/external/locomo/ingest_only.py::main` | Loaded cases and grouped scope | Iterates the group's conversation through the same adapter | It does not restore metadata already omitted by the loader. |
| Adapter: `benchmarks/external/locomo/adapters/seam.py::ingest_turn`, `_format_turn` | Speaker, text, timestamp, conversation scope | Formats `[Speaker timestamp] text`, uses scope namespace, updates a query-time date anchor | Source reference hashes formatted text. Identical events with equal headers collapse. Structured speaker/timestamp arguments are passed only when derived facts are enabled. |
| Runtime: `seam_runtime/runtime.py::ingest_conversation_turn`, `_commit_ingest` | Text, source reference, namespace/scope, optional extractor and metadata | Calls `compile_nl`, persists IR/RAW and projections | Compiled document chunk count is floored at one even when the compiler emits no SPAN. |
| Compiler: `seam_runtime/nl.py::compile_nl`, `_validated_turn_metadata`, `_leading_subject` | Text and optional explicit turn envelope | Exact RAW, provenance, character-addressed admitted propositions; `Name:` prefix attribution | Default bracketed adapter input is not the colon speaker pattern. Without an explicit extractor the richer source-metadata path is unused. Later first-person sentences acquire subject `I`. |
| Segmentation: `seam_runtime/derived_fact_context.py::segment_propositions` | Whole source string | Exact trimmed source offsets around ASCII sentence punctuation | ASCII word admission excludes the Japanese control; abbreviations split, newline speakers do not, and there is no size cap. |
| Optional extraction: `seam_runtime/nl_extract.py`; `nl.py::compile_nl` | Explicit extractor plus validated source envelope | Grounding gates can admit richer records and retain source metadata | It is optional; its capability is not evidence that the default path supplies those records. Existing rejection gates must remain. |
| Canonical persistence: `seam_runtime/storage.py::_reconcile_entities`, `_entity_identity`, `_merge_entity_mentions` | Entities, explicit identity extension when supplied, namespace/scope, mentions | Exact-label coreference and evidence accumulation; explicit identity and boundary separation | Default floor supplies label-only `I`, so independent speakers' mentions coalesce inside the same boundary. This is not evidence that canonical identity machinery is absent. |
| Identity decisions: `seam_runtime/identity_resolution.py::propose_merge`, `accept_merge`, `split_merge` | Canonical/alias IDs, namespace/scope, supporting evidence | Auditable acceptance and reversible identity decisions | A downstream alias decision cannot recover source event metadata that never arrived. Alias discovery is not enabled merely by having a registry. |
| Graph projection: `seam_runtime/knowledge_graph.py::_project_record`; `storage.py::rebuild_graph_products`; `graph_products.py::_eligible_fact`, `_derive_products` | Canonical records, provenance, subject/object, record intervals, trust/currentness | Source-backed graph edges, entity/community summaries, cross-episode observations | Projection inherits wrong `I` attribution; generic `content` claims do not become semantic event/state histories merely by being projected. |
| Retrieval: `seam_runtime/runtime.py::retrieve`; `graph_source_selector.py::select_graph_source_raw`; adapter `answer` | Query, namespace/scope, eligible indexed records and optional graph-source selection | Supported source retrieval and boundaries; adapter returns complete source turns in this control | Retrieval success here does not validate structured identity, and a synthetic retrieval result is not a quality score. |

The Mem0-harness facade is a separate route:
`benchmarks/external/mem0_harness/seam_mem0_server.py::_split_speaker`,
`_epoch_to_iso`, and `add` preserve supplied message content after removing a
speaker prefix. A caption already appended inline therefore differs from a
separate native-loader caption field. Its LoCoMo timestamp conversion is
date-only; LongMemEval/BEAM handling preserves subday time. No live upstream
dataset or upstream service was checked in this audit.

## Confirmed observations and counterexamples

### M1-01: attribution error survives into a recurring graph observation

Minimal input is two turns: Alice says `I moved to Oslo. I enjoy painting.` on
2026-09-01; Bob says `I moved to Rome. I enjoy hiking.` on 2026-09-02.
In `observations.json`, `compiler.bracket_alice` and `compiler.bracket_bob`
show first-sentence subjects Alice/Bob, then subject `I`. In `adapter.claims`,
the painting and hiking claims have the **same persisted subject ID**.

The full recorded adapter probe also contains the duplicate Eve control below.
For that scope, `adapter.graph_product_build` accepts five facts and produces
four community summaries, nine entity summaries, and one observation. The
observation joins the painting and hiking claims across their two episodes:
`I has recurring content evidence across 2 episodes.` Both source references
remain available, but their subject grouping is incorrect.

Counterexamples: `compiler.colon_control` binds both propositions in
`Alice: I moved to Oslo. I enjoy painting.` to Alice. Existing exact-label
coreference, explicit-identity, boundary and alias-merge/split tests pass.
The defect is the source-to-subject mapping, not the absence of entity storage.

### M1-02: distinct dialogue events and separate captions disappear at intake

`loader.input` contains two Eve dialogue objects, IDs `D1:1` and `D1:2`, with
the same timestamp/text and a separate `blip_caption` marker
`M1_CAPTION_CEDAR`. `loader.output_turns` contains two equal three-field turns.
After adapter ingestion, `adapter.raw` contains one Eve RAW document.
The adapter's text-derived source reference cannot distinguish the events.

The explicit text-column checks were:

```sql
select count(*) from raw_docs where ns=? and content like ?;
```

For namespace `locomo:formation-audit`, the known-present controls `painting`
and `museum` each match one row. The supplied separate caption marker matches
zero, as does the deliberately absent `M1_UNSTATED_SENTINEL` control. This
supports a narrow native-loader loss claim. It does not support a blanket
claim that captions are missing from every LoCoMo/Mem0 store.

Counterexample: `distinct_source_reference_control` passes the same Eve text
twice to the runtime with distinct source references and retains two RAWs and
two provenance records. Persistence can preserve distinct events when intake
provides their identities. HISTORY#432 separately recorded a historical
Mem0-harness source-text check that disproved a blanket missing-caption theory.

### M1-03: segmentation coverage and chunk accounting need an explicit contract

| Artifact section | Minimal input | Observed result |
| --- | --- | --- |
| `compiler.unicode`, `persisted_unicode` | `東京が好きです。大阪に住んでいます。` | Exact RAW and provenance; zero SPAN/CLM. Persisted document reports `chunk_count: 1`, `extraction_status: compiled`. |
| `compiler.abbreviation` | `Dr. Chen moved to Oslo. She works there.` | Three propositions: `Dr.`, `Chen moved to Oslo.`, `She works there.`; subjects Dr, Chen, She. |
| `compiler.newline_speakers` | `Alice: I like tea` then newline `Bob: I like coffee` | One proposition assigned to Alice. This tests general text ingestion, outside the usual one-turn-per-adapter-call shape. |
| `compiler.unpunctuated_long` | `word ` repeated 2,000 times | Input length 10,000 characters; one 9,999-character span; RAW retains the trailing space. No bounded chunk size follows from sentence splitting. |

For every emitted span checked by the probe, the referenced RAW slice equals
the content claim exactly. The empty-span case's `span_text_exact: true` is
vacuous; it is not a coverage pass. RAW preservation and proposition coverage
must be separate assertions in M3 acceptance.

### M1-04: temporal prose survives, structured event/state meaning is limited

`compiler.state_changes` compiles `Alice: I lived in Oslo. I now live in Rome.`
as two asserted `content` claims with unset `t0`/`t1`; no EVT/STA records are
emitted. The adapter's timestamped control claims also have unset intervals,
and `adapter.raw[*].source_metadata` is null on the default path. Source dates
and change wording remain verbatim in RAW/claim text.

This is evidence of a structured representation limitation, not evidence that
all time information is lost or that every pair of residence statements is a
contradiction. Message time, asserted event time, ingestion time and unknown
time must remain distinct. Current functional/multivalued state reconciliation,
as-of graph intervals and conservative missing/equal-time behavior already
have passing controls; reuse them when source-grounded temporal facts arrive.

### Preserved source and graph behavior

`adapter.kinds` records three RAWs, three provenance records, five spans, five
claims and six entities for the four supplied turns including duplicate Eve.
`adapter.text_column_checks` proves positive text controls. `adapter.retrieval`
returns the complete Alice, Bob and Eve source turns for `What does Alice
enjoy?`; `generated_answer` is null. The graph has 74 edges despite zero
canonical REL rows in this default-floor sample. Claims and provenance already
feed a graph; REL row count alone is not a graph-coverage diagnostic.

## Historical constraints on the proposal

The governing contract is `SEAM_SPEC_V0.1.md` plus `docs/MIRL_V1.md`: source
phrasing, provenance, meaning, uncertainty and temporal distinctions survive
transformation. HISTORY#311 established the shared compiler path; HISTORY#317
records why regex enrichment became opt-in. Restoring indiscriminate regex
triples would repeat a grounding problem, not meet this audit's exit.

The checked KB `docs/kb/seam-internals/lever-graveyard.md` records
`entity_grounded_scoring`, dossier, entity aggregation and decomposition as
null/negative experiments, with decomposition harmful (#358/#396/#405).
The June 15 entity-aggregation audit also separates expanded lexical overlap
from demonstrated answer quality. Its older category names are inconsistent
with the corrected mapping: category 1 is multi-hop, category 4 is single-hop.
Do not transfer those labels or proxy gains into a new quality claim.

HISTORY#458/#459 established a correct default-off identity-fold mechanism but
no alias-candidate fuel in the recorded three-conversation probe
(`pairs_examined=0`). Exact-label identities were already deduplicated. That
historical result is compatible with today's wrong generic pronoun identity:
neither is evidence that turning on alias folding fixes attribution. The new
evidence justifies fixing intake contracts, not reviving killed ranking knobs.

## Narrow M2 proposal and dependency order

M1 supplies observations, not a selected implementation. Before M2 acceptance,
complete B1's metadata contract and E1's evaluation design as required by the
roadmap. Credential provisioning and report-home discovery can proceed
independently; no paid run is authorized by this audit.

1. **M2 design:** define a versioned source-event envelope with stable event
   identity, speaker evidence, timestamps with explicit meaning/precision,
   namespace/scope, exact source anchors, and separately attributed attachments.
   Make validated metadata usable by the faithful default compiler independently
   of extractor selection. Distinguish subject-of-proposition from speaker;
   first person may bind to a validated speaker, but a sentence about Bob inside
   Alice's turn must not automatically become a fact about Alice.
2. **M3 implementation/fixtures:** choose Unicode-safe, bounded segmentation
   that preserves exact offsets, speaker/discourse context and RAW fallback.
   Cover abbreviations, newline boundaries, Unicode-only input, long input,
   malformed envelopes and partial compilation. Explicitly report an empty
   proposition result. M2 names these fixtures; M3 implements their behavior.
3. **M4 implementation/fixtures:** project source-grounded event/state meaning
   into existing identities, lifecycle intervals and graph products. Preserve
   distinct repeated events and idempotent replay separately; preserve unknown
   time, contradictions, provenance and reversible identity decisions. Verify
   that Alice/Bob cannot generate the shared `I` observation above.
4. **Evaluation:** first compare formation correctness against these diagnostic
   controls and non-regression suites. Then use E1's pinned dataset, provider,
   answerer/judge, budget and split contract to measure retrieval/answer effects.
   Synthetic controls are not a holdout, calibration set or benchmark score.

Open design questions for B1/M2: fallback event identity when a source has no
ID; attachment provenance and textual rendering; partial/unknown speaker
handling; quoted speech; permitted chunk overlap and size budgets; restart and
cache migration when source identity changes. No new global identity registry
or default retrieval-policy switch is proposed.

## Verification

The first command ran against the same audited runtime/tests in the separate
report-site checkout; its runtime and named test diff against the base was
empty. The second ran in this M1 checkout. No external-service tests were
selected and neither run reported skips. Python below denotes the existing
project virtual environment interpreter.

`python -m pytest tests/audit/test_conversation_turn_compile.py tests/audit/test_entity_coreference.py tests/audit/test_identity_resolution.py tests/audit/test_s7_entity_evidence.py tests/audit/test_s7_temporal_identity_admission.py -q -m 'not external' -o addopts= -p no:cacheprovider`

Observed output: `55 passed in 4.75s`.

`python -m pytest tests/fidelity/test_nl_extract.py tests/audit/test_graph_products.py tests/audit/test_graph_source_selector.py -q -m 'not external' -o addopts= -p no:cacheprovider`

Observed output: `98 passed in 0.42s`.

`python -m ruff check tools/memory_formation_m1.py`

Observed output: `All checks passed!`.

The conversation-compile suite enables legacy regex enrichment in its fixture;
it validates that compatibility path. The observation probe explicitly
disables enrichment and derived facts to inspect the default path. Existing
tests passing do not mean the demonstrated gaps have been fixed. No runtime
implementation or new behavior-locking regression tests were added in M1.

## Evidence manifest

| Artifact | SHA-256 | Scope |
| --- | --- | --- |
| `docs/audits/evidence/2026-09-13-memory-formation-m1/observations.json` | `85a3096c0010d5875ad7ea630704f4936be10350ee9141a604c3a8148550b8df` | Synthetic compiler, native loader, real adapter, specific storage controls, graph products and retrieval observations |
| `tools/memory_formation_m1.py` | `671835eef3b42f86651df6455cafbca96ebd6de103b656370931d2ce8d5bedb7` | Exact observation helper used for this artifact |

Temporary databases are not retained. Durable evidence contains only the
synthetic examples and results above. No credentials, private conversation
links, operator transcripts or website content are included.
