# Suite MCP installation and registration

[SEAM Wiki](README.md) · [Release flow](RELEASE_FLOW.md) · [TestPyPI](TESTPYPI.md)

Suite includes the local stdio MCP server, `seam-mcp`. It uses the same runtime
and database as the other supported Suite interfaces. It does not require a
hosted service account.

## Use a reviewed local installation

Install the candidate in a fresh environment using
[the installation procedure](RELEASE_FLOW.md#install-the-reviewed-suite-candidate).
For clients that use an `mcpServers` configuration object:

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

Replace the paths; on Windows the executable ends in
`.venv-suite\Scripts\seam-mcp.exe`. Each client owns its configuration format.
Use a separate test database during qualification. Optional vector backends
need their own extra and setup. Keep credentials in a protected environment,
never the published manifest. The same
[personal, noncommercial terms](../LICENSES/SEAM-Suite-Personal.txt) apply;
business and organizational use require a written agreement.

## Prepared discovery metadata

[`server.json`](../server.json) names
`io.github.Canticle-AI-Research/seam-suite`, tied to the exact Suite package
version. The README contains the matching `mcp-name` ownership marker. A
versioned `uvx` launch installs that distribution and invokes `seam-mcp`.
These are candidate metadata, not proof of publication.

The official registry's
[package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx)
require the package on production PyPI, including the ownership marker in its
published README. TestPyPI is the earlier package qualification step; it cannot
serve as the official entry's package destination.

Before publication, use the absolute local executable above. A pinned registry
launch such as the following works only after that exact release is available:

```bash
uvx --default-index https://pypi.org/simple --from seam-suite==2.4.1rc1 seam-mcp
```

## Register only after package publication

The [manual workflow](../.github/workflows/mcp-registry.yml) retains a named
operator gate, protected-main checks, production-package preflight, and a pinned
publisher download. Configure its approver and environment protection before
dispatch. It verifies manifest/source/version agreement, public-upload
eligibility, and the production package's matching ownership marker and
non-yanked artifacts before authentication and registration.

For a reviewed checkout, the local preflight is:

```bash
python -m tools.release.verify_mcp_registry --expected-version 2.4.1rc1
python -m tools.release.verify_mcp_registry --expected-version 2.4.1rc1 --published
```

Stop on a failed check. The published check refuses private-classifier artifacts
and candidates without matching production PyPI publication; local validation
does not establish publication. The Suite candidate's reviewed TestPyPI
preparation is separate from that production prerequisite. Follow the official
[publisher instructions](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/cli/commands.md)
for authentication and registration only after the production package qualifies.
Read back the exact public server/version and package identity before claiming
registration complete. Other MCP directories may have separate ingestion rules.

No registry registration or production package upload follows merely from this
preparation. Historical listings and releases remain intact; this first-launch
work does not build a legacy-user migration project.
