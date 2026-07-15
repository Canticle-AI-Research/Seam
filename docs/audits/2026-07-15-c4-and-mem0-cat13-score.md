# Cat1/cat3 closeout: c4 negative and the mem0-harness scoreboard

This audit closes the paid-validation branch described by HISTORY#397. It keeps
two scoring contracts separate:

- `judge/1` is SEAM's strict, graded holdout scorer.
- `mem0-harness` is the unmodified `mem0ai/memory-benchmarks` LoCoMo answerer
  and binary lenient judge, pinned at commit `4b61c5d`, using SEAM through the
  Mem0-OSS HTTP facade from HISTORY#393/#394.

Numbers from one contract are not interchangeable with numbers from the other.

## 1. Conversation/4 did not improve the judge/1 champion

The full 344-case holdout A/B completed cleanly at code `96117b5`. Candidate =
`conversation/4` + `inference/high-confidence/1` + `temporal/1` + broad; fresh
baseline = stock. The private run record is
`20260715-071132-locomo-holdout.json` on the configured external record volume.

| view | aggregate | cat1 | cat2 | cat3 | cat4 | cat5 |
|---|---:|---:|---:|---:|---:|---:|
| c4 candidate | 0.754360 | 0.614754 | 0.682432 | 0.595238 | 0.850267 | 0.000000 |
| #390 champion | 0.768895 | 0.614754 | 0.722973 | 0.595238 | 0.855615 | 1.000000 |

The c4 candidate beat its freshly measured stock arm (`0.629360`) by
`+0.125000`, but regressed `-0.014535` against the actual #390 champion. Cat1
and cat3 were exactly unchanged. Against #390 candidate cases, c4 produced 16
upward and 22 downward verdict transitions overall; cat1 was 4 up / 4 down and
cat3 was 1 up / 1 down. Cat2 lost three binary-equivalent case points, cat4 lost
one, and the single cat5 item was a stochastic wrong answer rather than a c4
target.

The run used 5,200,972 tokens and cost `$0.793850`. It completed with 0 empty
answers, 0 judge retries, and no provider retry/error lines.

### What c4 changed

On #390 cat1 misses, 21 cases had terminated at the 64-token answer limit. c4
reduced that count to 10, proving that its precision clause changed generation,
but the gains and losses balanced exactly. The strict judge rewards some shorter
sets and rejects other product-correct sets when the gold list is incomplete.
This is not evidence that the memory layer regressed; it is evidence that c4 is
not a reliable route to a higher `judge/1` score. It remains default-off.

## 2. The remaining prompt-only proposals failed the cheap gate

Two uncommitted, default-off proposals were tested against stored #390
retrieved contexts before any further full holdout:

- `conversation/5`: c4 plus a private type/membership ledger and compact
  comma-separated set output.
- `inference/high-confidence/3`: bounded canonical-entity resolution from
  descriptive clues.

The first answerer-only microcheck used 18 stored contexts, no retrieval and no
judge calls. Estimated cost was `$0.034866` (230,673 prompt tokens, 441
completion tokens). Cat1 produced one clean recovery (`Luna, Oliver, Bailey`)
but retained broad false positives for board games, exercises, goals, and other
set questions. Cat3 recovered none of eight target entities.

A second 10-case microcheck repeated only the new requirement next to the final
question, guarding against instruction loss in long broad contexts. Estimated
cost was `$0.018784` (124,589 prompt tokens, 160 completion tokens). The pet-name
recovery remained the only clean cat1 movement. Cat3 recovered `Exploding
Kittens`, but the other key cases remained wrong: `John Williams` stayed
unknown, `Voyageurs National Park` became Yosemite, Mafia stayed Among Us, and
the Ireland-filming answer hallucinated only the Cliffs of Moher.

That is not credible movement toward either category exceeding 0.80. No second
full `judge/1` holdout was launched. The uncommitted v5/inf3 runtime and test
changes were removed; only this measured negative is retained.

## 3. Judge/1 ceiling and the honest scoreboard pivot

