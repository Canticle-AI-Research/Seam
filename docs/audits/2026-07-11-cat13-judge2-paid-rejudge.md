# Cat1/cat3 judge/2 paid replay

Date: 2026-07-11  
Code provenance: `e59cadf` (`main` at execution)  
Judge: `openai` / `gpt-4o-mini` / `judge/2`  
Scope: the corrected 82-case LoCoMo cat1/cat3 holdout record assembled by
case-id override from the two SHA-verified private source records documented in
HISTORY#375.

The operator explicitly approved the paid replay after a fresh dry-run
reconfirmed 82/82 eligible cases and a maximum projected cost of `$0.007422`.
The command used the fail-closed `--max-cost-usd 0.0075` guard. It replayed only
stored questions, gold answers, and generated answers; it performed no ingest,
retrieval, or answer generation.

## Execution result

- 82/82 cases judged; no empty-answer or budget-guard skips.
- Actual tokens: 35,069 input and 3,349 output.
- Actual cost: `$0.007270`, below both the estimate and approved cap.
- Private report SHA-256:
  `87700afc6f25e8b40ed11e2954b98cdd189705236005bb96162d1a03f6497848`.
- The report remains on the private T7 and is not committed. Per-case questions,
  answers, rationales, and failure data remain private with it.

## Measured score movement

| scope | cases | judge/1 | judge/2 | delta | correct count |
|---|---:|---:|---:|---:|---:|
| cat1 | 61 | 0.688525 | 0.704918 | +0.016393 | 28 -> 29 |
| cat3 | 21 | 0.428571 | 0.404762 | -0.023809 | 7 -> 7 |
| combined | 82 | 0.621951 | 0.628049 | +0.006098 | 35 -> 36 |

Nineteen verdict labels changed, but only seven changes affected score. Twelve
were `incorrect -> abstain` relabels for exact `unknown` answers and therefore
remained score zero. The score-changing transitions were:

- cat1: three `partial -> correct`, one `incorrect -> partial`, and two
  `correct -> partial` (net +1.0 score point across 61 cases).
- cat3: one `partial -> incorrect` (net -0.5 across 21 cases).

Groundedness totals were 47 `grounded`, 20 `unsupported_extra`, 12 `na`, and 3
`contradicts`.

## Reconciliation against the 30-case uncertain failure bucket

The HISTORY#375 bucket means the 30 non-correct cat1 cases classified
`uncertain` by `evidence/1`, not all cases whose evidence status is uncertain.
Under `judge/2`:

- 3/30 became `correct`;
- 23/30 remained `partial`;
- 2/30 became `abstain`;
- 2/30 remained `incorrect`.

Therefore 27/30 remain non-correct. The earlier 12-case hand sample's rough
hypothesis that about half might resolve at judge level was not borne out by the
full replay. The two canonical alias/specificity examples embedded in the
`judge/2` prompt did resolve, plus one complete answer with additional detail.
The remaining cat1 target is still substantive and retains the documented
list/enumeration-completeness pattern.

Cat3 received no correctness gain. Its 14 non-correct cases remain non-correct;
ten exact `unknown` answers were merely relabeled from `incorrect` to `abstain`.
The world-knowledge/inference answerer scope remains untouched and necessary.

## Judge-contract caveat

The paid replay also exposed imperfect contract adherence. Two previously
correct cat1 answers were downgraded to partial; one was penalized solely for an
extra, non-contradicting item even though `judge/2` explicitly says such detail
must not lower the verdict. The cat3 score regression labeled an incomplete
answer as contradictory. These are measurement defects, not evidence that the
answerer regressed—the stored answers were identical.

Do not automatically treat every surviving `judge/2` failure as a product
defect. Before PR 3 implementation, perform a free, offline review of the 27
survivors and the three downward score transitions, separating genuine
answerer omissions from residual judge/gold-label errors. Scope cat1 PR 3 to
verified enumeration-completeness failures and cat3 PR 3 to verified
world-knowledge/inference abstentions. Any further paid replay remains a new
operator-gated action.
