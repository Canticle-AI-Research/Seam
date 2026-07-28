# Architecture Task: Parallel Graph (G3→G4) and Reasoning (R3) Build

**Date:** 2026-07-22
**Author:** handoff author (Opus), for a downstream architect model
**Status:** design brief — not yet architected, not yet implemented
**Anchors:** HISTORY#462, handoff `2026-07-22-reasoned-retrieval-g3a`
**Governing contracts:** `docs/roadmap/GRAPH_MEMORY_MATURITY.md`,
`docs/REASONING_GRAPH.md`

---

## 0. How to use this brief

You are being asked to **architect**, not to receive a step-by-step SOP. This
document frames the problem, fixes the hard constraints, states the acceptance
boundaries, and lists the open design questions you must resolve. Your output is
an **architecture/design document** per track (data model, algorithm, module
placement, migration story, test contract), which a subsequent implementation
pass will build against.

Two tracks run **in parallel** (see §2). You may design them together or hand
each to a separate architect. Do not collapse them into one graph.

Read these before designing anything:

- `docs/roadmap/GRAPH_MEMORY_MATURITY.md` — the G1–G7 lane and its build table.
- `docs/REASONING_GRAPH.md` — the R1–R6 lane and its contracts.
- `seam_runtime/knowledge_graph.py` — canonical MIRL→SQLite projector (G lane).
- `seam_runtime/graph_source_selector.py` — G3a semantic-seed → edge-traversal.
- `seam_runtime/reasoning_graph.py` — R1 run graph + R2 retrieval decisions.
- `seam_runtime/retrieval_policy.py` — versioned provider-free planner/fusion
  identities and evidence fingerprints shared by runtime and reasoning.
- `seam_runtime/sdk.py` — `SeamSDK` / `ReasoningSession`; the stable boundary.

---

## 1. Current position (as of HISTORY#462)

The knowledge graph is a **projection of canonical RAW/MIRL**, never a competing
truth store. It grows beside an **append-only reasoning graph** that records
public run justification without becoming canonical truth. Two parallel lanes:

| Lane | Done | Next open |
| --- | --- | --- |
| **G (knowledge)** | G1 identity index, G2 reversible resolution, **G3a partial slice** | **finish G3 → G4** |
| **R (reasoning)** | R1 durable run graph, R2 retrieval decisions (mature) | **R3** |

**G3a is a partial slice only.** It proves provider-free semantic fact/episode
MIRL seeds feeding 0–3-hop *current*-graph traversal with deterministic
lexical/vector/graph fusion and explicit decision/latency traces; a semantic
seed earns graph credit only after an in-boundary edge actually connects it. It
does **not** discharge the full G3 contract.

> Naming note: the operator referred to "R1 and G4." R1 and R2 are already
> implemented and closed. The live open work is **R3** (reasoning lane) and
> **finish-G3-then-G4** (knowledge lane). This brief targets that real work. If
> R1/G4 were meant literally as rework, stop and reconcile before designing.

---

## 2. The parallelism contract (why G and R can run concurrently)

`docs/REASONING_GRAPH.md` states it explicitly: *"Knowledge stages G1-G7 and
reasoning stages R1-R6 advance in parallel. The planes meet through stable
references and reviewed promotion boundaries, not by collapsing knowledge and
reasoning into one ambiguous graph."*

Concretely, these tracks are safe to build simultaneously because:

- **Separate storage & modules.** Knowledge lives in `knowledge_graph.py`
  tables; reasoning lives in `reasoning_graph.py` tables. No shared mutable
  state, no shared migration.
- **One-way, ID-level coupling only.** The reasoning/retrieval side *reads*
  knowledge by exact record/edge IDs (R2 already fingerprints MIRL evidence;
  G3a already seeds from MIRL hits). Reasoning never writes knowledge; the only
  path from reasoning into MIRL is the future **R5 reviewed-promotion** contract,
  which is out of scope here.
- **The SDK is the join.** `SeamSDK`/`ReasoningSession` (`sdk.py`) already
  expose `ingest`, `knowledge`, `retrieve`, `retrieval(s)`, `reasoning`. Both
  tracks extend behind this boundary; CLI/REST/MCP stay thin adapters.

**Single coordination rule:** any new R3 evidence reference must cite exact
G-lane record/edge IDs and must never assert G-lane truth by implication. If a
track needs a new shared identity/evidence fingerprint, it goes through
`retrieval_policy.py`, not an ad-hoc format.

