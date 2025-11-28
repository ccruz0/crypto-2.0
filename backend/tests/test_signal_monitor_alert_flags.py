from types import SimpleNamespace

from app.services.signal_monitor import SignalMonitorService


def _item(alert=True, buy=True, sell=True):
    return SimpleNamespace(
        alert_enabled=alert,
        buy_alert_enabled=buy,
        sell_alert_enabled=sell,
    )


def test_evaluate_alert_flag_allows_buy_when_enabled():
    service = SignalMonitorService()
    allowed, reason, details = service._evaluate_alert_flag(_item(), "BUY")
    assert allowed is True
    assert reason == "ALERT_ENABLED"
    assert details["alert_enabled"] is True
    assert details["buy_alert_enabled"] is True


def test_evaluate_alert_flag_blocks_when_master_disabled():
    service = SignalMonitorService()
    allowed, reason, details = service._evaluate_alert_flag(_item(alert=False, buy=True), "BUY")
    assert allowed is False
    assert reason == "DISABLED_ALERT"
    assert details["alert_enabled"] is False


def test_evaluate_alert_flag_blocks_buy_when_buy_flag_disabled():
    service = SignalMonitorService()
    allowed, reason, details = service._evaluate_alert_flag(_item(buy=False), "BUY")
    assert allowed is False
    assert reason == "DISABLED_BUY_SELL_FLAG"
    assert details["buy_alert_enabled"] is False


def test_evaluate_alert_flag_blocks_sell_when_sell_flag_disabled():
    service = SignalMonitorService()
    allowed, reason, details = service._evaluate_alert_flag(_item(sell=False), "SELL")
    assert allowed is False
    assert reason == "DISABLED_BUY_SELL_FLAG"
    assert details["sell_alert_enabled"] is False

