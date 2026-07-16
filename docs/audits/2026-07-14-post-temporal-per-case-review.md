# Per-case review: the #390 record (0.7689) and what closes the last 0.031 to 0.80

Free record mining of `20260714-192938-locomo-holdout.json` (T7, 688 rows), the
HISTORY#390 paid A/B: candidate = conversation/2 + inference/high-confidence/1 +
temporal/1 + broad profile, judged by gpt-4o-mini `judge/1`. Zero additional
spend. Cross-run comparisons use the #386 record (same 344 cases, same judge).

Arithmetic frame: 0.80 aggregate needs 275.2 case-points; the candidate holds
264.5. **Gap = +10.7 points** across 115 misses (71 partial = 35.5 pts headroom
at 0.5 each, 44 incorrect = 44 pts at 1.0 each).

## 1. What the levers actually did (case-level transitions vs #386)

| cat | ups | downs | signature |
|-----|-----|-------|-----------|
| 1 | 9 | 7 | conversation/2 nearly a WASH — converts some, regresses others (see §3) |
| 2 | 15 | 4 | temporal/1 clean win: 9 incorrect→correct, 4 partial→correct |
| 3 | 3 | 0 | pure win |
| 4 | 13 | 11 | churn ≈ noise, slight net positive |

temporal/1's nine cat2 conversions are exactly the designed shapes: "the week
before 1 January 2023" → answered "25 December", bare years resolved from "last
year", the months-between-appointments duration computed, and **five formerly
"Unknown" abstentions now answered correctly** — the directive licensed
commitment to a resolved time the model previously hedged on. Causality is
clean.

## 2. THE BINDING CONSTRAINT IS NOW judge/1's SCORING CONTRACT (Bucket A)

**24 of the 115 misses (19 partial, 5 incorrect — 14.5 case-points, more than
the whole 10.7-point gap) contain the complete gold answer inside the generated
answer text.** Another 15 contain ≥60% of it. The judge rationales show three
defect patterns, all previously documented in #372/#376:

- **Extra-detail penalty (explicit):** the run's poster child — "When did
  Melanie paint a sunrise?" (gold `2022`) answered *"Melanie painted a lake
  sunrise in 2022."* Verdict: partial. Rationale: *"includes the correct year
  but adds unnecessary detail about a lake"* — the "unnecessary detail" is the
  question's own subject. Same pattern on John's basketball goals ("adds extra
  details beyond those in the gold answer").
- **Misread list-format answers:** "Where has Maria made friends?" — the answer
  text contains homeless shelter, gym, AND church; rationale claims "does not
  mention the gym". The item was buried in a numbered list and the judge missed
  it.
- **Alias/subset under-scoring:** the movies case reproduces the LITERAL
  canonical judge/2 example ("Lord of the Rings" trilogy phrasing).

Verdict-by-format: answers containing numbered lists / multi-line enumeration
score **14% correct (4/29) vs 67% overall**. Mean answer length: partials 199
chars vs corrects 119.

## 3. conversation/2's own regression mode (Bucket B)

cat1's near-wash is self-inflicted: the exhaustive-sweep directive produces
numbered lists and "Additionally, …" narrative (cat1 mean answer length 177→190
vs #386). That format (a) triggers judge/1's extra-detail penalty and (b) gets
misread (§2). 21 of the 25 list-formatted misses are cat1. The scan behavior is
right; the OUTPUT CONTRACT is wrong — v2 needs "sweep everything, then answer
with the complete set as one concise line and nothing else."

## 4. Genuine remaining failures (Bucket C)

- **cat2 (17 incorrect):** ~5 retrieval gaps (gold tokens absent from retrieved
  context); ~4 wrong-event-instance selections (multiple dated mentions of a
  similar event; model picks the wrong occurrence — needs an
  enumerate-instances-then-pick-by-tense/reference clause in temporal/1);
  1 duration miss; plus judge date-window strictness (one REGRESSION:
  temporal/1 resolved Evan's palpitation to "29 May 2023" vs gold "first week
  of June 2023" — precise-but-adjacent now fails where vague-but-fuzzy passed;
  a date-tolerance is a judge-contract question, not an answerer bug).
- **cat1:** 18 partials with <60% gold coverage = real list incompleteness
  survives conversation/2.
- **cat4:** 25 misses with <60% gold coverage = real single-hop errors
  (wrong item/event picked from context).

## 5. Ranked path to 0.80

1. **judge/2 rejudge replay of this record's stored answers** — the #372
   harness (`tools/h2/rejudge_record.py`) exists exactly for this: no
   re-retrieval, no re-answering, dry-run cost first, expected ~cents.
   Cleanly measures Bucket A. If ~60% of the 14.5 locked points convert,
   aggregate ≈ 0.794 before any code change. OPERATOR-GATED (paid, cents).
2. **Terse-set output contract for conversation/2** (free build): keep the
   exhaustive scan, constrain the answer to the bare set. Recovers part of
   Buckets A+B under judge/1 and is strictly better formatting under any
   judge, including mem0's harness.
3. **temporal/1 instance-disambiguation clause** (free build): enumerate all
   dated instances before choosing; pick by tense + reference window. Targets
   ~4 cat2 incorrects.
4. Re-validate 2+3 stacked in one ~$0.80 holdout A/B (operator-gated).

Realistic combined landing zone: 0.80–0.81 under judge/1; higher under judge/2.

## 6. Measurement-contract note (operator decision, #377 framework)

Adopting judge/2 as the primary validation judge changes the measurement
contract mid-program: old numbers (0.6337/0.7326/0.7689) are judge/1 numbers
and stay comparable only to each other. judge/2 was built and live-validated in
#372/#376 to fix exactly the defects §2 documents; a rejudge replay reports
BOTH views from the same stored answers, which fits the raw+adjudicated
product-correct direction the operator chose after #377. Separately noted for
the public story: mem0's own harness judge explicitly credits partial lists,
extra detail, and ±14-day dates — most of Bucket A would already score CORRECT
there (see the mem0-harness scope, session scratchpad, to be tracked when that
work is picked up).