---

## 3. Track A — Knowledge lane: finish G3, then G4

### 3.1 Why G3 before G4

G4 graph products (entity summaries, communities, observations) are **consumers
of G3 hybrid retrieval and returned paths/traces**. Building G4 on the partial
G3a foundation means summaries/observations are assembled over an incomplete,
un-normalized retrieval base with no exact returned paths — the provenance
guarantees G4 must make ("every derived sentence names supporting record and
episode IDs") are hard to honor without G3's exact path/episode traces. Finish
G3 first unless you can show G4's provenance contract is fully satisfiable on
G3a alone (justify explicitly if you claim so).

### 3.2 G3 remaining gaps (from `GRAPH_MEMORY_MATURITY.md`)

The G3 acceptance boundary is *lexical terms + semantic node/fact vectors +
bounded traversal with explicit fusion trace; stable ranking, current/history
correctness, query-shape and latency fixtures.* Still missing:

1. **Semantic vectors for entity/value/agent/symbol nodes** (today only
   fact/episode seeds vectorize). Design where these embeddings live, how they
   stay in sync with the MIRL projection, and how they stay provider-free by
   default.
2. **Calibrated or rank-normalized cross-leg fusion** — lexical, vector, and
   graph legs currently fuse deterministically but are not calibrated/normalized
   across legs. Design a stable, reproducible normalization with a fusion trace.
3. **Historical-view semantics** — G3a traverses *current* edges only. Design
   correct `at`/history traversal consistent with `knowledge_graph.py`'s
   existing current/history validity views and supersession.
4. **Exact returned graph paths and episode traces** — return the actual path
   and episode backtrace per hit, not just a score. This is the input G4 needs.
5. **Corpus-scale latency/quality qualification** — query-shape and latency
   fixtures; bounded traversal that never loads a whole scope.
6. **pgvector scope resync** — external pgvector rows created before the scope
   column cannot be backfilled from canonical SQLite; they need one explicit
   boundary-only `seam index` resync (no embedding recompute). Fold this into
   the migration design.

### 3.3 G4 contract (`GRAPH_MEMORY_MATURITY.md` build table)

> **G4 Graph products** — evolving entity summaries, communities, community
> summaries, multi-episode observations. **Acceptance:** every derived sentence
> names supporting record and episode IDs; trust gates fail closed.

Design decisions you must make:

- **Entity summaries:** what evidence set, how they *evolve* (append vs
  recompute vs versioned), and how each sentence pins record+episode IDs.
- **Communities:** detection algorithm over `knowledge_edges`, determinism,
  scope isolation, recompute cost.
- **Community summaries & multi-episode observations:** same provenance rule —
  every derived sentence carries supporting IDs; trust gate fails closed when
  evidence is missing or below trust.
- **Storage:** new projected tables vs derived-on-read; must remain a
  disposable/rederivable projection of canonical MIRL, not new truth.

### 3.4 Track A acceptance gates

- Deterministic given fixed MIRL + policy version.
- No assertion/source-text leakage into indexes (same rule that G1 enforces).
- No cross-scope / cross-namespace matches or tenant leakage.
- Graph candidates **never silently displace** the primary evidence lane
  (non-displacement tests).
- Current/history correctness fixtures; query-shape + latency fixtures.
- G4: every derived sentence cites record+episode IDs; trust gate fails closed.

---

## 4. Track B — Reasoning lane: R3

### 4.1 R3 contract (`docs/REASONING_GRAPH.md` maturity table)

> **R3 Verification loops** — tests, tool outcomes, contradictions, retries, and
> supersession. **Acceptance:** failed paths remain visible; final outcomes
> identify the checks that support them.

R3 builds directly on the R1 durable run graph (`add_reasoning_node`,
`add_reasoning_edge`, `transition_reasoning_node`, status vocabulary
`open`/`supported`/`challenged`/… in `reasoning_graph.py`) and R2 retrieval
decisions. It does **not** depend on G3/G4.

### 4.2 Open architecture decisions

- **Verification node/edge model:** how a test/tool-outcome/contradiction/retry
  attaches to a reasoning node as append-only evidence, extending the existing
  node/edge/state-transition schema rather than mutating history.
- **Failed-path visibility:** superseded/challenged paths must remain queryable
  — design supersession as a new append-only state + edge, never a delete.
- **Outcome→check linkage:** a `supported` final outcome must enumerate the
  exact checks (test/tool results) that support it, by ID.
- **SDK surface:** extend `ReasoningSession` in `sdk.py` (e.g., record a
  verification / tool outcome / contradiction) so CLI/REST/MCP stay adapters.
- **No canonical promotion:** R3 outcomes are never facts and never auto-promote
  to MIRL (promotion is R5, out of scope).

### 4.3 Track B acceptance gates

- Isolation (run/namespace/scope), immutability, append-only.
- Failed/retried/challenged paths remain visible after supersession.
- Every supported outcome identifies its supporting checks by exact ID.
- No hidden chain-of-thought, provider payloads, activation/logit capture.
- No automatic reasoning→MIRL promotion.

---

## 5. Cross-cutting guardrails (both tracks)

These are hard constraints, not preferences:

1. **Provider-free by default.** No paid/provider model call, install, or
   download without explicit operator approval. Default embeddings/analysis must
   run locally/offline (mirror the existing offline posture).
2. **RAW/MIRL and the knowledge graph stay canonical.** Reasoning records public
   justification, never truth by implication.
3. **No hidden CoT / raw model payloads / activation or logit capture** anywhere.
4. **Non-displacement.** Graph/derived candidates must not silently displace the
   primary evidence lane (`GRAPH_MEMORY_MATURITY.md`).
5. **Reversibility & auditability.** Append-only; supersession over deletion;
   old identities/evidence remain auditable (G2 pattern, R3 failed paths).
6. **SDK is the boundary.** Extend `SeamSDK`/`ReasoningSession`; do not expose
   reasoning/knowledge SQLite tables as the integration contract.
7. **Determinism.** Fixed inputs + fixed policy version → identical outputs.
   Route new shared identities/fingerprints through `retrieval_policy.py`.
8. **Preserve unrelated files:** `.ua/`, `seam_runtime/.ua/`, `report*.png`,
   `docs/pricing-tiers.md`.

---

## 6. Verification gates (what "done" means per track)

Structural/provenance/temporal/isolation/determinism contracts pass **first**;
benchmark score movement is measured only **after** the capability exists
(benchmarks qualify, they do not gate whether the substrate is built).

Every track increment must green:

- full non-external suite (baseline at HISTORY#462: 1,823 selected, 1,821
  passed, 2 established xfails, 0 fail, 0 skip);
- the track's direct collection (reasoning-graph / reasoned-retrieval / graph
  tests) plus new contract tests for the increment;
