"""Minimal tests for portfolio_consistency_check: empty data -> FAIL unless ALLOW_EMPTY_PORTFOLIO=1; drift > threshold -> FAIL."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Load script as module (scripts dir as parent for app.* imports)
_scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if _scripts_dir not in sys.path:
    sys.path.insert(0, os.path.dirname(_scripts_dir))


def test_empty_data_fails_without_allow_empty():
    """No portfolio data and ALLOW_EMPTY_PORTFOLIO unset -> FAIL (exit 1)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("portfolio_consistency_check", os.path.join(_scripts_dir, "portfolio_consistency_check.py"))
    pcc = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"ALLOW_EMPTY_PORTFOLIO": "", "DRIFT_THRESHOLD_PCT": "1.0"}, clear=False):
        with patch("app.database.SessionLocal", MagicMock(return_value=MagicMock())):
            with patch("app.services.portfolio_cache.get_portfolio_summary", return_value={"total_usd": 0.0, "balances": []}):
                with patch("app.services.brokers.crypto_com_trade.trade_client", MagicMock(get_account_summary=MagicMock(return_value={}))):
                    spec.loader.exec_module(pcc)
                    exit_code = pcc.main()
    assert exit_code == 1


def test_empty_data_passes_with_allow_empty():
    """No portfolio data but ALLOW_EMPTY_PORTFOLIO=1 -> PASS (exit 0)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("portfolio_consistency_check", os.path.join(_scripts_dir, "portfolio_consistency_check.py"))
    pcc = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"ALLOW_EMPTY_PORTFOLIO": "1", "DRIFT_THRESHOLD_PCT": "1.0"}, clear=False):
        with patch("app.database.SessionLocal", MagicMock(return_value=MagicMock())):
            with patch("app.services.portfolio_cache.get_portfolio_summary", return_value={"total_usd": 0.0, "balances": []}):
                with patch("app.services.brokers.crypto_com_trade.trade_client", MagicMock(get_account_summary=MagicMock(return_value={}))):
                    spec.loader.exec_module(pcc)
                    exit_code = pcc.main()
    assert exit_code == 0


def test_drift_above_threshold_fails():
    """Drift > DRIFT_THRESHOLD_PCT -> FAIL (exit 1)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("portfolio_consistency_check", os.path.join(_scripts_dir, "portfolio_consistency_check.py"))
    pcc = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"ALLOW_EMPTY_PORTFOLIO": "", "DRIFT_THRESHOLD_PCT": "1.0"}, clear=False):
        with patch("app.database.SessionLocal", MagicMock(return_value=MagicMock())):
            with patch("app.services.portfolio_cache.get_portfolio_summary", return_value={"total_usd": 100.0, "balances": [{"currency": "USD", "balance": 1, "usd_value": 100}]}):
                with patch("app.services.brokers.crypto_com_trade.trade_client", MagicMock(get_account_summary=MagicMock(return_value={"accounts": [{"wallet_balance": 90}]}))):
                    spec.loader.exec_module(pcc)
                    exit_code = pcc.main()
    assert exit_code == 1
