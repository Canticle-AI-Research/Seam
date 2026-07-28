from __future__ import annotations

import base64
import io
import json
import tarfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from seam_runtime.runtime import SeamRuntime
from seam_runtime.selfhost import (
    _read_required_secret,
    create_selfhost_app,
)
from seam_runtime.selfhost_entitlement import (
    ENTITLEMENT_PRODUCT,
    ENTITLEMENT_SCHEMA,
    EntitlementError,
    canonical_entitlement_payload,
    verify_entitlement,
)
from tools.release.build_selfhost import build_command, project_version, validate_public_key
from tools.release.issue_selfhost_entitlement import main as issue_entitlement
from tools.release.verify_selfhost_artifact import RESERVED_CONTENT_BUDGET, verify_archive

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def _entitlement_files(tmp_path: Path, **changes: object) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_path = tmp_path / "entitlement.pub.pem"
    public_path.write_bytes(
        public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    payload: dict[str, object] = {
        "schema": ENTITLEMENT_SCHEMA,
        "product": ENTITLEMENT_PRODUCT,
        "entitlement_id": "ent_test_001",
        "customer_id": "customer-test",
        "issued_at": "2026-07-01T00:00:00Z",
        "not_before": "2026-07-01T00:00:00Z",
        "expires_at": "2026-08-01T00:00:00Z",
        "features": ["opaque-v1"],
    }
    payload.update(changes)
    signature = private_key.sign(canonical_entitlement_payload(payload))
    envelope = {
        "payload": payload,
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    }
    entitlement_path = tmp_path / "entitlement.json"
    entitlement_path.write_text(json.dumps(envelope), encoding="utf-8")
    return entitlement_path, public_path


def test_entitlement_verifies_and_rejects_tampering(tmp_path: Path) -> None:
    entitlement_path, public_path = _entitlement_files(tmp_path)
    verified = verify_entitlement(entitlement_path, public_path, now=NOW)
    assert verified.customer_id == "customer-test"
    assert verified.features == ("opaque-v1",)

    envelope = json.loads(entitlement_path.read_text(encoding="utf-8"))
    envelope["payload"]["customer_id"] = "attacker"
    entitlement_path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(EntitlementError, match="signature verification failed"):
        verify_entitlement(entitlement_path, public_path, now=NOW)


def test_entitlement_rejects_expired_wrong_product_and_unknown_fields(
    tmp_path: Path,
) -> None:
    expired_path, public_path = _entitlement_files(
        tmp_path,
        expires_at="2026-07-27T11:59:59Z",
    )
    with pytest.raises(EntitlementError, match="expired"):
        verify_entitlement(expired_path, public_path, now=NOW)

    wrong_path, wrong_public = _entitlement_files(
        tmp_path,
        product="other-product",
    )
    with pytest.raises(EntitlementError, match="different product"):
        verify_entitlement(wrong_path, wrong_public, now=NOW)

    unknown_path, unknown_public = _entitlement_files(
        tmp_path,
        unexpected="not-allowed",
    )
    with pytest.raises(EntitlementError, match="fields do not match"):
        verify_entitlement(unknown_path, unknown_public, now=NOW)

    perpetual_path, perpetual_public = _entitlement_files(
        tmp_path,
        expires_at=None,
    )
    with pytest.raises(EntitlementError, match="expires_at must be"):
        verify_entitlement(perpetual_path, perpetual_public, now=NOW)

    padded_path, padded_public = _entitlement_files(
        tmp_path,
        customer_id=" customer-test ",
    )
    with pytest.raises(EntitlementError, match="leading or trailing"):
        verify_entitlement(padded_path, padded_public, now=NOW)


def test_selfhost_exposes_only_opaque_v1_routes(tmp_path: Path) -> None:
    entitlement_path, public_path = _entitlement_files(tmp_path)
    entitlement = verify_entitlement(entitlement_path, public_path, now=NOW)
    runtime = SeamRuntime(tmp_path / "selfhost.db")
    client = TestClient(
        create_selfhost_app(
            runtime,
            entitlement,
            api_token="a" * 32,
        )
    )

    assert {route.path for route in client.app.routes} == {
        "/v1/health",
        "/v1/memories",
        "/v1/memories/recall",
        "/v1/context",
    }
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/stats").status_code == 404
    assert client.get("/knowledge-graph").status_code == 404
    assert client.get("/v1/health").json() == {
        "status": "ok",
        "api_version": "v1",
        "edition": "compiled-self-host",
    }

    assert client.post("/v1/memories", json={"text": "secret"}).status_code == 401
    response = client.post(
        "/v1/memories",
        json={"text": "The launch preference is cobalt."},
        headers={"Authorization": f"Bearer {'a' * 32}"},
    )
    assert response.status_code == 200
    serialized = json.dumps(response.json(), sort_keys=True)
    assert "raw:" not in serialized
    assert "clm:" not in serialized
    assert "mirl" not in serialized.lower()

    expired_client = TestClient(
        create_selfhost_app(
            SeamRuntime(tmp_path / "selfhost-expired.db"),
            replace(
                entitlement,
                expires_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            ),
            api_token="c" * 32,
        )
    )
    assert expired_client.get("/v1/health").status_code == 503


def test_selfhost_requires_strong_token_and_supports_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "api-token"
    secret.write_text("b" * 32 + "\n", encoding="utf-8")
    assert _read_required_secret(
        env_name="DOES_NOT_EXIST",
        file_env_name="ALSO_DOES_NOT_EXIST",
        default_file=secret,
    ) == "b" * 32

    secret.write_text("short", encoding="utf-8")
    with pytest.raises(RuntimeError, match="at least 32"):
        _read_required_secret(
            env_name="DOES_NOT_EXIST",
            file_env_name="ALSO_DOES_NOT_EXIST",
            default_file=secret,
        )


def test_build_command_is_local_only_and_uses_public_key(tmp_path: Path) -> None:
    _, public_path = _entitlement_files(tmp_path)
    key = validate_public_key(public_path)
    command = build_command(tag="seam-selfhost:test", public_key=key, progress="plain")
    assert "--load" in command
    assert "--push" not in command
    assert command[command.index("--platform") + 1] == "linux/amd64"
    project_root = Path(__file__).resolve().parents[2]
    assert Path(command[-1]).resolve() == project_root
    assert any(item.startswith("SEAM_ENTITLEMENT_PUBLIC_KEY_B64=") for item in command)

    dockerfile = (project_root / "selfhost" / "Dockerfile").read_text(encoding="utf-8")
    compose = (project_root / "selfhost" / "compose.yaml").read_text(encoding="utf-8")
    dockerignore = (project_root / ".dockerignore").read_text(encoding="utf-8")
    assert "/lib/x86_64-linux-gnu/libz.so.1" in dockerfile
    assert "/lib/x86_64-linux-gnu/libgcc_s.so.1" in dockerfile
    assert "${SEAM_SELFHOST_ENTITLEMENT_FILE:-./entitlement.json}" in compose
    assert "${SEAM_SELFHOST_TOKEN_FILE:-./api-token.txt}" in compose
    assert "seam_runtime/config.toml" in dockerignore


def test_entitlement_issuer_writes_exclusive_verifiable_file(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "signing.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path = tmp_path / "signing.pub.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    output = tmp_path / "issued.json"
    argv = [
        "--private-key",
        str(private_path),
        "--entitlement-id",
        "ent-issued-001",
        "--customer-id",
        "customer-issued",
        "--issued-at",
        "2026-07-01T00:00:00Z",
        "--not-before",
        "2026-07-01T00:00:00Z",
        "--expires-at",
        "2026-08-01T00:00:00Z",
        "--output",
        str(output),
    ]
    assert issue_entitlement(argv) == 0
    assert verify_entitlement(output, public_path, now=NOW).customer_id == "customer-issued"
    assert issue_entitlement(argv) == 1


def _docker_archive(path: Path, files: dict[str, bytes], *, user: str = "65532:65532") -> Path:
    layer_buffer = io.BytesIO()
    with tarfile.open(fileobj=layer_buffer, mode="w") as layer:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o555 if name.endswith("seam-selfhost") else 0o444
            info.size = len(content)
            layer.addfile(info, io.BytesIO(content))
    layer_content = layer_buffer.getvalue()
    config = {
        "architecture": "amd64",
        "config": {
            "User": user,
            "Entrypoint": ["/opt/seam/app/seam-selfhost"],
            "WorkingDir": "/var/lib/seam",
            "Labels": {"com.seam.edition": "compiled-self-host"},
        },
        "os": "linux",
    }
    manifest = [
        {
            "Config": "config.json",
            "RepoTags": ["seam-selfhost:test"],
            "Layers": ["layer.tar"],
        }
    ]
    with tarfile.open(path, "w") as archive:
        for name, content in {
            "config.json": json.dumps(config).encode(),
            "manifest.json": json.dumps(manifest).encode(),
            "layer.tar": layer_content,
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def test_selfhost_artifact_verifier_accepts_compiled_minimal_image(
    tmp_path: Path,
) -> None:
    archive = _docker_archive(
        tmp_path / "image.tar",
        {
            # Crypto libraries contain PEM format labels. A label in an ELF is
            # not private key material; token-shaped values still remain gated.
            "opt/seam/app/seam-selfhost": (
                b"\x7fELF -----BEGIN " + b"PRIVATE KEY-----"
            ),
            "opt/seam/app/libgcc_s.so.1": b"\x7fELF runtime dependency",
            "opt/seam/app/libz.so.1": b"\x7fELF runtime dependency",
            "opt/seam/entitlement-public-key.pem": b"PUBLIC KEY",
            "licenses/SEAM-LICENSE": b"proprietary terms",
            # The license texts legitimately name MIRL and HS/1 and are exempt
            # from the reserved-identifier content scan.
            "licenses/BUSL-1.1.txt": b"Business Source License 1.1 covering MIRL and HS/1",
        },
    )
    assert verify_archive(archive) == ()


def test_selfhost_artifact_verifier_rejects_source_shell_and_secrets(
    tmp_path: Path,
) -> None:
    archive = _docker_archive(
        tmp_path / "bad-image.tar",
        {
            "opt/seam/app/seam-selfhost": b"\x7fELF compiled",
            "opt/seam/app/libgcc_s.so.1": b"\x7fELF runtime dependency",
            "opt/seam/app/libz.so.1": b"\x7fELF runtime dependency",
            "opt/seam/entitlement-public-key.pem": b"PUBLIC KEY",
            "licenses/SEAM-LICENSE": b"proprietary terms",
            "licenses/BUSL-1.1.txt": b"Business Source License 1.1",
            "opt/seam/seam_runtime/mirl.py": b"print('private source')",
            "bin/sh": b"shell",
            "run/key.txt": b"-----BEGIN " + b"PRIVATE KEY-----",
        },
        user="0",
    )
    errors = verify_archive(archive)
    assert any("source-like file" in error for error in errors)
    assert any("mutable runtime tool" in error for error in errors)
    assert any("secret-shaped content" in error for error in errors)
    assert any("uid 65532" in error for error in errors)


def test_selfhost_artifact_verifier_ratchets_reserved_identifier_exposure(
    tmp_path: Path,
) -> None:
    """A measured Nuitka build leaks module names, qualified helper names, and SQL
    schemas verbatim; path-only checks passed that image. Zero is unreachable while
    the engine is compiled in, so the gate pins measured exposure and fails on any
    increase."""
    payload = (
        b"\x7fELF compiled"
        b"compile_nl.<locals>.add_claim"
        b"seam_runtime/reasoning_graph.py"
        b"create table if not exists knowledge_graph_meta ("
        b"Write MIRL/RC/LX bytes into a lossless PNG surface"
    )
    files = {
        "opt/seam/app/seam-selfhost": payload,
        "opt/seam/app/libgcc_s.so.1": b"\x7fELF runtime dependency",
        "opt/seam/app/libz.so.1": b"\x7fELF runtime dependency",
        "opt/seam/entitlement-public-key.pem": b"PUBLIC KEY",
        "licenses/SEAM-LICENSE": b"proprietary terms",
        "licenses/BUSL-1.1.txt": b"Business Source License 1.1",
    }
    archive = _docker_archive(tmp_path / "leaky-image.tar", files)

    # Exposure above budget fails and names the offending identifier and counts.
    errors = verify_archive(archive, budget={b"compile_nl": 0, b"knowledge_graph": 0})
    increased = [error for error in errors if "exposure increased" in error]
    assert increased, errors
    assert any("compile_nl appears 1 times, budget 0" in error for error in increased)
    assert any("knowledge_graph appears 1 times, budget 0" in error for error in increased)

    # Exposure at budget passes, so the ratchet does not block a steady build.
    assert verify_archive(archive, budget={b"compile_nl": 1, b"knowledge_graph": 1}) == ()


def test_selfhost_reserved_budget_matches_measured_baseline() -> None:
    """The budget is a measured fact, not an aspiration. It may only go down."""
    assert RESERVED_CONTENT_BUDGET[b"MIRL"] == 134
    assert RESERVED_CONTENT_BUDGET[b"knowledge_graph"] == 18
    assert RESERVED_CONTENT_BUDGET[b"reasoning_graph"] == 13
    assert sum(RESERVED_CONTENT_BUDGET.values()) == 418


def test_selfhost_artifact_verifier_exempts_license_texts_from_content_scan(
    tmp_path: Path,
) -> None:
    """BUSL and the SEAM license name MIRL and HS/1 by design; naming the
    reserved material in the license that governs it is not a leak."""
    archive = _docker_archive(
        tmp_path / "licensed-image.tar",
        {
            "opt/seam/app/seam-selfhost": b"\x7fELF compiled",
            "opt/seam/app/libgcc_s.so.1": b"\x7fELF runtime dependency",
            "opt/seam/app/libz.so.1": b"\x7fELF runtime dependency",
            "opt/seam/entitlement-public-key.pem": b"PUBLIC KEY",
            "licenses/SEAM-LICENSE": b"MIRL and HS/1 reserved materials license",
            "licenses/BUSL-1.1.txt": b"BUSL-1.1 Licensed Work: SEAM MIRL and HS/1",
        },
    )
    assert verify_archive(archive) == ()


def test_selfhost_artifact_verifier_requires_busl_license_text(tmp_path: Path) -> None:
    """The image must carry the license that governs it, not merely claim it."""
    archive = _docker_archive(
        tmp_path / "no-busl.tar",
        {
            "opt/seam/app/seam-selfhost": b"\x7fELF compiled",
            "opt/seam/app/libgcc_s.so.1": b"\x7fELF runtime dependency",
            "opt/seam/app/libz.so.1": b"\x7fELF runtime dependency",
            "opt/seam/entitlement-public-key.pem": b"PUBLIC KEY",
            "licenses/SEAM-LICENSE": b"proprietary terms",
        },
    )
    errors = verify_archive(archive)
    assert any("licenses/BUSL-1.1.txt" in error for error in errors)


def test_selfhost_build_stamps_the_project_version(tmp_path: Path) -> None:
    _, public_path = _entitlement_files(tmp_path)
    key = validate_public_key(public_path)
    command = build_command(tag="seam-selfhost:test", public_key=key, progress="plain")
    assert f"SEAM_VERSION={project_version()}" in command
    assert project_version() == "2.4.0"

    dockerfile = (Path(__file__).resolve().parents[2] / "selfhost" / "Dockerfile").read_text()
    assert 'org.opencontainers.image.licenses="BUSL-1.1"' in dockerfile
    assert 'org.opencontainers.image.version="${SEAM_VERSION}"' in dockerfile
    assert "/licenses/BUSL-1.1.txt" in dockerfile
