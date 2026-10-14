# Persistent Concept State / CacheBridge Research Roadmap

**Status:** Planned experimental research lane. No runtime implementation or benchmark
improvement is claimed by this document.

**Research thesis:** investigate whether SEAM can support a stateful language-model
runtime that carries a bounded, reconstructable semantic working state across
interactions, updates only the novel semantic delta introduced by each turn, and
reactivates relevant state without replaying the full conversation as text.

## Research inputs and prior-art baselines

This lane intentionally treats the following work as prior art and experimental
controls rather than as SEAM inventions:

1. **Cache-to-Cache (C2C)** — Fu et al., *Cache-to-Cache: Direct Semantic
   Communication Between Large Language Models*, arXiv:2510.03215 / ICLR 2026.
   C2C projects and fuses a sharer model's KV cache into a receiver model and
   establishes direct latent cache transfer as a measurable baseline.
2. **Latent Cache Flow (LCF / cross-context LCF)** — Rossi, Raghunath, and Wu,
   *Latent Cache Flow: Model-to-Model Communication Without Text*,
   arXiv:2605.22863. LCF compresses and translates cache information and adds a
   cross-context transfer setting intended to communicate information absent
   from the receiver's context.
3. **Dynamic Large Concept Models (DLCM)** — Qu et al.,
   *Dynamic Large Concept Models: Latent Reasoning in an Adaptive Semantic
   Space*, arXiv:2512.24617 / ICLR 2026. DLCM learns variable-length semantic
   concepts and shifts part of reasoning into a compressed concept space.

SEAM's research question is different from any one of these baselines:

> Can a language model maintain a bounded persistent concept state backed by
> canonical provenance-bearing memory, update that state with only the minimum
> relevant semantic delta, and reactivate it through text or a learned latent
> bridge without replaying the complete conversation?

## Non-negotiable architecture boundary

SEAM remains the source of truth.

- **Canonical:** SQLite records, RAW/MIRL, provenance, lifecycle, graph state,
  replay evidence, and source hashes.
- **Derived/rebuildable:** persistent concept state, projected latent state,
  KV-cache artifacts, adapter outputs, summaries, and any model-specific
  reactivation representation.
- A derived state must never become the only copy of user or agent memory.
- Deleting, invalidating, or changing canonical records must make it possible to
  rebuild active state without relying on stale latent artifacts.
- Model, tokenizer, adapter, source-memory and state-version changes must
  invalidate incompatible latent artifacts.
- PACK remains derived prompt-time context under the existing SEAM contract.

## Baseline-first rule

**Never change the architecture before freezing the baseline that the change is
supposed to improve.** Each stage produces a retained, comparable evidence
bundle before the next stage begins.

The research ladder is:

### PCS0 — Measurement freeze

Freeze and hash:

- model revisions
- tokenizer revisions
- datasets and splits
- prompts / decoding configuration
- hardware and software environment
- benchmark scripts
- seeds where supported
- artifact formats

This is the prerequisite for every later claim.

### PCS1 — Full-context and bounded-context baselines

Measure the same long-horizon tasks with:

- full-context replay where supported
- fixed sliding window
- rolling textual summary
- ordinary RAG
- SEAM canonical retrieval / PACK context

Record quality, historical tokens processed, bytes retrieved, TTFT, end-to-end
latency, memory/VRAM, and provenance coverage.

### PCS2 — C2C reproduction baseline

Reproduce a bounded C2C-style cache-transfer experiment before modifying the
mechanism. The goal is measurement, not product integration.

Required outputs:

- exact model pair and revisions
- adapter parameter count / artifact bytes
- train and inference cost
- quality metrics
- latency and transferred bytes
- failure cases and context-alignment assumptions

### PCS3 — LCF / cross-context baseline

Reproduce an LCF-style compressed transfer and a cross-context condition.

Compare against PCS2 under matched tasks and explicitly record:

- adapter size
- compression ratio
- shared-context vs different-context behavior
- transferred latent bytes
- quality / latency trade-off
- information lost during compression

### PCS4 — DLCM concept-compression baseline

Measure whether variable-length semantic concepts reduce active historical
representation cost without introducing unacceptable information loss.

Compare at least:

- token context
- fixed sentence concepts
- fixed-size chunks
- dynamically learned concepts

