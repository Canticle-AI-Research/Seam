---
handoff_id: 2026-07-28-seam-node-wheel
supersedes: 2026-07-23-g3-rank-fusion-scale-qualification
handoff_status: current
history: HISTORY#482
---

# Handoff: compiled `seam-node` wheel

**Date:** 2026-07-28
**Base:** `origin/main` at `a21eded3b9d5a528b210ba8d347037db5ff14378`
**Branch:** `feat/seam-node-wheel`
**Artifact:** local only; nothing published

## One-line state

The BUSL self-host now has a separately defined, locally buildable and
runtime-proved CPython 3.12 `manylinux_2_28_x86_64` wheel containing one
compiled `seam_runtime` extension, no runtime Python source, and no upload path.

## Feasibility result

The required Nuitka module-mode spike passed before pipeline work began. An
empty `/probe` directory received only `seam_runtime*.so`; imports of
`seam_runtime`, `seam_runtime.mirl`, `seam_runtime.selfhost`, and
`seam_runtime.runtime` all succeeded.

## Implemented

- `node_pkg/pyproject.toml` defines `seam-node` 2.4.0 under BUSL-1.1 for
  CPython 3.12 and declares only runtime dependencies. Its `seam-node` console
  entry point runs `seam_runtime.selfhost:main`.
- `tools.release.build_node_wheel` builds only in digest-pinned Docker images,
  stages an explicit source allow-list, uses Nuitka 4.1.3 module mode, carries
  all 18 image exclusions, force-includes `public_api`, and retains the four
  lazy-import families required by remember and recall.
- `auditwheel` emits exactly
  `seam_node-2.4.0-cp312-cp312-manylinux_2_28_x86_64.whl`; `twine check` and
  the node gate run before the artifact is copied to the requested empty
  output directory.
- `verify_node_wheel` rejects runtime source, absent/incorrect BUSL text or
  metadata, secret-shaped content, missing compiled code, and reserved
  identifier counts above the wheel-specific measured budget.

## Real artifact evidence

- Wheel size: 3,531,719 bytes.
- Extension size: 9,813,104 bytes.
- SHA-256:
  `6eba58c8417229e8160eaeebd7b3ce8d17148cbac0908c3fd54896cd3a21bc2f`.
- Reserved identifiers: 414 total (`MIRL` 133, `MIRLRecord` 120, `IRBatch` 63,
  `TraceGraph` 11, `compile_nl` 10, `holographic` 10, `surface_adapter` 5,
  `HS/1` 15, `SEAM-RC` 13, `SEAM-LX` 4, `knowledge_graph` 18,
  `reasoning_graph` 12). This is the pinned wheel ratchet and is four below
  the post-G3 compiled image baseline. The single increase from the pre-G3
  wheel is the attributable `seam_runtime.knowledge_graph` module path already
  measured for the image in HISTORY#480.

## Clean-container runtime proof

The built wheel was installed with no repository checkout on the path into the
same digest-pinned Python 3.12 slim base used by the image build:

```text
GET /v1/health -> 200 {"api_version": "v1", "edition": "compiled-self-host", "status": "ok"}
POST /v1/memories unauthenticated -> 401
POST /v1/memories -> 200 accepted=True
POST /v1/memories/recall -> 200 memories=1
POST /v1/context -> 200 chars=34
response marker scan -> raw:=0 clm:=0 mirl=0
server log ModuleNotFoundError scan -> 0
```

## Verification

- Focused node/distribution/self-host audit slice: 35 passed.
- Strict full `tests/` suite against live pgvector: 1,485 collected, 1,483
  passed, two established xfails, zero skips, and zero failures.
- Touched-file Ruff, compileall, real-wheel gate, canonical history closeout,
  handoff, continuity, routing, integrity, and stream gates pass.
- CodeRabbit CLI was authenticated but free-plan rate-limited. Local boundary
  review found and fixed the nested `.data/purelib/seam_runtime` source bypass
  before the final suite.

## Open product decision

The wheel preserves `seam_runtime.selfhost`'s vendor-signed Ed25519
entitlement requirement. That conflicts with the operator's intended free
self-host product. Making entitlement optional is not part of this branch;
decide that separately, and retain the signed-entitlement path for a future
paid or supported tier if the free path changes.

## Publication boundary

Nothing was uploaded to PyPI, a container registry, GitHub Releases, or a
package workflow. The builder has no upload mode. The operator must review and
publish separately.
