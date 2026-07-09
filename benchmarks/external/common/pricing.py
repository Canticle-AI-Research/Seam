"""Token → USD cost estimation for benchmark runs.

Cost = real usage tokens (captured from each provider response) × a documented
price table. The token counts are EXACT; the prices are an approximate,
env-overridable table, so a run reports "tokens-exact, table-priced" cost, not
a fabricated number. An unknown model yields ``None`` (never a made-up cost).

Override the whole table with ``SEAM_BENCH_PRICING_JSON`` (a JSON object of
``{"model-id": {"input": <usd_per_1m>, "output": <usd_per_1m>}}``) when prices
move or a model is missing.
"""
from __future__ import annotations

import json
import os

# Approximate USD per 1,000,000 tokens, keyed by model id prefix (longest match
# wins). Documented as of the pricing snapshot below; override via env when it
# drifts. Deliberately conservative coverage -- unknown models return None.
PRICING_SNAPSHOT = "2026-01"
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    # DeepSeek's own API (deepseek-reasoner = R1, returns reasoning_content).
    # Approximate standard-price rates; DeepSeek also has off-peak discounts.
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
}


def _prices() -> dict[str, dict[str, float]]:
    override = os.environ.get("SEAM_BENCH_PRICING_JSON")
    if not override:
        return _DEFAULT_PRICES
    try:
        parsed = json.loads(override)
        if isinstance(parsed, dict):
            return {**_DEFAULT_PRICES, **parsed}
    except (json.JSONDecodeError, TypeError):
        pass
    return _DEFAULT_PRICES


def _rate(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    table = _prices()
    if model in table:
        return table[model]
    # Longest-prefix match so "gpt-4o-mini-2026-xx" resolves to "gpt-4o-mini".
    best: str | None = None
    for key in table:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return table[best] if best else None


def estimate_cost_usd(model: str | None, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """USD for one call from exact token counts, or None if the model is
    unpriced or tokens are missing (never a fabricated number)."""
    rate = _rate(model)
    if rate is None or prompt_tokens is None or completion_tokens is None:
        return None
    return (prompt_tokens / 1_000_000) * rate["input"] + (completion_tokens / 1_000_000) * rate["output"]


def is_priced(model: str | None) -> bool:
    return _rate(model) is not None
