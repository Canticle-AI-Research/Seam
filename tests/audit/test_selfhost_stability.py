from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from seam_runtime import selfhost, selfhost_mcp
from seam_runtime.runtime import SeamRuntime
from seam_runtime.selfhost import create_selfhost_app
from seam_runtime.storage import SQLiteStore
from seam_runtime.vector_adapters import PgVectorAdapter


class _HealthRuntime:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.checks = 0

    def check_ready(self) -> None:
        self.checks += 1
        if self.error is not None:
            raise self.error


def test_selfhost_health_is_cached_and_supports_head() -> None:
    runtime = _HealthRuntime()
    client = TestClient(create_selfhost_app(runtime, api_token="a" * 32))

    first = client.get("/v1/health")
    second = client.get("/v1/health")
    head = client.head("/v1/health")

    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert second.status_code == 200
    assert head.status_code == 200
    assert head.content == b""
    assert runtime.checks == 1


def test_selfhost_health_degrades_without_disclosing_backend_details() -> None:
    runtime = _HealthRuntime(error=OSError("private deployment detail"))
    client = TestClient(create_selfhost_app(runtime, api_token="a" * 32))

    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "api_version": "v1",
        "edition": "compiled-self-host",
    }
    assert "private deployment detail" not in response.text


def test_selfhost_returns_generic_json_for_unexpected_request_errors() -> None:
    class _BrokenRuntime(_HealthRuntime):
        def compile_nl(self, *_args: object, **_kwargs: object) -> None:
            raise ZeroDivisionError("private failure")

    client = TestClient(
        create_selfhost_app(_BrokenRuntime(), api_token="a" * 32),
        raise_server_exceptions=False,
    )
    response = client.post(
        "/v1/memories",
        json={"text": "remember this"},
        headers={"Authorization": f"Bearer {'a' * 32}"},
    )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal server error"}
    assert "private failure" not in response.text


def test_selfhost_rate_limit_includes_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE", "1")
    client = TestClient(create_selfhost_app(_HealthRuntime(), api_token="a" * 32))

    assert client.post("/v1/memories", json={"text": "one"}).status_code == 401
    limited = client.post("/v1/memories", json={"text": "two"})

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_selfhost_health_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE", "1")
    client = TestClient(create_selfhost_app(_HealthRuntime(), api_token="a" * 32))

    assert client.get("/v1/health").status_code == 200
    limited = client.head("/v1/health")

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_selfhost_rejects_unknown_embedding_provider_before_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEAM_EMBEDDING_PROVIDER", "totally-bogus")

    with pytest.raises(RuntimeError, match="SEAM_EMBEDDING_PROVIDER is not supported"):
        selfhost._configure_embedding_provider()

    assert "totally-bogus" not in capsys.readouterr().out


def test_selfhost_rejects_unknown_retrieval_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEAM_RETRIEVAL_PROFILE", "braod")

    with pytest.raises(RuntimeError, match="compact, broad|broad, compact"):
        selfhost._validate_retrieval_profile()


def test_pgvector_startup_check_retries_and_never_echoes_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_dsn = "postgresql://" + "user:" + "secret-password@" + "db.invalid/seam"
    calls: list[tuple[str, int]] = []

    class _ConnectionFailure(Exception):
        pass

    def _connect(dsn: str, *, connect_timeout: int) -> object:
        calls.append((dsn, connect_timeout))
        raise _ConnectionFailure(f"could not reach {dsn}")

    monkeypatch.setenv("SEAM_PGVECTOR_DSN", secret_dsn)
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=_connect))

    with pytest.raises(RuntimeError) as captured:
        selfhost._validate_vector_backend(attempts=3, retry_delay_seconds=0)

    assert len(calls) == 3
    assert all(timeout == 5 for _dsn, timeout in calls)
    assert "SEAM_PGVECTOR_DSN" in str(captured.value)
    assert secret_dsn not in str(captured.value)
    assert "secret-password" not in str(captured.value)


def test_pgvector_startup_check_accepts_a_live_connection_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: str) -> None:
            executed.append(statement)

    monkeypatch.setenv("SEAM_PGVECTOR_DSN", "postgresql://seam@db/seam")
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: _Connection()),
    )

    selfhost._validate_vector_backend(attempts=1, retry_delay_seconds=0)

    assert executed == ["select 1"]


