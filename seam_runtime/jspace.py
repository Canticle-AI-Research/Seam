from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.util
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse


class JLensUnavailable(RuntimeError):
    pass


class JLensWorker(Protocol):
    def capability(self) -> dict[str, object]: ...

    def analyze(self, *, messages: list[dict[str, str]], answer: str) -> "JLensResult": ...


@dataclass(frozen=True)
class JLensResult:
    backend: str
    model: str
    revision: str
    model_artifact_hash: str
    lens_artifact_hash: str
    concepts: tuple[dict[str, object], ...]
    identity_verified: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "model": self.model,
            "revision": self.revision,
            "model_artifact_hash": self.model_artifact_hash,
            "lens_artifact_hash": self.lens_artifact_hash,
            "identity_verified": self.identity_verified,
            "concepts": [dict(concept) for concept in self.concepts],
        }


def _ref_hash(model: str, revision: str) -> str:
    return hashlib.sha256(f"{model}@{revision}".encode("utf-8")).hexdigest()


def _bounded_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"J-lens concept {field} must be a string")
    limits = {"id": 160, "label": 240, "description": 1024, "module": 240, "source": 240}
    return value[: limits.get(field, 240)]


def _normalize_concepts(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError("J-lens adapter response must contain a concepts list")
    output: list[dict[str, object]] = []
    allowed = {"id", "label", "description", "score", "layer", "module", "rank", "source"}
    text_fields = {"id", "label", "description", "module", "source"}
    for index, raw in enumerate(value[:128]):
        if not isinstance(raw, dict):
            continue
        concept: dict[str, object] = {}
        for raw_key, item in raw.items():
            key = str(raw_key)
            if key not in allowed:
                continue
            # Concepts are compact readouts, never a tensor transport. Every
            # retained field is scalar; arrays/objects are rejected, including
            # a deceptively named description containing activation values.
            if item is not None and not isinstance(item, (str, bool, int, float)):
                continue
            if key in text_fields:
                if not isinstance(item, str):
                    continue
                concept[key] = _bounded_text(item, field=key)
            elif key == "score":
                try:
                    concept[key] = round(max(0.0, min(float(item), 1.0)), 6)
                except (TypeError, ValueError):
                    continue
            elif key in {"rank", "layer"}:
                if isinstance(item, bool):
                    continue
                if isinstance(item, int):
                    concept[key] = max(-100_000, min(item, 100_000))
                elif isinstance(item, str):
                    concept[key] = _bounded_text(item, field=key)
        concept.setdefault("id", f"concept:{index}")
        if not concept.get("label"):
            continue
        output.append(concept)
    return tuple(output)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


class UnavailableJLensWorker:
    def __init__(self, reason: str = "J-Space is disabled") -> None:
        self.reason = reason

    def capability(self) -> dict[str, object]:
        return {
            "available": False,
            "backend": "unavailable",
            "mode": "structured_workspace_only",
            "reason": self.reason,
            "genuine_jacobian_lens": False,
        }

    def analyze(self, *, messages: list[dict[str, str]], answer: str) -> JLensResult:
        del messages, answer
        raise JLensUnavailable(self.reason)


class LocalQwenJLensWorker:
    """Opt-in local Hugging Face Qwen adapter for an external J-lens analyzer.

    SEAM owns the worker boundary and safe event schema, but does not vendor the
    Anthropic implementation or any model/lens weights. The configured analyzer
    receives an activation-capable local Transformers model and tokenizer. A
    worker is reported available only when dependencies, an analyzer, and exact
    model/lens artifact hashes are all present.
    """

    def __init__(
        self,
        *,
        model: str = "Qwen/Qwen2.5-0.5B-Instruct",
        revision: str = "main",
        model_artifact_hash: str | None = None,
        lens_artifact_hash: str | None = None,
        model_manifest_path: str | Path | None = None,
        lens_artifact_path: str | Path | None = None,
        analyzer: Callable[..., object] | None = None,
        analyzer_ref: str | None = None,
        model_loader: Callable[..., tuple[object, object]] | None = None,
        allow_download: bool = False,
    ) -> None:
        self.model = model
        self.revision = revision
        self.model_artifact_hash = model_artifact_hash or ""
        self.lens_artifact_hash = lens_artifact_hash or ""
        self.model_manifest_path = Path(model_manifest_path).expanduser() if model_manifest_path else None
        self.lens_artifact_path = Path(lens_artifact_path).expanduser() if lens_artifact_path else None
        self._analyzer = analyzer
        self.analyzer_ref = analyzer_ref or ""
        self._model_loader = model_loader
        self.allow_download = allow_download

    def _resolve_analyzer(self) -> Callable[..., object] | None:
        if self._analyzer is not None:
            return self._analyzer
        if not self.analyzer_ref or ":" not in self.analyzer_ref:
            return None
        module_name, attribute = self.analyzer_ref.rsplit(":", 1)
        module = importlib.import_module(module_name)
        analyzer = getattr(module, attribute)
        if not callable(analyzer):
            raise TypeError(f"configured J-lens analyzer is not callable: {self.analyzer_ref}")
        self._analyzer = analyzer
        return analyzer

    def _dependencies_available(self) -> bool:
        if self._model_loader is not None:
            return True
        return importlib.util.find_spec("transformers") is not None and importlib.util.find_spec("torch") is not None

    def _verified_artifacts(self) -> tuple[str, str]:
        if self.model_manifest_path is None or self.lens_artifact_path is None:
            raise ValueError("local model manifest and lens artifact paths are required")
        if not self.model_manifest_path.is_file() or not self.lens_artifact_path.is_file():
            raise ValueError("local model manifest and lens artifact must be regular files")
        try:
            manifest = json.loads(self.model_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("local model manifest must be valid JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("local model manifest must be a JSON object")
        if str(manifest.get("model") or "") != self.model:
            raise ValueError("local model manifest model does not match configured model")
        if str(manifest.get("revision") or "") != self.revision:
            raise ValueError("local model manifest revision does not match configured revision")
        actual_model_hash = _sha256_file(self.model_manifest_path)
        actual_lens_hash = _sha256_file(self.lens_artifact_path)
        if not _valid_sha256(self.model_artifact_hash) or not _valid_sha256(self.lens_artifact_hash):
            raise ValueError("expected model-manifest and lens SHA-256 values are required")
        if not hmac.compare_digest(actual_model_hash, self.model_artifact_hash.lower()):
            raise ValueError("local model manifest SHA-256 does not match configured identity")
        if not hmac.compare_digest(actual_lens_hash, self.lens_artifact_hash.lower()):
            raise ValueError("local lens artifact SHA-256 does not match configured identity")
        return actual_model_hash, actual_lens_hash

    def capability(self) -> dict[str, object]:
        analyzer_available = self._analyzer is not None or bool(self.analyzer_ref)
        dependencies = self._dependencies_available()
        identity_error = ""
        verified_hashes: tuple[str, str] | None = None
        try:
            verified_hashes = self._verified_artifacts()
        except ValueError as exc:
            identity_error = str(exc)
        available = analyzer_available and verified_hashes is not None and dependencies
        reasons: list[str] = []
        if not analyzer_available:
            reasons.append("no external Jacobian-lens analyzer configured")
        if identity_error:
            reasons.append(identity_error)
        if not dependencies:
            reasons.append("transformers/torch are not installed")
        return {
            "available": available,
            "backend": "local_huggingface_qwen",
            "mode": "jacobian_lens" if available else "structured_workspace_only",
            "reason": "; ".join(reasons) if reasons else None,
            "model": self.model,
            "revision": self.revision,
            "model_ref_hash": _ref_hash(self.model, self.revision),
            "model_artifact_hash": verified_hashes[0] if verified_hashes else None,
            "lens_artifact_hash": verified_hashes[1] if verified_hashes else None,
            "genuine_jacobian_lens": available,
            "identity_verified": verified_hashes is not None,
            "downloads_enabled": self.allow_download,
        }

    def _load_model(self) -> tuple[object, object]:
        if self._model_loader is not None:
            return self._model_loader(
                model=self.model,
                revision=self.revision,
                local_files_only=not self.allow_download,
            )
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            self.model,
            revision=self.revision,
            local_files_only=not self.allow_download,
            trust_remote_code=False,
        )
        model = AutoModelForCausalLM.from_pretrained(
            self.model,
            revision=self.revision,
            local_files_only=not self.allow_download,
            trust_remote_code=False,
            output_hidden_states=True,
        )
        return model, tokenizer

    def analyze(self, *, messages: list[dict[str, str]], answer: str) -> JLensResult:
        capability = self.capability()
        if not capability["available"]:
            raise JLensUnavailable(str(capability["reason"]))
        analyzer = self._resolve_analyzer()
        if analyzer is None:  # pragma: no cover - capability guards this path
            raise JLensUnavailable("no external Jacobian-lens analyzer configured")
        before_hashes = self._verified_artifacts()
        model, tokenizer = self._load_model()
        raw = analyzer(
            model=model,
            tokenizer=tokenizer,
            model_id=self.model,
            revision=self.revision,
            messages=messages,
            answer=answer,
        )
        payload = raw if isinstance(raw, dict) else {"concepts": raw}
        after_hashes = self._verified_artifacts()
        if before_hashes != after_hashes:
            raise ValueError("local J-lens artifact identity changed during analysis")
        return JLensResult(
            backend="local_huggingface_qwen",
            model=self.model,
            revision=self.revision,
            model_artifact_hash=after_hashes[0],
            lens_artifact_hash=after_hashes[1],
            concepts=_normalize_concepts(payload.get("concepts")),
            identity_verified=True,
        )


def _validate_remote_endpoint(
    endpoint: str,
    *,
    allowed_hosts: frozenset[str] = frozenset(),
    pinned_ips: frozenset[str] = frozenset(),
) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote J-lens endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("remote J-lens endpoint must not contain userinfo or a fragment")
    host = parsed.hostname.lower()
    try:
        addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(parsed.hostname, parsed.port)]
    except socket.gaierror as exc:
        raise ValueError(f"remote J-lens endpoint does not resolve: {parsed.hostname}") from exc
    loopback = bool(addresses) and all(address.is_loopback for address in addresses)
    if parsed.scheme != "https" and not loopback:
        raise ValueError("remote J-lens endpoint must use HTTPS unless it is loopback")
    normalized_allowlist = {value.strip().lower() for value in allowed_hosts if value.strip()}
    if not loopback and host not in normalized_allowlist:
        raise ValueError("remote J-lens endpoint host is not in SEAM_JSPACE_REMOTE_ALLOWED_HOSTS")
    normalized_pins = {str(ipaddress.ip_address(value.strip())) for value in pinned_ips if value.strip()}
    resolved = {str(address) for address in addresses}
    if not loopback and (not normalized_pins or resolved != normalized_pins):
        raise ValueError("remote J-lens endpoint DNS does not exactly match operator-pinned IPs")
    for address in addresses:
        if address.is_loopback:
            continue
        if (
            address.is_private
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError(f"remote J-lens endpoint resolves to a disallowed address: {address}")


def _remote_transport(
    endpoint: str,
    token: str,
    body: dict[str, object],
    timeout: int,
    *,
    allowed_hosts: frozenset[str] = frozenset(),
    pinned_ips: frozenset[str] = frozenset(),
    max_response_bytes: int = 524_288,
) -> dict[str, object]:
    _validate_remote_endpoint(endpoint, allowed_hosts=allowed_hosts, pinned_ips=pinned_ips)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, "J-lens redirect blocked", headers, fp)

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=max(1, min(int(timeout), 30))) as response:
        declared = response.headers.get("content-length")
        if declared and int(declared) > max_response_bytes:
            raise ValueError("remote J-lens response exceeds the configured byte limit")
        raw = response.read(max_response_bytes + 1)
        if len(raw) > max_response_bytes:
            raise ValueError("remote J-lens response exceeds the configured byte limit")
        value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("remote J-lens worker returned a non-object response")
    return value


