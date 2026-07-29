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

The `/v1` stateful endpoints use the existing server bearer-token guard. A
hosted or remotely reachable deployment must configure `SEAM_API_TOKEN`; an
authorized local server may retain the existing loopback development behavior.

```http
Authorization: Bearer <SEAM_API_TOKEN>
```

`GET /v1/health` and `HEAD /v1/health` are rate-limited but do not require
authentication. Both expose storage-backed readiness, cached for five seconds.
GET returns `status: ok` with `200` or `status: degraded` with `503`, without
connection details. HEAD returns the corresponding status code without a body.

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
`text`, relevance `score`, and `created_at`.

### `POST /v1/context`

Accepts the recall fields plus `max_chars`. The response contains the same
public memory items and a bounded `context` string ready for insertion into an
agent prompt.

## Compatibility

The `v1` response shape is additive-only. Breaking changes require a new URL
version. Private implementation changes do not change the public contract.

The service rejects non-string `text`, `query`, and partition values instead
of coercing JSON objects, arrays, numbers, or booleans. Current limits are
100,000 characters for memory text, 4,096 for a query, 128 for namespace,
session, and agent identifiers, 50 recalled memories, and 65,536 characters
for assembled context. A `429` response includes `Retry-After: 60`.
