---
handoff_id: 2026-10-14-suite-integrated-testpypi-next
supersedes: 2026-10-14-suite-release-readiness
handoff_status: current
history: HISTORY#669
---

# Integrated Suite; TestPyPI access next

Suite PR #288 merged at `6c6ecd13490c9b675a77f246573491824313343c` after
independent exact-state qualification and all three required final-head checks.
Package CI and all five native-launcher jobs passed. The qualified public-v3
wheel/sdist and their exact hashes are in [the report](../audits/2026-10-14-suite-release-readiness.md).
The documentation-only closeout does not change package inputs. License terms
are settled; do not ask the owner to choose them again.

Website PR #33 merged at `a7be46329cd430d38c95961edbc820dacd65b5a0`.
Production Pages and email-worker checks passed. Fresh public responses match
eleven reviewed HTML pages plus pricing and download scripts. Stable Downloads
correctly requires a qualified production seam-suite release; a TestPyPI
prerelease does not enable it. Current docs link the new guides on main.

PR #266 is closed as superseded and its old branch deleted. Its useful
implementation is preserved or strengthened; intentionally omitted September
historical audit/handoff records remain reachable through `refs/pull/266/head`
at `8a120381f885cdcfc90b9157bae66ea8b452a99f`. Fourteen obsolete remote branches
were removed through this integration. Unique/open work is retained, including
website PR #29's locked planning proposals; its partial supersession is recorded.

The concrete external dependency is **TestPyPI publisher access**. No credential
is configured in this environment, and no upload occurred. Follow
[TESTPYPI.md](../TESTPYPI.md): verify the exact two qualified artifacts, use only
TestPyPI-specific access and explicit test endpoint, then read back file hashes
and repeat fresh downloaded-install smoke checks. Do not use production as a
fallback. Production publication and MCP registration remain separate.

Pinned owner issue #287 covers the blocked GitHub About-setting edit. Broader
browser/operator-product acceptance and formation/research work remain open.
Advisory PostgreSQL CI failed before tests because the shared runner's Docker
socket was unavailable; local extended tests retain browser-export timeouts
and explicitly blocked token-encoding downloads. No full-suite or PostgreSQL
qualification is claimed. Both working trees are clean at the integrated
commits; no stashes, extra worktrees or live test browsers were left.
