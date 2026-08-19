"""Entry order sizing: cap to the risk limit instead of refusing the trade.

Why this lives here and not in ``trading_guardrails``
-----------------------------------------------------
``backend/app/utils/trading_guardrails.py`` is a Path Guard protected path: PRs
touching it always fail CI, by design, so the risk limits cannot be edited as
routine work. That control is correct and this module does not work around it.

The distinction is real, not cosmetic: the *limit* is guardrail policy and stays
untouched — this module only reads it. What changes is how a caller **sizes** an
order before asking for permission, which is sizing logic and belongs with the
callers. ``can_place_real_order`` keeps its binary contract intact and still acts
as the backstop for any path that does not size through here.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def clamp_order_usd_to_limit(
    order_usd_value: float,
    *,
    symbol: str = "",
    side: str = "",
) -> Tuple[float, Optional[str]]:
    """Cap an entry order to MAX_USD_PER_ORDER instead of refusing it.

    A risk limit bounds size; it does not cancel the trade. Refusing filtered by
    SIZE rather than by quality, so the coins configured with the largest amounts
    were exactly the ones silenced: on 2026-08-19 five symbols (ETH_USD, AKT_USD,
    BTC_USD, SOL_USD, ALGO_USD) carried trade_amount_usd=1000 against a $100 cap
    and could not place a single order — 1000 > 100 always, whatever the market
    did. The only trace was the error_message of order_intents (issue #517).

    The project already prefers capping over refusing for protection orders
    (``cap_protection_qty_from_wallet``, same ``(value, note)`` contract); this
    brings entries in line.

    Returns ``(usd_to_use, note)``; ``note`` is None when nothing was capped.

    The caller MUST use the returned value for both the guardrail check and the
    actual placement. Capping only the check would let an oversized order
    through — worse than refusing it — so this is applied at the point where the
    amount is first read from the watchlist, never at the check.
    """
    from app.utils.trading_guardrails import resolve_max_usd_per_order

    limit = resolve_max_usd_per_order()
    value = float(order_usd_value or 0.0)
    if value <= limit:
        return value, None
    note = (
        f"order size capped from ${value:.2f} to ${limit:.2f} by MAX_USD_PER_ORDER"
    )
    logger.warning("[GUARDRAIL_CAP] %s %s - %s", symbol or "?", side or "?", note)
    return limit, note
