"""Unit tests for position dust thresholds in order_position_service."""

from decimal import Decimal

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import _is_position_dust, _infer_symbol_price


def _filled_buy(qty: str, price: str = "2500") -> ExchangeOrder:
    return ExchangeOrder(
        exchange_order_id="buy_1",
        symbol="ETH_USDT",
        side=OrderSideEnum.BUY,
        order_type="MARKET",
        status=OrderStatusEnum.FILLED,
        price=Decimal(price),
        quantity=Decimal(qty),
        cumulative_quantity=Decimal(qty),
        avg_price=Decimal(price),
    )


class TestIsPositionDust:
    def test_zero_net_is_dust(self):
        assert _is_position_dust(0.0, min_position_usd=5.0, last_price=2500.0) is True

    def test_usd_remnant_below_threshold_is_dust(self):
        # 0.0188 ETH @ $2500 ≈ $47 — dust when min USD is $50
        assert (
            _is_position_dust(
                0.0188,
                min_position_usd=50.0,
                last_price=2500.0,
            )
            is True
        )

    def test_usd_remnant_above_threshold_is_material(self):
        assert (
            _is_position_dust(
                0.0188,
                min_position_usd=5.0,
                last_price=2500.0,
            )
            is False
        )

    def test_qty_remnant_below_threshold_is_dust(self):
        assert _is_position_dust(0.0188, min_position_qty=0.05) is True

    def test_qty_remnant_above_threshold_is_material(self):
        assert _is_position_dust(0.1, min_position_qty=0.05) is False

    def test_no_thresholds_never_dust(self):
        assert _is_position_dust(0.0001) is False

    def test_usd_threshold_without_price_not_dust(self):
        assert _is_position_dust(0.0001, min_position_usd=5.0, last_price=None) is False


class TestInferSymbolPrice:
    def test_uses_avg_price_from_orders(self):
        price = _infer_symbol_price([_filled_buy("1", "3200")])
        assert price == 3200.0

    def test_returns_none_without_orders(self):
        assert _infer_symbol_price([]) is None
