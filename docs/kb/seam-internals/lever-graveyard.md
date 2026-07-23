# Retrieval / answer-policy lever graveyard

Every lever tried against the LoCoMo / mem0-harness gap, with the measured
result. **Read before proposing a lever — do not re-propose a dead one without
new evidence that the original kill reason no longer applies.**

Legend: 🟢 validated win (in a champion) · 🟡 built, default-off, inconclusive/
parked · 🔴 measured loser / killed · ⚙️ live, under evaluation.

## Killed / parked

| Lever | Verdict | Why (HISTORY) |
| --- | --- | --- |
| `exact-answer/1` (draft-then-verify prune) | 🔴 | Paid A/B loser, every category down; the precision-prune *deletes gold* under judge/1, which rewards fuller answers (#412). |
| `conversation/4` (precision-balanced set) | 🔴 | cat1 −0.041 vs champion; discards conversation/2's completeness wins (#402/#405). Keep `conversation/2` as base. |
| `conversation/3` (bare-answer format) | 🔴 | Terse sets make the model emit MORE-complete lists; judge/1 extra-detail penalty fires harder (#391/#392). |
| `temporal/2` (instance disambiguation, answer-side) | 🔴 | Regressed cat2 on revalidation (#392). |
| `inference/high-confidence/3` (cat3 naming) | 🟡 | Free preflight inert: identifying clues never reach the retrieved context — the cat3 naming wall is retrieval-side second-hop, not an answer directive (#419). |
| `entity-bridge/1` (second-hop retrieval) | 🔴 | Free gate: 0/48 misses gained. You cannot bridge from evidence you never retrieved; bridge terms are mined from primary results that, for these misses, don't contain the target (#431/#432). |
| `event-count/distinct/1` (count projection v1) | 🟡 | Microgate net +5 vs a *weak* answerer but 6/14 < 7 gate; full run not green-lit (#417). |
| `event-count/distinct/2` (same-event grouping) | 🔴 (matched) | Paid microgate net +1, gate 7. Strong gpt-4o answerer already counts well (baseline 6/13); count bucket has little headroom under the matched contract (#434). Built, default-off. |
| `entity_grounded_scoring`, `dossier`, `entity_agg`, `decomposition` | 🔴 | Null/negative on cat1; decomposition measured harmful (#358, #396, #405). |
| `resolve_identity` (G3 graph identity-fold into source-RAW retrieval) | 🟡 | Correct mechanism (alias→canonical reach + no double-count, default-off), but ZERO fuel on LoCoMo: a free probe over 3 conversations found `pairs_examined=0` — the honest-minimal extractor emits 0 alias terms and 0 entity labels are shared across distinct nodes (exact-label coreference already dedups identity at ingest). The alias-fold can never fire on LoCoMo, so it cannot move that score. Banked as an agent-memory capability, not a LoCoMo lever; would need a non-exact alias SOURCE (richer extractor / embedding-based candidates) to have any fuel, and even then LoCoMo's wall is retrieval-side second-hop, not identity (#458/#459). |

## Validated (in a champion)

| Lever | Where | HISTORY |
| --- | --- | --- |
| `conversation/2` (exhaustive set-completion evidence projection) | native champion base | #389/#390 |
| `temporal/1` (resolve relative dates against message timestamps) | native champion; cat2 +0.12 | #389/#390 |
| `inference/high-confidence/2` (anti-abstention) | modest net-positive (cat4/cat2) | #402/#405 |
| `broad` profile (top_k 300 / budget 60000) | native champion; every category up | #385/#386 |

Native judge/1 champion aggregate: **0.7762** (#402). Note: past ~0.82 the
binding constraint is judge/1's own scoring defects, not memory (#391/#396).

## Live

| Lever | State | HISTORY |
| --- | --- | --- |
| `grounded-clm/1` (derived facts at ingest) | ⚙️ built, default-off; free coverage preflight + faster extractor are the next gate | #435; see `derived-facts-grounded-clm.md` |
| `temporal-instance/1` (facade temporal projection, cat2) | 🟡 built, default-off, unvalidated | #427 |

## The pattern across the graveyard

Answer-side/format levers and single-query retrieval tricks are **exhausted**
against the matched-conditions gap. The two biggest #429 miss buckets (counts,
second-hop) both came up short under proper gates. The remaining headroom is
**retrieval/compile-side**: make the stored/retrieved memory lexically match the
question (derived facts), because the diagnosed wall is query↔evidence wording
distance (#432), not answer generation.
