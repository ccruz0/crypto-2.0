"""Contract and dormant-branch tests for ``live_trading_gate`` (enforcement still off by default)."""
import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.services.exchange_sync import ExchangeSyncService
from app.services.live_trading_gate import (
    LiveTradingBlockedError,
    assert_exchange_mutation_allowed,
    get_live_trading,
)
from app.services.signal_monitor import SignalMonitorService


def test_assert_exchange_mutation_allowed_noop_when_not_live():
    db = MagicMock()
    with patch("app.services.live_trading_gate.get_live_trading", return_value=False):
        assert_exchange_mutation_allowed(db, "any_op", "SYM", None)


def test_get_live_trading_read_only_delegates():
    with patch("app.utils.live_trading.get_live_trading_status", return_value=True):
        assert get_live_trading(MagicMock()) is True


@pytest.mark.parametrize("live", [True, False])
def test_assert_never_raises_today_when_live_on(live: bool):
    """Policy body is still empty after the live check; future raises only apply when live is on."""
    db = MagicMock()
    with patch("app.services.live_trading_gate.get_live_trading", return_value=live):
        assert_exchange_mutation_allowed(db, "op", "X", None)


def test_place_order_from_signal_returns_blocked_when_gate_raises():
    svc = SignalMonitorService()
    db = MagicMock()
    w = MagicMock()
    w.trade_amount_usd = 50
    w.trade_on_margin = False

    async def _run():
        with patch("app.core.trading_invariants_week5.validate_trading_decision", return_value=None):
            with patch("app.utils.live_trading.get_live_trading_status", return_value=True):
                with patch(
                    "app.services.live_trading_gate.assert_exchange_mutation_allowed",
                    side_effect=LiveTradingBlockedError("blocked"),
                ):
                    return await svc._place_order_from_signal(
                        db, "BTC_USDT", "BUY", w, 100_000.0
                    )

    r = asyncio.run(_run())
    assert r == {"error": "ORDER_BLOCKED_LIVE_TRADING", "blocked": True}


def test_place_order_from_signal_dry_run_reaches_broker_without_order_blocked():
    svc = SignalMonitorService()
    db = MagicMock()
    w = MagicMock()
    w.trade_amount_usd = 50
    w.trade_on_margin = False

    async def _run():
        with patch("app.core.trading_invariants_week5.validate_trading_decision", return_value=None):
            with patch("app.utils.live_trading.get_live_trading_status", return_value=False):
                with patch(
                    "app.services.signal_monitor.trade_client.place_market_order",
                    return_value={"order_id": "dry_1", "status": "FILLED"},
                ) as pm:
                    out = await svc._place_order_from_signal(
                        db, "BTC_USDT", "BUY", w, 100_000.0
                    )
                    return out, pm

    result, pm = asyncio.run(_run())
    pm.assert_called_once()
    call_kw = pm.call_args.kwargs
    assert call_kw.get("dry_run") is True
    assert result.get("order_id") == "dry_1"
    assert result.get("error") != "ORDER_BLOCKED_LIVE_TRADING"


def test_create_sell_order_returns_none_when_gate_raises():
    svc = SignalMonitorService()
    db = MagicMock()
    w = MagicMock()
    w.symbol = "ETH_USDT"
    w.trade_enabled = True
    w.trade_amount_usd = 50.0
    w.trade_on_margin = True

    async def _run():
        with patch("app.utils.live_trading.get_live_trading_status", return_value=True):
            with patch(
                "app.services.live_trading_gate.assert_exchange_mutation_allowed",
                side_effect=LiveTradingBlockedError("blocked"),
            ):
                return await svc._create_sell_order(db, w, 3000.0, 1.0, 1.0)

    assert asyncio.run(_run()) is None


def test_cancel_oco_sibling_returns_false_when_gate_raises():
    svc = ExchangeSyncService()
    filled = MagicMock()
    filled.exchange_order_id = "filled-1"
    filled.oco_group_id = "oco-1"
    filled.order_role = "STOP_LOSS"
    filled.symbol = "BTC_USDT"

    sibling = MagicMock()
    from app.models.exchange_order import OrderStatusEnum

    sibling.status = OrderStatusEnum.NEW
    sibling.exchange_order_id = "sib-1"
    sibling.order_role = "TAKE_PROFIT"
    sibling.symbol = "BTC_USDT"

    qm = MagicMock()
    qm.filter.return_value = qm
    qm.all.return_value = [sibling]
    db = MagicMock()
    db.query.return_value = qm

    with patch(
        "app.services.live_trading_gate.assert_exchange_mutation_allowed",
        side_effect=LiveTradingBlockedError("blocked"),
    ):
        assert svc._cancel_oco_sibling(db, filled) is False


