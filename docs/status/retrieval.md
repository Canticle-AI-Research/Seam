# Status Stream: Retrieval

> Retrieval engine, ranking policies, provenance chain, and the open cat3 decision

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Status: green, promotion decision open

One canonical engine. `RetrievalOrchestrator` owns SQL, vector, graph,
graph-node, and explicit temporal retrieval. `SeamRuntime.retrieve()` is the
canonical entry; `search_ir()` is a compatibility result/evidence adapter over
the same plan, not a second scorer.

Ranking policies are named and selectable: `legacy-weighted/1` (pre-refactor
RAW/BM25/vector weighted scorer, kept as behavioral control),
`reciprocal-rank-fusion/2`, and `weighted-reciprocal-rank-fusion/1` (per-leg
weights; all-1.0 reproduces `/2` bit for bit).

## The #503 hold is lifted (HISTORY#509)

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
comparison trustworthy. Canonical therefore **beats** legacy by **+0.009628**.

#503 was comparing legacy against a canonical engine handicapped by a graph leg
that cost −0.023854 and contributed nothing. A==B==C to six decimals in every
category: with structural-edge traversal removed, LoCoMo has **zero admissible
semantic relation edges**, so `mix` and `hybrid` are the same query plan.

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
2. **ENT provenance is 0.0000.** Entities carry `prov` (compile lineage) but
   empty `evidence`, so a retrieved entity cannot prove which span mentioned it
   — even though the entity id encodes the source doc hash. Fixing it is a
   `compile_nl` change that alters ingest output and every corpus digest.
3. **`fusion_leg_weights` is UNVALIDATED** on a live graph leg — #509's arm C was
   confounded because the structural exclusion had already zeroed the leg. It
   ships an env var (`SEAM_RETRIEVAL_LEG_WEIGHTS`) and a policy fingerprint; do
   not present it as a supported lever until isolated.
4. Keep validated levers in core `RetrievalFlags` so every surface benefits.

## Methodology note

Retrieval **mutates** the SQLite store, so A/B arms must each start from a clone
of one pristine ingest-only snapshot (`benchmarks.external.locomo.ingest_only`),
run with `--keep-db`. Cloning after a scored run is a confound.