class RemoteJLensWorker:
    def __init__(
        self,
        *,
        endpoint: str,
        token: str,
        model: str,
        revision: str = "main",
        model_artifact_hash: str | None = None,
        lens_artifact_hash: str | None = None,
        timeout: int = 120,
        allowed_hosts: frozenset[str] = frozenset(),
        pinned_ips: frozenset[str] = frozenset(),
        transport: Callable[[str, str, dict[str, object], int], dict[str, object]] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.model = model
        self.revision = revision
        self.model_artifact_hash = model_artifact_hash or ""
        self.lens_artifact_hash = lens_artifact_hash or ""
        self.timeout = max(1, min(int(timeout), 30))
        self.allowed_hosts = allowed_hosts
        self.pinned_ips = pinned_ips
        self._identity_verified = False
        if transport is None:
            self._transport = lambda endpoint, token, body, timeout: _remote_transport(
                endpoint,
                token,
                body,
                timeout,
                allowed_hosts=self.allowed_hosts,
                pinned_ips=self.pinned_ips,
            )
        else:
            self._transport = transport

    def capability(self) -> dict[str, object]:
        reason = ""
        if not (self.endpoint and self.token and self.model and self.revision):
            reason = "endpoint, token, model, and revision are required"
        elif not _valid_sha256(self.model_artifact_hash) or not _valid_sha256(self.lens_artifact_hash):
            reason = "expected model and lens SHA-256 identities are required"
        else:
            try:
                _validate_remote_endpoint(
                    self.endpoint,
                    allowed_hosts=self.allowed_hosts,
                    pinned_ips=self.pinned_ips,
                )
            except ValueError as exc:
                reason = str(exc)
        available = not reason
        return {
            "available": available,
            "backend": "remote_authenticated_worker",
            "mode": (
                "jacobian_lens"
                if available and self._identity_verified
                else "jacobian_lens_pending_identity"
                if available
                else "structured_workspace_only"
            ),
            "reason": None if available else reason,
            "model": self.model or None,
            "revision": self.revision,
            "model_ref_hash": _ref_hash(self.model, self.revision) if self.model else None,
            "model_artifact_hash": self.model_artifact_hash or None,
            "lens_artifact_hash": self.lens_artifact_hash or None,
            "genuine_jacobian_lens": available and self._identity_verified,
            "identity_verified": self._identity_verified,
            "authenticated": bool(self.token),
        }

    def analyze(self, *, messages: list[dict[str, str]], answer: str) -> JLensResult:
        capability = self.capability()
        if not capability["available"]:
            raise JLensUnavailable(str(capability["reason"]))
        raw = self._transport(
            self.endpoint,
            self.token,
            {
                "schema": "seam-jlens-request/v1",
                "model": self.model,
                "revision": self.revision,
                "messages": messages,
                "answer": answer,
                "return_raw_activations": False,
            },
            self.timeout,
        )
        remote_model = str(raw.get("model") or "")
        remote_revision = str(raw.get("revision") or "")
        model_hash = str(raw.get("model_artifact_hash") or "").lower()
        lens_hash = str(raw.get("lens_artifact_hash") or "").lower()
        if remote_model != self.model or remote_revision != self.revision:
            raise ValueError("remote J-lens response model or revision identity mismatch")
        if not hmac.compare_digest(model_hash, self.model_artifact_hash.lower()):
            raise ValueError("remote J-lens response model artifact identity mismatch")
        if not hmac.compare_digest(lens_hash, self.lens_artifact_hash.lower()):
            raise ValueError("remote J-lens response lens artifact identity mismatch")
        self._identity_verified = True
        return JLensResult(
            backend="remote_authenticated_worker",
            model=remote_model,
            revision=remote_revision,
            model_artifact_hash=model_hash,
            lens_artifact_hash=lens_hash,
            concepts=_normalize_concepts(raw.get("concepts")),
            identity_verified=True,
        )


def jlens_worker_from_env() -> JLensWorker:
    backend = (os.environ.get("SEAM_JSPACE_BACKEND") or "off").strip().lower()
    if backend in {"", "off", "disabled", "none"}:
        return UnavailableJLensWorker("J-Space is opt-in; set SEAM_JSPACE_BACKEND to local or remote")
    model = (os.environ.get("SEAM_JSPACE_MODEL") or "Qwen/Qwen2.5-0.5B-Instruct").strip()
    revision = (os.environ.get("SEAM_JSPACE_REVISION") or "main").strip()
    model_hash = (os.environ.get("SEAM_JSPACE_MODEL_SHA256") or "").strip()
    lens_hash = (os.environ.get("SEAM_JSPACE_LENS_SHA256") or "").strip()
    if backend == "local":
        return LocalQwenJLensWorker(
            model=model,
            revision=revision,
            model_artifact_hash=model_hash,
            lens_artifact_hash=lens_hash,
            model_manifest_path=(os.environ.get("SEAM_JSPACE_MODEL_MANIFEST") or "").strip(),
            lens_artifact_path=(os.environ.get("SEAM_JSPACE_LENS_ARTIFACT") or "").strip(),
            analyzer_ref=(os.environ.get("SEAM_JSPACE_LOCAL_ANALYZER") or "").strip(),
            allow_download=os.environ.get("SEAM_JSPACE_LOCAL_ALLOW_DOWNLOAD") == "1",
        )
    if backend == "remote":
        return RemoteJLensWorker(
            endpoint=(os.environ.get("SEAM_JSPACE_REMOTE_URL") or "").strip(),
            token=(os.environ.get("SEAM_JSPACE_REMOTE_TOKEN") or "").strip(),
            model=model,
            revision=revision,
            model_artifact_hash=model_hash,
            lens_artifact_hash=lens_hash,
            timeout=max(1, min(int(os.environ.get("SEAM_JSPACE_REMOTE_TIMEOUT") or "30"), 30)),
            allowed_hosts=frozenset(
                value.strip().lower()
                for value in (os.environ.get("SEAM_JSPACE_REMOTE_ALLOWED_HOSTS") or "").split(",")
                if value.strip()
            ),
            pinned_ips=frozenset(
                value.strip()
                for value in (os.environ.get("SEAM_JSPACE_REMOTE_PINNED_IPS") or "").split(",")
                if value.strip()
            ),
        )
    return UnavailableJLensWorker(f"unknown SEAM_JSPACE_BACKEND: {backend}")


def workspace_capabilities(worker: JLensWorker) -> dict[str, object]:
    return {
        "schema": "seam-workspace-capabilities/v1",
        "workspace_events": True,
        "append_only_replay": True,
        "post_sse": True,
        "raw_chain_of_thought_persisted": False,
        "raw_activations_persisted": False,
        "hosted_provider_traces_are_jspace": False,
        "jlens": worker.capability(),
    }
