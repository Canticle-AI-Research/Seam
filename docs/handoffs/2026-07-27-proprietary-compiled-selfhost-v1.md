---
handoff_id: 2026-07-27-proprietary-compiled-selfhost-v1
supersedes: 2026-07-24-seam-client-0-1-0-live
handoff_status: current
history: HISTORY#471
---

# Handoff: proprietary compiled self-host v1

**Date:** 2026-07-27
**Source base:** `0006698ead19b024da903b66be33285b2669daeb`
**Branch:** `feat/proprietary-selfhost-v1`
**Public client:** `seam-client` 0.1.0
**Spend:** zero provider or paid model calls.

## One-line state

The first proprietary compiled self-host MIRL edition is implemented and
verified locally for Linux/amd64 behind the existing opaque four-route `/v1`
contract; no image, package, entitlement, key, or customer artifact was
published.

## Checkout reconciliation

- The canonical implementation base is Documents-checkout `origin/main` at
  `0006698ead19b024da903b66be33285b2669daeb`.
- The original Documents checkout remains on dirty
  `fix/public-shim-2.3.1`; its tracked and untracked shim/package work was not
  edited, staged, or incorporated.
- The T7 checkout is stale: its local `main` is 169 commits behind the same
  fetched `origin/main`, and `feat/dashboard-functional` is one commit behind
  its remote tracking branch. It was treated as reconciliation evidence, not
  an implementation base.
- Work was isolated in a clean worktree on
  `feat/proprietary-selfhost-v1`.

## Implemented standard edition

- `seam_runtime/selfhost.py` registers only `/v1/health`, `/v1/memories`,
  `/v1/memories/recall`, and `/v1/context`; docs/OpenAPI, stats, graph,
  dashboard, benchmark, storage, MIRL, PACK, HS/1, and operator routes are not
  registered.
- `seam_runtime/selfhost_entitlement.py` verifies an exact-schema Ed25519
  envelope using only the image-baked public key. Entitlements require a
  bounded expiry and the `opaque-v1` feature, and become inactive without a
  server restart when their validity window ends.
- `selfhost/Dockerfile` compiles the private engine with Nuitka 4.1.3 into a
  pinned distroless Linux/amd64 image. The final image has no Python source,
  docs, tests, package manager, shell, or interpreter.
- `selfhost/compose.yaml` publishes only to loopback and runs uid 65532 with a
  read-only root, tmpfs scratch space, all capabilities dropped,
  no-new-privileges, read-only entitlement input, secret-file token input, and
  a persistent data volume.
- Release tools issue entitlements without overwriting existing files, build
  only with `docker buildx --load`, and scan real Docker/OCI archives for
  private source/docs, secrets, mutable runtime tools, platform/config drift,
  and the runtime libraries found necessary by real boot testing.

## Verified artifact

- Local image ID:
  `sha256:e1cce54cdde63046c54320fc2b7c043afb850df26e08008ec5d141bef6cef6a2`
- Image size: 60,202,804 bytes.
- Exported archive SHA-256:
  `2130245186f12089cd5ec65baacc4845f1a4ec6ba2b6560380c21e5da98c1dc0`
- The archive scanner passed. All 16 unique ELF dependencies resolved.
- The compiled executable had zero defined symbol lines and contained neither
  `SEAM_SPEC_V0.1` nor `MIRL_V1.md`. It retained one `mirl.py`, one
  `selfhost.py`, and six generic `/src/` string occurrences. This is expected
  compiled metadata and remains customer-discoverable.
- Real installed `seam-client` 0.1.0 calls passed health, remember, recall, and
  context. Non-public routes returned 404, unauthenticated stateful writes
  returned 401, and recalled state survived a container restart.
- Container inspection confirmed loopback-only port mapping, uid 65532,
  read-only root, `cap_drop=ALL`, and no-new-privileges.
- `pytest tests/audit -m "not external"` collected and passed 1,313 tests with
  23 external tests deselected and zero skips/failures. The final
  platform/scanner-focused slice passed 13 tests; touched-file Ruff,
  collect-only, and `git diff --check` passed.

## Honest protection boundary

This standard edition raises reverse-engineering cost and reduces accidental
source, secret, registry, and at-rest leakage. It does not protect the
executable, process memory, system calls, entitlement enforcement, or unlocked
database from a malicious administrator who controls the customer host.
Offline signatures are license controls, not hostile-owner DRM.

## Next steps

1. Obtain operator and legal/commercial approval before any private-registry
   push or customer distribution.
2. On approval, build from the reviewed commit, generate SBOM and provenance,
   re-run the archive/SDK gates, sign the immutable digest, and grant
   per-customer read access. Never publish this image or `seam-runtime` to a
   public registry/PyPI.
3. Qualify Linux/arm64 separately before claiming support.
4. Design the distinct confidential tier around a measured confidential
   guest/container, attestation policy, and remote image/data-key release.
   Do not claim ordinary OCI encryption protects against the host admin.
