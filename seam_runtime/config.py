"""Declarative registry of every operator-settable SEAM environment variable.

This module is the single source of truth for what is configurable, what each
knob means, what values it accepts, and which knobs carry credentials. The
dashboard Settings screen renders itself from `SETTINGS` rather than hardcoding
inputs, so a new env var becomes settable by adding one row here.

Three rules shape the design:

1. **Process env always wins.** Persisted values are applied only to names that
   are not already set in the environment, so `SEAM_X=1 seam-dash` keeps
   behaving the way every other CLI does and CI stays reproducible. Values
   this module itself promotes from the settings file retain their provenance,
   so a later Save/Reload can refresh them without mistaking them for shell
   overrides.
2. **Secrets never touch the working tree.** Persistence goes to a private
   per-user file (mode 0600) under the XDG config dir, never the repo-root
   `.env`, because a settings page that writes API keys into the checkout is
   one `git add -A` away from publishing them.
3. **Validation is borrowed, not reimplemented.** Retrieval knobs defer to
   `retrieval.coerce_flag_value` and the policy vocabularies defer to their
   owning modules, so the UI cannot accept a value the runtime would reject.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Setting",
    "SETTINGS",
    "SETTINGS_BY_NAME",
    "GROUPS",
    "config_path",
    "load_persisted",
    "save_persisted",
    "apply_persisted_to_environ",
    "effective_value",
    "value_source",
    "validate",
    "mask",
    "is_env_name",
]

#: What the OS accepts as an environment variable name. Also the gate on
#: anything read back out of the persisted file, which operators hand-edit.
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Values copied into the real process environment by
# `apply_persisted_to_environ`. Tracking their source is what lets
# `effective_value` distinguish a launch-time shell override (which must keep
# winning) from our own stale copy of a settings-file value (which may be
# changed while the TUI is running). Custom mappings passed by tests/callers
# are deliberately not tracked.
_PERSISTED_ENV_VALUES: dict[str, tuple[Path, str]] = {}


# ---------------------------------------------------------------------------
# Registry types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Setting:
    """One operator-settable environment variable."""

    name: str
    group: str
    kind: str = "str"  # str | int | float | bool | path | enum | csv
    default: str = ""
    secret: bool = False
    description: str = ""
    placeholder: str = ""
    choices: tuple[str, ...] = ()
    #: Name of a `RetrievalFlags` field to validate against, when applicable.
    flag_key: str = ""
    #: Inclusive numeric bounds for int/float kinds.
    minimum: float | None = None
    maximum: float | None = None
    #: Lazily-resolved choice provider, used where the vocabulary is owned by
    #: another module and must not be duplicated here.
    choices_loader: str = field(default="", compare=False)

    def resolved_choices(self) -> tuple[str, ...]:
        """Return the accepted values, loading from the owning module if needed."""
        if self.choices:
            return self.choices
        if not self.choices_loader:
            return ()
        return _load_choices(self.choices_loader)


def _load_choices(loader: str) -> tuple[str, ...]:
    """Resolve a ``module:attribute`` vocabulary reference to a sorted tuple.

    Imported lazily and failure-tolerant: a settings screen that cannot import
    an optional subsystem should degrade to a free-text field, never crash.
    """
    module_name, _, attribute = loader.partition(":")
    try:
        module = __import__(f"seam_runtime.{module_name}", fromlist=[attribute])
        values = getattr(module, attribute)
    except Exception:  # pragma: no cover - optional/omitted subsystem
        return ()
    try:
        return tuple(sorted(str(value) for value in values))
    except TypeError:  # pragma: no cover - not iterable
        return ()


# ---------------------------------------------------------------------------
# Group ordering (drives Settings screen section order)
# ---------------------------------------------------------------------------

GROUPS: tuple[str, ...] = (
    "Provider Keys",
    "Chat",
    "Embedding",
    "Storage",
    "Retrieval",
    "Policies",
    "Local Models",
    "API & Server",
    "Surface",
    "J-Space",
    "Dashboard",
    "Benchmarks",
    "Runtime",
    "Custom Keys",
)


_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off", ""}


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

SETTINGS: tuple[Setting, ...] = (
    # -- Provider Keys ------------------------------------------------------
    Setting("OPENAI_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="sk-...",
            description="OpenAI key. Also the default source for the OpenAI embedding provider."),
    Setting("ANTHROPIC_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="sk-ant-...",
            description="Anthropic key, used by the benchmark judge extra."),
    Setting("GEMINI_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="AIza...", description="Google Gemini key."),
    Setting("OPENROUTER_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="sk-or-...", description="OpenRouter key for the chat panel."),
    Setting("GITHUB_TOKEN", "Provider Keys", "str", secret=True,
            placeholder="ghp_...", description="GitHub token for release and registry tooling."),
    Setting("GH_TOKEN", "Provider Keys", "str", secret=True,
            placeholder="ghp_...", description="Alternate GitHub token name honoured by the gh CLI."),
    Setting("GROQ_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="gsk_...", description="Groq inference key."),
    Setting("DEEPSEEK_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="sk-...", description="DeepSeek key."),
    Setting("MISTRAL_API_KEY", "Provider Keys", "str", secret=True,
            description="Mistral key."),
    Setting("XAI_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="xai-...", description="xAI / Grok key."),
    Setting("TOGETHER_API_KEY", "Provider Keys", "str", secret=True,
            description="Together AI key."),
    Setting("FIREWORKS_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="fw_...", description="Fireworks AI key."),
    Setting("COHERE_API_KEY", "Provider Keys", "str", secret=True,
            description="Cohere key, for generation or rerank."),
    Setting("VOYAGE_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="pa-...", description="Voyage AI embedding key."),
    Setting("PERPLEXITY_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="pplx-...", description="Perplexity key."),
    Setting("HF_TOKEN", "Provider Keys", "str", secret=True,
            placeholder="hf_...", description="Hugging Face token, used by the local J-lens and sbert extras."),
    Setting("REPLICATE_API_TOKEN", "Provider Keys", "str", secret=True,
            placeholder="r8_...", description="Replicate token."),
    Setting("CEREBRAS_API_KEY", "Provider Keys", "str", secret=True,
            description="Cerebras inference key."),
    Setting("NVIDIA_API_KEY", "Provider Keys", "str", secret=True,
            placeholder="nvapi-...", description="NVIDIA NIM key."),
    Setting("AZURE_OPENAI_API_KEY", "Provider Keys", "str", secret=True,
            description="Azure OpenAI key. Pair with the endpoint below."),
    Setting("AZURE_OPENAI_ENDPOINT", "Provider Keys", "str",
            placeholder="https://<resource>.openai.azure.com",
            description="Azure OpenAI resource endpoint."),
    Setting("AWS_ACCESS_KEY_ID", "Provider Keys", "str", secret=True,
            description="AWS key id, for Bedrock."),
    Setting("AWS_SECRET_ACCESS_KEY", "Provider Keys", "str", secret=True,
            description="AWS secret key, for Bedrock."),
    Setting("AWS_REGION", "Provider Keys", "str", placeholder="us-east-1",
            description="AWS region for Bedrock calls."),
    Setting("GOOGLE_APPLICATION_CREDENTIALS", "Provider Keys", "path",
            description="Path to a Google service-account JSON, for Vertex AI."),

    # -- Chat ---------------------------------------------------------------
    Setting("SEAM_CHAT_API_KEY", "Chat", "str", secret=True,
            placeholder="falls back to OPENAI_API_KEY",
            description="Key for the dashboard chat client. Falls back to OPENAI_API_KEY."),
    Setting("SEAM_CHAT_BASE_URL", "Chat", "str", default="https://api.openai.com/v1",
            placeholder="https://api.openai.com/v1",
            description="OpenAI-compatible chat endpoint base URL."),
    Setting("SEAM_CHAT_MODEL", "Chat", "str", default="gpt-4o-mini",
            placeholder="gpt-4o-mini", description="Default chat model."),
    Setting("SEAM_CHAT_MODELS", "Chat", "csv",
            placeholder="gpt-4o-mini,qwen/qwen3-coder",
            description="Comma-separated model list offered in the chat model picker."),
    Setting("SEAM_CHAT_ALLOWED_HOSTS", "Chat", "csv",
            placeholder="api.openai.com,openrouter.ai",
            description="Comma-separated host allowlist for chat egress. Empty allows the base URL host."),
    Setting("SEAM_CHAT_TRANSCRIPT_DIR", "Chat", "path", default=".seam/chat_transcripts",
            placeholder=".seam/chat_transcripts",
            description="Directory for saved chat transcripts."),

    # -- Embedding ----------------------------------------------------------
    Setting("SEAM_EMBEDDING_PROVIDER", "Embedding", "enum", default="hash",
            choices=("hash", "openai"),
            description="Embedding backend. 'hash' is deterministic and offline; 'openai' calls the API."),
    Setting("SEAM_EMBEDDING_MODEL", "Embedding", "str", default="text-embedding-3-small",
            placeholder="text-embedding-3-small", description="Embedding model name."),
    Setting("SEAM_EMBEDDING_BASE_URL", "Embedding", "str",
            default="https://api.openai.com/v1/embeddings",
            description="Embedding endpoint URL."),
    Setting("SEAM_EMBEDDING_API_KEY_ENV", "Embedding", "str", default="OPENAI_API_KEY",
            placeholder="OPENAI_API_KEY",
            description="Name of the env var holding the embedding key (indirection, not the key itself)."),
    Setting("SEAM_EMBEDDING_TIMEOUT_S", "Embedding", "float", default="30",
            minimum=0.1, maximum=600, description="Embedding request timeout in seconds."),
    Setting("SEAM_EMBEDDING_DIMENSIONS", "Embedding", "int",
            placeholder="blank = model default", minimum=1, maximum=8192,
            description="Explicit embedding dimensionality. Blank uses the model default."),

    # -- Storage ------------------------------------------------------------
    Setting("SEAM_DB_PATH", "Storage", "path",
            placeholder="~/.seam/seam.db", description="Runtime SQLite database path."),
    Setting("SEAM_SERVER_DB", "Storage", "path",
            placeholder="falls back to SEAM_DB_PATH",
            description="Database the REST server opens, when it differs from the CLI default."),
    Setting("SEAM_DB_POOL_SIZE", "Storage", "int", default="5", minimum=1, maximum=256,
            description="SQLite connection pool size."),
    Setting("SEAM_DB_POOL_TIMEOUT", "Storage", "int", default="300", minimum=1,
            description="Idle timeout in seconds before a pooled connection is retired."),
    # The placeholder deliberately omits a password segment: a `user:pass@`
    # example trips the repo's own dsn_password secret scan, and a placeholder
    # is not worth teaching the gate to ignore credential-shaped DSNs.
    Setting("SEAM_PGVECTOR_DSN", "Storage", "str", secret=True,
            placeholder="postgresql://user@host:5432/db",
            description="pgvector DSN. Credential-bearing; stored masked and never logged."),
    Setting("SEAM_PGVECTOR_TABLE", "Storage", "str", default="seam_vector_index",
            description="Table name for the pgvector index."),
    Setting("SEAM_PGVECTOR_PORT", "Storage", "int",
            placeholder="5432", minimum=1, maximum=65535,
            description="pgvector port used when composing a DSN from parts."),

    # -- Retrieval ----------------------------------------------------------
    Setting("SEAM_RETRIEVAL_PROFILE", "Retrieval", "enum",
            choices=("", "compact", "broad"),
            description="Answerer-tier preset. 'compact' = (top_k 100, budget 8000); "
                        "'broad' = (300, 60000). Explicit knobs below override it."),
    Setting("SEAM_RETRIEVAL_TOP_K", "Retrieval", "int", placeholder="100", minimum=1,
            description="Candidates retrieved before fusion. Overrides the profile."),
    Setting("SEAM_RETRIEVAL_CONTEXT_BUDGET", "Retrieval", "int", placeholder="8000", minimum=1,
            description="Token budget for assembled context. Overrides the profile."),
    Setting("SEAM_RETRIEVAL_RRF", "Retrieval", "bool",
            description="Use reciprocal-rank fusion instead of weighted fusion."),
    Setting("SEAM_RETRIEVAL_RRF_K", "Retrieval", "int", placeholder="60", minimum=1,
            flag_key="rrf_k", description="RRF k constant. Must be positive."),
    Setting("SEAM_RETRIEVAL_LEG_WEIGHTS", "Retrieval", "str",
            placeholder="graph=0.3,vector=1.0",
            description="Per-leg fusion weights. Malformed specs are rejected whole, not partially applied."),
    Setting("SEAM_RETRIEVAL_BM25_ALL", "Retrieval", "bool",
            description="Run BM25 across all record kinds rather than the default subset."),
    Setting("SEAM_RETRIEVAL_ENTITY_GROUNDED", "Retrieval", "bool",
            description="Enable entity-grounded scoring."),
    Setting("SEAM_RETRIEVAL_SCOPED_VECTORS", "Retrieval", "bool",
            description="Restrict the vector leg to the active scope."),
    Setting("SEAM_RETRIEVAL_SEMANTIC_ZERO", "Retrieval", "bool",
            description="Skip the vector leg when the semantic score is zero."),
    Setting("SEAM_GRAPH_SEMANTIC_SEEDS", "Retrieval", "int", minimum=0, maximum=128,
            flag_key="graph_semantic_seeds",
            description="Number of semantic seed nodes for graph expansion (0-128)."),
    Setting("SEAM_GRAPH_SEMANTIC_MIN_SCORE", "Retrieval", "float", minimum=-1.0, maximum=1.0,
            flag_key="graph_semantic_min_score",
            description="Minimum similarity for a semantic graph seed (-1.0 to 1.0)."),

    # -- Policies -----------------------------------------------------------
    Setting("SEAM_CONVERSATION_ADAPTER", "Policies", "enum",
            choices_loader="conversation:CONVERSATION_ADAPTERS",
            flag_key="conversation_adapter", description="Conversation ingest adapter."),
    Setting("SEAM_INFERENCE_POLICY", "Policies", "enum",
            choices_loader="conversation:INFERENCE_POLICIES",
            flag_key="inference_policy", description="Inference policy applied during retrieval."),
    Setting("SEAM_TEMPORAL_POLICY", "Policies", "enum",
            choices_loader="conversation:TEMPORAL_POLICIES",
            flag_key="temporal_policy", description="Temporal reasoning policy."),
    Setting("SEAM_ANSWER_CONTRACT", "Policies", "enum",
            choices_loader="conversation:ANSWER_CONTRACTS",
            flag_key="answer_contract", description="Answer contract enforced on generated answers."),
    Setting("SEAM_COUNT_CONTEXT_POLICY", "Policies", "enum",
            choices_loader="event_count_context:EVENT_COUNT_POLICIES",
            flag_key="count_context_policy", description="Event-count context policy."),
    Setting("SEAM_DERIVED_FACTS_POLICY", "Policies", "enum",
            choices_loader="derived_fact_context:DERIVED_FACTS_POLICIES",
            default="off", description="Derived-facts context policy."),
    Setting("SEAM_NL_EXTRACTOR", "Policies", "str",
            placeholder="blank = default extractor",
            description="Natural-language extractor selection."),
    Setting("SEAM_NL_REGEX_ENRICH", "Policies", "bool",
            description="Enable regex enrichment alongside the NL extractor."),

    # -- Local Models -------------------------------------------------------
    Setting("SEAM_OLLAMA_HOST", "Local Models", "str", default="http://127.0.0.1:11434",
            description="Ollama server URL."),
    Setting("SEAM_OLLAMA_MODEL", "Local Models", "str", default="qwen2.5:3b",
            description="Ollama model tag."),
    Setting("SEAM_OLLAMA_MODEL_DIGEST", "Local Models", "str",
            placeholder="sha256:...",
            description="Pinned Ollama model digest for reproducibility."),
    Setting("SEAM_OLLAMA_TIMEOUT_S", "Local Models", "float", default="300", minimum=1,
            description="Ollama request timeout in seconds."),
    Setting("SEAM_OLLAMA_NUM_PREDICT", "Local Models", "int", default="256", minimum=1,
            description="Ollama max tokens to predict."),
    Setting("SEAM_SENTENCE_FACT_MODEL", "Local Models", "str",
            description="Model used for sentence-grounded fact extraction."),
    Setting("SEAM_SENTENCE_FACT_NUM_PREDICT", "Local Models", "int", default="512", minimum=1,
            description="Max tokens for sentence-fact extraction."),

    # -- API & Server -------------------------------------------------------
    Setting("SEAM_API_TOKEN", "API & Server", "str", secret=True,
            placeholder="bearer token",
            description="Legacy/shared bearer token required by the REST API. Mandatory for remote binds."),
    Setting("SEAM_API_PRINCIPAL", "API & Server", "str",
            placeholder="stable caller subject",
            description="Optional subject bound to SEAM_API_TOKEN for in-process principal mode."),
    Setting("SEAM_API_PUBLIC_ID_KEY", "API & Server", "str", secret=True,
            placeholder="32+ byte stable secret",
            description="Stable HMAC key required for opaque IDs in principal mode."),
    Setting("SEAM_SERVER_HOST", "API & Server", "str", default="127.0.0.1",
            description="Bind address for the REST server."),
    Setting("SEAM_SERVER_WORKERS", "API & Server", "int", default="1", minimum=1,
            description="Server worker count. Note: >1 makes process-local rate limiting unsound."),
    Setting("SEAM_API_RATE_LIMIT_PER_MINUTE", "API & Server", "int", default="0", minimum=0,
            description="Requests per minute per key. 0 disables rate limiting."),
    Setting("SEAM_API_RATE_LIMIT", "API & Server", "int", minimum=0,
            description="Legacy alias for the per-minute rate limit."),
    Setting("SEAM_API_RATE_LIMIT_MAX_KEYS", "API & Server", "int", default="10000", minimum=1,
            description="Maximum tracked rate-limit keys before eviction."),
    Setting("SEAM_API_MAX_BODY_BYTES", "API & Server", "int", default="5000000", minimum=1,
            description="Maximum accepted request body size in bytes."),
    Setting("SEAM_CHAT_MAX_RESPONSE_BYTES", "API & Server", "int", default="5000000", minimum=1,
            description="Maximum accepted chat-provider response size in bytes."),
    Setting("SEAM_API_CORS_ORIGINS", "API & Server", "csv",
            placeholder="https://example.com",
            description="Comma-separated CORS origin allowlist."),
    Setting("SEAM_API_TREE_ROOT", "API & Server", "path",
            description="Root directory exposed by the /tree endpoint."),
    Setting("SEAM_API_TREE_MAX_DEPTH", "API & Server", "int", default="4", minimum=1,
            description="Maximum /tree recursion depth."),
    Setting("SEAM_API_TREE_MAX_ENTRIES", "API & Server", "int", default="2000", minimum=1,
            description="Maximum /tree entries returned."),
    Setting("SEAM_API_ALLOW_REMOTE_NO_TOKEN", "API & Server", "bool",
            description="DANGEROUS. Permit a remote bind with no API token."),
    Setting("SEAM_API_ALLOW_INSECURE_REMOTE", "API & Server", "bool",
            description="DANGEROUS. Permit a token-bearing remote bind without TLS."),
    Setting("SEAM_API_ALLOW_PROCESS_LOCAL_RATE_LIMIT", "API & Server", "bool",
            description="Permit process-local rate limiting with multiple workers (limits become per-worker)."),
    Setting("SEAM_API_ALLOW_BENCHMARK_HOLDOUT", "API & Server", "bool",
            description="Allow holdout benchmark runs through the API."),
    Setting("SEAM_API_CONFIRM_HOLDOUT", "API & Server", "bool",
            description="Confirm holdout execution, required alongside the allow flag."),
    Setting("SEAM_SHUTDOWN_TIMEOUT", "API & Server", "float", default="30", minimum=0,
            description="Graceful shutdown timeout in seconds."),
    Setting("SEAM_MCP_MAX_LINE_BYTES", "API & Server", "int", minimum=1,
            description="Maximum bytes per MCP stdio line."),

    # -- Surface ------------------------------------------------------------
    Setting("SEAM_SURFACE_DIR", "Surface", "path", description="Surface artifact directory."),
    Setting("SEAM_SURFACE_ROOT", "Surface", "path",
            placeholder="defaults to the database directory",
            description="Root under which surface artifacts are resolved."),
    Setting("SEAM_SURFACE_MODE", "Surface", "enum", default="rgb24",
            choices=("rgb24", "bw1", "rgba32", "rgba64"),
            description="Surface encoding mode."),
    Setting("SEAM_SURFACE_MAX_PAYLOAD_BYTES", "Surface", "int", minimum=1,
            description="Maximum surface payload size in bytes."),

    # -- J-Space ------------------------------------------------------------
    Setting("SEAM_JSPACE_BACKEND", "J-Space", "enum", default="off",
            choices=("off", "local", "remote"),
            description="J-lens backend. Off by default; no model or network dependency."),
    Setting("SEAM_JSPACE_MODEL", "J-Space", "str", default="Qwen/Qwen2.5-0.5B-Instruct",
            description="Hugging Face model id for the local J-lens."),
    Setting("SEAM_JSPACE_REVISION", "J-Space", "str", default="main",
            description="Pinned model revision."),
    Setting("SEAM_JSPACE_MODEL_SHA256", "J-Space", "str",
            description="Expected model artifact digest; verified before load."),
    Setting("SEAM_JSPACE_MODEL_MANIFEST", "J-Space", "path",
            description="Path to the model manifest."),
    Setting("SEAM_JSPACE_LENS_ARTIFACT", "J-Space", "path", description="Path to the lens artifact."),
    Setting("SEAM_JSPACE_LENS_SHA256", "J-Space", "str", description="Expected lens artifact digest."),
    Setting("SEAM_JSPACE_LOCAL_ANALYZER", "J-Space", "str", description="Local analyzer reference."),
    Setting("SEAM_JSPACE_LOCAL_ALLOW_DOWNLOAD", "J-Space", "bool",
            description="Permit the local backend to download model weights."),
    Setting("SEAM_JSPACE_REMOTE_URL", "J-Space", "str", description="Remote J-lens worker endpoint."),
    Setting("SEAM_JSPACE_REMOTE_TOKEN", "J-Space", "str", secret=True,
            description="Bearer token for the remote J-lens worker."),
    Setting("SEAM_JSPACE_REMOTE_ALLOWED_HOSTS", "J-Space", "csv",
            description="Comma-separated host allowlist for the remote worker."),
    Setting("SEAM_JSPACE_REMOTE_PINNED_IPS", "J-Space", "csv",
            description="Comma-separated pinned IPs for the remote worker."),
    Setting("SEAM_JSPACE_REMOTE_TIMEOUT", "J-Space", "int", default="30", minimum=1, maximum=30,
            description="Remote worker timeout in seconds. Clamped to 30."),

    # -- Dashboard ----------------------------------------------------------
    Setting("SEAM_DASHBOARD_ALLOW_SHELL", "Dashboard", "bool",
            description="Enable the dashboard shell mode. Off by default; enables local command execution."),
    Setting("SEAM_SHELL_TIMEOUT_SECONDS", "Dashboard", "float", minimum=1,
            description="Timeout for dashboard shell commands."),
    Setting("SEAM_TUI_MOTION", "Dashboard", "enum", default="full",
            choices=("full", "reduced", "off"),
            description="TUI motion: full type-on and cursor blink, reduced static lockup, or off."),
    Setting("SEAM_TUI_META_DIGITS", "Dashboard", "enum", default="on",
            choices=("on", "off"),
            description="Also jump tabs on the characters an 'Alt sends Escape' terminal "
                        "emits for alt+1..alt+9 (¡™£¢∞§¶•ª). Set off to type them literally."),
    Setting("SEAM_WEBUI_DIR", "Dashboard", "path",
            description="Override directory for the browser dashboard assets."),

    # -- Benchmarks ---------------------------------------------------------
    Setting("SEAM_BENCH_RECORD_DIR", "Benchmarks", "path", default="benchmarks/runs/records",
            description="Directory for recorded benchmark runs."),
    Setting("SEAM_BENCHMARK_SIGNING_KEY", "Benchmarks", "str", secret=True,
            description="HMAC key used to sign benchmark integrity records."),

    # -- Runtime ------------------------------------------------------------
    Setting("SEAM_AGENT", "Runtime", "str",
            placeholder="agent identifier",
            description="Default agent id attributed to writes from this process."),
    Setting("SEAM_LOCAL_ENV", "Runtime", "path",
            placeholder="path to a gitignored local .env",
            description="Path to an additional local env file loaded at startup."),
    Setting("SEAM_INSTALLER_USER_PATH", "Runtime", "str",
            description="Windows installer PATH bookkeeping. Set by the installer; rarely edited by hand."),
)

SETTINGS_BY_NAME: dict[str, Setting] = {s.name: s for s in SETTINGS}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def config_path() -> Path:
    """Return the private per-user settings file path.

    Honours ``XDG_CONFIG_HOME``. Deliberately outside any repository checkout:
    this file holds API keys and credential-bearing DSNs.
    """
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "seam" / "seam.env"


def _parse_env_text(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines, ignoring blanks and ``#`` comments.

    A leading ``export`` is stripped. The file lives at a path operators
    already keep shell env files at and hand-edit, so ``export FOO=bar`` is
    the expected idiom, not an edge case. Without this the key parses as the
    name ``export FOO``, which never reaches the environment as ``FOO`` --
    the variable silently goes missing instead of failing loudly.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_persisted(path: Path | None = None) -> dict[str, str]:
    """Read persisted settings. A missing or unreadable file yields ``{}``."""
    target = path or config_path()
    try:
        return _parse_env_text(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def save_persisted(values: Mapping[str, str], path: Path | None = None) -> Path:
    """Write settings atomically at mode 0600 and return the path.

    The temp file is created inside the destination directory so the rename is
    atomic, and its mode is set *before* any secret is written to it -- writing
    first and chmod-ing after would leave a world-readable window containing
    live API keys.
    """
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(stat.S_IRWXU)
    except OSError:  # pragma: no cover - non-POSIX or foreign-owned dir
        pass

    lines = [
        "# SEAM settings, written by the dashboard Settings screen.",
        "# Values already present in the environment take precedence over this file.",
        "# Mode 0600: this file can contain API keys and credential-bearing DSNs.",
        "",
    ]
    for name in sorted(values):
        value = values[name]
        if value == "":
            continue
        lines.append(f"{name}={value}")
    payload = "\n".join(lines) + "\n"

    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(target.parent),
        prefix=".seam-env-", suffix=".tmp", delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(tmp_path, target)
    except BaseException:
        handle.close()
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def apply_persisted_to_environ(
    environ: dict[str, str] | None = None,
    path: Path | None = None,
) -> list[str]:
    """Apply persisted settings to the process environment, returning applied names.

    Names already present in the environment are left untouched, so an explicit
    ``SEAM_X=1 seam-dash`` and CI configuration both keep winning over whatever
    the Settings screen last saved. Values previously injected by this function
    are refreshed (or removed) from the latest file because they are not true
    process overrides.
    """
    env = os.environ if environ is None else environ
    values = load_persisted(path)
    applied: list[str] = []
    if env is os.environ:
        source_path = (path or config_path()).expanduser().resolve()
        for name, (tracked_path, tracked_value) in tuple(_PERSISTED_ENV_VALUES.items()):
            current = os.environ.get(name)
            if current != tracked_value:
                # Something outside this module changed or removed the value;
                # from now on treat any replacement as an explicit override.
                _PERSISTED_ENV_VALUES.pop(name, None)
                continue
            if tracked_path != source_path:
                os.environ.pop(name, None)
                _PERSISTED_ENV_VALUES.pop(name, None)
                continue
            replacement = values.get(name, "")
            if not replacement or not is_env_name(name):
                os.environ.pop(name, None)
                _PERSISTED_ENV_VALUES.pop(name, None)
                applied.append(name)
                continue
            if replacement != tracked_value:
                os.environ[name] = replacement
                _PERSISTED_ENV_VALUES[name] = (source_path, replacement)
                applied.append(name)

    for name, value in values.items():
        if name in env or value == "" or not is_env_name(name):
            continue
        env[name] = value
        applied.append(name)
        if env is os.environ:
            _PERSISTED_ENV_VALUES[name] = (source_path, value)
    return applied


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def effective_value(name: str, path: Path | None = None) -> str:
    """Return the value the runtime would actually see for ``name``."""
    if name in os.environ:
        source_path = (path or config_path()).expanduser().resolve()
        tracked = _PERSISTED_ENV_VALUES.get(name)
        if tracked is None or tracked[0] != source_path or os.environ[name] != tracked[1]:
            # A real process override always wins. If a tracked value was
            # changed externally, forget its file provenance permanently.
            if tracked is not None and os.environ[name] != tracked[1]:
                _PERSISTED_ENV_VALUES.pop(name, None)
            return os.environ[name]
    persisted = load_persisted(path).get(name)
    if persisted is not None:
        return persisted
    setting = SETTINGS_BY_NAME.get(name)
    return setting.default if setting else ""


def value_source(name: str, path: Path | None = None) -> str:
    """Return where the effective value comes from: env, file, default, or unset."""
    if name in os.environ:
        source_path = (path or config_path()).expanduser().resolve()
        tracked = _PERSISTED_ENV_VALUES.get(name)
        if tracked is None or tracked[0] != source_path or os.environ[name] != tracked[1]:
            if tracked is not None and os.environ[name] != tracked[1]:
                _PERSISTED_ENV_VALUES.pop(name, None)
            return "env"
    if name in load_persisted(path):
        return "file"
    setting = SETTINGS_BY_NAME.get(name)
    if setting and setting.default:
        return "default"
    return "unset"


def mask(value: str) -> str:
    """Render a secret for display without revealing it."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 8}{value[-2:]}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(setting: Setting, raw: str) -> tuple[bool, str]:
    """Validate ``raw`` for ``setting``; return ``(ok, message)``.

    An empty value is always valid: it means "unset this knob and take the
    runtime default", which every var in the registry tolerates.
    """
    raw = raw.strip()
    if raw == "":
        return True, ""

    kind = setting.kind

    if kind == "bool":
        if raw.lower() in _TRUTHY or raw.lower() in _FALSEY:
            return True, ""
        return False, "expected one of: 1/0, true/false, yes/no, on/off"

    if kind in ("int", "float"):
        try:
            number: float = int(raw) if kind == "int" else float(raw)
        except ValueError:
            return False, f"expected {'an integer' if kind == 'int' else 'a number'}"
        if setting.minimum is not None and number < setting.minimum:
            return False, f"must be >= {setting.minimum:g}"
        if setting.maximum is not None and number > setting.maximum:
            return False, f"must be <= {setting.maximum:g}"
        return _validate_against_flag(setting, number)

    if kind == "enum":
        choices = setting.resolved_choices()
        if choices and raw not in choices:
            return False, f"expected one of: {', '.join(c for c in choices if c)}"
        return _validate_against_flag(setting, raw)

    if kind == "path":
        if "\x00" in raw:
            return False, "path contains a null byte"
        return True, ""

    return _validate_against_flag(setting, raw)


