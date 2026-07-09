"""Tests for first-alert price change consistency in Telegram signals."""
import unittest
from unittest.mock import patch

from app.services.signal_monitor import SignalMonitorService
from app.services.telegram_notifier import TelegramNotifier


class TestFirstAlertPriceChange(unittest.TestCase):
    def test_is_first_side_alert_detects_throttle_reason(self):
        self.assertTrue(
            SignalMonitorService._is_first_side_alert(
                "No previous same-side signal recorded - allowing first signal"
            )
        )
        self.assertFalse(
            SignalMonitorService._is_first_side_alert(
                "Δt=5.23m>= 5.00m & |Δp|=↑ 1.50%>= 1.00%"
            )
        )

    def test_resolve_previous_alert_price_skips_cross_strategy_on_first_alert(self):
        service = SignalMonitorService()
        with patch.object(
            SignalMonitorService,
            "_get_last_alert_price",
            return_value=0.89,
        ) as mock_last:
            resolved = service._resolve_previous_alert_price(
                snapshot_price=None,
                symbol="DOT_USD",
                side="BUY",
                throttle_reason="No previous same-side signal recorded",
                db=object(),
            )
        self.assertIsNone(resolved)
        mock_last.assert_not_called()

    def test_resolve_previous_alert_price_uses_cross_strategy_when_not_first(self):
        service = SignalMonitorService()
        with patch.object(
            SignalMonitorService,
            "_get_last_alert_price",
            return_value=0.89,
        ) as mock_last:
            resolved = service._resolve_previous_alert_price(
                snapshot_price=None,
                symbol="DOT_USD",
                side="BUY",
                throttle_reason="Δt=6.00m>= 5.00m & |Δp|=↑ 2.00%>= 1.00%",
                db=object(),
            )
        self.assertEqual(resolved, 0.89)
        mock_last.assert_called_once()

    @patch.object(TelegramNotifier, "send_message", return_value=True)
    def test_send_buy_signal_first_alert_ignores_price_variation(self, mock_send):
        notifier = TelegramNotifier()
        notifier.send_buy_signal(
            symbol="DOT_USD",
            price=0.8328,
            reason="Scalp/Conservative",
            price_variation="-6.36%",
            previous_price=0.89,
            throttle_reason="No previous same-side signal recorded",
            origin="AWS",
        )

        message = mock_send.call_args[0][0]
        self.assertIn("Cambio desde última alerta: Primera alerta", message)
        self.assertNotIn("-6.36%", message)
        self.assertIn("Primera alerta para este símbolo/lado", message)


if __name__ == "__main__":
    unittest.main()
