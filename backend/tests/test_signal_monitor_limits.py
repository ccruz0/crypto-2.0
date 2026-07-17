import os
from unittest.mock import patch

from app.services.signal_monitor import SignalMonitorService


def test_max_open_orders_per_symbol_reads_from_config():
    svc = SignalMonitorService()
    with patch(
        "app.services.config_loader.get_trading_limits",
        return_value={"maxOpenOrdersPerCoin": 5},
    ):
        assert svc.MAX_OPEN_ORDERS_PER_SYMBOL == 5


def test_global_high_symbol_low_allows_order():
    svc = SignalMonitorService()
    with patch(
        "app.services.config_loader.get_trading_limits",
        return_value={"maxOpenOrdersPerCoin": 3},
    ):
        limit = svc.MAX_OPEN_ORDERS_PER_SYMBOL
        assert svc._should_block_open_orders(
            per_symbol_open=0,
            max_per_symbol=limit,
            global_open=24,
        ) is False


def test_symbol_reaching_limit_blocks_order():
    svc = SignalMonitorService()
    with patch(
        "app.services.config_loader.get_trading_limits",
        return_value={"maxOpenOrdersPerCoin": 3},
    ):
        limit = svc.MAX_OPEN_ORDERS_PER_SYMBOL
        assert svc._should_block_open_orders(
            per_symbol_open=limit,
            max_per_symbol=limit,
            global_open=1,
        ) is True
