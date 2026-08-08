"""Tests for path-guard-safe DOGE TP price_decimals runtime patch."""
from app.utils.tp_price_decimals_patch import derive_price_decimals


def test_derive_from_quote_decimals_when_price_decimals_missing():
    assert (
        derive_price_decimals(
            {"quote_decimals": 6, "price_tick_size": "0.000001"},
            "0.000001",
        )
        == 6
    )


def test_derive_from_tick_when_quote_missing():
    assert derive_price_decimals({}, "0.000001") == 6


def test_default_two_when_nothing_available():
    assert derive_price_decimals({}, None) == 2


def test_explicit_price_decimals_wins():
    assert (
        derive_price_decimals(
            {"price_decimals": 4, "quote_decimals": 6},
            "0.000001",
        )
        == 4
    )
