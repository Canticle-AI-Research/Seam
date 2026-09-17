# Package installation and release flow

[SEAM Wiki](README.md) · [Products](PRODUCTS.md) · [TestPyPI](TESTPYPI.md)

## Product names

| Product | Purpose | Distribution state |
| --- | --- | --- |
| `seam-suite` | Self-hosted TUI, browser graph dashboard and benchmark glassbox | Root wheel/sdist candidate; not yet on PyPI |
| `seam-api` | Public API surface and WebUI | Selected product name; confirm public client versus server artifact before creating a new wheel |
| `seam-sdk` | Private SDK for paying users | Separate private delivery |

The old `seam-client` wheel is an HTTP transport library. It is not the new
Suite, the WebUI, or the private SDK. Keep its existing imports compatible
until its replacement contract and source ownership are resolved.

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
