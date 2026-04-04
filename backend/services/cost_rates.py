"""
LLM and API cost rate constants.

All prices are USD per million tokens (or per unit for non-token operations).
Update these when provider pricing changes — they are used at event-write time,
so historical events retain the rate that was current when they were created.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Token-based rates (USD per 1,000,000 tokens)
# ---------------------------------------------------------------------------

_TOKEN_RATES: dict[str, dict[str, float]] = {
    # Anthropic Claude
    "claude-sonnet-4-6": {
        "input_per_m":  3.00,
        "output_per_m": 15.00,
    },
    "claude-opus-4-6": {
        "input_per_m":  15.00,
        "output_per_m": 75.00,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_m":  0.80,
        "output_per_m": 4.00,
    },
    # OpenAI embeddings
    "text-embedding-3-small": {
        "input_per_m":  0.02,
        "output_per_m": 0.00,
    },
    "text-embedding-3-large": {
        "input_per_m":  0.13,
        "output_per_m": 0.00,
    },
    # Ollama — no external cost (local inference)
    "llama3.2":           {"input_per_m": 0.00, "output_per_m": 0.00},
    "llama3.2-8k":        {"input_per_m": 0.00, "output_per_m": 0.00},
    "qwen2.5:7b":         {"input_per_m": 0.00, "output_per_m": 0.00},
    "gemma4":             {"input_per_m": 0.00, "output_per_m": 0.00},
    "nomic-embed-text":   {"input_per_m": 0.00, "output_per_m": 0.00},
    "qwen3-embedding":    {"input_per_m": 0.00, "output_per_m": 0.00},
}

# ---------------------------------------------------------------------------
# Per-unit rates (USD per call)
# ---------------------------------------------------------------------------

SCRAPE_COST_USD: float = 0.002      # Firecrawl per page
EMAIL_COST_USD: float = 0.001       # Resend per email


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def compute_token_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a single LLM or embedding call.

    Args:
        model:         Model identifier (must match a key in _TOKEN_RATES).
        input_tokens:  Number of input/prompt tokens consumed.
        output_tokens: Number of output/completion tokens generated.

    Returns:
        Cost in USD (float). Returns 0.0 for unknown models (e.g. local Ollama).
    """
    rates = _TOKEN_RATES.get(model, {"input_per_m": 0.0, "output_per_m": 0.0})
    return (
        input_tokens  / 1_000_000 * rates["input_per_m"] +
        output_tokens / 1_000_000 * rates["output_per_m"]
    )


def get_known_models() -> list[str]:
    """Return list of models with known pricing."""
    return list(_TOKEN_RATES.keys())
