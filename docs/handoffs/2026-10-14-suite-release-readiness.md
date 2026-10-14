---
handoff_id: 2026-10-14-suite-release-readiness
supersedes: 2026-10-14-current-suite-licensing
handoff_status: superseded
history: HISTORY#667
---

# Suite release-candidate continuation

The owner has authorized completing the functional installation/release
candidate and deleting verified obsolete branches. Licensing is settled:
PR #286 is merged at `607ac308`, and current website terms/Docs are live through
PR #32. Do not ask for the licensing choice again or build a historical-user
migration project. Pinned issue #287 covers the remaining manual repo About
setting, which the integration cannot edit.

This successor starts from protected main `607ac308`. It reconciles the useful
remaining package/release/MCP work from PR #266, preserves current safeguards,
and adds source/archive manifest drift enforcement. See
[the report](../audits/2026-10-14-suite-release-readiness.md) and
[release flow](../RELEASE_FLOW.md). Wheel and sdist installed behavior is verified
in fresh external environments. After independent source/package review, the
TestPyPI candidate's private-upload tripwire is removed and its actual rebuilt
files require final verification.

Finish current-head independent assurance, unsuppressed continuity and required
CI, then store exact-state qualification and merge through protected main.
Recheck resulting main. Only then close the superseded PR #266 and delete its
unchanged branch after preserving/dispositioning all useful work. Eleven
completed remote branches are already deleted with preservation proof; unique
and unrelated active branches remain intact.

Website downloads still need their separate reviewed correction, live
deployment and served-page verification. Do not enable stable production
downloads merely because the `2.4.1rc1` candidate passed local testing.

TestPyPI publisher access is the concrete external dependency. No credentials
are configured here; the owner setup question is pending. After access is
established, upload only the qualified exact wheel/sdist to TestPyPI, read back
their hashes, and install downloaded artifacts in a new environment. Production
publication and MCP registration remain separate. Browser/operator-product
acceptance and unrelated open formation/research work are not completed by
startup smoke checks. No private SDK, user database, stash or unrelated dirty
work belongs in this task.
