# SEAM Suite MCP installation and registration

[SEAM Wiki](README.md) · [Release flow](RELEASE_FLOW.md) · [TestPyPI](TESTPYPI.md)

The MCP server is part of **`seam-suite`**, exposed by the existing `seam-mcp`
console command. It runs locally over stdio and uses the self-hosted runtime.
It does not depend on the planned `seam-api` product or a hosted API account.

## Where it is published

1. **PyPI hosts the reviewed Python distribution:** `seam-suite`.
2. **The official MCP Registry hosts discovery metadata:**
   `io.github.Canticle-AI-Research/seam-suite`, defined in
   [`server.json`](../server.json).
3. MCP clients install the Python package and launch `seam-mcp`. Registry
   registration is not an upload of the source code or a hosted server.

The registry's [package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx)
require the package to exist on production PyPI and its published README to
contain the matching `mcp-name` ownership marker. TestPyPI cannot serve as the
package destination for an official PyPI-backed registry entry. SEAM's separate
TestPyPI-first qualification still happens before production publication.

## Current state

On 2026-09-17 the official registry returned the active legacy listing
`io.github.BlackhatShiftey/seam-runtime` 1.3.1. Its PyPI files are yanked with
reason `broken`. The new Suite namespace returned no entries. Neither a new
listing nor a replacement public package has been published by this repair.

The root candidate remains `seam-suite` 2.4.1rc1 with
`Private :: Do Not Upload`. Resolve its exact public artifact membership and
notices, qualify the actual files on TestPyPI, then complete the production
release. Do not remove that classifier just to register MCP. The private paid
SDK remains outside both public package indexes.

The local candidate manifest and README marker are prepared for the Suite
namespace. Its version must advance with the package version. The old listing
is not renamed in place or silently redirected. After a working replacement
is publicly verified, deprecate the old listing with a migration message;
preserve its history and do not delete its versions as part of this repair.

## Use a reviewed local installation now

Install the eligible local candidate into a fresh environment using the
[installation procedure](RELEASE_FLOW.md#install-the-reviewed-suite-candidate).
Point the MCP client's command at that environment's absolute `seam-mcp` path.
For clients with an `mcpServers` configuration object:

```json
{
  "mcpServers": {
    "seam": {
      "command": "/absolute/path/to/.venv-suite/bin/seam-mcp",
      "args": ["--db", "/absolute/path/to/seam-agent-memory.db"]
    }
  }
}
```

Replace the paths; on Windows the executable is
`.venv-suite\\Scripts\\seam-mcp.exe`. Each client owns its configuration format
and location. Use a new test database for installation checks. The server's
default is local SQLite; optional vector backends require their own extras and
setup. Credentials belong in the client's protected environment, never in the
published manifest.

Once the exact candidate version has actually been published, its pinned
command will be:

```bash
uvx --default-index https://pypi.org/simple --from seam-suite==2.4.1rc1 seam-mcp
```

That PyPI command is not available until publication. The manifest leaves
`--from` as the final runtime argument so a registry client can insert
`seam-suite@2.4.1rc1`, followed by the `seam-mcp` command. It omits
`registryBaseUrl` because clients such as VS Code can insert an index argument
between `--from` and the package spec. The explicit `--default-index` supplies
the official simple index before `--from`. Do not put a second package name
or executable into `runtimeArguments`.

## Register after the public package is ready

The [manual workflow](../.github/workflows/mcp-registry.yml) prepares this path:

- Set repository variable `MCP_REGISTRY_APPROVER` to the intended GitHub
  operator, and configure the `mcp-registry` environment's release protection.
- Dispatch **Publish Suite MCP Registry metadata** from protected `main`, with
  the exact already-published Suite version. Branch runs, reruns and a missing
  or mismatched approver cannot enter the publishing job.
- It checks source/manifest/version agreement, the private-upload tripwire,
  the production PyPI ownership marker, and non-yanked wheel/sdist metadata.
  It rechecks current main and publication before authenticating.
- It downloads the pinned official `mcp-publisher` v1.8.1 Linux archive and
  verifies its SHA-256, validates the manifest, authenticates with GitHub OIDC,
  publishes, logs out, and verifies the exact public registry record.

This workflow publishes registry metadata only. It does not upload a Python
package, run on every code change, or waive exact-artifact qualification.
It has not been dispatched in this preparation session; environment protection
and registry authentication remain to be exercised on a publishable release.

The same order can be performed from a reviewed checkout with the official
[publisher CLI](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/cli/commands.md):

```bash
python -m tools.release.verify_mcp_registry --expected-version 2.4.1rc1
python -m tools.release.verify_mcp_registry --expected-version 2.4.1rc1 --published
mcp-publisher validate server.json
mcp-publisher login github --registry https://registry.modelcontextprotocol.io
mcp-publisher publish server.json
mcp-publisher logout
```

Stop on any failed check. The `--published` check currently fails intentionally
because the private-upload classifier is still present. A successful local
check or `mcp-publisher validate` alone does not establish a published package
or registered server. Publisher v1.8.1 has a help-dispatch quirk:
`validate --help` reports an unknown command, while `validate server.json`
works; the latter was exercised successfully here.

For interactive registration under the organization namespace, the GitHub
identity must be an organization owner. The existing operator's membership
was verified as active/admin through GitHub; no new registry login or publish
was performed. See the registry's
[authentication requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/authentication.mdx).

Read back `/v0.1/servers/io.github.Canticle-AI-Research%2Fseam-suite/versions/<version>`
from `https://registry.modelcontextprotocol.io` and verify the package/version
before claiming registration complete. Other client directories or catalogs
may have their own ingestion or submission process; this official entry does
not promise immediate placement in every client.
