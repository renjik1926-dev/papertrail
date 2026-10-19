"""Estimated cost per run, for the "About this result" drawer.

Prices are USD per million tokens, for prompts of 100K tokens or fewer (the 50-page cap
keeps PaperTrail far below that). Check Anthropic's pricing page before quoting them.
"""

from __future__ import annotations

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
}


def estimate_cost_usd(
    model: str, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    prices = PRICES_PER_MILLION.get(model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    input_price, output_price = prices
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 6)
