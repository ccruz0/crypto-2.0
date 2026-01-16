"""Symbol normalization helpers."""
from typing import Optional


def normalize_symbol_for_exchange(symbol: Optional[str]) -> str:
    """Normalize symbol to exchange-friendly format (e.g., BTC/USDT -> BTC_USDT)."""
    if not symbol:
        return ""
    normalized = (
        symbol.strip()
        .upper()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "")
    )
    # Collapse repeated underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized
