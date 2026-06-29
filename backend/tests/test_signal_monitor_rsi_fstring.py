import inspect
import sys
from pathlib import Path

# Ensure `backend/` is on sys.path so `import app...` works when pytest is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_sell_condition_log_has_no_malformed_format_spec() -> None:
    """
    Regression guard for the malformed f-string format spec on the
    SELL_CONDITION_TRUE branch:
        rsi={rsi:.1f if rsi else 'N/A'}
    which raises ValueError: Invalid format specifier at runtime.
    """
    from app.services.signal_monitor import SignalMonitorService

    src = inspect.getsource(SignalMonitorService._check_signal_for_coin_sync)
    assert ":.1f if " not in src, "malformed f-string format spec must not be present"


def test_rsi_formatting_builds_without_value_error() -> None:
    """The intended rsi rendering must work for a numeric value and for None/falsy."""
    for rsi, expected in ((55.234, "rsi=55.2"), (None, "rsi=N/A"), (0, "rsi=N/A")):
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        assert f"rsi={rsi_str}" == expected
