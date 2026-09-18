# SEAM Latent CacheBridge Roadmap

Status: planned research lane  
Owner boundary: SEAM research/experimental runtime  
Priority: parallel to Memory Formation; must not displace its current acceptance work

## Purpose

This lane explores a SEAM-native form of direct semantic communication between
language models using model-internal cache state, inspired by *Cache-to-Cache:
Direct Semantic Communication Between Large Language Models* (Fu et al.,
ICLR 2026) and informed by *In-context Learning and Induction Heads* (Olsson et
al., 2022).

The target is not to turn opaque model state into canonical memory. The target
is to let SEAM derive model-native latent context from verified MIRL retrieval
and optionally transfer/fuse that context between compatible open-weight models.

The architectural invariant is:

\`\`\`text
RAW / MIRL = durable truth and provenance
PACK       = disposable token-facing context
LATENT     = disposable model-specific acceleration/communication artifact
\`\`\`

A latent artifact must always be traceable back to the MIRL records and
retrieval decision that produced it. It is never allowed to become the only
copy of a fact, the owner of provenance, or a replacement for canonical memory.

## Why this belongs in SEAM first

Keep the work in the canonical SEAM repository while it depends directly on:

- MIRL record identity and evidence boundaries
- retrieval decisions and PACK construction
- trust/lifecycle eligibility
- benchmark glassbox and provenance
- local agent/model adapters

Use a dedicated branch and optional experimental package boundary so model
dependencies do not leak into the base runtime.

Extract a separate \`seam-cachebridge\` repository only when at least two of the
following are true:

1. projector/fuser training requires an independently deployed GPU service;
2. model-serving dependencies materially inflate or destabilize SEAM Suite;
3. its release cadence diverges from the memory runtime;
4. non-SEAM consumers need the latent bridge as a standalone library;
5. the training/evaluation surface can be versioned independently behind a
   stable SEAM adapter contract.

If extraction happens, MIRL selection, provenance, trust gating and benchmark
claim policy remain owned by SEAM. Only model-specific capture/projection/fusion
moves out.

## Research questions

1. Can a SEAM retrieval be converted into a receiver-native KV representation
   without reducing answer quality relative to a normal text PACK?
2. Can a frozen sharer model transfer useful cache state into a frozen receiver
   through a small learned projector/fuser?
3. Can SEAM provenance and trust eligibility remain exact through that latent
   path?
4. Does induction-shaped ordering of retrieved memories improve the prefill
   cache used for transfer?
5. When does latent transfer reduce total latency or prompt tokens enough to
   justify VRAM, adapter storage and compatibility complexity?
6. Can several specialist sharers contribute complementary cache state to one
   receiver without provenance ambiguity or destructive interference?

## Non-goals

- no replacement of MIRL or SQLite as canonical memory;
- no storage of hidden chain-of-thought as durable memory;
- no claim that KV state is portable across arbitrary hosted APIs;
- no dependency on private provider internals;
- no production enablement before matched baselines and rollback evidence;
- no copied implementation from the upstream C2C repository. The paper and
  Apache-2.0 reference implementation are research inputs; SEAM's implementation
  should be independently structured around SEAM contracts.

## Proposed architecture

\`\`\`text
                     SEAM canonical memory
                            MIRL
                              |
                 retrieval + trust eligibility
                              |
                    selected record refs
                              |
               +--------------+--------------+
               |                             |
          text PACK path                latent path
               |                             |
          normal prompt              LatentContextSpec
                                             |
                                   model prefill/capture
                                             |
                                      LatentArtifact
                                             |
                       +---------------------+--------------------+
                       |                                          |
                 same-model replay                         CacheBridge
                                                                  |
                                                       projector / fuser
                                                                  |
                                                             receiver
\`\`\`

### LatentContextSpec

A provider-free manifest describing what should be converted into latent state:

- namespace / scope
- ordered MIRL record IDs
- retrieval-decision ID and fingerprint
- PACK/lens identity
- trust/lifecycle status snapshot
- model family + exact revision
- tokenizer identity/hash
- requested layer map
- generation/prefill template version
- source hash and artifact policy

It contains no tensor payload.

### LatentArtifact

A derived, disposable artifact containing or referencing captured model state:

- schema version
- source \`LatentContextSpec\` fingerprint
- exact model/tokenizer revisions
- KV tensor metadata and checksum
- layer/head/dimension shape
- dtype/device serialization metadata
- source MIRL refs
- provenance/evidence fingerprint
- capture timestamp
- adapter/projector version
- expiry/compatibility policy

A stale model revision, tokenizer mismatch, trust-state change or MIRL
fingerprint drift invalidates the artifact.

### CacheBridge adapter

A model-specific boundary that can:

1. capture sharer KV state;
2. capture receiver prefill state;
3. align token/position correspondence when tokenizers differ;
4. project source K/V tensors into receiver dimensions;
5. fuse projected and native receiver cache through a bounded gate;
6. report layer-level gate values, latency, memory use and compatibility.

The initial implementation should freeze both source and receiver weights and
train only the bridge parameters, matching the cleanest experimental question.

## Work streams

### LC0 — Reproduction and measurement contract

**Goal:** establish a reproducible local baseline before changing SEAM.

Deliverables:

- pin one small open-weight receiver and one sharer pair;
- record model revisions, tokenizer hashes and hardware;
- reproduce ordinary text-to-text and receiver-only baselines;
- reproduce a minimal cache capture path;
- freeze the SEAM-specific benchmark schema.

Minimum metrics:

- task accuracy / exactness
- answerer and judge configuration
- prompt/input token count
- time-to-first-token
- end-to-end latency
- GPU memory peak
- cache bytes transferred
- bridge parameter count
- provenance exactness
- invalid/stale artifact rejection rate
- no-change/control regression rate

Exit: a provider-free baseline bundle exists and can be rerun without bridge
training.

### LC1 — Induction-aware PACK baseline

**Goal:** exploit the induction-head finding before introducing latent transfer.

Add an experimental PACK ordering strategy that groups retrieved evidence into
repeated structural motifs such as:

\`\`\`text
situation -> action -> outcome
situation' -> action' -> outcome'
current situation -> ?
\`\`\`

The implementation must preserve the exact same selected MIRL refs and evidence
budget as the control PACK. Only ordering/grouping changes.

Exit:

- matched relevance-order vs induction-order comparison;
- no provenance loss;
- no benchmark promotion unless answer quality improves on a predeclared set.

This gives CacheBridge a stronger prefill baseline and tells us whether some
benefit comes from context structure rather than cache transfer itself.

### LC2 — Same-model latent capture and replay

**Goal:** prove SEAM can produce a model-native derived context artifact without
cross-model projection.

Implement an optional experimental adapter for Hugging Face causal LMs that:

- prefills from a SEAM context;
- captures DynamicCache-compatible K/V state;
- serializes metadata/checksums separately from tensor storage;
- rejects mismatched model/tokenizer/layer shapes;
- reuses captured state for a later receiver continuation.

Suggested boundary:

\`\`\`python
spec = seam.latent.plan(query, model_id=...)
artifact = adapter.capture(spec)
answer = adapter.generate(query, latent=artifact)
\`\`\`

Exit: replay is behaviorally equivalent to a normal matched prefill within a
declared tolerance and all provenance checks round-trip.

### LC3 — SEAM CacheBridge v0: same-family projection

**Goal:** train our own source->receiver bridge.

Start with a small Qwen-to-Qwen pair to reduce tokenizer and architecture
variance. Freeze both models. Train only:

- K projector
- V projector
- bounded residual gate
- optional layer mapping parameters

Start with a simple MLP or low-rank projector before testing more elaborate
fusers. Every new projector must beat or justify its added complexity.

Exit criteria:

- receiver+bridge improves over receiver-only on the development benchmark;
- compare directly against text-mediated sharer->receiver communication;
- rollback to normal text PACK is one configuration switch;
- artifact incompatibility fails closed.

### LC4 — Provenance-aware trust gating

**Goal:** make latent communication obey the same evidence boundaries as text
context.

Before capture/fusion, SEAM filters records using canonical lifecycle/trust
eligibility. The bridge records which MIRL refs contributed to each artifact
and which latent source(s) were admitted.

Required tests:

- contradicted/superseded/deleted-soft records cannot silently enter a new
  latent artifact;
- changing an evidence fingerprint invalidates reuse;
- cross namespace/scope artifacts fail closed;
- stale adapters or model revisions fail closed;
- receiver answers retain a backtrace to the selected MIRL refs even though the
  intermediate representation is latent.

Exit: latent use cannot bypass an eligibility decision available to the normal
PACK path.

### LC5 — Heterogeneous model transfer

**Goal:** test whether useful semantics survive across different model families
or tokenizer boundaries.

Candidate sequence:

1. Qwen -> Qwen with different sizes;
2. Qwen math/code specialist -> Qwen general receiver;
3. Llama/Gemma -> Qwen receiver;
4. receiver smaller than sharer for edge-agent use.

Introduce explicit token/position alignment only when required by the pair.
Measure alignment failures separately from projection failures.

Exit: at least one heterogeneous pair shows a reproducible benefit without
losing provenance or materially regressing controls.

### LC6 — Multi-sharer fusion

**Goal:** let multiple specialists contribute to one receiver.

Examples:

\`\`\`text
code specialist ----\
math specialist -----+--> SEAM fusion policy --> receiver
memory retrieval ----/
\`\`\`

SEAM, not the models, owns the admission ledger:

- source model identity
- source artifact fingerprint
- selected MIRL refs
- fusion order
- gate values
- rejection reason
- resulting benchmark outcome

Start with two sharers. Add a third only after interaction effects are
measurable.

Exit: multi-sharer fusion beats the strongest single-sharer baseline on a
predeclared mixed-domain set.

### LC7 — Security and failure campaign

Threats to test:

- latent prompt/instruction injection surviving projection;
- malicious or corrupted tensor artifacts;
- cross-tenant artifact reuse;
- model-revision confusion;
- tokenizer drift;
- stale provenance;
- NaN/Inf tensor poisoning;
- oversized cache / VRAM exhaustion;
- gate saturation that effectively overwrites receiver behavior;
- serialization tampering.

Controls:

- content-addressed tensor artifacts;
- schema and shape bounds;
- model/tokenizer revision pinning;
- finite-value checks;
- namespace/scope binding;
- trust gate before capture;
- maximum injected layers/tokens/bytes;
- residual gate caps;
- easy disable/fallback to text PACK.

Exit: malformed or stale latent artifacts fail closed and normal SEAM retrieval
remains available.

### LC8 — Qualification and extraction decision

Run a matched benchmark matrix:

| Lane | Memory input | Sharer communication | Receiver |
| --- | --- | --- | --- |
| A | text PACK | none | receiver |
| B | induction PACK | none | receiver |
| C | text PACK | text answer | receiver |
| D | text PACK | KV CacheBridge | receiver |
| E | induction PACK | KV CacheBridge | receiver |
| F | text PACK | multi-sharer CacheBridge | receiver |

For each lane retain accuracy, latency, tokens, VRAM, transferred bytes,
provenance integrity and failure counts.

Decision outputs:

- keep experimental in SEAM;
- promote to supported optional SEAM adapter;
- extract \`seam-cachebridge\` behind a stable interface;
- abandon if benefits do not survive matched evaluation.

No product or benchmark claim is promoted from a single demo.

## Implementation boundaries

Recommended initial package layout:

\`\`\`text
seam_runtime/
  latent/
    __init__.py
    contract.py        # LatentContextSpec / LatentArtifact metadata
    compatibility.py   # model/tokenizer/layer checks
    provenance.py      # MIRL/backtrace bindings
    adapters/
      base.py
      hf_cache.py
    bridge/
      projector.py
      fusion.py
      layer_map.py

tests/
  audit/
    test_latent_contract.py
    test_latent_provenance.py
    test_latent_compatibility.py
  latent/
    test_hf_cache_replay.py
    test_cachebridge_projector.py
\`\`\`

Do not add torch/transformers to SEAM core dependencies. Introduce a deliberate
optional extra only when LC2 begins, after dependency/security review.

## Branch and delivery strategy

Roadmap work begins on:

\`feat/latent-cachebridge-roadmap-20260917\`

Implementation should use a fresh branch from the then-current protected
\`main\`, preferably one branch/PR per LC stage. Do not build LC2-LC6 directly on
the roadmap branch.

Suggested progression:

\`\`\`text
main
  |
  +-- feat/latent-cachebridge-lc0
  +-- feat/induction-pack-lc1
  +-- feat/latent-cache-lc2
  +-- feat/cachebridge-lc3
  ...
\`\`\`

Each stage must preserve the repo's existing history, handoff, benchmark and
protected-main gates.

## Source and attribution notes

Primary research inputs:

- Fu et al., *Cache-to-Cache: Direct Semantic Communication Between Large
  Language Models*, ICLR 2026 / arXiv:2510.03215.
- Olsson et al., *In-context Learning and Induction Heads*, Transformer
  Circuits Thread, 2022.

The upstream C2C repository is Apache-2.0 and useful as a reference for
experimental coverage, but this lane is deliberately specified around SEAM's
own contracts and evaluation boundaries rather than importing the upstream
package wholesale.
