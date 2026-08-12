# SEAM Topic Ledgers

[Back to the SEAM Wiki](../README.md)

Topic ledgers hold stable facts for high-value routes. They are not session
logs, current-state streams, or substitutes for `HISTORY.md`. Route structure
lives in `tools/history/routing_manifest.json`; chronology remains in
[history](../../HISTORY_INDEX.md).

Use ledgers for facts future agents should find quickly: known failures,
maintenance decisions, durable verification commands, source-of-truth files,
and the next safe action.

## Agent integration

- [DeepSeek corrections ledger](agents/deepseek.md) — durable corrections for the DeepSeek execution route.

## Maintenance

- [Maintenance ledger index](maintenance/README.md)
- [Docker maintenance](maintenance/docker.md)
- [PgVector maintenance](maintenance/pgvector.md)

## Protocol

- [Protocol ledger index](protocol/README.md)
- [Context routing](protocol/context.md)
- [Security routing](protocol/security.md)

## Runtime

- [Compression ledger](runtime/compression.md)

When a stable routed fact changes, append the chronology to history and update
the relevant ledger; do not turn this index into another status stream.
