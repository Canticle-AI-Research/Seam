"""Opaque API-only entrypoint for the proprietary compiled self-host edition."""

from __future__ import annotations

import argparse
import hmac
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime import SeamRuntime
from .selfhost_entitlement import REQUIRED_FEATURE, VerifiedEntitlement, verify_entitlement
from .server import (
    BodySizeLimitMiddleware,
    RateLimiter,
    ReadinessCache,
    ShutdownMiddleware,
    ShutdownState,
    _client_key,
    _max_body_bytes_from_env,
    _rate_limit_max_keys_from_env,
)

DEFAULT_PUBLIC_KEY_PATH = Path("/opt/seam/entitlement-public-key.pem")
DEFAULT_ENTITLEMENT_PATH = Path("/run/seam/entitlement.json")
DEFAULT_DB_PATH = Path("/var/lib/seam/seam.db")
LOGGER = logging.getLogger(__name__)


def create_selfhost_app(
    runtime: SeamRuntime,
    entitlement: VerifiedEntitlement | None = None,
    *,
    api_token: str,
    shutdown_state: ShutdownState | None = None,
) -> Any:
    """Create the self-host surface containing only the opaque public ``/v1`` API.

    ``entitlement`` is optional. Self-hosting is granted by BUSL-1.1 without limit
    on scale or users, so an unentitled node runs the full ``/v1`` surface. A
    mounted entitlement identifies a supported deployment; it does not unlock
    capability and its expiry does not withdraw a right the license already grants.
    """
    if not api_token:
        raise RuntimeError("self-host API token is required")
    if entitlement is not None and REQUIRED_FEATURE not in entitlement.features:
        raise RuntimeError(f"self-host entitlement lacks required feature {REQUIRED_FEATURE}")

    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Request
    except ImportError as exc:  # pragma: no cover - build image always includes server deps
        raise RuntimeError("SEAM self-host server dependencies are not installed") from exc

    globals()["Request"] = Request
    from starlette.responses import JSONResponse

    state = shutdown_state or ShutdownState()
    limit = _positive_int_env("SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE", default=120)
    limiter = RateLimiter(limit, max_keys=_rate_limit_max_keys_from_env())
    readiness = ReadinessCache(runtime)
    app = FastAPI(
        title="SEAM Self-Host API",
        version="v1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    app.state.entitlement = entitlement
    app.add_middleware(ShutdownMiddleware, state=state)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=_max_body_bytes_from_env(),
    )

    def guard(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        if not limiter.check(_client_key(request, authorization)):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        expected = f"Bearer {api_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    def rate_limit_only(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        if not limiter.check(_client_key(request, authorization)):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )

    @app.exception_handler(Exception)
    async def unhandled_request_error(_request: Request, exc: Exception) -> Any:
        if _debug_enabled():
            LOGGER.exception("Request failed")
        else:
            LOGGER.error("Request failed: %s", type(exc).__name__)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.api_route(
        "/v1/health",
        methods=["GET", "HEAD"],
        dependencies=[Depends(rate_limit_only)],
    )
    def health() -> Any:
        # Deliberately unauthenticated, so it must not disclose who runs this node.
        payload = {
            "status": "ok",
            "api_version": "v1",
            "edition": "compiled-self-host",
        }
        if not readiness.check():
            payload["status"] = "degraded"
            return JSONResponse(payload, status_code=503)
        return payload

    @app.post("/v1/memories", dependencies=[Depends(guard)])
    def remember_memory(payload: dict[str, object]) -> dict[str, object]:
        from .public_api import PublicAPIInputError, remember

        try:
            return remember(runtime, payload)
        except PublicAPIInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/memories/recall", dependencies=[Depends(guard)])
    def recall_memories(payload: dict[str, object]) -> dict[str, object]:
        from .public_api import PublicAPIInputError, recall

        try:
            return recall(runtime, payload)
        except PublicAPIInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/context", dependencies=[Depends(guard)])
    def build_context(payload: dict[str, object]) -> dict[str, object]:
        from .public_api import PublicAPIInputError, context

        try:
            return context(runtime, payload)
        except PublicAPIInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def create_selfhost_app_from_env(db_path: str | Path | None = None) -> Any:
    """Load the fixed public key, mounted entitlement, token secret, and database."""
    entitlement_path = Path(
        os.environ.get("SEAM_SELFHOST_ENTITLEMENT_PATH", str(DEFAULT_ENTITLEMENT_PATH))
    )
    public_key_path = Path(
        os.environ.get("SEAM_SELFHOST_PUBLIC_KEY_PATH", str(DEFAULT_PUBLIC_KEY_PATH))
    )
    entitlement = _load_optional_entitlement(entitlement_path, public_key_path)
    api_token = _read_required_secret(
        env_name="SEAM_API_TOKEN",
        file_env_name="SEAM_API_TOKEN_FILE",
        default_file=Path("/run/secrets/api_token"),
    )
    resolved_db_path = Path(db_path) if db_path is not None else _default_db_path()
    _configure_embedding_provider()
    _validate_retrieval_profile()
    _validate_vector_backend()
    return create_selfhost_app(
        SeamRuntime(resolved_db_path),
        entitlement,
        api_token=api_token,
    )


def _configure_embedding_provider() -> None:
    """Keep SEAM's own embedder as the default, and fail fast on a keyless API.

    SEAM is local-first: the built-in embedder needs no network, no third-party
    account, and no per-request cost, so a self-hoster who installs the wheel gets
    a node that runs on its own. Sending every memory to an external embedding API
    is an opt-in, not something a free self-host should do by default.

    An operator who does opt in is checked here rather than on the first
    ``remember``, because a 500 per request is a much worse way to learn a key is
    missing.
    """
    provider = str(os.environ.get("SEAM_EMBEDDING_PROVIDER") or "hash").strip().lower()
    supported = {
        "deterministic",
        "hash",
        "local",
        "openai",
        "openai-compatible",
        "sbert",
        "sentence-transformers",
        "st",
    }
    if provider not in supported:
        allowed = ", ".join(
            ("hash", "openai", "openai-compatible", "sentence-transformers")
        )
        raise RuntimeError(
            f"SEAM_EMBEDDING_PROVIDER is not supported; choose one of: {allowed}"
        )
    os.environ["SEAM_EMBEDDING_PROVIDER"] = provider
    if provider in {"hash", "local", "deterministic"}:
        print(f"[seam-selfhost] embeddings: {provider} (built-in)", flush=True)
        return
    if provider in {"sentence-transformers", "st", "sbert"}:
        print(f"[seam-selfhost] embeddings: {provider} (local model)", flush=True)
        return
    api_key_env = os.environ.get("SEAM_EMBEDDING_API_KEY_ENV", "OPENAI_API_KEY")
    if not str(os.environ.get(api_key_env) or "").strip():
        raise RuntimeError(
            f"SEAM_EMBEDDING_PROVIDER is 'openai' but {api_key_env} is empty. "
            f"Set {api_key_env}, or set SEAM_EMBEDDING_PROVIDER=hash to run "
            "without an embedding API."
        )
    print(
        "[seam-selfhost] embeddings: external API "
        f"({os.environ.get('SEAM_EMBEDDING_MODEL', 'text-embedding-3-small')})",
        flush=True,
    )


def _validate_retrieval_profile() -> None:
    raw_profile = str(os.environ.get("SEAM_RETRIEVAL_PROFILE") or "").strip()
    if not raw_profile:
        return
    from .retrieval import RETRIEVAL_PROFILES, resolve_retrieval_profile

    if resolve_retrieval_profile(raw_profile) is None:
        allowed = ", ".join(sorted(RETRIEVAL_PROFILES))
        raise RuntimeError(
            f"SEAM_RETRIEVAL_PROFILE is not recognized; choose one of: {allowed}"
        )


def _validate_vector_backend(
    *,
    attempts: int = 3,
    retry_delay_seconds: float = 2.0,
) -> None:
    """Prove the configured vector backend is usable before serving traffic.

    ``SEAM_PGVECTOR_DSN`` selects the pgvector adapter at query time, so a missing
    driver used to surface as a 500 on the first write rather than as a startup
    failure. The wheel now ships ``psycopg``; this check keeps the failure at
    startup if a deployment somehow lacks it.
    """
    dsn = str(os.environ.get("SEAM_PGVECTOR_DSN") or "").strip()
    if not dsn:
        print("[seam-selfhost] vectors: sqlite", flush=True)
        return
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "SEAM_PGVECTOR_DSN is set but psycopg is not installed; "
            "install seam-self-host[pgvector] or unset SEAM_PGVECTOR_DSN"
        ) from exc
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            with psycopg.connect(dsn, connect_timeout=5) as connection:
                connection.execute("select 1")
        except Exception as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                time.sleep(max(0.0, retry_delay_seconds))
            continue
        print("[seam-selfhost] vectors: pgvector", flush=True)
        return
    error_name = type(last_error).__name__ if last_error is not None else "connection error"
    raise RuntimeError(
        "SEAM_PGVECTOR_DSN is invalid or unreachable "
        f"({error_name}); verify the value and database availability"
    ) from last_error


