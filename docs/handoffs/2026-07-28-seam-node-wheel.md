---
handoff_id: 2026-07-28-seam-node-wheel
supersedes: 2026-07-27-proprietary-compiled-selfhost-v1
handoff_status: current
history: HISTORY#478
---

# Handoff: compiled `seam-node` wheel

**Date:** 2026-07-28
**Base:** `origin/main` at `05ff4963739471ffd6a37511e2f131031018b1f7`
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

- Wheel size: 3,486,260 bytes.
- Extension size: 9,690,160 bytes.
- SHA-256:
  `915d90d7cc00e11f33996e7ee494b861ceaa778a98795ea1ab74c66174313eca`.
- Reserved identifiers: 413 total (`MIRL` 133, `MIRLRecord` 120, `IRBatch` 63,
  `TraceGraph` 11, `compile_nl` 10, `holographic` 10, `surface_adapter` 5,
  `HS/1` 15, `SEAM-RC` 13, `SEAM-LX` 4, `knowledge_graph` 17,
  `reasoning_graph` 12). This is the pinned wheel ratchet and is four below
  the compiled image baseline; no image budget was raised.

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
