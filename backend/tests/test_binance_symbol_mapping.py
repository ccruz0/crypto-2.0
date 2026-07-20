"""Bare watchlist symbols must map to valid Binance kline symbols.

Regression: XRP/ALGO (no _USD/_USDT) were sent to Binance as "XRP"/"ALGO",
which returns HTTP 400. Market updater then stored RSI=50, MAs=price,
volume_ratio=0 → Watchlist Volume column showed "—".
"""
import pytest

from market_updater import to_binance_symbol


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("XRP", "XRPUSDT"),
        ("ALGO", "ALGOUSDT"),
        ("xrp", "XRPUSDT"),
        ("XRP_USD", "XRPUSDT"),
        ("XRP_USDT", "XRPUSDT"),
        ("ALGO_USD", "ALGOUSDT"),
        ("ALGO_USDT", "ALGOUSDT"),
        ("BTC_USD", "BTCUSDT"),
        ("BTC_USDT", "BTCUSDT"),
        ("DOT_USD", "DOTUSDT"),
        ("BNB_USDT", "BNBUSDT"),
    ],
)
def test_to_binance_symbol(symbol, expected):
    assert to_binance_symbol(symbol) == expected


def test_to_binance_symbol_empty():
    assert to_binance_symbol("") == ""
    assert to_binance_symbol("   ") == ""
