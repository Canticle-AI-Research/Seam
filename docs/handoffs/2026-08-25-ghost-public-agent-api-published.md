---
handoff_id: 2026-08-25-ghost-public-agent-api-published
supersedes: 2026-08-25-ghost-public-agent-api-locally-qualified
handoff_status: superseded
history: HISTORY#609
---

# Ghost public agent-turn API published

## Protected-main result

PR #231 merged the opaque Ghost agent-turn API to protected SEAM
`main@9d29c24429431ab036bfc4981358055a475ac3b7`. Its exact source head
`40562b36e7922b7bc63db2856b5183281a2a69f7` passed all seven hosted jobs:
`repo-hygiene`, `chroma-real-smoke`, `locomo-quickstart-bil2`,
`pgvector-integration`, `package-smoke`, `registry-plan`, and
`test-and-benchmark`.

The published routes are `/v1/agent/turns/begin`,
`/v1/agent/turns/actions`, `/v1/agent/turns/complete`, and
`/v1/agent/turns/fail`. The server remains the sole owner of MIRL, retrieval,
reasoning graphs, evidence selection, verification state, persistence, and
terminal replay. Ghost receives only bounded memory text, opaque handles, and
terminal receipts.

## Claim boundary

This closes source/API parity for the server half of the Ghost integration. It
does not publish the private runtime, release a new package, deploy an endpoint,
exercise a paid provider, or change Track S stage. A Ghost client merge proves
the public install and transport boundary only after its own exact-head CI; it
still cannot claim a live compatible service until deployment is separately
qualified.

## Next

Finish Ghost PR #8 against this protected contract, retain hosted public CI,
and keep live provider/service checks behind explicit credentials and operator
approval. Hosted operations, backup/restore, and disaster-recovery proof remain
later roadmap work.
