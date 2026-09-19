# Package installation and release flow

[SEAM Wiki](README.md) · [Products](PRODUCTS.md) · [TestPyPI](TESTPYPI.md)

## Product names

| Product | Purpose | Distribution state |
| --- | --- | --- |
| `seam-suite` | Usable self-hosted core; TUI, browser graph dashboard and benchmark glassbox still in development | Early-access product; root wheel/sdist candidate not yet on PyPI |
| `seam-api` | Planned local API server, client support, and WebUI | Product development has not started; no download |
| `seam-sdk` | Private SDK for paying users | Separate private delivery |

The old `seam-client` wheel is an HTTP transport library. It is not the new
Suite, the WebUI, or the private SDK. Keep its existing imports compatible
until its replacement contract and source ownership are resolved.

Product maturity and package availability are independent. The operator
considers the self-hosted core usable for plug-and-play local operation. The
operator interfaces remain unfinished. Downloads must show both that maturity
and whether an actual, verified package is published; it must not present the
future API product as ready because Console or low-level API code exists.

## Planned seam-api installation

The selected direction is to install the software needed to run SEAM locally
through the API and WebUI. This is a plan, not an implemented package:

```text
API client or WebUI -> local API server -> shared SEAM runtime -> local storage
```

1. Reuse the same runtime as Suite through a reviewed runtime dependency.
   Do not ship a second, independently maintained copy of `seam_runtime`, and
   do not rename the legacy HTTP client and present it as a complete server.
2. Include the API server, served WebUI assets, and required client libraries.
   A client alone only sends requests; it does not run the memory engine.
3. Provide a first-run path that configures local storage, starts a loopback
   server, opens the WebUI, and checks a real client/server memory round trip.
   Define exact commands during implementation; no working `seam-api` command
   is claimed here.
4. Preserve the public API contract and private SDK boundary. Review exposed
   routes, authentication, version compatibility, restart/recovery and clean
   installation before offering the new package.
5. Qualify the exact eligible artifacts on TestPyPI before production PyPI.
   A hosted API endpoint remains a separate deployment with its own access
   and operational requirements.

Existing server routes and the browser prototype can inform that work. The
API product itself has not started. The exact runtime dependency, artifact
membership, launcher and supported client contract still need implementation
design; no new public core package name is implied by this plan.

## Install the reviewed Suite candidate

Use Python 3.11 or later and a **new environment**. Installing a differently
named distribution does not remove an older distribution's overlapping files.
Do not co-install `seam-runtime`, `seam-self-host`, and `seam-suite`.

From a reviewed checkout, subject to the existing license terms:

```bash
python3 -m venv .venv-suite
.venv-suite/bin/python -m pip install .
.venv-suite/bin/seam-tui --help
.venv-suite/bin/seam-server --help
```

On Windows, use `.venv-suite\Scripts\python.exe` and the corresponding
console commands. The [platform installers](../installers/README.md) need
a complete checkout; their shell wrappers are not standalone remote bootstrap
scripts and must not be piped directly from a download URL into a shell.

The default Suite includes Textual, HTTP client and browser-server dependencies.
`[dash]` and `[server]` remain compatible aliases. Optional embedding models,
vector backends and paid benchmark providers remain opt-in. Launching the
Suite does not itself authorize paid inference.

Preserve the old environment and back up operator data before a migration.
Validate a copy of the database with the new version before replacing an
existing installation. Clean-install tests do not prove every historical
database or compiled self-host upgrade path.

## What updates automatically

Changing code on GitHub does **not** publish a Python package. A release must
have a new version and pass artifact qualification before publication.

The companion Canticle website repair consumes `https://pypi.org/pypi/seam-suite/json`.
It selects one supported, non-yanked stable wheel and derives the displayed
version, exact file URL and SHA-256-pinned install command from that release.
The early-access maturity label does not change that selector; offering a
prerelease candidate would need a separate release-channel change and review.
Missing, mismatched or unavailable metadata keeps downloads disabled. Existing
account checks remain separate. The website change needs its own reviewed
deployment; this SEAM branch does not deploy Canticle.cc.

An installed Suite updates only when its operator runs an upgrade in its own
environment. Once a qualified release is actually published, the ordinary
upgrade command for an existing **Suite** environment is:

```bash
python -m pip install --upgrade seam-suite
python -m pip check
```

Stop running Suite processes and back up the database first. This command is
not a migration from the old distribution names. An unattended updater that
replaces a running installation is not implemented by this repair.

## Artifact checks and GitHub release

The [preparation workflow](../.github/workflows/package-release.yml) accepts
canonical Python versions such as `2.4.1rc1`, checks the exact metadata version,
scans archives, installs the built Suite, and prepares a reviewed GitHub draft.
The [publication workflow](../.github/workflows/publish-private-release.yml)
retains its separate operator, protected-head and checksum checks. Their
historical names do not establish private repository or artifact visibility.

The [package CI job](../.github/workflows/ci.yml) installs the wheel and sdist
into separate fresh environments. Its [installed smoke](../tests/package/smoke_installed_suite.py)
uses isolated Python imports and verifies console entrypoints, TUI mount,
public health and served browser assets. Optional extras and the source tree
must not conceal missing default dependencies. This proves package startup,
not complete graph/glassbox interaction or production service qualification.

Neither GitHub workflow uploads to PyPI. The full source candidate still
declares `Private :: Do Not Upload`. Exact public artifact membership/notices,
publisher access and approved hashes must be resolved before following the
[TestPyPI-first procedure](TESTPYPI.md). Production publication follows verified
TestPyPI installation and an explicit release decision. The paid SDK never
belongs in either public registry.

## Review checkpoint

Suite's [personal license](../LICENSES/SEAM-Suite-Personal.txt) allows only
personal, noncommercial self-hosting. Internal business use also requires a
separate written agreement from licensing@canticle.cc. Before a new release,
compare its exact implementation bytes against
[the license manifest](../LICENSES/SEAM-Suite-manifest.json), review any changes
and include the controlling terms. Packaging approval does not expand rights
in MIRL, HS/1 or the private paid SDK.

Suite includes the `seam-mcp` server. Its prepared
[MCP Registry flow](MCP_REGISTRY.md) registers discovery metadata only after a
qualified production PyPI release exists. The manual registry workflow checks
the exact package/version and ownership marker; it cannot publish the Python
package or clear its private-upload restriction. The legacy registry listing
still points to yanked `seam-runtime` 1.3.1 until migration is completed.

Live PyPI metadata queried on 2026-09-17 reported:

- `seam-runtime` 1.3.1: both artifacts yanked, reason `broken`.
- `seam-self-host` 1.1.2: only a CPython 3.12 manylinux x86-64 wheel; no portable
  wheel or sdist was listed for that version.
- `seam-client` 2.0.0: an HTTP client whose metadata still links to the legacy
  repository; that repository returned HTTP 404 through `gh api`.
- `seam-suite` and `seam-api`: HTTP 404 on both PyPI and TestPyPI. This does not
  prove name reservation, ownership or future eligibility.

These observations came from each registry's `/pypi/<name>/json` endpoint.
Existing artifacts were not deleted or changed. See HISTORY#647 and the
[current handoff](handoffs/INDEX.md) for the exact verification and review
continuation. Recheck the registry before making a release decision.
