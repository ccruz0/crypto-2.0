"""Hourly SL/TP check: primary-only + no false-fail paging."""
from app.services.scheduler import (
    _classify_hourly_sl_tp_create_result,
    _hourly_sl_tp_dashboard_hint,
    _is_primary_report_sender,
    _sl_tp_check_dashboard_url,
)


def test_primary_report_sender_true_by_default(monkeypatch):
    monkeypatch.delenv("RUN_TELEGRAM_POLLER", raising=False)
    assert _is_primary_report_sender() is True


def test_primary_report_sender_false_on_canary(monkeypatch):
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", "false")
    assert _is_primary_report_sender() is False


def test_classify_created_when_both_legs_in_db():
    assert (
        _classify_hourly_sl_tp_create_result(
            None, sl_count=1, tp_count=1, symbol="SUI_USD", ensured_symbols=set()
        )
        == "created"
    )


def test_classify_created_when_result_ok():
    result = {
        "sl_result": {"order_id": "sl1"},
        "tp_result": {"order_id": "tp1"},
    }
    assert (
        _classify_hourly_sl_tp_create_result(
            result, sl_count=0, tp_count=0, symbol="SUI_USD", ensured_symbols=set()
        )
        == "created"
    )


def test_classify_expected_skip_wallet_mismatch():
    result = {"status": "wallet_side_mismatch"}
    assert (
        _classify_hourly_sl_tp_create_result(
            result, sl_count=0, tp_count=0, symbol="SUI_USD", ensured_symbols=set()
        )
        == "expected_skip"
    )


def test_classify_expected_skip_flatten_close():
    """Emergency flatten BUY/SELL must not page as hourly SL/TP failure."""
    result = {"status": "flatten_close"}
    assert (
        _classify_hourly_sl_tp_create_result(
            result, sl_count=0, tp_count=0, symbol="SUI_USD", ensured_symbols=set()
        )
        == "expected_skip"
    )


def test_classify_covered_by_ensure_same_symbol():
    """Ensure healed the open balance; parent-link check can still look empty."""
    assert (
        _classify_hourly_sl_tp_create_result(
            {"status": "error"},
            sl_count=0,
            tp_count=0,
            symbol="SUI_USD",
            ensured_symbols={"SUI_USD"},
        )
        == "covered_by_ensure"
    )


def test_classify_failed_when_uncovered():
    assert (
        _classify_hourly_sl_tp_create_result(
            {"sl_result": {"error": "boom"}, "tp_result": {}},
            sl_count=0,
            tp_count=0,
            symbol="SUI_USD",
            ensured_symbols={"ALGO_USD"},
        )
        == "failed"
    )


def test_hourly_check_gated_inside_primary_block():
    """Regression: canary must not call check_hourly_sl_tp_missed (duplicate Telegram)."""
    import inspect
    from app.services import scheduler as sched_mod

    src = inspect.getsource(sched_mod.TradingScheduler.run_scheduler)
    # Hourly call must sit inside the primary_reports block, not after it.
    primary_idx = src.find("if primary_reports:")
    hourly_idx = src.find("await self.check_hourly_sl_tp_missed()")
    approval_idx = src.find("await self.check_approval_queue()")
    assert primary_idx != -1 and hourly_idx != -1 and approval_idx != -1
    assert primary_idx < hourly_idx < approval_idx


def test_sl_tp_check_dashboard_url_uses_frontend_env(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://dashboard.hilovivo.com/")
    assert _sl_tp_check_dashboard_url() == "https://dashboard.hilovivo.com/reports/sl-tp-check"


def test_sl_tp_check_dashboard_url_falls_back_to_public_base(monkeypatch):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    assert _sl_tp_check_dashboard_url() == "https://example.test/reports/sl-tp-check"


def test_hourly_hint_wallet_gap_only_links_report():
    url = "https://dashboard.hilovivo.com/reports/sl-tp-check"
    hint = _hourly_sl_tp_dashboard_hint(
        [{"symbol": "ETH_USD", "naked_parent": False}], url
    )
    assert "hidden from Cartera" not in hint
    assert f'<a href="{url}">SL/TP Check</a>' in hint


def test_hourly_hint_splits_fifo_vs_lookback():
    url = "https://dashboard.hilovivo.com/reports/sl-tp-check"
    hint = _hourly_sl_tp_dashboard_hint(
        [
            {"naked_parent": True, "in_open_lot": True, "order_id": "a"},
            {"naked_parent": True, "in_open_lot": False, "order_id": "b"},
        ],
        url,
    )
    assert "1 still in FIFO" in hint
    assert "1 lookback-only" in hint
    assert "hidden from Cartera P" not in hint
    assert f'<a href="{url}">SL/TP Check</a>' in hint
