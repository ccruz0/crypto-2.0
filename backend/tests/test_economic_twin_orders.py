"""Unit tests for Crypto.com TP/SL dual-ID (trigger + spot remap) dedupe."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.utils.economic_twin_orders import (
    choose_canonical_protection_close,
    dedupe_protection_close_twins,
    protection_close_fingerprint,
    shadow_protection_close_ids_against_canonicals,
)


def _order(**kwargs):
    defaults = dict(
        exchange_order_id="x",
        symbol="AAVE_USD",
        side=SimpleNamespace(value="SELL"),
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status="FILLED",
        price=Decimal("93.15"),
        avg_price=Decimal("93.163"),
        quantity=Decimal("0.108"),
        cumulative_quantity=Decimal("0.108"),
        cumulative_value=Decimal("0"),
        parent_order_id="5755600492185071232",
        oco_group_id=None,
        exchange_create_time=datetime(2026, 7, 25, 0, 10, 40, tzinfo=timezone.utc),
        exchange_update_time=datetime(2026, 7, 26, 6, 33, 8, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 25, 0, 10, 40, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestProtectionCloseTwinDedupe(unittest.TestCase):
    def test_aave_prod_twins_keep_oco_trigger(self):
        trigger = _order(
            exchange_order_id="73817490102030139",
            oco_group_id="oco_5755600492185071232_1784938239",
            cumulative_value=Decimal("10.061604"),
            price=Decimal("93.15"),
            avg_price=Decimal("93.163"),
            exchange_update_time=datetime(2026, 7, 26, 6, 33, 8, tzinfo=timezone.utc),
        )
        shadow = _order(
            exchange_order_id="5755600492222958387",
            oco_group_id=None,
            cumulative_value=Decimal("0"),
            price=Decimal("93.163"),
            avg_price=Decimal("93.163"),
            exchange_create_time=datetime(2026, 7, 25, 0, 10, 40, tzinfo=timezone.utc),
            exchange_update_time=datetime(2026, 7, 26, 6, 33, 10, tzinfo=timezone.utc),
            created_at=datetime(2026, 7, 26, 6, 33, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(
            protection_close_fingerprint(trigger),
            protection_close_fingerprint(shadow),
        )
        self.assertEqual(
            choose_canonical_protection_close([trigger, shadow]).exchange_order_id,
            "73817490102030139",
        )
        deduped = dedupe_protection_close_twins([shadow, trigger])
        ids = [o.exchange_order_id for o in deduped]
        self.assertEqual(ids, ["73817490102030139"])

    def test_shadow_only_on_page_dropped_when_canonical_in_siblings(self):
        trigger = _order(
            exchange_order_id="73817490102030139",
            oco_group_id="oco_x",
            cumulative_value=Decimal("10"),
        )
        shadow = _order(
            exchange_order_id="5755600492222958387",
            oco_group_id=None,
            cumulative_value=Decimal("0"),
            exchange_update_time=trigger.exchange_update_time + timedelta(seconds=2),
        )
        drop = shadow_protection_close_ids_against_canonicals(
            [shadow], [trigger, shadow]
        )
        self.assertEqual(drop, {"5755600492222958387"})

    def test_unrelated_second_tp_not_dropped(self):
        first = _order(
            exchange_order_id="tp-1",
            oco_group_id="oco-1",
            cumulative_value=Decimal("10"),
            exchange_update_time=datetime(2026, 7, 26, 6, 33, 8, tzinfo=timezone.utc),
        )
        later = _order(
            exchange_order_id="tp-2",
            parent_order_id="other-parent",
            oco_group_id="oco-2",
            cumulative_value=Decimal("10"),
            exchange_update_time=datetime(2026, 7, 27, 6, 33, 8, tzinfo=timezone.utc),
        )
        deduped = dedupe_protection_close_twins([first, later])
        self.assertEqual({o.exchange_order_id for o in deduped}, {"tp-1", "tp-2"})


if __name__ == "__main__":
    unittest.main()
