from unittest.mock import patch

from app.services.brokers.crypto_com_trade import CryptoComTradeClient


def _client(live):
    c = CryptoComTradeClient.__new__(CryptoComTradeClient)
    c.live_trading = live
    return c


def test_aws_uses_caller_dry_run():
    c = _client(False)  # AWS pinnea live_trading=False
    with patch("app.core.runtime.is_aws_runtime", return_value=True):
        assert c._resolve_actual_dry_run(False) is False  # LIVE -> orden real
        assert c._resolve_actual_dry_run(True) is True  # caller dry -> dry


def test_local_honors_live_trading():
    with patch("app.core.runtime.is_aws_runtime", return_value=False):
        assert _client(True)._resolve_actual_dry_run(False) is False
        assert _client(False)._resolve_actual_dry_run(False) is True
