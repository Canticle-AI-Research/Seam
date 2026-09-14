"""Claude Code subscription transport for benchmark answerers and judges.

The CLI's reported USD is a usage estimate, not an account debit. CLI budget
caps are best effort, not prepaid accounting. No direct API fallback exists.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from decimal import Decimal, InvalidOperation

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
BILLING_BASIS = "claude-code-reported-usd-not-account-charge"
_SYSTEM_PROMPT = "Return only the requested answer. No tools."


class ClaudeCodeError(RuntimeError):
    """Content-free failure from the isolated subscription transport."""


# Immutable settings are captured at first use; all instances and threads share
# reservations. Failed/uncertain attempts are never refunded. This does not
# coordinate independent benchmark processes or represent prepaid accounting.
_lock = threading.Lock()
_limits = None
_reserved = Decimal("0")
_calls = 0


def _configuration():
    global _limits
    with _lock:
        if _limits is None:
            failure = False
            try:
                total = Decimal(os.environ.get("SEAM_BENCH_CLAUDE_CODE_TOTAL_BUDGET_USD", "1.00"))
                per_call = Decimal(os.environ.get("SEAM_BENCH_CLAUDE_CODE_MAX_BUDGET_USD", "0.10"))
                max_calls = int(os.environ.get("SEAM_BENCH_CLAUDE_CODE_MAX_CALLS", "10"))
                timeout = float(os.environ.get("SEAM_BENCH_CLAUDE_CODE_TIMEOUT_SECONDS", "120"))
                if not (total.is_finite() and per_call.is_finite() and total > 0
                        and per_call > 0 and max_calls > 0 and math.isfinite(timeout) and timeout > 0):
                    failure = True
            except (ValueError, InvalidOperation):
                failure = True
            if failure:
                raise ClaudeCodeError("claude-code: invalid limits")
            _limits = total, per_call, max_calls, timeout
        return _limits


def _reserve(total, per_call, max_calls):
    global _reserved, _calls
    with _lock:
        if _calls >= max_calls or _reserved + per_call > total:
            raise ClaudeCodeError("claude-code: allowance exhausted")
        _reserved += per_call
        _calls += 1


def _environment() -> dict[str, str]:
    # An allowlist also excludes future provider-routing overrides and injected
    # runtime options. HOME retains the installed CLI's normal OAuth storage.
    allowed = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "SYSTEMROOT"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _run(args: list[str], *, env: dict, cwd: str, timeout: float, prompt: str = "") -> dict:
    failure = None
    try:
        # Spool to an anonymous file, then read at most 1 MiB. The process time
        # limit bounds the producer; arbitrarily large JSON is never buffered.
        with tempfile.TemporaryFile() as output:
            with subprocess.Popen(args, stdin=subprocess.PIPE, text=True, stdout=output,
                                  stderr=subprocess.DEVNULL, env=env, cwd=cwd, start_new_session=True) as process:
                try:
                    process.communicate(prompt, timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
            if process.returncode:
                failure = "CLI failed"
            elif output.tell() > 1024 * 1024:
                failure = "CLI output too large"
            else:
                output.seek(0)
                data = json.loads(output.read(1024 * 1024))
                if isinstance(data, dict):
                    return data
                failure = "invalid CLI JSON"
    except subprocess.TimeoutExpired:
        failure = "CLI timeout"
    except (OSError, UnicodeError, ValueError):
        failure = "invalid CLI response"
    # Raise outside except: no captured output/command survives in a cause.
    raise ClaudeCodeError(f"claude-code: {failure}")


def generate(model: str | None, prompt: str, *, diag_out: dict | None = None) -> str:
    model = model or DEFAULT_MODEL
    if not re.fullmatch(r"claude-[a-z0-9]+(?:-[a-z0-9]+)+", model):
        raise ClaudeCodeError("claude-code: explicit full model required")
    total, per_call, max_calls, timeout = _configuration()
    env = _environment()
    executable = shutil.which("claude", path=env.get("PATH", ""))
    if not executable:
        raise ClaudeCodeError("claude-code: CLI unavailable")
    with tempfile.TemporaryDirectory(prefix="seam-claude-code-") as cwd:
        base = [executable, "--safe-mode", "--setting-sources", ""]
        auth = _run(base + ["auth", "status", "--json"], env=env, cwd=cwd, timeout=timeout)
        if not (auth.get("loggedIn") is True and auth.get("authMethod") == "claude.ai"
                and auth.get("apiProvider") == "firstParty"):
            raise ClaudeCodeError("claude-code: Claude.ai subscription authentication required")
        _reserve(total, per_call, max_calls)
        data = _run(base + ["--strict-mcp-config", "--tools", "", "--no-session-persistence",
                          "--model", model, "--max-budget-usd", str(per_call), "--effort", "low",
                          "--system-prompt", _SYSTEM_PROMPT, "--print", "--output-format", "json"],
                    env=env, cwd=cwd, timeout=timeout, prompt=prompt)
    if data.get("is_error") is not False or data.get("subtype") != "success":
        raise ClaudeCodeError("claude-code: unsuccessful CLI result")
    answer = data.get("result")
    if not isinstance(answer, str) or not answer.strip():
        raise ClaudeCodeError("claude-code: empty CLI result")
    usage = data.get("usage")
    model_usage = data.get("modelUsage")
    cost = data.get("total_cost_usd")
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    def tokens(value):
        return type(value) is int and value >= 0
    if not number(cost) or not isinstance(usage, dict) or not isinstance(model_usage, dict) or not model_usage:
        raise ClaudeCodeError("claude-code: invalid accounting metadata")
    usage_fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    model_fields = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    if not all(tokens(usage.get(key)) for key in usage_fields):
        raise ClaudeCodeError("claude-code: invalid token metadata")
    safe_models = {}
    for served, values in model_usage.items():
        if (not re.fullmatch(r"claude-[a-z0-9]+(?:-[a-z0-9]+)+", served)
                or not isinstance(values, dict)
                or not all(tokens(values.get(key)) for key in model_fields)
                or not number(values.get("costUSD"))):
            raise ClaudeCodeError("claude-code: invalid model metadata")
        safe_models[served] = {key: values[key] for key in (*model_fields, "costUSD")}
        for key in ("provider", "costBasis", "canonicalModel", "thinkingTokens"):
            if key not in values:
                continue
            value = values[key]
            valid = (
                value == "firstParty" if key == "provider" else
                value == "list" if key == "costBasis" else
                isinstance(value, str) and bool(re.fullmatch(r"claude-[a-z0-9]+(?:-[a-z0-9]+)+", value)) if key == "canonicalModel" else
                tokens(value)
            )
            if not valid:
                raise ClaudeCodeError("claude-code: invalid optional model metadata")
            safe_models[served][key] = value
    if model not in safe_models:
        raise ClaudeCodeError("claude-code: requested model missing from metadata")
    if diag_out is not None:
        diag_out.update({"provider": "claude-code", "transport": "claude-code-cli",
                         "auth_method": "claude.ai", "model": model,
                         "served_model": model, "model_usage": safe_models,
                         "prompt_tokens": usage.get("input_tokens"),
                         "completion_tokens": usage.get("output_tokens"),
                         "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                         "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                         "cli_reported_cost_usd": data.get("total_cost_usd"),
                         "billing_basis": BILLING_BASIS})
    return answer.strip()