def test_pgvector_readiness_establishes_required_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = PgVectorAdapter(
        "postgresql://seam@db/seam",
        SimpleNamespace(name="test-model", dimension=3),
    )
    calls: list[str] = []
    monkeypatch.setattr(adapter, "ensure_schema", lambda: calls.append("schema"))

    adapter.check_ready()

    assert calls == ["schema"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission modes")
def test_sqlite_wal_sidecars_inherit_private_database_mode(tmp_path: Path) -> None:
    parent = tmp_path / "operator-selected-parent"
    parent.mkdir()
    parent.chmod(0o755)
    previous_umask = os.umask(0)
    store: SQLiteStore | None = None
    try:
        store = SQLiteStore(parent / "seam.db")
        with store._pool.checkout() as connection:
            connection.execute("create table sidecar_probe (value text)")
            connection.execute("insert into sidecar_probe values ('private')")
            connection.commit()
            modes = {
                path.name: stat.S_IMODE(path.stat().st_mode)
                for path in parent.iterdir()
            }
    finally:
        if store is not None:
            store.close()
        os.umask(previous_umask)

    assert modes["seam.db"] == 0o600
    assert modes["seam.db-wal"] == 0o600
    assert modes["seam.db-shm"] == 0o600


def test_selfhost_cli_flags_override_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    app = object()

    monkeypatch.setattr(
        selfhost,
        "create_selfhost_app_from_env",
        lambda db_path=None: captured.setdefault("db", db_path) and app,
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda received, **kwargs: captured.update(app=received, **kwargs)),
    )
    monkeypatch.setenv("SEAM_SELFHOST_HOST", "0.0.0.0")
    monkeypatch.setenv("SEAM_SELFHOST_PORT", "8765")
    db_path = tmp_path / "cli.db"

    selfhost._run_selfhost(
        ["--host", "127.0.0.1", "--port", "8830", "--db", str(db_path)]
    )

    assert captured["app"] is app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8830
    assert captured["db"] == str(db_path)
    assert os.environ["SEAM_SERVER_DB"] == str(db_path)


def test_selfhost_startup_errors_are_one_line_unless_debug_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEAM_API_TOKEN", "")
    monkeypatch.delenv("SEAM_DEBUG", raising=False)

    with pytest.raises(SystemExit) as captured:
        selfhost.main([])

    assert captured.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.strip() == "error: SEAM_API_TOKEN is set but empty"
    assert "Traceback" not in stderr


def test_selfhost_help_parses_before_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEAM_SELFHOST_PORT", "not-a-port")
    monkeypatch.setenv("SEAM_SERVER_DB", "")

    with pytest.raises(SystemExit) as captured:
        selfhost.main(["--help"])

    assert captured.value.code == 0
    assert "--host" in capsys.readouterr().out


def test_selfhost_empty_database_argument_is_a_clean_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SEAM_API_TOKEN", "a" * 32)
    monkeypatch.delenv("SEAM_DEBUG", raising=False)

    with pytest.raises(SystemExit) as captured:
        selfhost.main(["--db", ""])

    assert captured.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.strip() == "error: --db path must be non-empty"
    assert "Traceback" not in stderr


def test_selfhost_empty_server_db_falls_back_to_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEAM_SERVER_DB", " ")
    monkeypatch.setenv("SEAM_DB_PATH", "/tmp/selfhost-alias.db")

    assert selfhost._default_db_path() == Path("/tmp/selfhost-alias.db")


def test_mcp_defaults_to_private_xdg_path_outside_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    xdg = tmp_path / "xdg"
    monkeypatch.setattr(
        selfhost_mcp,
        "DEFAULT_DB_PATH",
        tmp_path / "unwritable-system" / "seam.db",
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.delenv("SEAM_SERVER_DB", raising=False)
    monkeypatch.delenv("SEAM_DB_PATH", raising=False)
    monkeypatch.setattr(selfhost_mcp, "run_selfhost_mcp_server", lambda _runtime: None)

    selfhost_mcp._run_mcp([])

    database = xdg / "seam" / "seam.db"
    assert database.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700


def test_mcp_accepts_seam_db_path_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEAM_SERVER_DB", " ")
    monkeypatch.setenv("SEAM_DB_PATH", "/tmp/alias.db")
    assert selfhost_mcp._default_db_path() == "/tmp/alias.db"


def test_mcp_bad_db_path_reports_one_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail(_path: Path) -> None:
        raise PermissionError("private host path")

    monkeypatch.setattr(selfhost_mcp, "SeamRuntime", _fail)
    monkeypatch.delenv("SEAM_DEBUG", raising=False)

    with pytest.raises(SystemExit) as captured:
        selfhost_mcp.main(["--db", "/not-usable/seam.db"])

    assert captured.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.strip() == "error: --db path is unavailable (PermissionError)"
    assert "Traceback" not in stderr


def test_mcp_empty_db_argument_reports_one_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SEAM_DEBUG", raising=False)

    with pytest.raises(SystemExit) as captured:
        selfhost_mcp.main(["--db", " "])

    assert captured.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.strip() == "error: --db path must be non-empty"
    assert "Traceback" not in stderr


def test_sqlite_database_and_new_parent_are_private(tmp_path: Path) -> None:
    database = tmp_path / "private" / "memory.db"

    runtime = SeamRuntime(database)
    runtime.close()

    if os.name != "nt":
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700


def test_runtime_normalizes_user_database_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / "nested" / "memory.db"

    runtime = SeamRuntime("~/nested/memory.db")
    try:
        assert runtime.store.path == str(expected)
        assert runtime.vector_adapter.path == str(expected)
    finally:
        runtime.close()

    assert expected.is_file()
