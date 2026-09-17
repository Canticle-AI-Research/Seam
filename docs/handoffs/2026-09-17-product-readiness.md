---
handoff_id: 2026-09-17-product-readiness
supersedes: 2026-09-17-package-release-repair
handoff_status: superseded
history: HISTORY#648
---

# Product readiness and API installation direction

The operator clarified that the self-hosted core is usable for plug-and-play
local operation, while Suite's TUI, graph dashboard and benchmark glassbox are
unfinished. The full Suite is early access. The `seam-api` product has not
started; they selected the local installation direction from the previous
client-versus-server question.

The planned shape is client/WebUI -> local API server -> shared SEAM runtime
and storage. A client alone cannot run the engine. The exact runtime dependency,
package membership, launcher and supported client contract remain implementation
design work. Existing low-level routes and prototypes are building blocks;
they do not establish a completed API product. See the
[setup plan](../RELEASE_FLOW.md#planned-seam-api-installation).

## Documentation delivery

This follow-up resumes [SEAM PR #266](https://github.com/Canticle-AI-Research/Seam/pull/266)
from `0a4771efe873c9b3c5ae9f3d1175b3a7666b2438` and website PR #29 in the private
`BlackhatShiftey/Cantlicle` repository from
`090be67008ab8031dc435a1a68f3317fd38d3f85`. Both remain draft for DeepSeek review.
The branch names and preserved primary-checkout work are recorded in the
[preceding handoff](2026-09-17-package-release-repair.md).

Downloads now separates product readiness from package publication: usable core
and unfinished Suite interfaces, versus an unstarted API product with no
download. API cards link to the plan and account management without implying
keys provide a working API product. README, product map, release/TestPyPI docs,
surface/packaging status and launch backlog carry the same distinction. Account,
pricing, cohort, vault, private SDK and license boundaries remain unchanged.
No runtime behavior, API implementation, publication selector or package
contents changed in this follow-up. The stable-release selector still rejects
prereleases; product early-access wording is not a release-channel change.

## Verification and open conditions

Website `node --test tests/downloads-release.test.js` and
`python3 -m unittest discover -s tests -p 'test_package_downloads.py'` passed
after the copy changes. Diff checks passed. The canonical continuity gates
and independent documentation closeout must be reconciled on the final head.
No new wording-only tests were added and no runtime TDD claim is made.

The previous package-repair receipt is still **NOT_QUALIFIED / TDD_UNPROVEN**:
its path classifier requires behavioral evidence for installer README and
dashboard install-hint text. That open condition is retained; qualification of
this documentation-only delta cannot qualify the cumulative package PR.
The prior handoff also preserves the full-audit and website-suite failures.
Required GitHub checks and the website's failing email-worker check must be
rechecked on the current heads before any merge. No CI pass is inferred here.

A live production-page request failed with a TLS error in this environment;
rendered production copy was not verified. Website branch pushes can create
Cloudflare previews; use the exact PR preview for owner browser review. No
headless browser or production deployment was performed.

External evidence and receipts are retained under
`/home/terrabyte/LLM-Logs/codex/releases/20260917-seam-packages/readiness/`.
Task worktrees are removed after pushed draft delivery; preserve unrelated
worktrees and do not clear their changes to satisfy a push hook.

## Next work

1. Review the maturity copy and local API setup plan with DeepSeek.
2. Finish Suite artifact eligibility and TestPyPI publisher setup, then qualify
   the exact release. A usable core is not proof that a package is on PyPI.
3. Continue operator-surface acceptance under the existing product backlog;
   the memory-formation roadmap keeps its current execution priority.
4. Start API implementation as a separate bounded task. Reuse the runtime,
   preserve the public/private boundary, and prove a real client/server memory
   round trip before offering an API product download.
