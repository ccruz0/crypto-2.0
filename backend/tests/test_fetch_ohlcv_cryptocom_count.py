"""Crypto.com OHLCV fetch must pass count so MA50 has enough candles without Binance."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _cdc_response(n: int) -> MagicMock:
    candles = [
        {"t": i * 3600_000, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10"}
        for i in range(n)
    ]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": 0, "result": {"data": candles}}
    return resp


def test_fetch_ohlcv_passes_count_and_skips_binance_when_enough_candles():
    import market_updater as mu

    with patch("market_updater.requests.get", return_value=_cdc_response(200)) as get:
        data = mu.fetch_ohlcv_data("BTC_USDT", interval="1h", limit=200)

    assert data is not None
    assert len(data) == 200
    assert get.call_count == 1
    args, kwargs = get.call_args
    assert "crypto.com" in args[0]
    assert kwargs["params"]["count"] == 200
    assert kwargs["params"]["instrument_name"] == "BTC_USDT"


def test_fetch_ohlcv_caps_count_at_300():
    import market_updater as mu

    with patch("market_updater.requests.get", return_value=_cdc_response(300)) as get:
        mu.fetch_ohlcv_data("ETH_USDT", interval="1h", limit=1000)

    _, kwargs = get.call_args
    assert kwargs["params"]["count"] == 300


def test_fetch_ohlcv_falls_back_to_binance_only_when_cdc_still_short():
    import market_updater as mu

    binance_resp = MagicMock()
    binance_resp.raise_for_status = MagicMock()
    # Binance kline row: open time, o, h, l, c, volume, ...
    binance_resp.json.return_value = [
        [i * 3600_000, "1", "2", "0.5", "1.5", "10", 0, 0, 0, 0, 0, 0] for i in range(100)
    ]

    with patch(
        "market_updater.requests.get",
        side_effect=[_cdc_response(25), binance_resp],
    ) as get:
        data = mu.fetch_ohlcv_data("BTC_USDT", interval="1h", limit=200)

    assert data is not None
    assert len(data) == 100
    assert get.call_count == 2
    assert "crypto.com" in get.call_args_list[0].args[0]
    assert "binance.com" in get.call_args_list[1].args[0]
