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

The node needs only an API token of at least 32 characters and a writable
database path. It runs with no third-party account:

```bash
export SEAM_API_TOKEN_FILE=/run/secrets/seam-api-token
export SEAM_SERVER_DB=/var/lib/seam/seam.db
seam-self-host
```

The server listens on `0.0.0.0:8765` by default. Keep it on a trusted network
or place an authenticated TLS reverse proxy in front of it.

Command-line flags are available for the three deployment settings most often
changed by a service manager. Flags override environment defaults:

```bash
seam-self-host --host 127.0.0.1 --port 8830 --db /srv/seam/state.db
```

`GET` and `HEAD` on `/v1/health` are unauthenticated. The endpoint performs a
cached storage-readiness check: healthy nodes return `200`; a node whose
configured store cannot answer a trivial read returns `503` without disclosing
the backend or connection error.

## Configuration

Everything below is optional. Defaults are chosen so a fresh install works
offline; the settings that most affect answer quality are in the first two
tables.

### Retrieval quality

The single highest-impact setting. Retrieval depth and context size are tuned
together, because the right pair depends on how capable the model consuming the
context is. Shipping defaults are deliberately conservative.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_RETRIEVAL_PROFILE` | unset | Presets a matched depth/budget pair. `compact` = `(100, 8000)` for small or local models, which are hurt by long context. `broad` = `(300, 60000)` for capable models, which convert wide context into more correct answers. |
| `SEAM_RETRIEVAL_TOP_K` | call-site budget | Candidates fetched per query. Overrides the profile. Low values starve recall: raising this from 20 toward ~100 was worth a large measured accuracy gain, and the knee sits near 100. |
| `SEAM_RETRIEVAL_CONTEXT_BUDGET` | call-site budget | Character budget for the returned context. Overrides the profile. Raise it only alongside a capable model; a wide context measurably degrades small ones. |

Start with `SEAM_RETRIEVAL_PROFILE=compact`. Move to `broad` only if the model
reading the context is a frontier-class one.

### Embeddings

The built-in embedder is the default. It needs no network, no account, and no
per-request cost, which is why a fresh install just runs. It is lexical, so
paraphrased recall ("how often does the key rotate" against "key rotates every
90 days") is weaker than a semantic model. Switching is the main quality upgrade
after the retrieval profile.

Treat the built-in option as a keyword-search baseline, not a semantic
embedding model. In a deterministic characterization with 100 memories and 41
queries, its measured recall was:

| Query class | Recall@1 | Recall@5 | Recall@10 |
| --- | ---: | ---: | ---: |
| Word overlap | 0.889 | 1.000 | 1.000 |
| Paraphrase | 0.200 | 0.600 | 0.700 |
| Numeric | 0.700 | 1.000 | 1.000 |
| Disambiguation | 0.917 | 0.917 | 1.000 |
| All queries | 0.683 | 0.878 | 0.927 |

On the same fixed queries, recall@1 fell from 0.786 at 20 memories to 0.500 at
100. Use `openai`, `openai-compatible`, or a qualified local semantic model for
paraphrase-heavy or larger corpora. The offline default is preserved so a new
installation never silently requires an account or network call.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_EMBEDDING_PROVIDER` | `hash` | `hash` (built-in, offline), `openai` / `openai-compatible` (hosted API), or `sentence-transformers` (local model). |
| `SEAM_EMBEDDING_MODEL` | `text-embedding-3-small` | Model name for the chosen provider. |
| `SEAM_EMBEDDING_BASE_URL` | OpenAI's endpoint | Point `openai-compatible` at any compatible server, including a local one. |
| `SEAM_EMBEDDING_API_KEY_ENV` | `OPENAI_API_KEY` | Which environment variable holds the key. |
| `SEAM_EMBEDDING_DIMENSIONS` | provider default | Override the vector width. |
| `SEAM_EMBEDDING_TIMEOUT_S` | `30` | Per-request timeout for API providers. |

Selecting an API provider without its key is refused at startup rather than
failing on the first write. `sentence-transformers` is not bundled; install it
yourself if you want local semantic embeddings.

Changing the provider changes how vectors are computed. Existing memories keep
their old vectors, so re-ingest if you switch after storing data.

### Retrieval ranking

