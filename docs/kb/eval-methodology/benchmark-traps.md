# Memory-benchmark traps (read before any paid run)

Every entry here cost a real paid run or a wasted session to learn. Check this
page before spending, and add to it after any surprising result.

## 1. Judge-model non-determinism inflates the miss set

**What happened (HISTORY#434):** re-answering 13 stored cat1 count *misses* with
the same model + same stored context, no lever, recovered **6/13 to CORRECT**.
gpt-4o at `temperature=0` is not deterministic enough; ~46% of that miss set
was unstable.

**Consequence:** a single run's per-category score carries several points of
rerun noise. A "miss" is not necessarily a stable miss. Before attributing a
gap to the memory layer, estimate the noise floor (rerun the same miss set once
with no change and count how many flip).

**Rule:** never gate a lever on a single-run miss set without accounting for
rerun variance. A lever's isolated effect = candidate-arm minus baseline-arm
*in the same rerun*, not candidate-arm minus the stored label.

## 2. Answerer strength changes where the headroom is

**What happened (#417 vs #434):** the count lever scored net **+5** against a
weak (gpt-4o-mini) answerer that got only 1/14 counts right, but net **+1**
against a strong (gpt-4o) answerer that already got 6/13 right without any
lever.

**Consequence:** a lever validated on the mini lane can evaporate on the
matched (gpt-4o) lane. Context-assembly levers help weak answerers most; the
matched contract uses the strong one.

**Rule:** validate on the answerer the *claim* will be made under. For a
"we beat mem0's published table" claim, that is mem0's published answerer/judge.

## 3. Model-mismatch on the paid runner (check the constants)

**What happened (#434):** the microgate runner had `ANSWERER_MODEL`/`JUDGE_MODEL`
hardcoded to `gpt-4o-mini` (a v1-era default). It was fired against a gpt-4o
artifact and produced an invalid result (the cases were selected as misses
under gpt-4o, not mini).

**Rule:** before any paid run against an artifact, confirm the runner's model
constants match the artifact's `metadata.answerer_model` / `judge_model`.
Runners now default to the artifact metadata and expose `--answerer-model` /
`--judge-model`; use them. Read the runner, don't assume.

## 4. Lenient vs. strict judge are not comparable — never average them

**What happened (#400, #415, #429):** SEAM's cat3 looked "topped" (86.5% vs
mem0's 72.7%) under mem0's **lenient** binary judge, but matched conditions with
a strict gpt-4o judge put it at 69.8% — *behind*. The lenient judge credits
partial lists, paraphrases, extra detail, ±14-day dates.

**Rule:** SEAM keeps **two separate scoreboards** — native judge/1 (strict,
internal ratchet) and the mem0-harness lenient judge (incumbent-relative). They
are never averaged and a number from one is never quoted against the other. A
public "we beat X" claim must hold under X's own judge.

## 5. Token-overlap / recall metrics false-positive on generic tokens

**What happened (multiple sessions, e.g. #369, and a Fable re-analysis in #405):**
a token-overlap classifier inflated "answerer-had-evidence" to 52% (real ~35%)
and set-drop ratios to 4:1 (real ~1.5:1). Years, counts, and generic tokens
match spuriously.

**Rule:** free deterministic recall/overlap checks *overstate*. Phrase-match and
hand-read a sample before claiming a bucket size. Use the free metric to
*rank/triage*, then confirm with a paid judge — never to declare a win.

## 6. "Evidence absent from the store" is easy to mis-scan

**What happened (#432, self-caught):** a blanket `SELECT *`-across-tables scan
wrongly concluded 36/40 golds were missing from the store (suggesting an ingest
bug). Targeted SQL disproved it — the evidence was present and retrievable by
target-side wording. The blanket scan silently missed content (swallowed
per-table exceptions, huge vector blobs).

**Rule:** to prove evidence is/ isn't in the store, query the specific text
columns (`raw_docs.content`) with `LIKE`, and validate the scan against a
known-present term before trusting a negative.

## 7. Invisible passes: artifacts under-report true spend

**What happened (#428, #434):** result artifacts hold only the *last clean pass*
per case. Rate-limit storms → strip-and-rerun; aborted partial passes and
provider retries bill but leave no artifact trace.

**Rule:** `benchmarks.external.common.cost_report` gives a tokenizer-true
(o200k for the gpt-4o/4.1/5 families) single-pass number — treat it as a
**LOWER BOUND**. Reconcile true spend against the provider dashboard.

## 8. Retrieval neutrality: fresh re-ingest ≠ frozen stored context

**What happened (#421):** a fresh full re-ingest+search shifted 316/378 top-200
lists (mean Jaccard 0.924) but was miss-set-neutral. Two already-correct cases
(`conv3_q61`, `conv5_q36`) lost partial evidence — the only regression risk a
fresh judged run carries.

**Rule:** stored-context probes (freeze the retrieval, vary only the thing under
test) isolate cleaner than fresh runs. When you must re-ingest, expect ±1–2
cases of ranking churn and watch the known-fragile pair.
