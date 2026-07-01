"""Risk guard equity source: must use get_equity_from_user_balance, not get_account_summary."""
from unittest.mock import patch

import pytest

from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.services.risk_guard import RiskViolationError, check_trade_allowed


def test_place_market_order_passes_user_balance_equity_to_risk_guard():
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)

    with patch("app.core.runtime.is_aws_runtime", return_value=True):
        client = CryptoComTradeClient()
        with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
            with patch.object(
                client,
                "get_equity_from_user_balance",
                return_value=(37000.0, 21000.0, 0.0),
            ) as get_equity:
                with patch("app.services.risk_guard.check_trade_allowed", side_effect=_capture):
                    with patch(
                        "app.services.live_trading_gate.require_mutation_allowed_for_broker"
                    ):
                        with patch.object(
                            client,
                            "sign_request",
                            return_value={"skipped": True, "reason": "test"},
                        ):
                            client.place_market_order(
                                symbol="DOT_USD",
                                side="BUY",
                                notional=10.0,
                                dry_run=False,
                                source="TEST",
                            )
                get_equity.assert_called_once()

    assert captured["account_equity"] == 37000.0
    assert captured["total_margin_exposure"] == 21000.0
    assert captured["daily_loss_pct"] == 0.0


def test_positive_user_balance_equity_not_blocked_on_equity_check():
    """With real risk_guard, positive equity must not trip the zero-equity guard."""
    try:
        check_trade_allowed(
            symbol="DOT_USD",
            side="BUY",
            is_margin=False,
            leverage=None,
            trade_value_usd=10.0,
            entry_price=None,
            account_equity=37000.0,
            total_margin_exposure=0.0,
            daily_loss_pct=0.0,
            trade_on_margin_from_watchlist=False,
        )
    except RiskViolationError as exc:
        assert "Account equity must be positive" not in str(exc)


def test_equity_lookup_failure_blocks_trade_fail_safe():
    with patch("app.core.runtime.is_aws_runtime", return_value=True):
        client = CryptoComTradeClient()
        with patch("app.services.brokers.crypto_com_trade.require_aws_or_skip", return_value=None):
            with patch.object(
                client,
                "get_equity_from_user_balance",
                side_effect=ValueError("equity unavailable"),
            ):
                with patch(
                    "app.services.live_trading_gate.require_mutation_allowed_for_broker"
                ):
                    with pytest.raises(RiskViolationError, match="Risk check failed"):
                        client.place_market_order(
                            symbol="ETH_USDT",
                            side="BUY",
                            notional=10.0,
                            dry_run=False,
                            source="TEST",
                        )