Defaults reproduce the shipped ranking exactly. Change one at a time and
measure; these interact.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_RETRIEVAL_RRF` | off | `1` switches fusion from weighted scoring to reciprocal-rank fusion. |
| `SEAM_RETRIEVAL_RRF_K` | `60` | Rank constant for RRF. Only read when RRF is on. Lower favours top ranks more sharply. |
| `SEAM_RETRIEVAL_BM25_ALL` | off | `1` runs lexical BM25 across all record kinds rather than the default subset. |
| `SEAM_RETRIEVAL_SCOPED_VECTORS` | off | `1` restricts vector search to the requested scope instead of searching across scopes and filtering after. |
| `SEAM_RETRIEVAL_SEMANTIC_ZERO` | off | `1` scores records that have no vector as zero rather than falling back to lexical similarity. |
| `SEAM_RETRIEVAL_ENTITY_GROUNDED` | off | `1` scores candidates by entity-label overlap with the query. Only has signal when entity extraction is enabled, so leave it off unless you set `SEAM_NL_EXTRACTOR`. |

### Context and answer policies

All default to the baseline single-pass path. They change the shape of the
context returned to your model, not just its ranking.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_CONVERSATION_ADAPTER` | `off` | `conversation/1` renders retrieved turns as a provenance-preserving evidence table instead of raw text. Helps models that must attribute an answer to a specific turn. |
| `SEAM_INFERENCE_POLICY` | `context-only` | Controls whether the layer may infer beyond what the retrieved context literally states. |
| `SEAM_TEMPORAL_POLICY` | `off` | Enables time-aware handling for questions about when something happened, or which instance of a repeated event is meant. |
| `SEAM_COUNT_CONTEXT_POLICY` | `off` | Groups same-event records so "how many times" questions do not double-count. |
| `SEAM_ANSWER_CONTRACT` | `off` | Adds an explicit answer-shape contract to the returned context. |

### Storage

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_SERVER_DB` / `SEAM_DB_PATH` | `/var/lib/seam/seam.db` | SQLite database path. `SEAM_SERVER_DB` wins when both are set. Must be writable. New database files and parent directories are created with private permissions on POSIX systems. |
| `SEAM_PGVECTOR_DSN` | unset | Use a pgvector-enabled Postgres instead of SQLite, e.g. `postgresql://user@host:5432/seam`. Supply the password out of band via `PGPASSWORD` or a `.pgpass` file rather than inlining it. The driver ships with the wheel and the DSN is validated at startup. |
| `SEAM_PGVECTOR_TABLE` | `seam_vector_index` | Table name for the vector index when using Postgres. |
| `SEAM_DB_POOL_SIZE` | `5` | Pooled connections. |
| `SEAM_DB_POOL_TIMEOUT` | `300` | Seconds an idle pooled connection is kept. |

SQLite is the default and is sufficient for a single node. Use Postgres when you
need several nodes against one store. Run one writer per database either way.

### Extraction

Off by default: ingest uses a deterministic parser that needs no model. The
optional extractor sends memory text to a local Ollama server, which improves
entity and relation quality and is what makes `SEAM_RETRIEVAL_ENTITY_GROUNDED`
useful.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_NL_EXTRACTOR` | unset | Set to enable the model-backed extractor. Unset keeps the deterministic floor. |
| `SEAM_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama endpoint. |
| `SEAM_OLLAMA_MODEL` | `qwen2.5:3b` | Extraction model. |
| `SEAM_OLLAMA_MODEL_DIGEST` | unset | Pin an exact model digest for reproducibility. |
| `SEAM_OLLAMA_TIMEOUT_S` | `300` | Per-request timeout. |
| `SEAM_OLLAMA_NUM_PREDICT` | `256` | Token cap per extraction. |
| `SEAM_NL_REGEX_ENRICH` | off | Re-enables legacy regex enrichment. Not recommended: it mislabels a substantial share of real prose for no measured recall benefit. |

