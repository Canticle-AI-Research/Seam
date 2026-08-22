# Public SEAM Agent SDK API

The public SDK talks to a deliberately small, opaque `/v1` API. This document
is the private runtime-side contract. The public implementation and examples
live in `BlackhatShiftey/Seam_Runtime/sdk`.

Install the released public client with:

```bash
python -m pip install seam-client
```

PyPI project: <https://pypi.org/project/seam-client/>

## Boundary

The public API exposes:

- health
- remember one text memory
- recall text memories
- assemble prompt-ready text context
- delete caller-owned opaque memory handles in principal mode
- agent, namespace, scope, and session partitioning

It does not expose:

- MIRL records, identifiers, schemas, parsers, or compiler output
- HS/1, surface, compression, or PACK payloads
- storage paths, migrations, vector tables, or graph internals
- retrieval reasons, candidate ledgers, ranking policy, or benchmark data

Public responses contain only user-facing text, opaque `rcpt_...` or
`mem_...` identifiers, timestamps, scores, public partitions, and the API
version.

## Authentication

The `/v1` stateful endpoints use a bearer-token guard. Legacy token-only mode
authenticates one trusted deployment boundary; it is not multi-tenant identity.
Principal mode resolves the bearer credential to a stable subject inside the
process, derives the tenant boundary from that subject, and disables legacy
private data routes. The environment adapter pairs `SEAM_API_TOKEN` with
`SEAM_API_PRINCIPAL`; an embedding application can inject its own resolver.

```http
Authorization: Bearer <SEAM_API_TOKEN>
```

`GET /v1/health` and `HEAD /v1/health` are rate-limited but do not require
authentication. Both expose storage-backed readiness, cached for five seconds.
GET returns `status: ok` with `200` or `status: degraded` with `503`, without
connection details. HEAD returns the corresponding status code without a body.

Principal mode always has a bounded process-local limiter: when the configured
limit is unset or zero, it defaults to 60 requests per minute. Invalid or
rotating credentials share a client-address pre-resolver bucket; a successfully
resolved subject uses its own stable bucket. Multi-worker launch is refused
while this process-local limiter is active unless an operator explicitly
acknowledges a shared upstream limiter. Legacy mode retains its existing
configuration, including an unset/zero limit disabling rate limiting.

## Partitions

- `namespace` identifies an agent or application.
- `session_id` optionally isolates a conversation or run.
- `scope` is semantic and must be one of `ephemeral`, `global`, `org`,
  `project`, `thread`, or `user`.

The server maps these values into an SDK-only internal namespace. A client
cannot use the public API to address arbitrary private runtime namespaces.

## Endpoints

### `POST /v1/memories`

```json
{
  "text": "The operator prefers evidence-backed answers.",
  "namespace": "research-agent",
  "scope": "thread",
  "session_id": "thread-42",
  "agent_id": "researcher"
}
```

```json
{
  "api_version": "v1",
  "accepted": true,
  "receipt_id": "rcpt_...",
  "memory_count": 1,
  "namespace": "research-agent",
  "scope": "thread",
  "session_id": "thread-42"
}
```

### `POST /v1/memories/recall`

```json
{
  "query": "answer style",
  "namespace": "research-agent",
  "scope": "thread",
  "session_id": "thread-42",
  "limit": 5
}
```

The response contains a `memories` list. Each item has an opaque `id`, public
`text`, relevance `score`, and `created_at`. In principal mode, recall registers
the returned opaque handles in the caller's exact tenant/namespace/scope before
the response is sent. The registration is derived state, but it makes this API
call a storage write even though canonical memory content is unchanged.

### `POST /v1/context`

Accepts the recall fields plus `max_chars`. The response contains the same
public memory items and a bounded `context` string ready for insertion into an
agent prompt. Principal-mode context assembly has the same handle-registration
write as recall.

### `POST /v1/memories/delete` (principal mode only)

```json
{
  "memory_ids": ["mem_..."],
  "namespace": "research-agent",
  "scope": "thread",
  "session_id": "thread-42",
  "idempotency_key": "delete-turn-42"
}
```

```json
{
  "api_version": "v1",
  "accepted": true,
  "deletion_id": "del_...",
  "status": "deleted",
  "namespace": "research-agent",
  "scope": "thread",
  "session_id": "thread-42"
}
```

Deletion resolves at most 50 registered opaque handles inside the exact caller
boundary and reuses the canonical lifecycle soft-delete/audit/recoverable-
cleanup engine. A cleanup adapter failure returns the same opaque receipt with
`status: pending`; retrying the same request resumes it. Foreign, forged, stale,
or replaced-generation handles return the same content-free 404. Reusing an
idempotency key for a different handle set, recalling a stale snapshot, or
remembering content while an earlier scoped deletion is still active returns
409. Re-remembering after a completed delete mints a new generation and the old
handle cannot delete it. Deletion receipts remain stable across public-ID-key
rotation.

## Compatibility

The `v1` response shape is additive-only. Breaking changes require a new URL
version. Private implementation changes do not change the public contract.

The service rejects non-string `text`, `query`, and partition values instead
of coercing JSON objects, arrays, numbers, or booleans. Current limits are
100,000 characters for memory text, 4,096 for a query, 128 for namespace,
session, and agent identifiers, 50 recalled memories, and 65,536 characters
for assembled context. A `429` response includes `Retry-After: 60`.

Principal mode requires a stable public-ID key of at least 32 bytes, supplied
by the embedding application or `SEAM_API_PUBLIC_ID_KEY`. The key renders
`mem_` capabilities; it, the resolved principal subject, canonical IDs, and
lifecycle operation IDs are never returned by this API.
