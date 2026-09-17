---
handoff_id: 2026-09-17-package-release-repair
supersedes: 2026-09-14-claude-code-benchmark-next
handoff_status: current
history: HISTORY#647
---

# Package names, release repair, and DeepSeek review

## Operator direction

The operator selected `seam-suite` for self-hosted TUI, graph dashboard and
benchmark glassbox, and `seam-api` for the public API surface and WebUI. They
requested package/update/website pipeline repairs and matching GitHub/SEAM
documentation, followed by their own DeepSeek review. Preserve the private paid
SDK boundary. The previous formation handoff remains the continuation for that
separate workstream; no paid benchmark was run here.

SEAM branch: `fix/pypi-release-flow-20260917`, based on
`66fd3f93081712871ff827e756026c3e73c71790`.
Website branch: `fix/seam-product-downloads-20260917`, based on
`075b0f12d93538bb1c73d6dfa3eb1e001c735117` in
`BlackhatShiftey/Cantlicle`. Inspect the live PR heads before continuing; branch
source does not imply merged main, a registry upload, or a deployed website.

## Concrete repairs

- Root remains `seam-suite` 2.4.1rc1. Default dependencies now include the TUI
  and browser-server stack; compatibility extras remain. Doctor checks that
  dependency contract, including the supported legacy multipart import name.
- Release preparation and publication share canonical Python version parsing.
  `2.4.1rc1` is a prerelease. Requested versions, archive filenames and metadata
  must agree exactly; normalization cannot admit a different version spelling.
  Existing approver, protected-head, digest and publication boundaries remain.
- CI installs wheel and sdist in separate fresh environments without pip cache
  reuse. The installed smoke tests all console help commands, TUI mount,
  `/v1/health`, and packaged browser assets with isolated Python imports.
- README, product map, launch plan, TestPyPI procedure, installer docs and
  packaging status use the selected names and truthful install/release state.
- The companion website branch removes stale v2.4.0 links and the retired
  mirror/publisher helper. Its PyPI consumer binds version, exact wheel URL,
  SHA-256 and install command together, preserves the existing account gate,
  and leaves downloads unavailable on absent or invalid metadata. CSP includes
  the metadata host. The website needs separate browser review and deployment.

See [release flow](../RELEASE_FLOW.md) for the user-facing installation,
migration and update procedure. Opening the website never updates an installed
environment; upgrades remain explicit operator actions.

## Verification and limits

The original built wheel failed `tests/package/smoke_installed_suite.py`'s
acceptance behavior because terminal and browser dependencies were absent.
The test was initially named `test_installed_suite.py`, then renamed to keep
ordinary source-tree pytest collection separate from installed-package tests.
After the dependency repair, fresh wheel and sdist environments each passed
the four unittest cases on Linux/Python 3.12 without extras; dependency checks
passed. A separate environment pinned to python-multipart 0.0.6 exposed and
then verified the legacy-import compatibility repair. These are startup checks,
not full graph/glassbox acceptance or Windows/macOS qualification.

Focused source regression command:

```bash
python -m pytest tests/audit/test_chroma_optional.py tests/audit/test_dependency_contract.py tests/audit/test_github_issue_release_config.py tests/audit/test_mcp_stdio_smoke.py tests/audit/test_tui_supersedes_dashboard.py -q
```

That selection passed. Independent package assurance found the multipart
lower-bound problem; it was repaired and rechecked. The release-configuration
module's expanded tests pass for canonical versions, malformed versions and
artifact identity. The dashboard dependency-install hint is a presentation-only
name correction; no behavioral TDD claim is made for that text edit.

`python -m pytest tests/audit -m 'not external' -q` completed with three
failures. The unchanged main baseline reproduced the gate-order failure in
`tests/audit/test_history_closeout.py::test_preflight_gates_match_canonical_commit_hook`
([issue #260](https://github.com/Canticle-AI-Research/Seam/issues/260)). The two
`test_locomo_result_durability.py::TestDurableWriteHelpers` failures are
`test_tmp_paths_flagged_ephemeral` and `test_archive_dir_respects_env_override`:
their assumptions reject the task's `/tmp` checkout. Both passed in an unchanged
main checkout outside `/tmp`. No external backend or full cross-platform lane
was claimed here. Preserve these failures; do not suppress the required gates.

Website focused checks passed: `node --test tests/downloads-release.test.js`
and `python3 -m unittest discover -s tests -p 'test_package_downloads.py'`.
Full `python3 -m unittest discover -s tests` has the same failure/error records
as unchanged website main, with no newly failing record in this candidate.
The offline tests cover publication changes, 404, malformed/yanked metadata,
trusted URLs, timeouts and authentication ordering. No browser render or live
deployment was verified. Follow that repo's owner-browser-review policy.

Evidence is retained externally under
`/home/terrabyte/LLM-Logs/codex/releases/20260917-seam-packages/`; do not commit
virtual environments, archives, credentials or local agent session records.
Canonical continuity gates, draft PR delivery and independent closeout receipts
must be checked against the final exact state before calling it qualified.

## DeepSeek review and remaining decisions

1. Review both diffs and the tests above, including default dependency and
   sdist isolation, exact version/digest checks, website account/metadata races,
   and preserved private SDK/license boundaries.
2. Resolve the `seam-api` payload question: a client connecting to the hosted
   API/WebUI versus a locally installable server/WebUI. The selected product
   name is confirmed; this implementation choice is not. No new API wheel has
   been fabricated from the full private runtime.
3. Review the exact Suite public file/version membership and notices. The root
   build still retains `Private :: Do Not Upload`; its existing source bundle
   has not become eligible merely through a rename.
4. Configure verified TestPyPI publisher access, then build/scan/test approved
   bytes, upload only to TestPyPI, download/hash-check and reinstall them.
   Production PyPI publication needs its subsequent explicit decision. No
   package, tag or release was published or yanked during this repair.
5. Browser-review and deploy the website branch separately. Its runtime source
   of release truth is PyPI; a source merge alone does not populate Downloads.
6. Reconcile required checks and the release receipt before protected merge.
   Existing unrelated formation/report work and issue #260 remain separate.

## Preserved work

The primary SEAM checkout remains on `docs/deep-audit-20260829` with unrelated
dirty HISTORY/index, cross-index/history stream, audit/handoff indexes and August
audit/handoff work; untracked `.codex`, `.disposable`, orchestration data,
cross-index archive, audit/handoff documents and `error.log` are excluded.
Other existing SEAM worktrees were not modified. The primary website checkout's
untracked `.blender-toolkit` and `Temp downloads for implementation` are excluded.
No stash was created. Task worktrees are removed after pushed draft delivery;
resume from the named remote branches in fresh checkouts.
