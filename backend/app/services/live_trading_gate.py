"""
Policy hooks for live trading and exchange mutations.

Contract (stable for future enforcement)
----------------------------------------
- **Real exchange mutations only:** gates must not block dry-run, local simulation, or any path
  where the broker would not perform a real HTTP mutation against the exchange.
- **DB-backed gate:** ``assert_exchange_mutation_allowed`` returns immediately when
  ``get_live_trading(db)`` is false, matching app-wide “live off ⇒ broker dry_run” behavior.
  Stricter rules added later run only after that check (governance, kill-switch, etc.).
- **Broker gate:** ``require_mutation_allowed_for_broker`` is invoked from ``crypto_com_trade``
  only **after** the client has resolved that the call will hit the real API (not dry-run /
  not ``live_trading`` short-circuit), including
  ``create_stop_loss_take_profit_with_variations`` (variant SL/TP fallback).
- **Read-only:** ``get_live_trading`` is a status helper; it does not block.

**Current posture:** enforcement is **not** enabled—policy hooks are no-ops after the live-trading
early exit in ``assert_exchange_mutation_allowed``. This keeps today’s runtime identical while
fixing ordering so future raises cannot block simulation by mistake.

The file must exist in the tree (it was previously missing, causing ``ModuleNotFoundError``).
See ``docs/development/SERVICES_SINGLETON_IMPORTS.md`` for import/mocking notes.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session


class LiveTradingBlockedError(Exception):
    """Raised when an exchange mutation is blocked by policy."""


def get_live_trading(db: Optional[Session]) -> bool:
    """True if live (non-paper) trading is enabled for this session/environment."""
    from app.utils.live_trading import get_live_trading_status

    return bool(get_live_trading_status(db))


def assert_exchange_mutation_allowed(
    db: Optional[Session],
    operation: str,
    symbol: Optional[str],
    _context: Any = None,
) -> None:
    """
    Pre-flight for code paths that may call the broker with intent to mutate the exchange.

    When live trading is **off** (DB/env via ``get_live_trading``), returns immediately so dry-run
    and simulation are never blocked here. When live is **on**, future policy may raise
    ``LiveTradingBlockedError``; call sites already catch it.
    """
    if not get_live_trading(db):
        return
    _ = operation, symbol, _context  # reserved for logging / future policy


def require_mutation_allowed_for_broker(operation: str, symbol: Optional[str] = None) -> None:
    """
    Broker-only pre-flight: call **only** when this request will perform a real exchange mutation
    (after ``actual_dry_run`` / live short-circuits in ``crypto_com_trade``).

    No DB session. Default: allow. Future policy may raise (callers typically do not catch—prefer
    ``assert_exchange_mutation_allowed`` at orchestration layer for graceful handling).
    """
    _ = operation, symbol
