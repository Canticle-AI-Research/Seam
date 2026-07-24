---
handoff_id: 2026-07-24-seam-client-0-1-0-live
supersedes: 2026-07-24-public-agent-sdk-boundary
handoff_status: current
history: HISTORY#470
---

# Handoff: seam-client 0.1.0 live

**Date:** 2026-07-24
**Private main:** `dc7de12fcc23c1633097a5abef368d206eefbe96`
**Public main:** `361bf123b0f23f1d68024b0b2952332f0786f67b`
**Spend:** zero provider or paid model calls.

## One-line state

The MIRL/HS/1 proprietary boundary, opaque private `/v1` agent-memory API, and
independently authored Apache-2.0 `seam-client` SDK are merged; version 0.1.0
is live and clean-install verified on PyPI.

## Merged boundary

- Private licensing PR #163 is merged. New/private MIRL and HS/1 materials are
  proprietary while exact legacy Apache versions retain their prior grant.
- Private API PR #164 is merged. Public calls receive text and opaque IDs, not
  MIRL records, HS/1 surfaces, PACK, storage, graph/provenance, or ranking
  internals.
- Public SDK PR #1 is merged in `BlackhatShiftey/Seam_Runtime`.
- Private `seam-runtime` 2.3.0 remains `Private :: Do Not Upload` and fails
  the PyPI distribution boundary by design.

## Public release

- PyPI: <https://pypi.org/project/seam-client/>
- Version: `0.1.0`
- License expression: `Apache-2.0`
- Artifacts: one universal wheel and one sdist
- Workflow: public `sdk-publish.yml`, run 30107050434
- Identity: GitHub OIDC through protected environment `pypi`; no stored PyPI
  token
- PyPI generated and uploaded digital attestations.

## Verification

- Public PR and post-merge `main` SDK CI passed Python 3.10, Python 3.12, and
  the distribution-boundary job.
- Private post-merge `main` CI passed the complete test-and-benchmark matrix,
  repo hygiene, Chroma smoke, live pgvector, package smoke, and LoCoMo BIL-2.
- Live PyPI JSON reports `seam-client` 0.1.0, Apache-2.0, wheel, and sdist.
- A fresh isolated network install of `seam-client==0.1.0` succeeded and
  imported `SeamClient`, `AsyncSeamClient`, `AgentMemory`, and
  `AsyncAgentMemory`.

## Next product work

1. Build custom agent examples against `AgentMemory` and `AsyncAgentMemory`.
2. Choose and provision the first authorized hosted `/v1` endpoint if desired.
3. Keep SDK API evolution additive within `/v1`; use a new URL version for a
   breaking contract change.
4. Never publish private `seam-runtime`, resume the legacy mirror, or copy
   MIRL/HS/1 implementation into the public SDK.
