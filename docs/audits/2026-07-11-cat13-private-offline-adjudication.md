# Cat1/cat3 private offline adjudication after judge/2

Date: 2026-07-11  
Private case-table SHA-256:
`2533688694306ddc66ae2e69ad4b44d4cf04a91c9fe56a93f0343636acb13cc5`

This document records aggregate, non-private conclusions from a free offline
review of the private LoCoMo records. The 43-row case table, retrieved context,
answers, rationales, and reasoning remain only on the operator's T7. No API
call was made and no additional money was spent.

## Scope and method

The review joined the two SHA-pinned source records from HISTORY#375 with the
paid `judge/2` report from HISTORY#376. It read each stored question, gold
answer, generated answer, judge transition, retrieved context, and locally
stored answerer reasoning.

Scope:

- all 27 cat1 cases from the original non-correct `uncertain` bucket that
  remained non-correct under `judge/2`;
- the two cat1 downward score transitions introduced by `judge/2`, which were
  originally correct and are therefore additional to and disjoint from those
  27 non-correct cases;
- all 14 non-correct cat3 cases, including the cat3 downward transition.

That is 43 unique cases: 29 cat1 and 14 cat3.

## Cat1 finding

| primary disposition | cases |
|---|---:|
| confirmed answerer failure | 8 |
| retrieval gap / insufficient retrieved evidence | 5 |
| judge or gold-label defect | 13 |
| mixed answerer + scope/gold ambiguity | 3 |

The confirmed answerer failures are not a generic verbosity problem. Their
shared mechanism is stopping after the first strong turn instead of completing
a cross-turn set: missed list members, an unresolved identity, an incorrect
count, or selection of a nearby fact over the queried one. The supported
answerer strategy is therefore:

1. collect candidate evidence items across all relevant turns;
2. preserve provenance and temporal scope;
3. deduplicate aliases/coreferences;
4. validate counts and required dimensions;
5. synthesize only after the set-completion pass.

The ceiling math changes the strategy. Cat1 currently has 43.0 score points
over 61 cases (`0.704918`). Perfectly converting all eight confirmed answerer
failures adds at most 4.5 points, reaching 47.5/61 (`0.778689`)—still below
0.80. Reaching strictly above 0.80 requires at least 49 points. Within the eight
confirmed cases, seven currently score 0.5 and one scores 0, so perfect
conversion adds `7 * 0.5 + 1 * 1.0 = 4.5` points. All three mixed cases
currently score 0.5, so their perfect conversion adds another
`3 * 0.5 = 1.5` points. The confirmed and mixed sets therefore provide exactly
six points together, reaching 49/61 (`0.803279`) only if every one converts. An
answerer-only PR has no tolerance for a single miss; retrieval or honest
judge/gold correction is otherwise required.

## Cat3 finding

| primary disposition | cases |
|---|---:|
| defensible world-knowledge inference target | 6 |
| judge/gold defect or underspecified inference | 8 |

The six defensible targets have a unique or reasonably strong mapping from
conversation clues to ordinary world knowledge—for example a recognizable
place, creator, game, or career inference. The other eight require ambiguous,
arbitrary, or unsupported guesses, or were already answered with an
alias-equivalent fact that the judge failed to credit.

Cat3 currently has 8.5 score points over 21 cases (`0.404762`). Perfectly
converting all six defensible inference targets reaches only 14.5/21
(`0.690476`). A score strictly above 0.80 requires at least 17 points, leaving a
2.5-point gap even after perfect conversion. Safe world-knowledge licensing
alone cannot reach the operator's 0.80 goal; doing so against the current gold
would require benchmark-specific guessing or correction of judge/gold defects.

## Decision point before product code

The measured goal and the honest product target have diverged. PR 3 can still
build two bounded, generalizable behaviors:

- cat1 cross-turn set-completion synthesis;
- cat3 high-confidence world-knowledge inference with ambiguity-aware
  abstention.

But those behaviors cannot honestly guarantee both raw LoCoMo category scores
above 0.80. Before implementation, the operator should choose which success
contract governs PR 3:

1. **Product-correct:** improve only verified, generalizable failures and
   report both raw and adjudicated score views.
2. **Raw-benchmark target:** permit benchmark-specific guessing/heuristics to
   chase the uncorrected gold score; this is not recommended as product logic.
3. **Measurement-first:** build an adjudicated evaluation overlay for the
   verified judge/gold defects, then set the PR 3 threshold against that honest
   view.

No further paid validation is justified until that choice is made and a free
implementation passes local survivor-set tests.