### Server

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_API_TOKEN` / `SEAM_API_TOKEN_FILE` | required | Bearer token for every route except `/v1/health`. Minimum 32 characters. Prefer the file form so the secret stays out of the process environment. |
| `SEAM_SELFHOST_HOST` | `0.0.0.0` | Bind address. Set `127.0.0.1` when a reverse proxy fronts it. |
| `SEAM_SELFHOST_PORT` | `8765` | Bind port. |
| `SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE` | `120` | Process-local request cap. Must be from 1 through 65,535; this edition does not support disabling it. |
| `SEAM_API_RATE_LIMIT_MAX_KEYS` | `10000` | Distinct clients tracked by the limiter. |
| `SEAM_API_MAX_BODY_BYTES` | `5000000` | Largest accepted request body, in bytes. |
| `SEAM_SHUTDOWN_TIMEOUT` | `30` | Seconds to drain in-flight requests on shutdown. |
| `SEAM_MCP_MAX_LINE_BYTES` | `5000000` | Largest accepted MCP request line. |
| `SEAM_AGENT` | unset | Default agent identifier attached to stored memories when a request omits one. |

Successful and failed guarded requests both consume the rate-limit bucket.
Authenticated requests are keyed by a one-way digest of the authorization
header, so every client using the node's one valid token shares a bucket.
Requests without that header are keyed by the direct socket peer. Forwarding
headers are deliberately ignored; behind a reverse proxy, unauthenticated
requests therefore share the proxy's bucket. A `429` response includes
`Retry-After: 60`. Use the proxy's own trusted-client rate limiter for
per-user enforcement, and do not treat this in-process limiter as a
multi-node quota system.

### Request limits

| Field or request | Maximum |
| --- | ---: |
| Memory `text` | 100,000 characters |
| Recall/context `query` | 4,096 characters |
| `namespace`, `session_id`, or `agent_id` | 128 characters |
| Recall `limit` | 50 memories |
| Context `max_chars` | 65,536 characters |
| HTTP request body | 5,000,000 bytes by default |
| MCP request line | 5,000,000 bytes by default |

Text, query, and partition fields must be JSON strings; objects, arrays,
numbers, and booleans are rejected rather than converted into Python text.

### Entitlement

Optional, and gates no capability. Absence is the normal free path.

| Variable | Default | What it does |
| --- | --- | --- |
| `SEAM_SELFHOST_ENTITLEMENT_PATH` | `/run/seam/entitlement.json` | Mounted entitlement file, for supported deployments. |
| `SEAM_SELFHOST_PUBLIC_KEY_PATH` | `/opt/seam/entitlement-public-key.pem` | Public key used to verify it. |

### Present but not used by this edition

These are read by code compiled into the binary but are not reachable through
the `/v1` routes or the MCP surface. Setting them has no effect here; they are
listed so the set is complete rather than mysterious:

`SEAM_API_CORS_ORIGINS`, `SEAM_API_TREE_ROOT`, `SEAM_API_TREE_MAX_DEPTH`,
`SEAM_API_TREE_MAX_ENTRIES`, `SEAM_API_ALLOW_BENCHMARK_HOLDOUT`,
`SEAM_API_CONFIRM_HOLDOUT`, `SEAM_CHAT_ALLOWED_HOSTS`, `SEAM_WEBUI_DIR`,
`SEAM_API_RATE_LIMIT_PER_MINUTE`, `SEAM_API_RATE_LIMIT`,
`SEAM_INSTALLER_USER_PATH`, `SEAM_SURFACE_DIR`,
`SEAM_SURFACE_MAX_PAYLOAD_BYTES`, `SEAM_DERIVED_FACTS_POLICY`,
`SEAM_SENTENCE_FACT_MODEL`, `SEAM_SENTENCE_FACT_NUM_PREDICT`,
`SEAM_API_ALLOW_REMOTE_NO_TOKEN`, `SEAM_API_ALLOW_INSECURE_REMOTE`,
`SEAM_API_ALLOW_PROCESS_LOCAL_RATE_LIMIT`, and the `SEAM_JSPACE_*` family.

The three `SEAM_API_ALLOW_*` names are worth calling out: they relax authentication and transport checks on the full runtime's REST server, which this edition does not start. They cannot be used to weaken the `/v1` surface's bearer-token requirement.

### A reasonable production start

```bash
export SEAM_API_TOKEN_FILE=/run/secrets/seam-api-token
export SEAM_SERVER_DB=/var/lib/seam/seam.db
export SEAM_SELFHOST_HOST=127.0.0.1          # behind a TLS reverse proxy
export SEAM_RETRIEVAL_PROFILE=compact        # or broad, for a frontier model
# optional semantic embeddings:
# export SEAM_EMBEDDING_PROVIDER=openai
# export OPENAI_API_KEY=sk-...
seam-self-host
```

The node prints its resolved configuration at startup — entitlement state,
embedding provider, and vector backend — so you can confirm what it actually
picked up.

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

Outside a writable container layout, `seam-mcp` needs no arguments: it defaults
to `${XDG_DATA_HOME:-~/.local/share}/seam/seam.db`. An explicit `--db` wins
over the environment. Without the flag, `SEAM_SERVER_DB` wins over
`SEAM_DB_PATH`; the user-data default applies only when neither contains a
path.

The MCP server exposes the same three operations as the HTTP surface —
`seam_remember`, `seam_recall`, and `seam_context` — talking directly to the
local database instead of over the network. Run it only for a trusted local
client and protect the database with operating-system permissions.
