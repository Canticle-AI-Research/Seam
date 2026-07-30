---
handoff_id: 2026-07-29-stable-packages-live
supersedes: 2026-07-29-package-stability-release-candidate
handoff_status: superseded
history: HISTORY#490
---

# Handoff: stable package channels live; resume G3 and R4

**Date:** 2026-07-29
**Merged source:** `01f35817810f1490c88e9f832d92c8f1aab3944d`
**Publication state:** both package channels live and independently verified

## One-line state

The package-stability diversion is complete: private hosted `seam-runtime`
2.4.0 and compiled `seam-self-host` 1.1.2 are released, clean-install verified
with SQLite and live pgvector, and no longer block G3 or R4 work.

## Distribution boundary

- Apache-2.0 `seam-client` 2.0.0 remains the public HTTP client.
- Private `seam-runtime` 2.4.0 is the future subscriber service's hosted
  authenticated `/v1` server package. It is live only on the private GitHub
  release channel, not PyPI.
- BUSL-1.1 `seam-self-host` 1.1.2 is the compiled package for
  customer-operated Linux/x86-64 CPython 3.12 nodes. It is live on PyPI.
- `public_pkg/` remains only the fail-closed compatibility shim and was not
  published.
- DigitalOcean provisioning and subscriber deployment remain deliberately
  deferred. No infrastructure resource changed during this release.

## Live release evidence

Protected PR #180 merged the unchanged qualified head into `main` at
`01f35817810f1490c88e9f832d92c8f1aab3944d`.

Private hosted API:

- Workflow run `30419432598` passed build, exact-version check, `twine`,
  private distribution boundary, installed-wheel API proof, artifact transfer,
  and private GitHub release creation.
- GitHub release `v2.4.0` targets the merge SHA.
- Downloaded wheel:
  `seam_runtime-2.4.0-py3-none-any.whl`, 818,620 bytes, SHA-256
  `cb71fc3e15d103ef63e5c15d9325c2b24645b61d6b42548dcfda4b64fe2f3d21`.
- Downloaded sdist:
  `seam_runtime-2.4.0.tar.gz`, 790,485 bytes, SHA-256
  `c47fb91433db0b01a579679bc8cf2850e51f33e20d89f71bce601416bab6988f`.

Compiled self-host:

- Workflow run `30419432631` passed the digest-pinned compiled build, runtime
  proof, repeated boundary gate, single-wheel/no-sdist assertion, artifact
  transfer, and PyPI Trusted Publishing.
- PyPI reports live non-yanked 1.1.2:
  `seam_self_host-1.1.2-cp312-cp312-manylinux_2_28_x86_64.whl`,
  3,623,685 bytes, SHA-256
  `36d67629dbd97c74634f61c3bbadc2f37d768ac21bfe599216ee89a19153d362`.
- The downloaded wheel re-passed `twine` and the compiled source/privacy gate
  with the unchanged 414/414 reserved-content ratchet.

## Independent installed-artifact verification

- Fresh private wheel and sdist environments passed dependency checks and real
  health/remember/recall/context calls through released
  `seam-client==2.0.0`.
- The private wheel passed with SQLite and the configured live pgvector
  service; the exact proprietary/BUSL/Apache license expression was installed.
- A fresh PyPI self-host environment passed dependency and BUSL metadata
  checks, SQLite and live-pgvector API calls, and its two console entry points.
- No-argument self-host MCP initialized and listed tools while using its XDG
  fallback database; the database mode was 0600.
- Fresh PyPI upgrades from both 1.0.0 and 1.1.0 reached 1.1.2, passed dependency
  checks, and started the installed command.

## Graph/reasoning restart point

- Resume G3 with a versioned derived graph-node vector projection for entity,
  value, agent, and symbol nodes. Preserve namespace/scope prefiltering and the
  explicit-reindex migration contract, then qualify the projection on a
  predeclared real corpus and backend-specific scale.
- Start R4 independently as retrieval and reuse of prior reasoning patterns.
  Require task/run compatibility, freshness, trust, and exact provenance; a
  prior conclusion must never become its own evidence.
- Keep G3 and R4 measurements independent until each contract passes.
