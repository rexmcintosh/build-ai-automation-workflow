"""Static estimate map ($/1M tokens for text). Estimates only — the diem
reconciler is the authoritative cross-check. Update as Venice pricing moves;
unknown/image models return None and the caller passes --usd."""
from __future__ import annotations

# $ per 1,000,000 tokens: (input, output). Seed values — verify vs Venice pricing.
TEXT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "deepseek-v4-pro": (0.5, 2.0),
    "qwen3-235b-a22b-instruct-2507": (0.2, 0.6),
}

def estimate_usd(model, tokens_in, tokens_out):
    price = TEXT_PRICES.get(model)
    if price is None:
        return None
    pin, pout = price
    return round(tokens_in / 1e6 * pin + tokens_out / 1e6 * pout, 6)
