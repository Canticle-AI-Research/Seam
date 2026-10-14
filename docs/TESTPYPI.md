# TestPyPI-first package migration

[Product map](PRODUCTS.md) · [Packaging status](status/packaging-licensing.md)

HISTORY#642 records the operator's requirement: test the renamed public
distribution on TestPyPI before any production PyPI publication. Production
uploads, legacy-release deletion, and private SDK uploads are excluded from
this preparation pass.

## Verified test publication

[seam-suite 2.4.1rc1](https://test.pypi.org/project/seam-suite/2.4.1rc1/) was
published from protected main `7b96a012784296989958e1774dbb8a0f52c3bfed` in
[run38562182535](https://github.com/Canticle-AI-Research/Seam/actions/runs/38562182535).
Exact wheel/sdist public hashes match the preparation receipt. Both downloaded
formats passed eight installed smoke cases and dependency checks; independent
root downloads matched too. Licensing is finished and TestPyPI publisher access
is resolved. See HISTORY#680 and [release evidence](audits/evidence/2026-10-14-testpypi-release/live-readback.json).
The instructions below remain the qualification contract for future candidates.
Existing published files must not be replaced or retried as a different build.

## Package boundaries

| Name | What it identifies | Test destination |
| --- | --- | --- |
| `seam-suite` | Self-hosted runtime, TUI, benchmark glassbox, and browser graph dashboard | Local candidate first; TestPyPI only after exact public artifact review |
| SEAM Client | Paid API service and its all-in-one WebUI | Service staging environment, not a replacement payload for the Python client wheel |
| `seam-client` | Existing Python HTTP client for the service | Separate client release process after source/owner recovery |
| `seam-sdk` | Private SDK for paying users | Local test environment or authenticated private distribution; never PyPI or TestPyPI |

The root candidate is `seam-suite` 2.4.1rc1. It keeps the existing `seam` and
`seam_runtime` imports and console commands. Install it in a fresh environment;
do not co-install older distributions that own those same paths. The candidate
includes the server/TUI dependency set by default. `[server,dash]` remains a
compatible extra selection rather than a prerequisite for normal operation.

## Publisher boundary

- The candidate's private-upload tripwire was removed after independent review
  of the owner-authorized Suite membership and installed behavior. The
  [manifest guard](../tools/release/verify_suite_manifest.py) checks exact source
  and archive membership; the license terms remain unchanged. Rebuild and
  verify the exact final files after any eligible source or metadata change.
- `.github/workflows/publish-testpypi.yml` is the only TestPyPI publisher. It is
  manual, main-only, and accepts the exact `seam-suite` package, canonical
  project version, and full current protected-main commit. The repository
  secret `TEST_PYPI` is exposed only to its upload step as a Twine token.
  Presence of the secret does not by itself establish project ownership; the
  first upload and public readback provide that evidence.
- The GitHub release workflows accept canonical Python versions, including
  `2.4.1rc1`, while retaining their operator and exact-artifact controls. They
  do not upload to TestPyPI; do not dispatch them as a test-registry upload.
- TestPyPI project names and ownership are independent of production PyPI.
  A missing project page does not prove registration eligibility.

TestPyPI is public. It is not an access-controlled registry and is not a safe
destination for the private SDK. Its database may be pruned. See the
[official TestPyPI guide](https://packaging.python.org/en/latest/guides/using-testpypi/)
and [PyPI private-package guidance](https://pypi.org/help/#how-can-i-publish-my-private-packages-to-pypi).

## Verification before any test upload

The current Suite personal-use membership is identified by
[the reviewed manifest](../LICENSES/SEAM-Suite-manifest.json) and
[license](../LICENSES/SEAM-Suite-Personal.txt). The owner has authorized completing
this TestPyPI-first candidate. Publishing access and verification of the exact
actual files remain prerequisites; production publication is separate. A
changed implementation requires refreshed membership review.

1. Build a wheel and sdist from the reviewed source in an isolated build
   directory. Record the source commit, package name/version, and both SHA-256
   hashes. Run `python -m twine check --strict` on those exact two files.
2. Run `python -m tools.release.verify_private_artifacts --expected-name
   seam-suite --expected-version 2.4.1rc1` with the exact wheel/sdist paths.
   Inspect the archive member inventory and license notices. Scanner success
   does not supersede the public membership decision above.
3. Install the exact wheel with its default dependencies in a fresh environment outside
   the source tree. Check dependency consistency, command help, installed
   module origins, MCP version/discovery, and write-then-read persistence.
   Keep test data separate from operator databases. Preserve old environments
   and backups; this is not an arbitrary legacy-upgrade qualification.
4. Bind qualification to the reviewed member inventory and exact hashes.
   The current candidate's classifier change follows independent source and
   installed-package review; verify the rebuilt files rather than uploading
   the earlier private-classifier archives. A future eligibility change needs
   its own review.
5. Configure only TestPyPI-specific publishing access. Prefer a narrowly bound
   GitHub OIDC publisher; never reuse a production token. Store credentials in
   the approved secret store, never in chat, source, reports, or artifacts.
6. The upload mechanism must use the explicit endpoint
   `https://test.pypi.org/legacy/`, an exact two-file list, and noninteractive
   operation. It must reject unexpected package names/versions, private SDK
   members, hash mismatches, and unapproved artifacts. Do not use a default
   Twine destination, upload globs, or production-workflow fallback.
7. Verify the TestPyPI project and downloaded file hashes. Install from
   TestPyPI in another clean environment and repeat the smoke checks. Obtain
   dependencies separately from the intended trusted index; do not combine
   public and private indexes indiscriminately.
8. Record test results and remaining limitations. Stop at the test registry.
   Production publication is a separate decision and cannot be inferred from
   a passing test upload, package rename, or a merged documentation PR.

## Manual TestPyPI run

Dispatch **Publish reviewed Suite candidate to TestPyPI** from `main` with:

- `package`: `seam-suite`
- `version`: the exact version in `pyproject.toml` (currently `2.4.1rc1`)
- `commit_sha`: the full current `main` commit shown by GitHub

The credential-free preparation job binds those inputs to checkout HEAD,
workflow SHA, and current remote `main`; runs the six canonical continuity
gates, Suite manifest guard, and secret scan; builds one wheel and one sdist;
and runs Twine, archive, manifest, default-install, and `pip check` verification
for both formats. Its receipt records source identity, artifact names, sizes,
SHA-256 values, and the Suite manifest digest. The publication job downloads
that immutable Actions artifact and revalidates the receipt and current remote
`main` immediately before invoking Twine with the fixed
`https://test.pypi.org/legacy/` endpoint and exact two paths.

After upload, the workflow polls the version-specific TestPyPI JSON endpoint.
It requires exactly the receipted filenames, byte sizes, and SHA-256 values,
accepts downloads only from the approved TestPyPI file host over HTTPS, and
checks the downloaded bytes before fresh wheel and sdist installs. Dependencies
for all install smokes come only from the explicit trusted production PyPI
dependency index; the Suite candidate itself always comes from a validated
local file. Any partial upload, ownership conflict, stale `main`, bad redirect,
metadata conflict, missing secret, or polling exhaustion fails the run for
operator review. The workflow never deletes or replaces a remote release.

## Private SDK delivery

A private registry serves versioned Python packages only to authenticated,
authorized customers. Customer entitlement, download credentials, revocation,
retention, and package integrity need an explicit service contract. Revoking
access stops future downloads; it cannot recall code already delivered.

The private `Seam_SDK` repository remains the source boundary until private
artifact delivery is selected and qualified. Do not publish a placeholder
public SDK package, copy private SDK source into Suite, or put access tokens
in install examples. SDK compatibility and its runtime dependency remain a
separate private workstream.
