# SEAM v0.1

SEAM stands for Surface Encoded Agent Memory.

Product names and deployment roles are defined in [SEAM products](docs/PRODUCTS.md).
This naming update preserves the technical contracts below (HISTORY#634).

It is a universal, machine-first language for storing, compressing, retrieving, and evolving information for AI systems. It is designed to work across:

- vector databases
- relational databases
- graph databases
- document stores
- retrieval pipelines
- context-window packing
- CLI tooling

SEAM is not optimized for human readability. It is optimized for:

- loss-minimizing canonicalization
- semantic retrieval
- deterministic parsing
- cross-system portability
- progressive token compression

## 1. Design Goals

SEAM exists to solve one problem:

Store as much usable meaning as possible in as few tokens as possible without losing recoverable information.

This is done by separating memory into layers instead of forcing one representation to do everything.

### 1.1 Core principles

1. Raw data is never the same thing as compressed memory.
2. Compression should remove redundancy, not meaning.
3. Canonical structure should be stable even if natural-language phrasing changes.
4. Every compressed form must remain traceable back to evidence.
5. Memory objects must be portable across storage backends.
6. The language must support iterative improvement over time.

## 2. The Four-Layer Memory Stack

SEAM uses four layers.

### 2.1 `RAW`

Verbatim source material.

Examples:

- chat messages
- code snippets
- documents
- logs
- API responses
- transcripts

Properties:

- lossless
- append-only
- provenance-first
- not optimized for prompt injection

### 2.2 `IR`

Canonical semantic intermediate representation.

This is the main SEAM language.

Properties:

- machine-readable
- line-oriented
- deterministic
- normalized
- database-friendly

### 2.3 `PACK`

Dense retrieval and context-window form.

Properties:

- compact
- salience-ranked
- optimized for prompt budget
- derivable from `IR`

### 2.4 `LENS`

Task-specific projections over memory.

Examples:

- coding lens
- project lens
- user preference lens
- temporal lens
- debugging lens

Properties:

- view-specific
- reversible to `IR` references
- optimized for a downstream agent or tool

## 3. Translation Model

SEAM needs an explicit translator because the language is not for humans.

Natural language is the surface form.
SEAM is the semantic machine form.

The translator is the bridge between them.

### 3.1 Three translation directions

1. `NL -> IR`
2. `IR -> PACK`
3. `IR or PACK -> NL`

This means SEAM is not just a storage format.
It is a compile/decompile system for memory.

### 3.2 Translator roles

#### Compiler

Compiles natural language, documents, logs, code comments, and raw text into canonical `IR`.

Responsibilities:

- entity extraction
- predicate normalization
- contradiction detection
- temporal normalization
- provenance binding
- salience tagging

#### Packer

Compiles `IR` into dense `PACK` optimized for context windows and retrieval budgets.

Responsibilities:

- symbol substitution
- motif compression
- lens-specific shaping
- token-budget enforcement

#### Decompiler

Reconstructs natural language from `IR` or `PACK`.

Responsibilities:

- expand symbols
- restore predicate names
- resolve references
- express uncertainty correctly
- preserve key provenance when requested

### 3.3 Round-trip contract

SEAM must support round-tripping.

The standard round-trip path is:

```txt
natural language -> IR -> PACK -> IR-equivalent -> natural language
```

The generated natural language does not need to preserve the original wording.
It must preserve:

- semantic content
- important structure
- uncertainty
- contradiction state
- provenance references when requested

### 3.4 Translator modes

The decompiler should support at least these output modes:

- `nl.min`: shortest faithful natural language
- `nl.std`: standard readable natural language
- `nl.exp`: expanded explanation with provenance
- `nl.tool`: tool-facing structured text for another model

Example:

```txt
decompile(mode=nl.min)
decompile(mode=nl.std)
decompile(mode=nl.exp)
```

## 4. SEAM Object Model

SEAM is built from a small set of universal object types.

### 4.1 `ent`

Stable entity.

Examples:

- person
- org
- project
- system
- file
- concept
- model
- database

### 4.2 `clm`

Claim or fact unit.

Examples:

- a project goal
- a user preference
- a system property
- an assumption
- a requirement

### 4.3 `evt`

Time-bound occurrence.

Examples:

- a decision
- a deployment
- a user request
- a failure
- a meeting

### 4.4 `rel`

Typed relationship between two entities or memory objects.

Examples:

- owns
- depends_on
- caused_by
- contradicts
- derived_from

### 4.5 `state`

Resolved current state for an entity or topic.

This is not raw truth. It is the current best canonical state after reconciliation.

### 4.6 `src`

Source or provenance anchor.

Examples:

- conversation turn
- file path
- URL
- document section
- database row

### 4.7 `evd`

Evidence binding between a semantic object and one or more sources.

### 4.8 `delta`

A state transition or revision.

Used when new information changes prior interpretation.

### 4.9 `alias`

Alternative surface form for an entity, predicate, or concept.

Important for semantic normalization and cross-model retrieval.

## 5. Canonical Record Shape

SEAM `IR` is line-oriented. One line is one record.

General record form:

```txt
<tag>|<id>|<field>=<value>|<field>=<value>|...
```

Tags:

- `@` entity
- `#` claim
- `!` event
- `>` relation
- `~` state
- `^` evidence
- `%` source
- `+` delta
- `=` alias

Example:

```txt
@|u:1|t=user|name="ivan"
@|p:1|t=project|name="SEAM"
#|c:1|s=p:1|p=goal|o="universal AI memory language"
#|c:2|s=p:1|p=property|o="loss-minimizing compression"
!|e:1|a=u:1|v=propose|o=p:1|ts=2026-04-11
>|r:1|s=u:1|p=owns|o=p:1
~|st:p:1|goal="universal AI memory language"|property=["loss-minimizing compression","db portable","rag native"]
%|src:1|kind=chat|ref="thread://local/turn/2"
^|x:1|obj=c:1|src=src:1|span="i want to design a language for ai"
```

## 6. Field Semantics

Required field abbreviations:

- `t`: type
- `s`: subject
- `p`: predicate
- `o`: object
- `a`: actor
- `v`: verb
- `ts`: timestamp
- `src`: source id
- `obj`: referenced object
- `ref`: external reference

Field naming rules:

1. Use short stable keys in `IR`.
2. Expand only in developer tools or human-facing renderers.
3. Prefer canonical enumerated predicates where possible.
4. Allow arbitrary extension fields with namespace prefixes.

Example extension:

```txt
#|c:9|s=p:1|p=req|o="must support sqlite"|ext.rank=0.91
```

## 7. Value Encoding Rules

### 7.1 Primitive types

- strings: `"..."` quoted
- ids: unquoted if stable and safe
- numbers: unquoted
- booleans: `0` or `1`
- null: `_`
- arrays: `[a,b,c]`
- maps: `{k:v,k2:v2}`

### 7.2 Canonicalization rules

1. Trim surface noise.
2. Normalize tense when possible.
3. Normalize core entity names into stable ids.
4. Preserve uncertainty as explicit structure instead of hedged prose.
5. Preserve contradiction as explicit structure instead of overwriting.

Example:

```txt
#|c:10|s=u:1|p=pref.ui_theme|o=dark|conf=0.72
#|c:11|s=u:1|p=pref.ui_theme|o=light|conf=0.35|status=contradicted
```

## 8. Loss Minimization Strategy

SEAM does not define "lossless" as "the original words are still present in the compressed object."

It defines "lossless enough" through recoverability:

Information is preserved if the system can recover:

- the semantic meaning
- the structural relationships
- the provenance
- the temporal ordering
- the uncertainty state

Anything required beyond that must remain in `RAW`.

This is the core contract:

`RAW` preserves phrasing.
`IR` preserves meaning.
`PACK` preserves utility.

## 9. PACK: Dense Context Form

`PACK` is a compressed projection generated from `IR`.

It is intended for prompt injection, context windows, and agent recall.

### 9.1 PACK objectives

- minimize tokens
- maximize task relevance
- preserve references to canonical records
- support fast reconstruction

### 9.2 PACK shape

Example:

```txt
P|lens=design|focus=p:1|refs=[st:p:1,c:1,c:2,e:1]
P|p:1|goal=universal_ai_memory_lang;props=loss_min_compress,db_portable,rag_native,context_pack
P|open|need=formal_grammar,sqlite_schema,cli_ops,improvement_loop
```

Rules:

1. Replace repeated long strings with normalized symbols.
2. Collapse common predicates into packed keys.
3. Emit only the minimal references needed for downstream reconstruction.
4. Keep `PACK` disposable and regenerable.

## 10. LENS: Task-Specific Views

Lenses prevent one universal summary from becoming bloated or ambiguous.

A lens is a projection recipe:

```txt
lens:<name> = filter + score + pack
```

Examples:

- `lens:recall.user`
- `lens:project.status`
- `lens:code.intent`
- `lens:rag.query`
- `lens:db.sync`

Each lens should specify:

- objects included
- ranking rules
- packing rules
- max token budget

## 11. Storage Mappings

SEAM is universal because the same record model maps cleanly to many systems.

### 11.1 SQLite / Postgres

Recommended base tables:

- `raw_items`
- `seam_records`
- `seam_edges`
- `seam_states`
- `seam_sources`
- `seam_embeddings`
- `seam_packs`

Minimum `seam_records` columns:

- `id`
- `tag`
- `subject_id`
- `predicate`
- `object_value`
- `object_id`
- `payload_json`
- `timestamp`
- `confidence`
- `status`
- `source_id`

### 11.2 Graph DB

Mappings:

- `ent` -> node
- `rel` -> edge
- `clm` -> node or edge-with-properties
- `state` -> resolved node snapshot

### 11.3 Vector DB

Embed at multiple granularities:

- claim embedding
- state embedding
- event embedding
- lens pack embedding

Do not embed only `RAW`.
Prefer embedding canonicalized semantic units from `IR`.

### 11.4 CLI

Line-oriented `IR` means the language can be:

- appended to files
- diffed
- streamed
- piped
- chunked
- merged

Example commands:

```txt
seam ingest
seam canon
seam merge
seam pack
seam recall
seam trace
seam evolve
```

## 12. The Improvement Loop

This is the heart of the system.

SEAM should improve its own compression efficiency over time while preserving recoverability.

### 12.1 Goal

Allow the language to store more usable information in fewer tokens as it learns better canonical forms.

### 12.2 Loop stages

1. Ingest
2. Canonicalize
3. Score redundancy
4. Learn compressions
5. Validate recoverability
6. Promote new shorthand
7. Repack memory

### 12.3 Stage details

#### Ingest

New `RAW` enters the system.

#### Canonicalize

Convert raw information into `IR`.

#### Score redundancy

Detect repeated surface forms, repeated predicate patterns, repeated entity clusters, and repeated event motifs.

Examples:

- "vector database"
- "vec db"
- "embedding store"

These may map to one canonical symbol or alias cluster.

#### Learn compressions

The system proposes new compact symbols for repeated high-value patterns.

Examples:

- `rag_native` instead of `"optimized for retrieval-augmented generation"`
- `prov_full` instead of `"retains full provenance traceability"`

#### Validate recoverability

A proposed shorthand is accepted only if reconstruction quality passes threshold.

Validation tests:

- semantic equivalence
- provenance retention
- contradiction retention
- temporal retention
- retrieval quality

#### Promote new shorthand

Accepted compressions become part of the active symbol table.

#### Repack memory

Only `PACK` and optional render layers are rewritten.
`RAW` and canonical `IR` remain stable except for additive aliasing and reconciliation updates.

## 13. Symbol Tables

To store more in fewer tokens, SEAM uses symbol dictionaries.

### 13.1 Levels

- global symbols
- workspace symbols
- project symbols
- user symbols
- session symbols

### 13.2 Example

```txt
=|sym:1|scope=project:p:1|long="retrieval-augmented generation"|short=rag
=|sym:2|scope=project:p:1|long="surface encoded agent memory"|short=seam
```

Rules:

1. Symbols must be deterministic within scope.
2. Symbol collisions must be tracked.
3. Symbols must be versioned.
4. Symbols must be reversible.

## 14. Versioning

Every record may include:

- `lang`
- `schema`
- `packv`
- `symv`

Example:

```txt
~|st:p:1|lang=seam|schema=0.1|symv=3|goal=universal_ai_memory_lang
```

This allows the language to evolve without invalidating stored memory.

## 15. Reconciliation

Memory is not static. New evidence can refine old memory.

SEAM handles this with:

- explicit contradiction markers
- confidence changes
- state resolution
- additive deltas

Example:

```txt
+|d:1|target=st:p:1|op=set|path=goal|old="memory language"|new="universal AI memory language"
```

Rules:

1. Never silently overwrite prior meaning.
2. Prefer additive updates plus resolved state snapshots.
3. Preserve old claims when provenance matters.

## 16. Retrieval Contract

Every retrieval flow should specify:

- retrieval unit
- ranking function
- pack strategy
- max token budget
- backtrace path to evidence

Example:

For design assistance:

1. search `state`
2. expand to top `claims`
3. include recent `events`
4. attach source anchors
5. emit `PACK`

## 17. Minimal Grammar Draft

EBNF-style sketch:

```txt
record   = tag "|" id { "|" field } ;
tag      = "@" | "#" | "!" | ">" | "~" | "^" | "%" | "+" | "=" ;
id       = token ;
field    = key "=" value ;
key      = token ;
value    = token | string | array | map ;
array    = "[" [ value { "," value } ] "]" ;
map      = "{" [ key ":" value { "," key ":" value } ] "}" ;
token    = ? unquoted safe token ? ;
string   = "\"" { char } "\"" ;
```

## 18. Example End-to-End Flow

### 17.1 Raw input

```txt
"I want to design a language for AI that permanently remembers things. It should work for databases, RAG pipelines, and context windows. The goal is to compress information to the simplest state possible without losing any information."
```

### 17.2 IR

```txt
@|u:1|t=user|name="ivan"
@|p:1|t=project|name="SEAM"
#|c:1|s=p:1|p=goal|o="design universal AI memory language"
#|c:2|s=p:1|p=scope|o=[db,rag,ctx,cli]
#|c:3|s=p:1|p=principle|o="compress to simplest recoverable state"
#|c:4|s=p:1|p=constraint|o="minimize information loss"
!|e:1|a=u:1|v=request|o=p:1|ts=2026-04-11
%|src:1|kind=chat|ref="thread://turn/1"
^|x:1|obj=c:1|src=src:1
^|x:2|obj=c:2|src=src:1
^|x:3|obj=c:3|src=src:1
^|x:4|obj=c:4|src=src:1
~|st:p:1|goal=design_universal_ai_memory_language|scope=[db,rag,ctx,cli]|principle=simplest_recoverable_state|constraint=min_info_loss
```

### 17.3 PACK

```txt
P|focus=p:1|goal=univ_ai_mem_lang|scope=db,rag,ctx,cli|principle=simplest_recoverable_state|minfo=1|refs=st:p:1,c:1,c:2,c:3,c:4
```

## 19. Open Questions For v0.2

The next version should decide:

1. Should predicates use a fixed registry or allow open vocabulary by default?
2. Should packed symbols be model-specific or universal?
3. Should `PACK` support binary token dictionaries?
4. How should multimodal evidence be normalized?
5. How should cross-agent merge conflicts be resolved?
6. What is the best recoverability benchmark suite?

## 20. Implementation Priorities

Build order:

1. parser
2. canonical record schema
3. SQLite storage
4. embedding pipeline for `IR`
5. pack generator
6. recall engine
7. compression improvement loop

## 21. SQLite Blueprint

Suggested starting schema:

```sql
create table raw_items (
  id text primary key,
  kind text not null,
  body text not null,
  ref text,
  created_at text not null,
  meta_json text
);

create table seam_records (
  id text primary key,
  tag text not null,
  subj text,
  pred text,
  obj_text text,
  obj_ref text,
  actor text,
  verb text,
  ts text,
  status text,
  conf real,
  source_id text,
  payload_json text not null default '{}',
  schema_v text not null default '0.1'
);

create table seam_edges (
  id text primary key,
  src_id text not null,
  edge text not null,
  dst_id text not null,
  weight real,
  payload_json text not null default '{}'
);

create table seam_states (
  id text primary key,
  target_id text not null,
  state_json text not null,
  resolved_from text,
  updated_at text not null,
  schema_v text not null default '0.1'
);

create table seam_evidence (
  id text primary key,
  obj_id text not null,
  source_id text not null,
  span_text text,
  span_start integer,
  span_end integer,
  payload_json text not null default '{}'
);

create table seam_symbols (
  id text primary key,
  scope text not null,
  short text not null,
  long text not null,
  kind text not null,
  score real,
  sym_v integer not null,
  unique(scope, short, sym_v)
);

create table seam_packs (
  id text primary key,
  lens text not null,
  focus_id text,
  body text not null,
  token_count integer,
  score real,
  pack_v integer not null,
  created_at text not null
);
```

## 22. Compression Metrics

The improvement loop needs hard metrics.

Recommended metrics:

- `cr`: compression ratio
- `rr`: reconstruction rate
- `sr`: semantic retention
- `pr`: provenance retention
- `tr`: temporal retention
- `qr`: retrieval quality

Definitions:

```txt
cr = original_token_count / packed_token_count
rr = recovered_fields / required_fields
sr = semantic_match_score(original_ir, reconstructed_ir)
pr = provenance_links_recovered / provenance_links_expected
tr = temporal_facts_recovered / temporal_facts_expected
qr = retrieval_success_at_k
```

Promotion threshold for new compression rules should require:

- `sr >= 0.98`
- `pr = 1.00`
- `tr >= 0.99`
- `qr` no worse than baseline
- `cr` strictly better than baseline

These are starting thresholds, not permanent doctrine.

## 23. Improvement Loop Rule Types

The language can evolve through several rule classes.

### 23.1 Alias rules

Merge repeated surface forms into one canonical symbol.

```txt
vector_db -> vdb
retrieval_augmented_generation -> rag
```

### 23.2 Predicate compaction rules

Map high-frequency predicates to shorter stable keys.

```txt
principle -> pr
constraint -> cs
depends_on -> dep
```

These rules must stay versioned and reversible.

### 23.3 Structural macros

Collapse common multi-record motifs into macro packs.

Example motif:

- entity
- goal claim
- scope claim
- resolved state

This can be packed with one motif key in `PACK` while leaving `IR` unchanged.

### 23.4 Lens-specific compression

Different tasks can tolerate different shorthand.

Example:

- a coding lens may compress project history aggressively
- a legal lens may compress almost nothing

## 24. Promotion Algorithm

Pseudo-flow:

```txt
for each candidate_rule:
  apply rule to sampled packs
  reconstruct packs to ir-equivalent form
  score cr, rr, sr, pr, tr, qr
  if thresholds pass and cr improves:
    increment sym_v or pack_v
    promote rule
  else:
    reject rule
```

The key idea:

The language is allowed to become denser only when it proves it can still recover what matters.

## 25. Universal Interop Contract

For SEAM to be universal, every implementation should support:

### 25.1 Required capabilities

- parse `IR`
- emit canonical JSON
- store source provenance
- generate embeddings from `IR` units
- produce a `PACK`
- trace a pack item back to `IR`
- trace an `IR` item back to `RAW`

### 25.2 Optional capabilities

- graph projection
- SQL sync
- CLI streaming
- compression rule learning
- multimodal evidence support

## 26. JSON Mirror

Every SEAM record should have a deterministic JSON mirror for interop.

Example:

```json
{
  "tag": "#",
  "id": "c:1",
  "s": "p:1",
  "p": "goal",
  "o": "design universal AI memory language"
}
```

This gives us:

- language-native line format
- API-friendly JSON format
- database-friendly flattened form

## 27. Initial CLI Contract

Suggested command surface:

```txt
seam ingest <input>
seam parse <file>
seam canon <raw-id>
seam embed <record-id>
seam pack --lens <lens> --focus <id>
seam recall <query>
seam trace <pack-or-record-id>
seam evolve --dry-run
seam evolve --promote
```

Expected behaviors:

- `ingest` stores `RAW`
- `canon` derives `IR`
- `pack` creates dense context form
- `recall` searches states, claims, events, and packs
- `trace` expands provenance chain
- `evolve` proposes or promotes compression rules

## 28. NLP Token Efficiency

SEAM should make tokens more effective by moving meaning out of redundant natural-language surface form and into canonical machine structure.

The system should treat NLP compression as representation optimization, not just summarization.

### 28.1 What makes NLP token-inefficient

Natural language spends tokens on:

- repeated phrasing
- function words
- stylistic variation
- ambiguity
- hedging
- restating context
- reintroducing entities by name

Humans need those patterns.
Agents usually do not.

### 28.2 What makes SEAM token-efficient

SEAM improves token efficiency by:

- replacing repeated phrases with symbols
- converting prose into typed records
- replacing names with stable ids
- separating evidence from state
- separating current truth from old claims
- reusing lens-specific shorthand
- packing repeated motifs once

### 28.3 NLP compilation strategy

The compiler should:

1. split text into semantic atoms
2. normalize entities
3. normalize predicates
4. normalize time
5. detect repeated motifs
6. emit canonical `IR`
7. optionally emit `PACK`

This makes the memory representation denser than the original prompt while remaining machine-usable.

### 28.4 Decompilation strategy

The decompiler should:

1. expand symbols using active symbol tables
2. reconstruct subject-predicate-object relations
3. restore discourse order when useful
4. insert only minimal glue words
5. expose provenance or uncertainty when requested

The goal is not literary output.
The goal is faithful re-expression.

### 28.5 Effective-token principle

A token is effective if it carries recoverable semantic load that helps retrieval, reasoning, or generation.

SEAM should optimize:

```txt
effective_token_rate = recoverable_semantic_units / total_tokens
```

Better compression means raising effective token rate, not merely shortening text.

### 28.6 Context-window optimization rules

When generating `PACK` for context windows:

1. prefer resolved state over repeated raw claims
2. include only contradiction records that still matter
3. prefer ids and symbols over repeated surface names
4. include provenance references, not full evidence, unless needed
5. emit lens-specific macros for common patterns
6. reserve token budget for task-relevant deltas and open questions

### 28.7 RAG optimization rules

For retrieval systems:

- embed `IR` units rather than only raw chunks
- retrieve claims, states, and events separately
- rerank by semantic match and source quality
- pack only the minimal reconstruction set
- decompile only at the final stage if human-readable output is needed

### 28.8 Model-specific packing

Different models have different tokenizers and different tolerance for shorthand.

SEAM should eventually support:

- tokenizer-aware symbol scoring
- model-specific pack dictionaries
- cross-model safe fallback dictionaries

This means universal `IR`, but possibly model-tuned `PACK`.

## 29. Translator API

An implementation should expose explicit translation functions.

Example surface:

```txt
compile_nl(raw_text, source_ref) -> IR records
pack_ir(record_ids, lens, budget) -> PACK
unpack_pack(pack_id) -> IR-equivalent records
decompile_ir(record_ids, mode) -> natural language
trace_nl(span_id) -> source evidence
```

### 29.1 Required translator guarantees

- deterministic parsing of valid `IR`
- reversible symbol expansion within scope
- configurable verbosity on decompile
- provenance-preserving decompile when requested
- failure-safe fallback to less compressed forms

### 29.2 Failure behavior

If the translator cannot safely preserve meaning:

1. prefer lower compression
2. prefer expanded predicates
3. include uncertainty markers
4. attach provenance references
5. refuse unsafe shorthand promotion

## 30. Example Translation

### 30.1 Natural language input

```txt
The project should permanently remember useful things for AI agents. It should work across databases, RAG pipelines, and context windows. We want to compress information to the simplest form possible without losing meaning.
```

### 30.2 Compiled IR

```txt
@|p:1|t=project|name="SEAM"
#|c:1|s=p:1|p=goal|o="durable memory for AI agents"
#|c:2|s=p:1|p=scope|o=[db,rag,ctx]
#|c:3|s=p:1|p=principle|o="simplest recoverable form"
#|c:4|s=p:1|p=constraint|o="preserve meaning"
~|st:p:1|goal=durable_agent_memory|scope=[db,rag,ctx]|principle=simplest_recoverable_form|constraint=preserve_meaning
```

### 30.3 Packed form

```txt
P|focus=p:1|goal=dur_agent_mem|scope=db,rag,ctx|pr=srf|cs=pres_mean|refs=st:p:1,c:1,c:2,c:3,c:4
```

### 30.4 Decompiled minimal natural language

```txt
SEAM is a durable AI memory project for databases, RAG, and context windows. Its principle is the simplest recoverable form that preserves meaning.
```

## 31. North Star

The north star for SEAM is not maximum compression by itself.

It is:

Maximum durable intelligence per token.

## 32. Working Definition

SEAM is a universal semantic memory language for AI systems.

It stores raw evidence, canonical meaning, and compact retrieval packs as separate but linked layers. Its compression strategy is not to delete information, but to normalize, deduplicate, symbolically encode, and continuously improve the representation while preserving recoverability.
