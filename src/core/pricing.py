"""Manual cost calculation — no API returns cost directly, so we maintain our own table."""

PRICES_PER_MILLION_TOKENS_USD = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def _normalize_model_name(model: str) -> str:
    normalized = (model or "").strip().lower()
    if not normalized:
        return ""
    if normalized.startswith("gpt-4o-mini"):
        return "gpt-4o-mini"
    if normalized.startswith("gpt-4o"):
        return "gpt-4o"
    return normalized


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    normalized_model = _normalize_model_name(model)
    prices = PRICES_PER_MILLION_TOKENS_USD.get(normalized_model)
    if prices is None:
        return 0.0
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
