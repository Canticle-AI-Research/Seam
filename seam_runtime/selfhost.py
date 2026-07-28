"""Opaque API-only entrypoint for the proprietary compiled self-host edition."""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime import SeamRuntime
from .selfhost_entitlement import REQUIRED_FEATURE, VerifiedEntitlement, verify_entitlement
from .server import (
    BodySizeLimitMiddleware,
    RateLimiter,
    ShutdownMiddleware,
    ShutdownState,
    _client_key,
    _max_body_bytes_from_env,
    _rate_limit_max_keys_from_env,
)

DEFAULT_PUBLIC_KEY_PATH = Path("/opt/seam/entitlement-public-key.pem")
DEFAULT_ENTITLEMENT_PATH = Path("/run/seam/entitlement.json")
DEFAULT_DB_PATH = Path("/var/lib/seam/seam.db")


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
    state = shutdown_state or ShutdownState()
    limit = _positive_int_env("SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE", default=120)
    limiter = RateLimiter(limit, max_keys=_rate_limit_max_keys_from_env())
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
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        expected = f"Bearer {api_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    @app.get("/v1/health")
    def health() -> dict[str, object]:
        # Deliberately unauthenticated, so it must not disclose who runs this node.
        return {
            "status": "ok",
            "api_version": "v1",
            "edition": "compiled-self-host",
        }

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


def create_selfhost_app_from_env() -> Any:
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
    db_path = Path(os.environ.get("SEAM_SERVER_DB", str(DEFAULT_DB_PATH)))
    return create_selfhost_app(
        SeamRuntime(db_path),
        entitlement,
        api_token=api_token,
    )


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


def main() -> None:
    """Run one API worker; horizontal scaling must use one writer per database."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - build image always includes uvicorn
        raise RuntimeError("Uvicorn is required for the self-host edition") from exc
    host = os.environ.get("SEAM_SELFHOST_HOST", "0.0.0.0")
    port = _positive_int_env("SEAM_SELFHOST_PORT", default=8765)
    uvicorn.run(
        create_selfhost_app_from_env(),
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
    direct = os.environ.get(env_name)
    file_path = Path(os.environ.get(file_env_name, str(default_file)))
    if direct and file_path.exists():
        raise RuntimeError(f"set only one of {env_name} or {file_env_name}")
    if direct:
        value = direct.strip()
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


def _entitlement_state_error(entitlement: VerifiedEntitlement) -> str | None:
    current = datetime.now(timezone.utc)
    if current < entitlement.not_before:
        return "not-active"
    if current >= entitlement.expires_at:
        return "expired"
    return None


if __name__ == "__main__":
    main()
