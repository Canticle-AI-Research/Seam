---
schema: seam-handoff-registry/v1
latest: 2026-07-24-mirl-hs1-proprietary-boundary
---

# SEAM Handoff Registry

This is the canonical startup route for tracked handoffs. Read the `latest`
document first; use older entries only when the current handoff or a bounded
history pack points back to them. The table is newest-first and forms one
linear supersession chain.

Every tracked handoff must declare `handoff_id`, `supersedes`,
`handoff_status`, and `history` in its opening metadata block. Add the new
handoff at the top, mark its predecessor `superseded`, advance `latest`, and
run `python -m tools.history.verify_handoffs`.

| handoff_id | path | supersedes | history | status |
| --- | --- | --- | --- | --- |
| `2026-07-24-mirl-hs1-proprietary-boundary` | [2026-07-24-mirl-hs1-proprietary-boundary.md](2026-07-24-mirl-hs1-proprietary-boundary.md) | `2026-07-23-reasoning-verification-r3` | `HISTORY#468` | `current` |
| `2026-07-23-reasoning-verification-r3` | [2026-07-23-reasoning-verification-r3.md](2026-07-23-reasoning-verification-r3.md) | `2026-07-22-reasoned-retrieval-g3a` | `HISTORY#466` | `superseded` |
| `2026-07-22-reasoned-retrieval-g3a` | [2026-07-22-reasoned-retrieval-g3a.md](2026-07-22-reasoned-retrieval-g3a.md) | `2026-07-22-reasoning-graph-sdk-foundation` | `HISTORY#462` | `superseded` |
| `2026-07-22-reasoning-graph-sdk-foundation` | [2026-07-22-reasoning-graph-sdk-foundation.md](2026-07-22-reasoning-graph-sdk-foundation.md) | `2026-07-22-graph-memory-identity-foundation` | `HISTORY#461` | `superseded` |
| `2026-07-22-graph-memory-identity-foundation` | [2026-07-22-graph-memory-identity-foundation.md](2026-07-22-graph-memory-identity-foundation.md) | `2026-07-22-graph-source-raw-lane` | `HISTORY#454` | `superseded` |
| `2026-07-22-graph-source-raw-lane` | [2026-07-22-graph-source-raw-lane.md](2026-07-22-graph-source-raw-lane.md) | `2026-07-22-fact-free-auxiliary-raw-ablation` | `HISTORY#453` | `superseded` |
| `2026-07-22-fact-free-auxiliary-raw-ablation` | [2026-07-22-fact-free-auxiliary-raw-ablation.md](2026-07-22-fact-free-auxiliary-raw-ablation.md) | `2026-07-21-non-displacing-pack-aux-raw-gate` | `HISTORY#452` | `superseded` |
| `2026-07-21-non-displacing-pack-aux-raw-gate` | [2026-07-21-non-displacing-pack-aux-raw-gate.md](2026-07-21-non-displacing-pack-aux-raw-gate.md) | `2026-07-21-multi-speaker-derived-facts-cloud-probe` | `HISTORY#450` | `superseded` |
| `2026-07-21-multi-speaker-derived-facts-cloud-probe` | [2026-07-21-multi-speaker-derived-facts-cloud-probe.md](2026-07-21-multi-speaker-derived-facts-cloud-probe.md) | `2026-07-21-multiscope-and-local-beam-complete` | `HISTORY#448` | `superseded` |
| `2026-07-21-multiscope-and-local-beam-complete` | [2026-07-21-multiscope-and-local-beam-complete.md](2026-07-21-multiscope-and-local-beam-complete.md) | `2026-07-21-multiscope-gate-and-local-beam-in-progress` | `HISTORY#446` | `superseded` |
| `2026-07-21-multiscope-gate-and-local-beam-in-progress` | [2026-07-21-multiscope-gate-and-local-beam-in-progress.md](2026-07-21-multiscope-gate-and-local-beam-in-progress.md) | `2026-07-21-canonical-graph-fill-broad-profile-correction` | `HISTORY#445` | `superseded` |
| `2026-07-21-canonical-graph-fill-broad-profile-correction` | [2026-07-21-canonical-graph-fill-broad-profile-correction.md](2026-07-21-canonical-graph-fill-broad-profile-correction.md) | `2026-07-21-canonical-graph-fill-free-gate` | `HISTORY#444` | `superseded` |
| `2026-07-21-canonical-graph-fill-free-gate` | [2026-07-21-canonical-graph-fill-free-gate.md](2026-07-21-canonical-graph-fill-free-gate.md) | `2026-07-21-longmemeval-beam-contract-repair-complete` | `HISTORY#443` | `superseded` |
| `2026-07-21-longmemeval-beam-contract-repair-complete` | [2026-07-21-longmemeval-beam-contract-repair-complete.md](2026-07-21-longmemeval-beam-contract-repair-complete.md) | `2026-07-20-longmemeval-beam-contract-repair-in-progress` | `HISTORY#441` | `superseded` |
| `2026-07-20-longmemeval-beam-contract-repair-in-progress` | [2026-07-20-longmemeval-beam-contract-repair-in-progress.md](2026-07-20-longmemeval-beam-contract-repair-in-progress.md) | `2026-07-20-sentence-grounded-pass-and-competitor-ratchet` | `HISTORY#440` | `superseded` |
| `2026-07-20-sentence-grounded-pass-and-competitor-ratchet` | [2026-07-20-sentence-grounded-pass-and-competitor-ratchet.md](2026-07-20-sentence-grounded-pass-and-competitor-ratchet.md) | `2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next` | `HISTORY#439` | `superseded` |
| `2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next` | [2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next.md](2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next.md) | `2026-07-20-derived-facts-landed-and-kb-scaffold` | `HISTORY#438` | `superseded` |
| `2026-07-20-derived-facts-landed-and-kb-scaffold` | [2026-07-20-derived-facts-landed-and-kb-scaffold.md](2026-07-20-derived-facts-landed-and-kb-scaffold.md) | `2026-07-20-second-hop-negative-and-count-lever-conflict` | `HISTORY#436` | `superseded` |
| `2026-07-20-second-hop-negative-and-count-lever-conflict` | [2026-07-20-second-hop-negative-and-count-lever-conflict.md](2026-07-20-second-hop-negative-and-count-lever-conflict.md) | `2026-07-19-matched-run-complete-recovery-closeout` | `HISTORY#432` | `superseded` |
| `2026-07-19-matched-run-complete-recovery-closeout` | [2026-07-19-matched-run-complete-recovery-closeout.md](2026-07-19-matched-run-complete-recovery-closeout.md) | `2026-07-19-matched-run-inflight-and-cat2-lever-handoff` | `HISTORY#430` | `superseded` |
| `2026-07-19-matched-run-inflight-and-cat2-lever-handoff` | [2026-07-19-matched-run-inflight-and-cat2-lever-handoff.md](2026-07-19-matched-run-inflight-and-cat2-lever-handoff.md) | `2026-07-19-matched-answerer-full-run-handoff` | `HISTORY#427` | `superseded` |
| `2026-07-19-matched-answerer-full-run-handoff` | [2026-07-19-matched-answerer-full-run-handoff.md](2026-07-19-matched-answerer-full-run-handoff.md) | `2026-07-18-answerer-parity-probe-handoff` | `HISTORY#423` | `superseded` |
| `2026-07-18-answerer-parity-probe-handoff` | [2026-07-18-answerer-parity-probe-handoff.md](2026-07-18-answerer-parity-probe-handoff.md) | `2026-07-17-event-count-context-handoff` | `HISTORY#422` | `superseded` |
| `2026-07-17-event-count-context-handoff` | [2026-07-17-event-count-context-handoff.md](2026-07-17-event-count-context-handoff.md) | `2026-07-17-hc3-open-domain-cat3-handoff` | `HISTORY#416` | `superseded` |
| `2026-07-17-hc3-open-domain-cat3-handoff` | [2026-07-17-hc3-open-domain-cat3-handoff.md](2026-07-17-hc3-open-domain-cat3-handoff.md) | `2026-07-17-exact-answer-contract-handoff` | `HISTORY#413` | `superseded` |
| `2026-07-17-exact-answer-contract-handoff` | [2026-07-17-exact-answer-contract-handoff.md](2026-07-17-exact-answer-contract-handoff.md) | `2026-07-15-cat1-cat3-scoreboard-closeout` | `HISTORY#409` | `superseded` |
| `2026-07-15-cat1-cat3-scoreboard-closeout` | [2026-07-15-cat1-cat3-scoreboard-closeout.md](2026-07-15-cat1-cat3-scoreboard-closeout.md) | `2026-07-15-cat1-cat3-past-80-handoff` | `HISTORY#400` | `superseded` |
| `2026-07-15-cat1-cat3-past-80-handoff` | [2026-07-15-cat1-cat3-past-80-handoff.md](2026-07-15-cat1-cat3-past-80-handoff.md) | `2026-07-13-improve-validate-profile-complete` | `HISTORY#397` | `superseded` |
| `2026-07-13-improve-validate-profile-complete` | [2026-07-13-improve-validate-profile-complete.md](2026-07-13-improve-validate-profile-complete.md) | `2026-07-11-cat13-semantic-conversation-adapter-complete` | `HISTORY#387` | `superseded` |
| `2026-07-11-cat13-semantic-conversation-adapter-complete` | [2026-07-11-cat13-semantic-conversation-adapter-complete.md](2026-07-11-cat13-semantic-conversation-adapter-complete.md) | `2026-07-11-cat13-semantic-conversation-adapter-in-progress` | `HISTORY#382` | `superseded` |
| `2026-07-11-cat13-semantic-conversation-adapter-in-progress` | [2026-07-11-cat13-semantic-conversation-adapter-in-progress.md](2026-07-11-cat13-semantic-conversation-adapter-in-progress.md) | `2026-07-11-cat1-cat3-success-contract-handoff` | `HISTORY#381` | `superseded` |
| `2026-07-11-cat1-cat3-success-contract-handoff` | [2026-07-11-cat1-cat3-success-contract-handoff.md](2026-07-11-cat1-cat3-success-contract-handoff.md) | `2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff` | `HISTORY#379` | `superseded` |
| `2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff` | [2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff.md](2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff.md) | `2026-07-09-cat1-cat3-deepseek-fixes-handoff` | `HISTORY#375` | `superseded` |
| `2026-07-09-cat1-cat3-deepseek-fixes-handoff` | [2026-07-09-cat1-cat3-deepseek-fixes-handoff.md](2026-07-09-cat1-cat3-deepseek-fixes-handoff.md) | `2026-07-07-cat1-cat3-scoping-handoff` | `HISTORY#369` | `superseded` |
| `2026-07-07-cat1-cat3-scoping-handoff` | [2026-07-07-cat1-cat3-scoping-handoff.md](2026-07-07-cat1-cat3-scoping-handoff.md) | `2026-06-26-seam-vs-mem0-rungc-handoff` | `HISTORY#362` | `superseded` |
| `2026-06-26-seam-vs-mem0-rungc-handoff` | [2026-06-26-seam-vs-mem0-rungc-handoff.md](2026-06-26-seam-vs-mem0-rungc-handoff.md) | `2026-06-13-mirl-compiler-fidelity-handoff` | `HISTORY#343` | `superseded` |
| `2026-06-13-mirl-compiler-fidelity-handoff` | [2026-06-13-mirl-compiler-fidelity-handoff.md](2026-06-13-mirl-compiler-fidelity-handoff.md) | `2026-06-08-h2-self-improvement-loop` | `HISTORY#306` | `superseded` |
| `2026-06-08-h2-self-improvement-loop` | [2026-06-08-h2-self-improvement-loop.md](2026-06-08-h2-self-improvement-loop.md) | `none` | `HISTORY#291` | `superseded` |