def test_place_market_order_dry_run_does_not_call_broker_gate():
    with patch.dict(os.environ, {"LIVE_TRADING": "false"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
    with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
        with patch.dict(os.environ, {"VERIFY_ORDER_FORMAT": "0"}, clear=False):
            with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker") as req:
                out = client.place_market_order(
                    symbol="BTC_USDT",
                    side="BUY",
                    notional=10.0,
                    dry_run=True,
                )
    req.assert_not_called()
    assert str(out.get("order_id", "")).startswith("dry_market_")


def test_cancel_order_dry_path_skips_broker_gate():
    with patch.dict(os.environ, {"LIVE_TRADING": "false"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
    with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
        with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker") as req:
            client.cancel_order("order-dry-1")
    req.assert_not_called()


def test_cancel_order_live_path_invokes_broker_gate():
    with patch.dict(os.environ, {"LIVE_TRADING": "true"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
                with patch("app.services.live_trading_gate.require_mutation_allowed_for_broker") as req:
                    with patch.object(client, "_get_order_detail_summary", return_value={}):
                        with patch.object(client, "_is_advanced_oto_order", return_value=False):
                            with patch.object(
                                client,
                                "sign_request",
                                return_value={"skipped": True, "reason": "test_skip"},
                            ):
                                client.cancel_order("order-live-1")
            req.assert_called_once()


def _sltp_variation_kwargs(**overrides):
    base = {
        "instrument_name": "BTC_USDT",
        "side": "BUY",
        "quantity": 0.01,
        "ref_price": 100_000.0,
        "stop_loss_price": 99_000.0,
        "take_profit_price": 101_000.0,
        "correlation_id": "test-corr",
        "existing_sl_order_id": None,
        "existing_tp_order_id": None,
        "max_variants_per_order": 2,
    }
    base.update(overrides)
    return base


def test_sltp_variations_dry_run_skips_http_and_broker_gate():
    with patch.dict(os.environ, {"LIVE_TRADING": "false"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            with patch.object(client, "_create_order_try_variants") as cov:
                with patch(
                    "app.services.live_trading_gate.require_mutation_allowed_for_broker"
                ) as req:
                    out = client.create_stop_loss_take_profit_with_variations(
                        **_sltp_variation_kwargs()
                    )
    cov.assert_not_called()
    req.assert_not_called()
    assert out.get("dry_run") is True
    assert out.get("ok_sl") is False
    assert out.get("ok_tp") is False


def test_sltp_variations_explicit_dry_run_skips_even_when_env_live():
    with patch.dict(os.environ, {"LIVE_TRADING": "true"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            with patch.object(client, "_create_order_try_variants") as cov:
                with patch(
                    "app.services.live_trading_gate.require_mutation_allowed_for_broker"
                ) as req:
                    out = client.create_stop_loss_take_profit_with_variations(
                        **_sltp_variation_kwargs(), dry_run=True
                    )
    cov.assert_not_called()
    req.assert_not_called()
    assert out.get("dry_run") is True


def test_sltp_variations_dry_run_respects_existing_order_ids():
    with patch.dict(os.environ, {"LIVE_TRADING": "false"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            out = client.create_stop_loss_take_profit_with_variations(
                **_sltp_variation_kwargs(
                    existing_sl_order_id="sl-1",
                    existing_tp_order_id="tp-1",
                )
            )
    assert out["ok_sl"] is True
    assert out["ok_tp"] is True
    assert out["sl_order_id"] == "sl-1"
    assert out["tp_order_id"] == "tp-1"


def test_sltp_variations_live_mutate_invokes_gate_and_try_variants():
    with patch.dict(os.environ, {"LIVE_TRADING": "true"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            fake_ok = {
                "ok": True,
                "order_id": "x",
                "variant_id": "v",
                "attempts": 1,
                "errors": [],
            }

            with patch.object(client, "_build_sltp_variant_grid", return_value=[{}]):
                with patch.object(
                    client, "_create_order_try_variants", return_value=fake_ok
                ) as cov:
                    with patch(
                        "app.services.live_trading_gate.require_mutation_allowed_for_broker"
                    ) as req:
                        out = client.create_stop_loss_take_profit_with_variations(
                            **_sltp_variation_kwargs(), dry_run=False
                        )
    req.assert_called_once()
    assert cov.call_count == 2
    assert out.get("ok_sl") is True
    assert out.get("ok_tp") is True


def test_sltp_variations_gate_raises_before_try_variants():
    with patch.dict(os.environ, {"LIVE_TRADING": "true"}, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            client = CryptoComTradeClient()
            with patch.object(client, "_build_sltp_variant_grid", return_value=[{}]):
                with patch.object(client, "_create_order_try_variants") as cov:
                    with patch(
                        "app.services.live_trading_gate.require_mutation_allowed_for_broker",
                        side_effect=RuntimeError("gate_blocked"),
                    ):
                        with pytest.raises(RuntimeError, match="gate_blocked"):
                            client.create_stop_loss_take_profit_with_variations(
                                **_sltp_variation_kwargs(), dry_run=False
                            )
    cov.assert_not_called()
