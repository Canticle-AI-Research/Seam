from __future__ import annotations

import os
import re
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_TRANSIENT_TEXT = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "temporarily unavailable",
    "server error",
    "service unavailable",
    "gateway",
    "timeout",
    "timed out",
    "connection",
)


def provider_retry(
    fn: Callable[[], T],
    *,
    label: str,
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> T:
    """Retry transient provider failures for paid benchmark calls.

    This is benchmark-local on purpose: OpenAI/Anthropic/mem0 SDK exceptions
    differ by version, and long paid runs should recover from rate limits
    without changing core runtime behavior. Non-transient errors still surface
    immediately.
    """
    attempts = max_attempts or int(os.environ.get("SEAM_BENCH_PROVIDER_MAX_RETRIES", "8"))
    base = base_delay if base_delay is not None else float(
        os.environ.get("SEAM_BENCH_PROVIDER_RETRY_BASE_SECONDS", "5")
    )
    cap = max_delay if max_delay is not None else float(
        os.environ.get("SEAM_BENCH_PROVIDER_RETRY_MAX_SECONDS", "90")
    )
    attempts = max(1, attempts)

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= attempts or not is_transient_provider_error(exc):
                raise
            delay = _retry_after_seconds(exc)
            if delay is None:
                delay = min(cap, base * (2 ** (attempt - 1)))
            print(
                f"[provider-retry] {label}: transient {type(exc).__name__} "
                f"attempt {attempt}/{attempts}; sleeping {delay:.1f}s",
                flush=True,
            )
            time.sleep(max(0.0, delay))

    raise RuntimeError("unreachable provider retry state")


def is_transient_provider_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = _status_code(current)
        if status in _TRANSIENT_STATUS_CODES:
            return True
        text = f"{type(current).__name__} {current}".lower()
        if any(marker in text for marker in _TRANSIENT_TEXT):
            return True
        current = current.__cause__ or current.__context__
    return False


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    match = re.search(r"\b(408|409|429|500|502|503|504)\b", str(exc))
    if match:
        return int(match.group(1))
    return None


def _retry_after_seconds(exc: BaseException) -> float | None:
    for attr in ("retry_after", "retry_after_seconds"):
        value = getattr(exc, attr, None)
        parsed = _parse_seconds(value)
        if parsed is not None:
            return parsed
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers:
        for key in ("retry-after", "Retry-After"):
            try:
                parsed = _parse_seconds(headers.get(key))
            except AttributeError:
                parsed = None
            if parsed is not None:
                return parsed
    current = exc.__cause__ or exc.__context__
    if current is not None:
        return _retry_after_seconds(current)
    return None


def _parse_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
