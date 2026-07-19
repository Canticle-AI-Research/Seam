---
handoff_id: 2026-07-19-matched-answerer-full-run-handoff
supersedes: 2026-07-18-answerer-parity-probe-handoff
handoff_status: superseded
history: HISTORY#423
---

# Handoff: parity probe DONE — next gate is the full matched-answerer run

- **Date:** 2026-07-19
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, draft)
- **State:** the #422 answerer-parity probe has been EXECUTED (~$1.35,
  operator-approved). Its decision table resolved decisively. The next paid
  step — the full matched-answerer Mem0-harness run (~$10–15) — is
  **operator-gated separately and NOT yet approved**.

## Probe result (HISTORY#423)

Private record: T7 `20260718-164944-mem0-parity-probe-answerer.json`.
45 stored miss cases (32 cat1 / 13 cat3), frozen top-200 contexts, both
answerer arms judged by gpt-4o via the verbatim upstream contract
(`mem0ai/memory-benchmarks` @ `4b61c5d`).

| arm (cat1, n=32) | correct |
| --- | --- |
| gpt-4o-mini rerun, gpt-4o judge | 6 |
| **gpt-4o answerer, gpt-4o judge** | **18** |

- **Decision gate `≥7` cat1 flips: met at 18.** Projected matched-answerer
  cat1 = 250 + 18 = **268/282 = 95.0%**, well past mem0's 91% — caveat: the
  250 stored-correct cases were not re-judged under gpt-4o (the probe only
  re-ran misses), so the full run is what makes the number citable.
- Effect split: 6/32 flips appear under the gpt-4o **judge** with the mini
  answerer (judge-drift + rerun noise ≈ 90.8% cat1 alone, matching #417's
  arithmetic — still under 91%); 12/32 are **parity-only** = pure answerer
  strength. Report the two effects separately in any writeup.
- cat3: 4/13 parity vs 3/13 baseline (+1 net; conv0_q59 flipped the other
  way = noise). Confirms #419: the cat3 wall is retrieval-side, an answerer
  upgrade does not buy cat3.
- Residual 14 cat1 still-wrong under gpt-4o: event-count numerics (SOL's
  `event-count/distinct/2` territory), set/list enumeration gaps, and
  specific-entity misses — i.e. the #420 levers (evidence-digest projection,
  second-hop retrieval) are now margin, exactly as the handoff predicted.

## Next paid step (operator-gated, not approved yet)

Full Mem0-harness run with the **gpt-4o answerer + gpt-4o judge** (published
contract), all 378 cat1+cat3 questions, ~$10–15. No new code first. Reuse the
#400 methodology (`seam_mem0_server` facade, harness @ `4b61c5d`, top-200,
mandatory T7 env). Watch conv3_q61 / conv5_q36 (#421: the only two correct
cases whose evidence regressed in fresh retrieval).

## Standing context

- SOL's `event-count/distinct/2` remains uncommitted and in-flight — do not
  touch; its ~$0.08 microgate fires once it lands, now for margin not for
  the 91% gate.
- Full local suite: exit 0, zero skips, 2 established xfails — requires the
  T7 offline HF env AND pgvector up (`~/.local/bin/docker-up`, local DSN
  `dbname=seam user=seam`, password from `docker inspect seam-pgvector`);
  the CI-only `seam_ci` DSN does not exist locally.
- Scoreboards stay separate, never averaged (#415).
