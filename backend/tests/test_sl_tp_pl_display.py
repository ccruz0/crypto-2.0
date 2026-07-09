"""Tests for SL/TP Telegram profit/loss display formatting."""
import re
import unittest
from unittest.mock import patch

from app.services.telegram_notifier import TelegramNotifier


class TestSlTpProfitLossDisplay(unittest.TestCase):
    @patch.object(TelegramNotifier, "send_message", return_value=True)
    def test_short_entry_shows_negative_sl_loss(self, mock_send):
        notifier = TelegramNotifier()
        notifier.send_sl_tp_orders(
            symbol="ETH_USD",
            sl_price=1969.73,
            tp_price=1772.75,
            quantity=0.0558,
            mode="conservative",
            sl_order_id="sl-1",
            tp_order_id="tp-1",
            original_order_id="parent-1",
            sl_side="BUY",
            tp_side="BUY",
            entry_price=1790.66,
            sl_percentage=10.0,
            tp_percentage=1.0,
            original_order_side="SELL",
        )

        message = mock_send.call_args[0][0]
        sl_line = next(line for line in message.splitlines() if "If SL hits" in line)
        tp_line = next(line for line in message.splitlines() if "If TP hits" in line)
        self.assertRegex(sl_line, r"If SL hits: \$-[\d,]+\.\d+")
        self.assertRegex(sl_line, r"\(-[\d,]+\.\d+%\)")
        self.assertRegex(tp_line, r"If TP hits: \$[\d,]+\.\d+")
        self.assertRegex(tp_line, r"\([\d,]+\.\d+%\)")

    @patch.object(TelegramNotifier, "send_message", return_value=True)
    def test_long_entry_shows_negative_sl_loss(self, mock_send):
        notifier = TelegramNotifier()
        notifier.send_sl_tp_orders(
            symbol="ETH_USD",
            sl_price=1700.00,
            tp_price=1900.00,
            quantity=0.05,
            mode="conservative",
            entry_price=1800.00,
            original_order_side="BUY",
            sl_side="SELL",
            tp_side="SELL",
        )

        message = mock_send.call_args[0][0]
        sl_match = re.search(r"If SL hits: (\$-?[\d,]+\.\d+)", message)
        self.assertIsNotNone(sl_match)
        self.assertTrue(sl_match.group(1).startswith("$-"))


if __name__ == "__main__":
    unittest.main()
