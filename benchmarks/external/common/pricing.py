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
# "input" is the CACHE-MISS rate (the safe default for prompt_tokens when no
# cache-hit breakdown is available); "input_cache_hit" is used for the portion
# of prompt tokens a provider reports as cache hits (see cache_hit_tokens on
# estimate_cost_usd). Providers without a cache-hit distinction simply omit
# "input_cache_hit" and all prompt tokens price at "input".
PRICING_SNAPSHOT = "2026-07"
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    # DeepSeek's own API, verified live against api-docs.deepseek.com/quick_start/pricing
    # 2026-07-09. NOTE: "deepseek-reasoner"/"deepseek-chat" are DEPRECATED aliases
    # (retiring 2026-07-24 15:59 UTC per DeepSeek's docs) that route to
    # deepseek-v4-flash's thinking/non-thinking modes -- always request the
    # explicit v4 model id, never the alias.
    "deepseek-v4-flash": {"input": 0.14, "input_cache_hit": 0.0028, "output": 0.28},
    "deepseek-v4-pro": {"input": 0.435, "input_cache_hit": 0.003625, "output": 0.87},
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


def estimate_cost_usd(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    *,
    cache_hit_tokens: int | None = None,
) -> float | None:
    """USD for one call from exact token counts, or None if the model is
    unpriced or tokens are missing (never a fabricated number).

    ``cache_hit_tokens`` (optional): the portion of ``prompt_tokens`` a
    provider reports as served from cache (e.g. DeepSeek's
    ``prompt_cache_hit_tokens``), priced at the model's ``input_cache_hit``
    rate if the table has one; the remainder prices at the normal (cache-miss)
    ``input`` rate. Omit it (or 0) to price all prompt tokens at the standard
    rate -- the safe default when no cache breakdown is available."""
    rate = _rate(model)
    if rate is None or prompt_tokens is None or completion_tokens is None:
        return None
    hit = min(cache_hit_tokens or 0, prompt_tokens)
    miss = prompt_tokens - hit
    hit_rate = rate.get("input_cache_hit", rate["input"])
    input_cost = (miss / 1_000_000) * rate["input"] + (hit / 1_000_000) * hit_rate
    return input_cost + (completion_tokens / 1_000_000) * rate["output"]


def is_priced(model: str | None) -> bool:
    return _rate(model) is not None
