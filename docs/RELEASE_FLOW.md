# Suite installation and release flow

[SEAM Wiki](README.md) · [Products](PRODUCTS.md) · [TestPyPI](TESTPYPI.md)

## Install the reviewed Suite candidate

Use Python 3.11 or later and a fresh environment. The current source candidate
is `seam-suite` 2.4.1rc1; an updated GitHub checkout does not publish it to a
package registry. From a reviewed checkout, under the
[personal-use terms](../LICENSES/SEAM-Suite-Personal.txt):

```bash
python3 -m venv .venv-suite
.venv-suite/bin/python -m pip install .
.venv-suite/bin/python -m pip check
.venv-suite/bin/seam --help
.venv-suite/bin/seam-tui --help
.venv-suite/bin/seam-server --help
```

On Windows use `.venv-suite\Scripts\python.exe` and the corresponding console
commands. The [platform installers](../installers/README.md) set up a managed
runtime and persistent database; their shell wrappers require a full reviewed
checkout. They are not standalone remote bootstrap scripts.

The default Suite includes Textual, HTTP client, and HTTP/browser server
dependencies. `[dash]` and `[server]` remain compatible aliases. Optional
vector backends, neural embeddings, and benchmark providers stay opt-in.
Do not co-install older distributions that own the same `seam` imports or
commands. Installation checks use isolated databases, not operator data.

## Verify the actual archives

Build wheel and sdist outside the active checkout. Record the source revision,
member inventory, and SHA-256 of both files. Strict Twine validation and
`tools.release.verify_private_artifacts` check those actual archives.
Compare every implementation member against the current
[license manifest](../LICENSES/SEAM-Suite-manifest.json); runtime edits require
refreshed exact hashes without reopening the settled licensing decision.

Run the check-only guard on source and on the exact two archives:

```bash
python -m tools.release.verify_suite_manifest
python -m tools.release.verify_suite_manifest /absolute/candidate.whl /absolute/candidate.tar.gz
```

It never expands permission or rewrites the license. Required hygiene and local
commit gates check source membership; the commit hook checks staged bytes.
Package CI also checks archive membership and source-identical notices. The
manifest records an implementation base plus explicit reviewed source changes
and exact file hashes, avoiding a circular dependency on its own final commit.

[Package CI](../.github/workflows/ci.yml) installs wheel and sdist into separate
fresh environments. The [installed smoke](../tests/package/smoke_installed_suite.py)
uses isolated imports and tests the supported CLI, TUI, HTTP, and MCP paths.
Source-checkout imports and optional extras must not conceal a missing default
dependency. A successful startup check does not finish all browser graph,
glassbox, or hosted-product acceptance; see [surface status](status/surfaces.md).

## Release destinations

The [preparation workflow](../.github/workflows/package-release.yml) accepts the
exact canonical three-component Python version from `pyproject.toml`, including
`2.4.1rc1`. It verifies and packages artifacts for a GitHub draft. The separate
[publication workflow](../.github/workflows/publish-private-release.yml) retains
operator, protected-head, checksum, and artifact controls. The historical word
"private" in their names does not establish destination visibility. Neither
workflow uploads a Python package to an index.

**TestPyPI first:** follow [the procedure](TESTPYPI.md) for exact artifact
qualification, TestPyPI-specific publishing access, upload, and fresh downloaded
installation. The current Suite candidate's private-upload tripwire is removed
after independent membership and installation review; verify the exact rebuilt
archives before upload. A registry lookup returning 404 does not establish
name ownership or publisher access. Production PyPI publication is a separate
release decision after successful TestPyPI verification.

The private paid `seam-sdk` stays separate and never enters either public
registry. SEAM Client and its hosted WebUI are distinct from the Suite and the
existing `seam-client` HTTP library; see [product definitions](PRODUCTS.md).

The [MCP Registry flow](MCP_REGISTRY.md) publishes discovery metadata only after
a qualified production PyPI package exists. Preparing its manifest does not
publish or register the package.

## Updates and downloads

An installed environment changes when its operator installs a reviewed update;
GitHub pushes do not update running installations. Preserve operator data and
stop running Suite processes before replacing that environment. Once a reviewed
Suite release actually exists on the selected registry, upgrade within that
Suite environment and run `python -m pip check` plus the supported smoke checks.
Do not infer a legacy migration path from a renamed distribution.

The website has its own deployment and download selector. A TestPyPI upload or
prerelease does not automatically enable its stable production download button.
Check the served download destination separately before claiming availability.
