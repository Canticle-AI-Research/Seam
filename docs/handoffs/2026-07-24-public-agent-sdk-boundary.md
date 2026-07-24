---
handoff_id: 2026-07-24-public-agent-sdk-boundary
supersedes: 2026-07-24-mirl-hs1-proprietary-boundary
handoff_status: current
history: HISTORY#469
---

# Handoff: public agent SDK boundary

**Date:** 2026-07-24
**Private branch:** `agent/public-sdk-boundary`
**Public branch:** `agent/public-agent-sdk`
**Spend:** zero provider or paid model calls.

## One-line state

The proprietary MIRL/HS/1 boundary now has a separately authored public
`seam-client` SDK and an opaque private-runtime `/v1` API, both locally
verified and awaiting review; private `seam-runtime` remains blocked from
PyPI.

## Private API

- `seam_runtime/public_api.py` implements remember, recall, and prompt-ready
  context with bounded inputs, SDK-prefixed namespaces, optional hashed
  session partitions, and opaque receipts/memory IDs.
- `seam_runtime/server.py` exposes `GET /v1/health`,
  `POST /v1/memories`, `POST /v1/memories/recall`, and
  `POST /v1/context`.
- Stateful endpoints use the existing bearer-token guard. Remotely reachable
  deployments must configure `SEAM_API_TOKEN`; loopback development keeps the
  existing server behavior.
- Public responses omit MIRL records and IDs, HS/1/surface payloads, PACK,
  storage paths, graph/provenance structures, candidate ledgers, and ranking
  reasons.

## Public SDK

- Separate checkout: `/home/terrabyte/Documents/Projects/Seam_Runtime`.
- Package: Apache-2.0 `seam-client` 0.1.0 under the isolated `sdk/` build root.
- API: `SeamClient`, `AsyncSeamClient`, `AgentMemory`, and
  `AsyncAgentMemory`, with typed response/error models.
- Release: isolated CI, wheel/sdist allow-list scanner, and manual OIDC PyPI
  workflow using GitHub environment `pypi`; no long-lived upload token.
- The old `seam-runtime` 1.x public source/tags retain their Apache-2.0 rights
  as a frozen legacy line. New private runtime code is not synced there.

## Verification

- Private API boundary tests: 5 passed.
- Existing server/auth regression slice: 59 passed.
- Public SDK tests: 12 passed; Ruff passed.
- Clean wheel and sdist: built successfully, passed `twine check`, and passed
  the artifact-boundary scanner; public `sdk/LICENSE` matches Apache-2.0.
- Cross-repository ASGI smoke: `AsyncAgentMemory` remembered and retrieved
  context through `/v1` with SQLite; responses contained no internal record
  identifiers.
- Public repo `verify_integrity` and stream verification pass. Its pre-existing
  routing/continuity defect remains: seven ledger paths named by the routing
  manifest are absent from public `origin/main`.

## Release order

1. Review and merge private licensing PR #163.
2. Review and merge the stacked private public-API PR.
3. Review and merge the public `seam-client` PR.
4. In PyPI, register the exact Trusted Publisher:
   owner `BlackhatShiftey`, repository `Seam_Runtime`, workflow
   `sdk-publish.yml`, environment `pypi`, project `seam-client`.
5. Manually dispatch `sdk-publish.yml` for exact version `0.1.0`, then verify
   the PyPI project and a clean install.

Do not publish private `seam-runtime` 2.3.0, do not resume the legacy mirror,
and do not use the old token-based release path.
