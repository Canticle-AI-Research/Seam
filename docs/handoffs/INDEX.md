---
schema: seam-handoff-registry/v1
latest: 2026-07-13-improve-validate-profile-complete
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
| `2026-07-13-improve-validate-profile-complete` | [2026-07-13-improve-validate-profile-complete.md](2026-07-13-improve-validate-profile-complete.md) | `2026-07-11-cat13-semantic-conversation-adapter-complete` | `HISTORY#386` | `current` |
| `2026-07-11-cat13-semantic-conversation-adapter-complete` | [2026-07-11-cat13-semantic-conversation-adapter-complete.md](2026-07-11-cat13-semantic-conversation-adapter-complete.md) | `2026-07-11-cat13-semantic-conversation-adapter-in-progress` | `HISTORY#382` | `superseded` |
| `2026-07-11-cat13-semantic-conversation-adapter-in-progress` | [2026-07-11-cat13-semantic-conversation-adapter-in-progress.md](2026-07-11-cat13-semantic-conversation-adapter-in-progress.md) | `2026-07-11-cat1-cat3-success-contract-handoff` | `HISTORY#381` | `superseded` |
| `2026-07-11-cat1-cat3-success-contract-handoff` | [2026-07-11-cat1-cat3-success-contract-handoff.md](2026-07-11-cat1-cat3-success-contract-handoff.md) | `2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff` | `HISTORY#379` | `superseded` |
| `2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff` | [2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff.md](2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff.md) | `2026-07-09-cat1-cat3-deepseek-fixes-handoff` | `HISTORY#375` | `superseded` |
| `2026-07-09-cat1-cat3-deepseek-fixes-handoff` | [2026-07-09-cat1-cat3-deepseek-fixes-handoff.md](2026-07-09-cat1-cat3-deepseek-fixes-handoff.md) | `2026-07-07-cat1-cat3-scoping-handoff` | `HISTORY#369` | `superseded` |
| `2026-07-07-cat1-cat3-scoping-handoff` | [2026-07-07-cat1-cat3-scoping-handoff.md](2026-07-07-cat1-cat3-scoping-handoff.md) | `2026-06-26-seam-vs-mem0-rungc-handoff` | `HISTORY#362` | `superseded` |
| `2026-06-26-seam-vs-mem0-rungc-handoff` | [2026-06-26-seam-vs-mem0-rungc-handoff.md](2026-06-26-seam-vs-mem0-rungc-handoff.md) | `2026-06-13-mirl-compiler-fidelity-handoff` | `HISTORY#343` | `superseded` |
| `2026-06-13-mirl-compiler-fidelity-handoff` | [2026-06-13-mirl-compiler-fidelity-handoff.md](2026-06-13-mirl-compiler-fidelity-handoff.md) | `2026-06-08-h2-self-improvement-loop` | `HISTORY#306` | `superseded` |
| `2026-06-08-h2-self-improvement-loop` | [2026-06-08-h2-self-improvement-loop.md](2026-06-08-h2-self-improvement-loop.md) | `none` | `HISTORY#291` | `superseded` |
