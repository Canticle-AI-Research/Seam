---
handoff_id: 2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff
supersedes: 2026-07-09-cat1-cat3-deepseek-fixes-handoff
handoff_status: superseded
history: HISTORY#375
---

# Handoff: cat1/cat3 → 0.80 program — PR 1 + PR 2 merged, PR 3 scoped by real data, nothing paid spent

- **Date:** 2026-07-11
- **From:** Claude (Opus)
- **To:** whoever picks up the cat1/cat3 → 0.80 thread next (human operator, Codex, or another Claude session)
- **Repo HEAD at handoff:** `3a6dac2` (`main`, == `origin/main`, tree clean apart from unrelated untracked Playwright artifacts from a separate session — `.playwright-mcp/`, `.wrangler/`, `visuals/` — left untouched, not part of this thread)
- **Operator's standing goal:** LoCoMo cat1 AND cat3 judged score > 0.80 each (memory `project_cat1_coreference_parked_and_20pt_goal`, `project_mem0_parity_goal`).
- **This session's total paid spend: $0.00.** Every step below is free/dry-run only. A ≤$0.0075 paid rejudge is built, tested, and awaiting explicit operator `--confirm-paid`.

---

## TL;DR

1. **PR 1 (#135, merged) — measurement integrity.** The old `context_recall` failure classifier (`context_recall >= 0.5`) mislabeled correct "unknown" refusals as answerer failures. Built a conservative `evidence_status` classifier (`present`/`absent`/`uncertain`/`open_domain`) requiring multi-token gold answers to **co-occur within a single conversational turn** before calling evidence "present." Real-data replay on the 82-case corrected holdout baseline: v1's 33 `answerer_miss` collapsed to **35 correct + 14 open_domain_inference (cat3) + 3 retrieval_miss + 30 uncertain, ZERO clean answerer_miss**. This means the prior "SEAM is answerer-bound" framing rested substantially on classifier false confidence.
2. **PR 2 (#136, merged) — judge correctness + replay harness.** Built `judge/2` (fixes alias/abbreviation scoring like `LeBron` vs `LeBron James`, subset-phrase scoring like `LOTR trilogy` vs gold `LOTR`, stops penalizing non-contradicting extra detail, separates a `groundedness` axis). Built `tools/h2/rejudge_record.py`: replays the 82 already-stored answers with **no re-retrieval, no re-answer** — dry-run by default, `--confirm-paid` + `--max-cost-usd` (fail-closed spend cap) + `--out` required to spend. Every output carries full reproducibility provenance (source-record SHA-256, code git SHA, UTC timestamp, judge/model/prompt versions, per-case + aggregate actual token usage/cost).
3. **PR 3 gap found and fixed same-day (#137, merged) — Claude judge/2 parity.** PR 2 gave `OpenAIJudge` full `judge/2` support but explicitly left `ClaudeJudge` on `judge/1` only. A Codex follow-up review correctly caught that this was a **real bug, not just deferred scope**: the CLI advertised `--judge claude --judge-prompt-version judge/2` but silently ran `judge/1` anyway — a paid Claude replay would have recorded false provenance. Fixed with the same version-plumbing pattern already used for OpenAI.
4. **A separate GitHub Actions billing block** stalled PR #137's CI for several hours (confirmed via the GitHub API annotation: "recent account payments have failed or your spending limit needs to be increased" — a real account-level block, not a code failure). Operator resolved it on GitHub's side; verified by rerunning the dead workflow run and watching it go from instant-death to real `in_progress` to `pass`.
5. **New, not-yet-acted-on finding (this entry): the 30-case "uncertain" bucket from PR 1 is 100% cat1, and splits into two genuinely different problem classes** — see below. This sharpens PR 3's scope from a vague "cat1 needs enumeration/count/date/identity fixes" into a much more specific, evidence-backed target.

---

## Repo / infrastructure state (all clean, all merged)

- `main` @ `3a6dac2`. HISTORY chain at **#374**. PRs #135, #136, #137 all merged via plain `--squash` (never `--auto`, per repo policy — see HISTORY#349/#351 incidents), CI green, CodeRabbit reviewed with zero findings on all three, branches auto-pruned.
- Only PR #121 (pgvector HNSW, pre-existing, unrelated) remains open.
- The private diagnostic data lives at `/media/terrabyte/T7/Proprietary/DATA/` (canonical) with byte-identical gitignored mirrors under `benchmarks/runs/records/` (confirmed `.gitignore:80` coverage). **Never commit these.** SHA-256 of the two files used throughout this thread:
  - `20260709-102349-locomo-holdout-cat1cat3-deepseek-v4-pro.json` → `887e18af5ea1d449b2ecb3fb69e029d238c684f3f144c03700a7bd35265357f4`
  - `20260709-125547-locomo-holdout-cat1cat3-deepseek-v4-pro-tokenfix.json` → `7d27969bba4f3850cbed1b6cfa25767b6951f5a93177c50216312326d396901c`
  - (A third file, `20260709-152111-locomo-holdout-precision-v2-deepseek-v4-pro.json`, was the earlier null-result precision-prompt experiment — not part of the corrected 82-case baseline, referenced only in HISTORY#369/#371.)
- **The "corrected baseline"** = the 82-case full run (`...102349...json`) with its 4 token-budget-truncated empty answers replaced by their rows from the tokenfix run (`...125547...json`), keyed by `case_id`. This reconciliation pattern is implemented in `tools/h2/rejudge_record.py::_load_cases` (later files override earlier by `case_id`) and was done manually via a small script for the PR 1 replay analysis.

---

## The new finding: what's actually inside the 30-case "uncertain" bucket

This is genuinely new analysis, done in this session, **read-only** against the private records — no code changed, no HISTORY entry needed for the analysis itself, but recorded here so it isn't lost.

Replaying the corrected 82-case baseline through the merged `evidence_status` + `classify_failure_conservative` code gives, per category:

```
by category: {'1': 30}   # the entire uncertain bucket is cat1; cat3 has none
by original verdict: {'partial': 25, 'incorrect': 5}
```

Sub-reasons (from `evidence_status`'s rationale string):

```
partial_token_coverage:   15/30   (some but not all distinctive gold tokens found in context)
scattered_across_turns:   10/30   (all gold tokens present, but not co-located in one turn)
single_weak_token:         3/30
gold_has_no_content_tokens: 2/30
```

### Hand-checking 12 real examples splits them into two distinct problem classes

**~5 of 12 look like judge-level false negatives — `judge/2` (already built, not yet run) should fix these for free:**
- `conv-42::q42`: gold `"Little Women", "Lord of the Rings"` vs model's `"Little Women and The Lord of the Rings trilogy"` — this is *literally* the canonical example written into the `JUDGE_PROMPT_V2` instructions.
- `conv-43::q36`: gold `LeBron James` vs model's `LeBron` — the other canonical example baked into the prompt.
- `conv-41::q21`: gold `Pacific northwest, east coast` vs model's `East Coast, Pacific Northwest, California` — extra correct, non-contradicting detail (verified true and explicitly stated in context, per HISTORY#369's manual check). Judge/1 penalizes this; judge/2's explicit rule says it must not.
- `conv-30::q5`, `conv-43::q0`: similar shape — model states every gold item plus additional verified-true detail.

**~6 of 12 look like genuine answerer omissions — `judge/2` will NOT fix these, only a generation-side change (a real PR 3) can:**
- `conv-26::q23`: gold has 2 books, model reported only 1 ("Charlotte's Web," missing "Nothing is Impossible") — a clean, real omission. Matches the exact "incomplete search across a large packed context" pattern already identified in HISTORY#369 as the one manually-confirmed fixable error class.
- `conv-42::q10`: gold lists 5 emotions, model reported 3 — missing "hope" and "anxiety" outright.
- `conv-42::q59`: gold has 2 actions (corkboard + notebook), model reported only the notebook one, generically paraphrased.
- `conv-47::q22`: gold has 3 charity beneficiary types, model reported 2 — missing "homeless" specifically. **Notable:** this exact case was flagged in HISTORY#369's earlier precision-prompt experiment as one where a prompt tweak *did* get the model to add "homeless beneficiaries" to its answer, but the score didn't move — because it was **judge/1 failing to credit it**, not the model failing to find it. Worth re-checking after the paid rejudge to see if judge/2 now credits this correctly, or if it's still missed and is a genuine remaining generation gap.
- `conv-42::q30`, `conv-42::q70`: mixed — contain most/all gold items but the boundary between "real extra detail" and "possibly ungrounded extra detail" is genuinely ambiguous here; exactly the kind of case the new `groundedness` axis (`grounded`/`unsupported_extra`/`contradicts`/`na`) is designed to separately flag without changing the verdict.

### Why this matters for sequencing

This is not "cat1 has a vague answerer problem" — it's specifically **a list/enumeration-completeness problem**: the model finds *some* items in a multi-fact answer but stops short of all of them, especially when the relevant facts are scattered across a long packed context. This exactly matches the operator's original PR 3 spec ("For lists, collect evidence items first, deduplicate aliases, then synthesize the final answer") — now with concrete supporting examples instead of a hypothesis.

**But roughly half the sampled "uncertain" cases look like they'll resolve for free once `judge/2` actually runs.** Building PR 3 before running the paid rejudge risks either (a) PR 3 effort landing on cases that would have resolved for free, or (b) an eventual before/after PR 3 comparison being confounded by the judge fix landing in the same measurement window.

---

## Recommended next steps (in order, not yet executed — operator decision pending)

1. **Run the paid rejudge** (`tools/h2/rejudge_record.py --confirm-paid`). Fully built, tested (33 tests across `test_rejudge_record.py` + related judge/run-record slices), fail-closed cost-capped. Real dry-run against the corrected 82-case baseline from current `main`:
   ```bash
   .venv/bin/python -m tools.h2.rejudge_record \
     --record /media/terrabyte/T7/Proprietary/DATA/20260709-102349-locomo-holdout-cat1cat3-deepseek-v4-pro.json \
     --record /media/terrabyte/T7/Proprietary/DATA/20260709-125547-locomo-holdout-cat1cat3-deepseek-v4-pro-tokenfix.json \
     --judge openai --judge-model gpt-4o-mini --judge-prompt-version judge/2
   ```
   Last confirmed estimate: **`max_estimated_cost_usd = 0.007422`**, 82/82 cases eligible. **Re-run this dry-run once more before spending** — `main` has moved since the last run (now `3a6dac2`) and the provenance's `code_git_sha` should reflect the current commit before any paid call. The paid form adds `--confirm-paid --max-cost-usd 0.0075 --out <T7 path>`.
2. **Read the rejudge output** to get REAL per-case judge/2 verdicts (not the 12-case hand estimate above) — this tells you exactly how many of the 30 uncertain cases flip to correct, and gives the real remaining target set for PR 3.
3. **Scope PR 3 (answerer strategy) against the remaining failures only**, using the sharpened target: enumeration/list-completeness synthesis for cat1 (collect-dedupe-synthesize per the operator's original spec), informed by which specific real-omission cases (like the `conv-26::q23`/`conv-42::q10`/`conv-42::q59` pattern) survive the judge/2 rejudge.
4. **cat3 remains untouched by any of PR 1/2/3 so far** — all 14 non-correct cat3 cases are `open_domain_inference` (correctly requiring world-knowledge inference the current prompt licenses but the answerer may still be declining to make). The operator's original PR 3 spec's cat3 section ("allow well-established world knowledge when the dialogue provides identifying clues... do not return unknown merely because the final answer is not explicitly written") is still fully open and untouched by this session's work.

---

## Guardrails (do not skip — all established and followed this session)

- **No paid API call without explicit operator `--confirm-paid` approval, shown with the exact command and cost estimate first** — followed throughout; zero spend this session.
- **Never delete anything without confirmation** (memory `feedback_never_delete_without_confirmation`) — the unrelated `.playwright-mcp/`/`.wrangler/`/`visuals/` untracked artifacts from a separate session were left untouched.
- **Never use `gh pr merge --auto`** (memory `feedback_merge_prs_promptly`, HISTORY#349/#351 incidents) — poll checks to genuinely `pass`, confirm `mergeStateStatus: CLEAN`, then plain `--squash`.
- **CodeRabbit's real review only completes after a PR is marked ready** (not draft) — its "Free plan" tier only ever produces a walkthrough/summary, never inline findings; wait for the `walkthrough_start`/`Estimated code review effort` marker in its comment, not just the commit-hash appearing (which also shows in the "still processing" placeholder — this bit a wait-loop earlier in this thread).
- **Never trust a background test-runner's exit-code summary alone** — one earlier run in this thread reported "exit code 0 / completed" while 9 real test failures were buried in the piped output; always grep the raw output directly for `FAILED`/`ERROR`.
- **Verify UI/settings/documentation steps by looking them up (WebSearch/WebFetch), never from training-data memory** — even for a familiar platform (this bit the operator's GitHub-billing troubleshooting earlier in this thread; see memory `feedback_verify_docs_dont_guess_from_memory`).
- **All per-case failure data + any rejudge output stays on the private T7**, never committed — enforced by `.gitignore` + the `external_mount_ready` guard in the tooling itself.