def _validate_against_flag(setting: Setting, value: object) -> tuple[bool, str]:
    """Defer to the runtime's own flag validation where one exists."""
    if not setting.flag_key:
        return True, ""
    try:
        from .retrieval import coerce_flag_value
    except Exception:  # pragma: no cover - retrieval unavailable
        return True, ""
    if coerce_flag_value(setting.flag_key, value) is None:
        return False, "rejected by retrieval flag validation"
    return True, ""


def settings_in_group(group: str) -> tuple[Setting, ...]:
    """Return the registry rows belonging to ``group``, in declaration order."""
    return tuple(s for s in SETTINGS if s.group == group)


def secret_names() -> frozenset[str]:
    """Return the names that must never be logged, echoed, or committed."""
    return frozenset(s.name for s in SETTINGS if s.secret)


#: Names matching this shape are treated as credentials when the operator adds
#: them by hand, so a custom key is masked without anyone having to say so.
_SECRET_HINT = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|DSN|CREDENTIAL)", re.IGNORECASE)


def looks_secret(name: str) -> bool:
    """Return whether a variable name should be treated as credential-bearing."""
    return bool(_SECRET_HINT.search(name))


def is_env_name(name: str) -> bool:
    """Return whether ``name`` is a usable environment variable name."""
    return bool(_ENV_NAME_RE.fullmatch(name))


