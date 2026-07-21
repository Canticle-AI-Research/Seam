# Mem0-harness cat1 non-count miss mining (free, 2026-07-18)

Source: private HISTORY#400 artifact (`20260715-091018-mem0-harness-cat13.json`,
SEAM cat1 250/282 = 88.65%). Method: for each of the 18 non-count cat1 misses,
resolve the question's gold `evidence` dia_ids against the local LoCoMo dataset
and shingle-match each evidence turn against the 200 retrieved memories, then
classify the failure from gold vs generated answer and judge reasoning. Zero
provider calls; no licensed text is reproduced here (question IDs only).

## Evidence-presence split (18 non-count misses)

| Evidence in top-200 | Cases | Meaning |
|---|---|---|
| ALL | 9 | retrieval delivered; answer generation missed it |
| PARTIAL | 7 | part of a multi-turn gold set never retrieved |
| NONE | 2 | the naming turns never retrieved at all |

With the 14 count misses (12/14 evidence-complete, HISTORY#416): **21 of 32
cat1 misses are answer/context-assembly-side; ~11 involve a retrieval gap.**

## Failure shapes

1. **Wrong-instance selection despite evidence present (ALL bucket, ~5)** —
   conv1_q23, conv3_q23, conv0_q61, conv5_q41, conv4_q50: the answerer picks
   plausible-but-wrong facts from neighboring events even though gold turns are
   in context; with the lenient judge these still score zero because *no* gold
   item appears. Same family as the native "answerer-had-evidence" bucket.
2. **Cross-turn join misses (ALL, ~2)** — conv1_q9 ("which city have BOTH
   visited"): needs joining two speakers' separate turns; answered "none".
   conv7_q77: location stated in a nearby turn, answer omits it.
3. **Date-resolution misses (ALL, 2)** — conv3_q51, conv0_q76: answer says
   "date not specified" while the evidence turn is in context with its
   bracketed timestamp; the model does not read the `[Speaker ts]` prefix as
   the event's date anchor.
4. **Planned-vs-done confusion (ALL, 1)** — conv5_q56: gold "No", answer "Yes"
   — a stated *plan* was read as a completed event. The
   `event_count_context` classifier already distinguishes exactly this
   (observed vs planned) but only fires on count questions.
5. **Set-enumeration with partial retrieval (PARTIAL, ~6)** — conv3_q58,
   conv3_q74, conv2_q35, conv8_q72, conv8_q82, conv4_q11: list-type golds
   ("what has X recommended/visited/does for stress") where several gold turns
   never retrieved; generated lists share zero items with gold.
6. **Second-hop entity naming (NONE, 2)** — conv2_q40 ("names of John's
   children"), conv6_q18 (book titles list): the turns that *name* the
   entities share no surface overlap with the question wording. **Identical
   shape to the cat3 naming root cause (HISTORY#419: John Williams /
   Voyageurs / Exploding Kittens).** One retrieval lever serves both
   categories.

## Lever candidates (ranked)

1. **Generalize the count projection into a query-aware evidence-digest block**
   (targets shapes 1–4, ≈10 cases + reinforces the count lane). In the Mem0
   facade only the projection *text block* survives the harness's re-sort
   (HISTORY#417), so the digest must quote the query-relevant rows verbatim
   with provenance inside one block: relevant-row promotion, per-row resolved
   date from the bracket timestamp, observed/planned tagging, and join hints
   (rows from both speakers on the queried attribute). Validate through the
   existing microgate runner on the 18 stored cases (same free-dry-run →
   ~$0.10 paid pattern). NOTE: touches `seam_runtime/event_count_context.py`,
   which SOL's uncommitted `event-count/distinct/2` build is editing — do not
   start until that lands.
2. **Second-hop entity/preference retrieval assembly** (shapes 5–6, ≈8 cat1
   cases + the cat3 naming wall): retrieve turns that name entities associated
   with the question's subject/attribute despite zero lexical overlap (graph
   closure / entity-preference aggregation). Query decomposition remains
   measured-harmful (HISTORY records); this is closure over already-linked
   entities, not query splitting. Retrieval-core, serves both scoreboards and
   real agent memory — the durable lever.
3. **Extend planned-vs-observed gating to yes/no "has X done Y" questions**
   (shape 4): cheap reuse of the existing clause classifier, fold into lever 1.

## Different tests / different comparisons — what would actually give clues

- **Answerer-parity is the mismatch worth testing first.** Our 88.65% used a
  gpt-4o-mini answerer/judge; mem0's published table numbers use their gpt-4o
  defaults. The current "beat 91%" comparison is therefore cross-answerer.
  Cheapest informative probe (~$2): rerun the 32 stored-context cat1 misses
  with a **gpt-4o answerer** through the existing microgate machinery — if a
  large fraction flip, much of the remaining gap is answerer-strength, and a
  matched-answerer full run (~$10–15) likely clears 91% with no new code. The
  native lane already showed a capable answerer rises with big contexts where
  the small one plateaus (capable-answerer knee, HISTORY#390-era).
- **Matched-budget mem0/Zep in-harness rerun (~$2.5, long-planned)**
  bulletproofs the head-to-head in the other direction (their systems under
  our conditions).
- **A second benchmark (LongMemEval/BEAM)** is the out-of-distribution guard
  against teaching-to-LoCoMo — right after the 91% goal or at lever plateau,
  not before.
- A frozen never-iterated holdout slice for promotion-time reads remains the
  recommended hygiene upgrade (this mining, like all prior mining, reuses the
  same artifact population).

All paid probes above are operator-gated; none were run in this slice.

## Addendum: free retrieval diff vs the scored run (2026-07-18, $0)

Question: did the post-score #400 facade fixes (temporal window pass-through,
SPAN→RAW closure expansion) or the merged #152 graph/auto-ingest work change
the Mem0-harness retrieval surface? Method: fresh full `--predict-only` pass
(378 questions, cats 1+3) through today's facade (README validated-stack env,
top-k 200, fresh scratch store, upstream harness @ `4b61c5d`, zero provider
calls), then per-question diff of fresh vs stored top-200 lists and a rerun of
the evidence-presence mining on both.

Result — **the code changes are effectively NEUTRAL on this lane**:

- 378/378 compared. Membership changed on 316 lists but shallowly: mean
  Jaccard 0.924 (15 more are pure reorders, 47 byte-identical). Tail churn,
  not systematic movement.
- **Miss set (45): evidence improved on 1 (conv3_q62, a count case that was
  already answer-side), regressed on 0, unchanged on 44.** The fixes did not
  materially bind on the miss set, and #152 did NOT displace RAW (no mass
  evidence loss anywhere).
- Correct set: 6 evidence-improved (already correct), **2 regressed
  ALL→PARTIAL (conv3_q61, conv5_q36)** — the only regression risk a fresh
  judged run would carry.

Conclusions: the 88.65% baseline remains valid within noise; a fresh $0.70
judged rerun would measure ±1–2 cases of ranking noise, so it is NOT
worthwhile as a fixes-probe — defer it to pre-publication re-anchoring. The
answerer-parity probe (~$2, stored contexts, unaffected by any of this)
remains the highest-information paid move, followed by the two levers.
Watch conv3_q61/conv5_q36 in any future full run.