No persistent state is introduced until these concept representations have an
independent baseline.

### PCS5 — Persistent Concept State with textual reactivation

Introduce a bounded active state `S_t`.

For turn `t`:

```
new input -> concepts
canonical SEAM memory -> relevant evidence
(S_(t-1), concepts, evidence) -> semantic delta
semantic delta -> S_t
S_t -> textual reactivation -> model
```

This stage tests persistence separately from latent injection. The active state
must remain reconstructable from canonical SEAM evidence.

### PCS6 — Provenance-gated semantic delta

Only admit active-state updates that preserve explicit evidence relationships.

Evaluate:

- addition
- revision
- contradiction
- invalidation
- temporal supersession
- unsupported-state rejection
- reconstruction after deliberate corruption

A useful state update is the minimum sufficient change, not a rewritten summary
of the entire history.

### PCS7 — Latent reactivation / SEAM CacheBridge

Replace textual reactivation with a learned bridge only after PCS5/PCS6 have
measured baselines.

Candidate interfaces may include:

- projected KV state
- learned prefix / soft-prompt state
- cross-attention memory
- another explicitly versioned model-specific adapter

Every latent payload is disposable. A minimum identity should bind:

```
canonical_memory_version
source_record_ids / provenance refs
source hashes
active_state_version
sharer model + revision
receiver model + revision
tokenizer revision
adapter id + hash
context/state hash
creation time
```

### PCS8 — Receiver-aware / novelty-aware transfer

Investigate whether SEAM can reduce transfer to information that is both
relevant to the current task and novel relative to receiver state.

Candidate measurements:

- quality retained per transferred byte
- redundant-state transfer rate
- novel-evidence precision / recall
- state-delta size
- contradiction handling

### PCS9 — Graph-to-latent state

Test whether SEAM-selected graph substructures can be represented as active
concept state without flattening all relationships into transcript text first.

The source graph remains canonical and inspectable. Latent graph
representations remain derived.

### PCS10 — Heterogeneous-model transfer

Only after the single-family and shared-architecture baselines are stable,
investigate model-independent or intermediate SEAM concept/latent spaces for
heterogeneous senders and receivers.

Do not claim a universal latent protocol unless cross-family evidence supports
that claim.

## Evaluation matrix

Every stage should preserve comparable columns for:

### Quality

- exact match / F1 where applicable
- task accuracy
- entity and preference recall
- temporal fact update accuracy
- multi-hop recall
- contradiction resolution

### Efficiency

- historical tokens processed per turn
- FLOPs or closest reproducible compute proxy
- TTFT
- end-to-end latency
- VRAM / memory
- retrieved bytes
- latent / KV bytes transferred
- adapter parameters and artifact size

### Persistence and reliability

- active-state size over history length
- state drift
- reconstruction fidelity
- stale-state detection
- model/version mismatch detection
- unsupported-state rate

### Provenance

- evidence coverage
- source attribution
- canonical-record traceability
- contradiction/source preservation

## Long-horizon scaling experiment

Hold the current task distribution approximately fixed while accumulated
history grows through orders of magnitude (for example 10, 100, 1,000, 10,000
turn-equivalents or corresponding token scales).

The target is not a claim of perfectly constant compute. The hypothesis is that
model-facing historical work for PCS should become substantially less coupled
to total accumulated history than full transcript replay.

## Promotion / extraction gates

Keep this lane inside SEAM research until evidence justifies extraction.

A separate CacheBridge or PCS repository is justified only when:

1. PCS0-PCS4 baselines are reproducible.
2. A SEAM-specific mechanism demonstrates a measurable advantage on at least one
   predeclared quality/efficiency axis without violating canonical-memory and
   provenance contracts.
3. The interface boundary is stable enough to test independently of SEAM core.
4. Patent/licensing review has been completed for any mechanism close to cited
   prior art.
5. The result can be reproduced from recorded artifacts and environment hashes.

Until those gates pass, this is an **experimental research lane**, not a SEAM
product capability.

## Immediate next action

The next action is **PCS0 only**: define and freeze the baseline harness before
implementing C2C, LCF, DLCM-derived concept state, or a SEAM-native bridge.

Do not jump directly to the proposed architecture. Preserve every baseline so
later evidence can show whether each added mechanism helped, hurt, or merely
shifted cost.
