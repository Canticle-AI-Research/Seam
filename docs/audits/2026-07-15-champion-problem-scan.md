# Problem scan of the #390 champion record (0.7689) — what stands between us and "amazing"

Free mining of `20260714-192938-locomo-holdout.json` (T7), candidate arm =
conversation/2 + inference/high-confidence/1 + temporal/1 + broad, judge/1.
115 of 344 cases miss. **0.80 needs +10.7 case-points; 0.90 needs +45.**

## Every miss, classified by root cause and who owns it

| Problem class | cases | pts | owner | lever |
|---|---|---|---|---|
| **Set incompleteness / imprecision** | 43 | 26.0 | SEAM answerer | `conversation/4` (validating now) |
| **Single-fact: wrong-fact-picked or paraphrase** | 41 | 27.0 | mixed | retrieval disambig + judge |
| **Temporal precision / wrong instance** | 16 | 13.5 | SEAM answerer | UNSOLVED (temporal/2 regressed) |
| **Judge defect (full gold IS in the answer)** | 24 | 14.5 | judge/1 | NOT fixable at our end |
| **Over-abstention (answered "unknown", answer was there)** | 4 | 4.0 | SEAM answerer | abstention tuning — easy |
| **Counting / aggregation (under-counts)** | 3 | 2.5 | SEAM answerer | enumerate-then-count directive |
| **True retrieval gap (gold genuinely absent)** | ~10 | ~8 | SEAM retrieval | recall work |
| **Gold-label defect (LoCoMo corrupt/incomplete)** | several | — | dataset | CAPS the ceiling |

(Buckets overlap slightly by construction; the point is the shape, not a partition.)

## The five findings that matter

**1. The path to 0.80 exists on SEAM-ownable levers — comfortably.**
Set handling (26 pts) + temporal precision (13.5) + over-abstention (4) +
counting (2.5) = **46 pts of answerer-side headroom** against the 10.7 needed.
We do not need retrieval breakthroughs or judge changes to reach 0.80. We need
the answerer to synthesize what is ALREADY retrieved.

**2. ~14.5 pts are locked behind judge/1 and cannot be unlocked by us.**
24 misses contain the *complete gold* in the answer text; judge/1 marks them
wrong (extra-detail penalty, misread lists, alias/paraphrase). The judge/2
rejudge (HISTORY#392) proved this is a judge-*model* limit, not a prompt bug —
judge/2 scored these no better and violated its own rubric. So **0.80 on
judge/1 is realistic; ~0.85+ is where the judge ceiling starts biting.** This
is the single most important strategic fact: past ~0.82 we are increasingly
fighting the judge, not improving memory — which is exactly why the mem0-harness
number (lenient judge) matters for knowing our true standing.

**3. Temporal precision is the hardest unsolved SEAM problem (13.5 pts).**
temporal/1 resolves relative dates but picks the WRONG event instance:
"pride parade during the summer" → gold "week before 3 July", answer "14
August" (a different event). temporal/2's enumerate-then-pick directive
regressed. This needs a retrieval-side fix (rank the right dated turn higher),
not just a prompt — the model can't disambiguate instances the ranker buried.

**4. Set handling is the biggest single answerer lever (26 pts) — under test.**
35 of 43 have ≥2 comma-separated gold items. Split between incompleteness
(missing items) and over-generation (padding, which judge/1 penalizes).
`conversation/4` targets the over-generation half; a genuine recall lever
(retrieve more of the entity's scattered claims) targets the incompleteness
half — the #358 cross-turn coreference thread is the natural home.

**5. Over-abstention and counting are cheap, ignored wins (6.5 pts).**
4 cases answered "unknown" with the 1-item answer sitting in context (Gina's
dance style = Contemporary; Tim's composer = John Williams). 3 counting
questions under-count ("won seven" → answered "4"). Both are one-directive
fixes and neither has been attempted.

## Data-quality caveat (bounds every number)

At least one gold is corrupted (`"an animalkeeper at a localzoo and
workingwith turtles..."` — missing spaces), and the #369 audit already found
material gold-incompleteness (John's 6 stated exercises, gold captured 4).
These are unfixable and mean the *achievable* ceiling on this dataset under
judge/1 is below 1.0 — realistically low-0.90s even with a perfect answerer.

## Recommended attack order (by pts/effort, SEAM-ownable only)

1. **`conversation/4`** (validating now) — set over-generation, ~part of 26 pts.
2. **Over-abstention + counting directive** (free, ~6.5 pts, untried, one prompt).
3. **Set-incompleteness recall** (retrieve scattered entity claims; ties to #358).
4. **Temporal instance ranking** (retrieval-side; the hard 13.5 pts).
5. Stop optimizing judge/1 near ~0.82 — switch the scoreboard to the mem0
   harness (lenient judge) to measure true standing, per the calibration run.

Everything above is free to build; only the paid A/B validations are gated.