def valid_custom_name(name: str) -> tuple[bool, str]:
    """Validate an operator-supplied variable name."""
    name = name.strip()
    if not name:
        return False, "name is required"
    if not is_env_name(name):
        return False, "use letters, digits, and underscores only"
    if name in SETTINGS_BY_NAME:
        return False, "already in the registry — edit it in its own section"
    return True, ""


def custom_settings(path: Path | None = None) -> tuple[Setting, ...]:
    """Return synthesized rows for persisted names the registry does not define.

    This is what makes "add your own key" work: anything the operator saves
    under a name SEAM does not ship is still rendered, still masked when it
    looks like a credential, and still editable next launch.
    """
    rows: list[Setting] = []
    for name in sorted(load_persisted(path)):
        if name in SETTINGS_BY_NAME:
            continue
        # The file is hand-editable, so it is an untrusted source of names.
        # The add-a-key UI validates, but nothing validated what was already
        # on disk; a name that is not a legal env var name cannot be applied
        # to the environment anyway, so rendering a row for it is a lie.
        if not is_env_name(name):
            continue
        rows.append(
            Setting(
                name=name,
                group="Custom Keys",
                kind="str",
                secret=looks_secret(name),
                description="Added by you. Exported to the environment at startup.",
            )
        )
    return tuple(rows)


def iter_settings(names: Iterable[str] | None = None) -> Iterable[Setting]:
    """Iterate registry rows, optionally restricted to ``names``."""
    if names is None:
        yield from SETTINGS
        return
    for name in names:
        setting = SETTINGS_BY_NAME.get(name)
        if setting is not None:
            yield setting