def _load_optional_entitlement(
    entitlement_path: Path,
    public_key_path: Path,
) -> VerifiedEntitlement | None:
    """Return a verified entitlement, or ``None`` when none is mounted.

    Absence is the free self-host path and is not an error. Presence is a
    deliberate act, so a mounted file that fails verification fails CLOSED: a bad
    signature, a foreign product, or a malformed payload is a tamper signal, not a
    downgrade to free. A cryptographically sound but lapsed entitlement is kept and
    reported as inactive rather than rejected, because it gates no capability and
    BUSL-1.1 grants self-hosting regardless of support status.
    """
    if not entitlement_path.exists():
        # flush explicitly: the runtime stage sets no PYTHONUNBUFFERED, so stdout is
        # block-buffered in the compiled binary and this line would never surface.
        print(
            "[seam-selfhost] no entitlement mounted; running unentitled under BUSL-1.1",
            flush=True,
        )
        return None
    entitlement = verify_entitlement(
        entitlement_path,
        public_key_path,
        enforce_validity_window=False,
    )
    state = _entitlement_state_error(entitlement)
    if state is None:
        print(
            f"[seam-selfhost] entitled deployment {entitlement.customer_id} "
            f"({entitlement.entitlement_id}), expires {entitlement.expires_at.isoformat()}",
            flush=True,
        )
    else:
        print(
            f"[seam-selfhost] entitlement {entitlement.entitlement_id} is {state}; "
            "continuing unentitled under BUSL-1.1",
            flush=True,
        )
    return entitlement


