"""SL/TP healing policy: default off aligns with fill-time-only business rule."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.exchange_sync import should_auto_create_sl_tp_on_sync
from app.services.sl_tp_checker import SLTPCheckerService
from app.services.sl_tp_protection import is_sltp_healing_enabled


def test_healing_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SLTP_HEALING_ENABLED", raising=False)
    assert is_sltp_healing_enabled() is False


def test_healing_enabled_when_env_true(monkeypatch):
    monkeypatch.setenv("SLTP_HEALING_ENABLED", "true")
    assert is_sltp_healing_enabled() is True


def test_sync_backfill_blocked_when_healing_disabled(monkeypatch):
    monkeypatch.delenv("SLTP_HEALING_ENABLED", raising=False)
    db = MagicMock()
    order = MagicMock(
        exchange_order_id="parent-1",
        symbol="BTC_USD",
        trade_signal_id=99,
    )
    allowed, reason = should_auto_create_sl_tp_on_sync(
        db, order, order_filled_time=None, now_utc=datetime.now(timezone.utc)
    )
    assert allowed is False
    assert reason == "healing_disabled"


@patch.object(SLTPCheckerService, "check_positions_for_sl_tp")
@patch.object(SLTPCheckerService, "_create_protection_order")
def test_ensure_missing_protection_read_only_when_healing_disabled(
    mock_create, mock_check, monkeypatch
):
    monkeypatch.delenv("SLTP_HEALING_ENABLED", raising=False)
    svc = SLTPCheckerService()
    mock_check.return_value = {
        "positions_missing_sl_tp": [
            {"symbol": "BTC_USD", "has_sl": True, "has_tp": False},
        ],
        "total_positions": 1,
        "oco_issues": {},
        "checked_at": None,
    }
    result = svc.ensure_missing_protection(MagicMock())
    mock_create.assert_not_called()
    assert result["healing_disabled"] is True
    assert result["created"] == []
    assert len(result["still_missing"]) == 1


def test_half_protected_backfill_requires_healing_enabled(monkeypatch):
    """Legacy half-protected sync backfill only runs when healing is on."""
    monkeypatch.setenv("SLTP_HEALING_ENABLED", "true")
    db = MagicMock()
    order = MagicMock(
        exchange_order_id="parent-1",
        symbol="ETH_USD",
        trade_signal_id=None,
        parent_order_id=None,
    )
    now = datetime.now(timezone.utc)
    filled_time = now - timedelta(hours=48)
    sl = ExchangeOrder(
        exchange_order_id="sl-1", order_role="STOP_LOSS", status=OrderStatusEnum.ACTIVE
    )

    with patch("app.services.exchange_sync.link_system_trade_signal_to_order", return_value=False):
        with patch("app.services.exchange_sync.is_system_created_order", return_value=False):
            with patch(
                "app.services.exchange_sync.has_complete_sl_tp_protection",
                return_value=False,
            ):
                with patch(
                    "app.services.exchange_sync.should_skip_rejected_tp_backfill",
                    return_value=False,
                ):
                    with patch(
                        "app.services.exchange_sync.get_active_protection_order",
                        side_effect=lambda _db, _parent, role: sl
                        if role == "STOP_LOSS"
                        else None,
                    ):
                        allowed, reason = should_auto_create_sl_tp_on_sync(
                            db, order, filled_time, now
                        )
    assert allowed is True
    assert reason == "half_protected_backfill"
