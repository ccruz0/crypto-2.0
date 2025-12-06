import pytest

from app.services.signal_monitor import SignalMonitorService


@pytest.fixture
def signal_monitor_service():
    return SignalMonitorService()


def test_global_high_symbol_low_allows_order(signal_monitor_service):
    svc = signal_monitor_service
    limit = svc.MAX_OPEN_ORDERS_PER_SYMBOL
    assert svc._should_block_open_orders(
        per_symbol_open=0,
        max_per_symbol=limit,
        global_open=24,
    ) is False


def test_symbol_reaching_limit_blocks_order(signal_monitor_service):
    svc = signal_monitor_service
    limit = svc.MAX_OPEN_ORDERS_PER_SYMBOL
    assert svc._should_block_open_orders(
        per_symbol_open=limit,
        max_per_symbol=limit,
        global_open=1,
    ) is True

