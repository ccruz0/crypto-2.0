"""Format indicator / price values for user-facing alerts (Telegram, reasons)."""

from __future__ import annotations

from typing import Optional, Union

Number = Union[int, float]


def format_indicator_value(value: Optional[Number], *, max_decimals: int = 8) -> str:
    """Format MA/EMA/price so sub-dollar coins are not shown as 0.00.

    Examples:
      65199.57 -> "65199.57"
      1.2345   -> "1.2345"
      0.00326  -> "0.003260"
      None     -> "N/A"
    """
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "N/A"

    abs_v = abs(num)
    if abs_v == 0:
        return "0"
    if abs_v >= 100:
        return f"{num:.2f}"
    if abs_v >= 1:
        text = f"{num:.4f}"
    elif abs_v >= 0.01:
        text = f"{num:.6f}"
    else:
        text = f"{num:.{max_decimals}f}"
    return text.rstrip("0").rstrip(".") or "0"
