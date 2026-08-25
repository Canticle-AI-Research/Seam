# Status Stream: Retrieval

> Retrieval engine, ranking policies, provenance chain, and the open cat3 decision

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Status: baseline measured, Track S promotion gates open

PR #222 merged the SQL leg's deterministic equal-score tiebreak and the
deleted-record vector-outbox replay repair at protected `main@a177852`. Those
repairs do not complete S8 or S9. See
`docs/audits/2026-08-18-track-s-deployment-readiness-audit.md`.

Published S6 derives the internal recall/context boundary from
an in-process principal and registers generation-bound opaque handles before
responding.
Its opaque delete path lifecycle-excludes an owned record immediately and
leaves derived cleanup recoverable. That is candidate tenancy/deletion
evidence, not S7 semantic-graph admission or S8 surface/retrieval-policy parity;
its protected-main publication does not advance those later Track S gates.

One canonical engine remains the architectural invariant.
`RetrievalOrchestrator` owns SQL, vector, graph, graph-node, and explicit
temporal retrieval. `SeamRuntime.retrieve()` is the canonical entry;
`search_ir()` is a compatibility result/evidence adapter over that engine, but
its legacy-policy hardcoding and the planner work executed around that path are
verified Track S S8 gaps.

The planner currently accepts `legacy-weighted/1` (the pre-refactor RAW/BM25/
vector behavioral control) and `reciprocal-rank-fusion/2`. Non-empty
`fusion_leg_weights` apply weighted contributions and report
`weighted-reciprocal-rank-fusion/1`. Unknown leg names ARE now rejected: the
S8 slice at HISTORY#605/#606 closed `FUSION_LEG_NAMES` over exactly the leg
names the engine can emit (`chroma`, `graph`, `graph_node`, `sql`, `temporal`,
`vector`) and validates once at the public runtime boundary, before planning,
adapter search, or candidate-dependent fusion. `reasoning_graph.RETRIEVAL_SOURCES`
is now that same definition, so the recorder cannot drift from what fusion
accepts. Name enforcement is split deliberately: `SEAM_RETRIEVAL_LEG_WEIGHTS`
normalizes whitespace around each name so `graph=0.3, vector=1.0` works, and
programmatic `RetrievalFlags` require an exact canonical name; a misspelling
from either surface fails before search. Policy persistence still does not
accept the `weighted-reciprocal-rank-fusion/1` identifier, so weighted fusion
remains an implemented, unpromoted path; S8 still owns its exact replay
contract.

## The #503 overall-regression premise is lifted; promotion remains open

HISTORY#503 reported canonical regressing −0.010804 and put the branch under a
DO-NOT-LAND hold. A matched four-arm ablation — every arm from its own clone of
one pristine ingest-only snapshot — **falsified that premise**:

| arm | config | overall |
| --- | --- | ---: |
| A | hybrid (sql+vector) | 0.776048 |
| B | mix (sql+vector+graph) | 0.776048 |
| C | mix + `graph=0.0` weight | 0.776048 |
| D | legacy-weighted | 0.766420 |

Arm D reproduces #503's legacy figure **exactly**, which is what makes the
comparison trustworthy. Canonical therefore **beats** legacy by **+0.009628**
overall on that run, while the category gate below remains open.

#503 was comparing legacy against a canonical engine handicapped by a graph leg
that cost −0.023854 and contributed nothing. A==B==C to six decimals in every
category: with structural-edge traversal removed, that default-ingest LoCoMo
snapshot had **zero admissible semantic relation edges**, so `mix` and `hybrid`
were the same query plan. This is a corpus observation, not a universal graph
claim. The explicit research compiler can emit REL records, but its measured
27/419 coverage remains insufficient and scorer-ineligible.

## Provenance chain (HISTORY#510)

Graph retrieval returns the **verified chain** back to source bytes —
`claim -> PROV -> SPAN -> RAW` with the exact source text sliced at the span's
character offsets. Contract `provenance-chain/1`, exposed as
`RetrievalCandidate.provenance` via `include_provenance=True`, default off and
pinned observationally inert.

Broken hops are reported with a specific reason code, never dropped. Measured:
**CLM 1.0000, RAW 1.0000, ENT 0.0000**.

