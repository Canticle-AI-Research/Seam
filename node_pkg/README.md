# seam-node

`seam-node` is the compiled Linux/x86-64 self-hosted SEAM agent-memory node.
It installs the same opaque `/v1` service exposed by the compiled container
edition while letting an operator use normal Python package tooling.

The wheel contains native extension modules and does not ship the
`seam_runtime` Python source. Native compilation raises the cost of casual
inspection; it is not a cryptographic boundary against an administrator who
controls the host. See the self-host security documentation for the complete
protection model.

This first wheel supports CPython 3.12 on `manylinux_2_28_x86_64`.

## Run

The current node requires a vendor-signed Ed25519 entitlement, an API token of
at least 32 characters, and a writable database path:

```bash
export SEAM_SELFHOST_ENTITLEMENT_PATH=/approved/entitlement.json
export SEAM_SELFHOST_PUBLIC_KEY_PATH=/approved/entitlement-public-key.pem
export SEAM_API_TOKEN_FILE=/run/secrets/seam-api-token
export SEAM_SERVER_DB=/var/lib/seam/seam.db
seam-node
```

The server listens on `0.0.0.0:8765` by default. Keep it on a trusted network
or place an authenticated TLS reverse proxy in front of it.

The entitlement requirement conflicts with the intended free self-host tier
and remains an explicit product decision. This wheel preserves the current
runtime behavior rather than silently weakening that control.