- live pgvector slice where storage/boundary changed;
- touched-file Ruff, `python -m compileall`, `git diff --check`.

No paid/provider/benchmark run is launched without operator approval.

---

## 7. Sequencing and coordination

- **Track A internal order:** finish G3 (§3.2) → then G4 (§3.3). G4 provenance
  depends on G3 returned paths/traces.
- **Track B:** R3 proceeds independently, no wait on Track A.
- **Only coupling point:** R3 evidence references cite exact G-lane record/edge
  IDs via `retrieval_policy.py` fingerprints; no new ad-hoc cross-lane format.
- **Merge discipline:** separate branches per track; each lands green
  independently; neither may weaken the other's contracts. Repo is multi-agent —
  re-read files fresh before editing and check `git status` before committing.

---

## 8. Expected architect deliverables

For each track, produce a design document containing:

1. Data model (tables/columns or derived-on-read), with the append-only /
   projection/versioning story and migration + pgvector-resync plan.
2. Algorithm/flow (fusion normalization for G3; summary/community/observation
   derivation for G4; verification/supersession model for R3), with the
   determinism argument.
3. Module placement and the exact `SeamSDK`/`ReasoningSession` surface changes.
4. Provenance mechanics: how every derived sentence / supported outcome pins its
   supporting record+episode/check IDs, and how the trust gate fails closed.
5. Test contract: the specific structural/provenance/temporal/isolation/
   determinism fixtures the increment must add, mapped to §6.
6. Explicit statement of what is **out of scope** (e.g., R5 promotion, G5+
   context assembly) so the increment stays bounded.

---

## 9. Guardrail on claims

Do not claim "G3 complete," "G4 complete," "graph maturity," or "R3 complete"
until the measured gates in §6 and the relevant acceptance boundaries in §3.4 /
§4.3 actually pass. Partial slices are labeled partial (as G3a was).