def main(argv: list[str] | None = None) -> None:
    """Run one API worker; horizontal scaling must use one writer per database."""
    try:
        _run_selfhost(argv)
    except (OSError, RuntimeError, ValueError) as exc:
        if _debug_enabled():
            raise
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _run_selfhost(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the SEAM self-host memory service")
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: SEAM_SELFHOST_HOST or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=_port_argument,
        default=None,
        help="Bind port (default: SEAM_SELFHOST_PORT or 8765)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Database path (default: SEAM_SERVER_DB, SEAM_DB_PATH, or /var/lib/seam/seam.db)",
    )
    args = parser.parse_args(argv)
    host = args.host or os.environ.get("SEAM_SELFHOST_HOST", "0.0.0.0")
    port = (
        args.port
        if args.port is not None
        else _positive_int_env("SEAM_SELFHOST_PORT", default=8765)
    )
    if args.db is None:
        db_path = str(_default_db_path())
    else:
        db_path = str(args.db).strip()
        if not db_path:
            raise ValueError("--db path must be non-empty")

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - build image always includes uvicorn
        raise RuntimeError("Uvicorn is required for the self-host edition") from exc
    os.environ["SEAM_SERVER_DB"] = db_path
    uvicorn.run(
        create_selfhost_app_from_env(db_path),
        host=host,
        port=port,
        workers=1,
        access_log=False,
        server_header=False,
    )


def _read_required_secret(
    *,
    env_name: str,
    file_env_name: str,
    default_file: Path,
) -> str:
    direct_is_set = env_name in os.environ
    direct = os.environ.get(env_name)
    file_path = Path(os.environ.get(file_env_name, str(default_file)))
    if direct_is_set and not str(direct or "").strip():
        raise RuntimeError(f"{env_name} is set but empty")
    if direct_is_set and file_path.exists():
        raise RuntimeError(f"set only one of {env_name} or {file_env_name}")
    if direct_is_set:
        value = str(direct).strip()
    else:
        try:
            value = file_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"required secret {file_env_name} is unavailable") from exc
    if len(value) < 32:
        raise RuntimeError("self-host API token must contain at least 32 characters")
    return value


def _positive_int_env(name: str, *, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0 or value > 65535:
        raise RuntimeError(f"{name} must be between 1 and 65535")
    return value


def _port_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _default_db_path() -> Path:
    for name in ("SEAM_SERVER_DB", "SEAM_DB_PATH"):
        configured = os.environ.get(name)
        if configured is not None and configured.strip():
            return Path(configured.strip())
    return DEFAULT_DB_PATH


def _debug_enabled() -> bool:
    return os.environ.get("SEAM_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _entitlement_state_error(entitlement: VerifiedEntitlement) -> str | None:
    current = datetime.now(timezone.utc)
    if current < entitlement.not_before:
        return "not-active"
    if current >= entitlement.expires_at:
        return "expired"
    return None


if __name__ == "__main__":
    main()