The #390 cat1 score is 37.5/61 (`0.614754`), so exceeding 0.80 requires another
11.5 case points. Its 41 misses contain 35 partial and 6 incorrect verdicts;
the prior problem scan found multiple cases where the full gold is already in a
product-correct answer but `judge/1` still assigns partial. Cat3 is 12.5/21
(`0.595238`) and needs another 4.5 points. The c4 transition audit and the two
microchecks do not prove a mathematical ceiling, but they do show that further
prompt pressure is an expensive, low-confidence way to chase this scorer.

The mem0 harness directly measures the separate public-table-style contract
identified in HISTORY#393: partial lists are correct, extra detail is accepted,
and dates have a tolerance. Its answerer and judge were both explicitly
overridden from the current expensive `gpt-5` defaults to `gpt-4o-mini`; the
harness used one top-200 cutoff.

The facade process was configured with the #390 environment
(`broad` + `conversation/2` + `inference/high-confidence/1` + `temporal/1`),
but the effective boundary matters: the unmodified harness owns answer
generation and judgment, while the facade constructs `SeamLocomoAdapter` with
`answerer=None`. Consequently the conversation, inference, and temporal answer
directives do not enter the harness prompt. This scoreboard measures SEAM's
retrieved memories at the harness's top-200 contract plus the harness answerer
and judge. That is the intended fair-comparison path, not a second execution of
SEAM's native #390 answer-policy stack.

### Small scored calibration

The apparently stalled calibration finished after the prior handoff. On the
first 40 questions from conversation 0 it scored 38/40 overall (95%):

- cat1 multi-hop: 15/15 (100%)
- cat3 open-domain: 5/5 (100%)
- cat2 temporal: 18/20 (90%)

Prompt reconstruction estimates `$0.078264` for those 40 answer+judge pairs.
This established that the HTTP facade, answer phase, structured judge phase,
and result writer were all stable before widening scope.

### Full cat1/cat3 category score

The final category-only run covers all ten LoCoMo conversations and every cat1
or cat3 question (282 multi-hop + 96 open-domain = 378 questions) at top-200.

| category | correct / total | accuracy |
|---|---:|---:|
| cat1 multi-hop | 250 / 282 | **88.7%** (`0.886525`) |
| cat3 open-domain | 83 / 96 | **86.5%** (`0.864583`) |
| combined scoped run | 333 / 378 | 88.1% (`0.880952`) |

Both categories therefore exceed 0.80 under the mem0-harness contract. All 378
questions wrote non-empty answers. The harness logged 27 retry-attempt warnings
while brushing the 200K TPM limit; every call recovered within its five-attempt
budget and no empty or failed result was saved.

The unified private artifact is retained on the configured external record
volume as `20260715-091018-mem0-harness-cat13.json` (24,392,640 bytes), SHA-256
`e93cc7a4cd2611bd7b68906d90d8ad0d63684a933ee637b50403fb74104c2b4f`.

The external harness does not retain provider usage objects, so its cost is
reconstructed rather than claimed as exact. Tokenizing the exact stored prompts
and stored outputs yields 4,545,540 input tokens and 24,512 output tokens,
estimated at `$0.696538` using the same July 2026 gpt-4o-mini pricing snapshot as
SEAM's run records. The 40-question calibration was estimated at `$0.078264`.
Together, scored mem0-harness work was approximately `$0.774802`.

Known successor-slice cost roll-up: c4 `$0.793850` exact + v5/inf3 microchecks
`$0.053650` estimated + mem0 calibration/full `$0.774802` estimated =
`$1.622302`. This does not invent usage for the earlier inference/2 functional
microcheck, whose provider response usage was not retained.

### Post-score facade hardening

Review of the pushed closeout head found two parity gaps in the HTTP facade.
The current code now passes the native adapter's `temporal_window` and
`temporal_reference` into `search_ir`, and expands `SPAN.raw_id` links before
filtering candidate closures to RAW records. Regression tests pin both paths.

These corrections were made after the scored artifact above was written. No
paid rescore was performed, and the retained JSON remains the exact record of
the pre-hardening run rather than being silently attributed to the corrected
facade.

## Decision

- `conversation/4`: tested and parked, default-off; not a new champion.
- `conversation/5` and `inference/high-confidence/3`: microverified negative and
  removed before commit.
- No further full `judge/1` run is justified by the evidence in this branch.
- Report the final mem0-harness cat1/cat3 result as the **mem0-harness
  scoreboard**, never as an improvement to the `0.768895` `judge/1` champion.
