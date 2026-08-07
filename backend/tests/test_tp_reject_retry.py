"""Fill-time TP must not treat REJECTED exchange legs as success (healing OFF)."""

from unittest.mock import MagicMock, patch

from app.services.tp_sl_order_creator import (
    create_take_profit_order,
    poll_protection_order_status,
)


class TestPollProtectionStatus:
    def test_prefers_advanced_detail(self):
        with patch("app.services.tp_sl_order_creator.trade_client") as tc:
            tc.get_advanced_order_detail.return_value = {
                "result": {"status": "REJECTED"}
            }
            assert poll_protection_order_status("tp-1", attempts=1) == "REJECTED"
            tc.get_order_detail.assert_not_called()


class TestCreateTpRejectRetry:
    def test_rejected_then_market_clamp_retry_succeeds(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(
            tp_percentage=1.0, trade_on_margin=True, leverage=None
        )

        place_calls = {"n": 0}

        def _place(**kwargs):
            place_calls["n"] += 1
            if place_calls["n"] == 1:
                return {"order_id": "tp-rej", "status": "REJECTED"}
            return {"order_id": "tp-ok", "status": "ACTIVE"}

        with patch(
            "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
            return_value=(True, None),
        ), patch(
            "app.services.tp_sl_order_creator.get_closing_side_from_entry",
            return_value="BUY",
        ), patch(
            "app.services.tp_sl_order_creator.can_place_real_order",
            return_value=(True, None),
        ), patch(
            "app.services.tp_sl_order_creator.trade_client"
        ) as tc, patch(
            "app.services.tp_sl_order_creator.poll_protection_order_status",
            side_effect=lambda oid, **kw: "ACTIVE" if str(oid) == "tp-ok" else "REJECTED",
        ), patch(
            "app.utils.sl_trigger_guard.fetch_last_price", return_value=0.597
        ), patch(
            "app.utils.sl_trigger_guard.ensure_valid_tp_trigger",
            side_effect=lambda **kw: (kw["tp_price"], None),
        ), patch(
            "app.utils.sl_trigger_guard.fetch_ticker_prices",
            return_value={"last": 0.597, "bid": 0.5965, "ask": 0.5975},
        ), patch(
            "app.utils.sl_trigger_guard.reference_price_for_trigger",
            return_value=0.5965,
        ), patch(
            "app.utils.sl_trigger_guard.compute_market_relative_tp",
            return_value=0.5905,
        ), patch(
            "app.utils.sl_trigger_guard.ensure_tp_clear_of_market_after_tick",
            side_effect=lambda **kw: kw["tp_price"],
        ):
            tc.place_take_profit_order.side_effect = _place
            tc._get_instrument_metadata.return_value = {
                "price_tick_size": "0.0001",
                "min_quantity": "0.01",
                "qty_tick_size": "0.01",
                "quantity_decimals": 2,
            }
            tc.normalize_quantity.return_value = "16.5"

            # First call sees REJECTED via place status; poll unused when place_status dead.
            # Force path through dead status without poll short-circuit:
            result = create_take_profit_order(
                db=db,
                symbol="APT_USD",
                side="SELL",
                tp_price=0.6,
                quantity=16.5,
                entry_price=0.6023,
                parent_order_id="entry-apt",
                dry_run=False,
                source="test",
            )

        assert result.get("order_id") == "tp-ok"
        assert result.get("error") is None
        assert place_calls["n"] == 2

    def test_rejected_without_retry_budget_returns_error(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock(
            tp_percentage=1.0, trade_on_margin=True, leverage=None
        )
        with patch(
            "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
            return_value=(True, None),
        ), patch(
            "app.services.tp_sl_order_creator.get_closing_side_from_entry",
            return_value="BUY",
        ), patch(
            "app.services.tp_sl_order_creator.can_place_real_order",
            return_value=(True, None),
        ), patch(
            "app.services.tp_sl_order_creator.trade_client"
        ) as tc:
            tc.place_take_profit_order.return_value = {
                "order_id": "tp-rej",
                "status": "REJECTED",
            }
            tc._get_instrument_metadata.return_value = {
                "price_tick_size": "0.0001",
                "min_quantity": "0.01",
                "qty_tick_size": "0.01",
                "quantity_decimals": 2,
            }
            tc.normalize_quantity.return_value = "16.5"
            with patch(
                "app.utils.sl_trigger_guard.fetch_last_price", return_value=0.597
            ), patch(
                "app.utils.sl_trigger_guard.ensure_valid_tp_trigger",
                side_effect=lambda **kw: (kw["tp_price"], None),
            ):
                result = create_take_profit_order(
                    db=db,
                    symbol="APT_USD",
                    side="SELL",
                    tp_price=0.6,
                    quantity=16.5,
                    entry_price=0.6023,
                    parent_order_id="entry-apt",
                    dry_run=False,
                    source="test",
                    _allow_reject_retry=False,
                )
        assert result.get("order_id") is None
        assert "REJECTED" in str(result.get("error") or "")
