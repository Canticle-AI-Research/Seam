# seam-self-host

`seam-self-host` is the compiled Linux/x86-64 self-hosted SEAM agent-memory node.
It installs the opaque `/v1` service plus the local MCP stdio surface used by
Claude, Cursor, Gemini, and other MCP-capable agents.

The wheel contains native extension modules and does not ship the
`seam_runtime` Python source. Native compilation raises the cost of casual
inspection; it is not a cryptographic boundary against an administrator who
controls the host. See the self-host security documentation for the complete
protection model.

This first wheel supports CPython 3.12 on `manylinux_2_28_x86_64`.

## Run

The HTTP node requires an API token of at least 32 characters and a writable
database path:

```bash
export SEAM_API_TOKEN_FILE=/run/secrets/seam-api-token
export SEAM_SERVER_DB=/var/lib/seam/seam.db
seam-self-host
```

The server listens on `0.0.0.0:8765` by default. Keep it on a trusted network
or place an authenticated TLS reverse proxy in front of it.

An entitlement is optional and gates no capability. When no entitlement is
mounted, the node logs that it is running unentitled under BUSL-1.1. Supported
deployments may set `SEAM_SELFHOST_ENTITLEMENT_PATH` and
`SEAM_SELFHOST_PUBLIC_KEY_PATH`; a mounted entitlement is verified and a
forged or malformed one fails closed.

## MCP

Connect an MCP client to the wheel's stdio command:

```bash
seam-mcp --db /var/lib/seam/seam.db
```

The MCP server exposes the same three operations as the HTTP surface —
`seam_remember`, `seam_recall`, and `seam_context` — talking directly to the
local database instead of over the network. Run it only for a trusted local
client and protect the database with operating-system permissions.