Completeness is enforced at *write* time, not by luck: `verify_ir` rejects a
claim citing a missing PROV and a PROV naming no entity/activity/agent, and
`raw_spans.raw_id` is NOT NULL. A broken chain cannot be ingested.

## Active

1. **cat3 −0.036775 vs legacy — promotion decision.** Canonical wins overall and
   on cat1/cat4 (n=1,123) and loses on cat3 (n=96). Mechanism hypothesis,
   confirmed in code but NOT measured: RRF contributes `1/(60+rank)` and
   discards score magnitude, while the legacy scorer preserves it; cat3 is the
   name-the-entity-from-clues category where one record is decisively right.
   Cheapest test is a free run preserving magnitude as a tiebreak.
2. **S7 is published, while the native ENT measurement remains 0.0000.**
   PR #226 at protected `main@3385343` accumulates exact proposition SPANs for
   repeated ENT mentions and its provider-free retrieval conformance fixture resolves 5/5
   retrieved entities through complete exact SPAN-to-RAW chains. Historical
   corpora still contain evidence-empty ENTs and every affected digest changes
   on re-ingest. The 5/5 fixture closes the S7 mechanism gate; it is not a
   replacement native-corpus measurement or scorer-promotion claim. Native
   corpus freeze/review and promotion remain S9.
3. **`fusion_leg_weights` replay is now proven** — #509's arm C was confounded
   because the structural exclusion had already zeroed the leg. It ships an env
   var (`SEAM_RETRIEVAL_LEG_WEIGHTS`) and a policy fingerprint. HISTORY#606
   closes the replay contract: fail-closed leg names, absent/all-one/zero/
   non-unit persisted replay, and all-one scores bitwise identical to `/2`.
   Policy persistence now accepts `weighted-reciprocal-rank-fusion/1`, stores
   the exact weights a run ranked under (`reasoning_retrieval.leg_weights_json`),
   and re-derives the recorded score from them. This is a mechanism gate, not a
   quality claim: no measured lift is attached to any non-unit weight, so the
   lever stays unpromoted and default-inert.
4. **Surface/event identity is qualified across the shipped surfaces**
   (HISTORY#606) — runtime, `search_ir`, REST, SDK, MCP, and the TUI read path. `search_ir` no longer hardcodes its ranking policy;
   it is an explicit pass-through that returns the `retrieve()` ranking narrowed
   to the compatibility record kinds, proven under BOTH policies. Retrieval
   telemetry moved to the engine, so every path records exactly one
   tenant-scoped (`ns:scope`) event per successful retrieval, default-off via
   `SEAM_RETRIEVAL_EVENTS`, with telemetry failure proven answer-inert. **Still
   open:** `search_ir`'s default remains `legacy-weighted/1` — retiring it in
   favour of `/2` changes every recorded LoCoMo/mem0 arm and is therefore an
   S9-gated measurement decision, not an S8 refactor.
5. **Promotion remains S9-gated.** The provider-free 1,542-case result must stay
   at or above `0.7664201903042236` with category non-regression. A qualifying
   semantic graph corpus and fresh attributable graph-only lift are separate
   requirements; otherwise graph/scorer behavior stays default-off.
6. **Top-level graph wording is multi-benchmark gated.** Current LoCoMo,
   WANDR, and G7/R6 evidence is parity or graph-inert. The proposed causal
   portfolio, ablations, artifacts, and R0-R4 evidence tiers live in
   `docs/audits/2026-08-18-graph-benchmark-readiness-research.md`.

## Methodology note

Retrieval **mutates** the SQLite store **when retrieval-event writing is
enabled**, as it is on the benchmark path. Under default flags, direct
`SeamRuntime.retrieve()` does not: it leaves the database and WAL byte-identical
(re-verified 2026-08-02 — ingest, close, hash, reopen, retrieve, close,
re-hash). The published S6 principal-mode `/v1/memories/recall` and
`/v1/context` routes are intentionally stateful even with event writing off:
they register every returned generation-bound opaque handle before responding.
Read-purity measurements must therefore use direct/non-principal retrieval or
a fresh isolated store and must not hash a store after principal-mode recall as
though no derived write occurred.

The cloning rule therefore stands unchanged for measurement: A/B arms must each
start from a clone of one pristine ingest-only snapshot
(`benchmarks.external.locomo.ingest_only`), run with `--keep-db`. Cloning after
a scored run is a confound.
