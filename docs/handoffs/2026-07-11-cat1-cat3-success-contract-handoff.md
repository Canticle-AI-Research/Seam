---
handoff_id: 2026-07-11-cat1-cat3-success-contract-handoff
supersedes: 2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff
handoff_status: current
history: HISTORY#379
---

# Handoff: cat1/cat3 success-contract decision after offline adjudication

- **Date:** 2026-07-11
- **Current durable state:** PR #140 merged; HISTORY#377 records the completed
  private offline adjudication; HISTORY#379 is the corrected durable record for
  this handoff-registry protocol change after HISTORY#378 lost inline labels to
  shell quoting.
- **Paid-work boundary:** no additional provider call is authorized. The
  offline adjudication added `$0.00` spend.
- **Unrelated local paths:** `.playwright-mcp/`, `.wrangler/`, and `visuals/`
  predate this workstream and remain outside its scope.

## Resume here

The next action is an operator product/measurement decision, not another
benchmark run and not an unapproved PR 3 implementation. Choose one success
contract:

1. **Product-correct raw + adjudicated reporting (recommended).** Improve the
   general product behavior that the evidence supports, preserve the raw
   benchmark score, and report a separately versioned adjudicated view for
   judge/gold defects.
2. **Raw-benchmark heuristics.** Add benchmark-specific guessing intended to
   move the raw score despite known underspecification. This is not recommended
   and must be isolated and labeled benchmark-only if selected.
3. **Measurement-first adjudicated overlay.** Build and validate the local,
   versioned adjudication layer before changing answer generation.

Do not implement product behavior until the operator selects one of these
contracts.

## Evidence that constrains the decision

- Cat1's 29 reviewed cases: 8 confirmed answerer failures, 5 retrieval gaps,
  13 judge/gold defects, and 3 mixed.
- Perfectly converting all 8 confirmed answerer failures reaches only
  `47.5/61 = 0.778689`. Converting all 8 plus all 3 mixed cases reaches exactly
  `49/61 = 0.803279`, with no tolerance for one miss.
- Cat3's 14 non-correct cases: 6 defensible high-confidence world-knowledge
  inference targets and 8 judge/gold-defective or underspecified cases.
- Perfectly converting all 6 defensible cat3 targets reaches only
  `14.5/21 = 0.690476`; safe inference licensing cannot honestly reach the raw
  `>0.80` target by itself.

The committed aggregate source is
`docs/audits/2026-07-11-cat13-private-offline-adjudication.md` (HISTORY#377).
The private 43-case table remains external and must never be committed.

## Implementation route after the decision

- Product-correct work: scope cat1 to cross-turn set completion
  (collect → provenance → deduplicate/coreference → validate → synthesize) and
  cat3 to high-confidence world-knowledge inference with ambiguity-aware
  abstention. Report raw and adjudicated results separately.
- Raw-benchmark work: first document the benchmark-only boundary and the
  expected product tradeoff; keep it out of default runtime behavior.
- Measurement-first work: define a versioned, reproducible local overlay from
  the completed adjudication before touching the answerer.

Any later paid validation remains separately operator-gated with an exact cost
estimate and fail-closed cap.

## Canonical continuity route

At every startup, read `docs/handoffs/INDEX.md`, follow its `latest` pointer,
and verify the chain with:

```bash
python -m tools.history.verify_handoffs
```

New handoffs must supersede this handoff through the registry instead of
creating an unindexed dated file.
