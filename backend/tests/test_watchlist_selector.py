"""Tests for watchlist_selector helpers."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.watchlist_selector import (  # noqa: E402
    deduplicate_watchlist_items,
    partition_watchlist_items,
    select_preferred_watchlist_item,
)


def _make_item(
    symbol: str,
    *,
    id_value: int,
    alert_enabled: bool,
    is_deleted: bool = False,
    created_offset_minutes: int = 0,
    exchange: str = "CRYPTO_COM",
):
    """Create a lightweight object that mimics WatchlistItem."""
    created_at = datetime.now() + timedelta(minutes=created_offset_minutes)
    return SimpleNamespace(
        symbol=symbol,
        id=id_value,
        alert_enabled=alert_enabled,
        is_deleted=is_deleted,
        exchange=exchange,
        created_at=created_at,
    )


def test_select_preferred_prioritizes_active_alerts():
    """When duplicates exist, prefer alert_enabled rows over disabled ones."""
    symbol = "ADA_USDT"
    disabled = _make_item(symbol, id_value=1, alert_enabled=False, created_offset_minutes=-10)
    enabled = _make_item(symbol, id_value=2, alert_enabled=True, created_offset_minutes=0)

    preferred = select_preferred_watchlist_item([disabled, enabled], symbol)
    assert preferred is enabled


def test_deduplicate_returns_single_row_per_symbol():
    """deduplicate_watchlist_items collapses duplicates using canonical selector."""
    symbol = "SOL_USDT"
    newer_disabled = _make_item(symbol, id_value=5, alert_enabled=False, created_offset_minutes=5)
    canonical = _make_item(symbol, id_value=10, alert_enabled=True, created_offset_minutes=0)
    other_symbol = _make_item("BTC_USDT", id_value=20, alert_enabled=True)

    canonical_items = deduplicate_watchlist_items([newer_disabled, canonical, other_symbol])

    # One entry per symbol
    assert len(canonical_items) == 2
    sol_item = next(item for item in canonical_items if item.symbol == symbol)
    btc_item = next(item for item in canonical_items if item.symbol == "BTC_USDT")

    assert sol_item is canonical
    assert btc_item is other_symbol


def test_partition_respects_exchange():
    """Symbols on different exchanges should both remain canonical."""
    symbol = "XRP_USDT"
    cron_item = _make_item(symbol, id_value=1, alert_enabled=True, exchange="CRYPTO_COM")
    cdc_dup = _make_item(symbol, id_value=2, alert_enabled=False, exchange="CRYPTO_COM", created_offset_minutes=-5)
    other_exchange = _make_item(symbol, id_value=3, alert_enabled=True, exchange="BINANCE")

    canonical, duplicates = partition_watchlist_items([cron_item, cdc_dup, other_exchange])

    assert len(canonical) == 2  # CRYPTO_COM + BINANCE
    assert cron_item in canonical
    assert other_exchange in canonical
    assert duplicates == [cdc_dup]
