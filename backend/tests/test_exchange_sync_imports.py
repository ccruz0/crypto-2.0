"""Lightweight sanity check: exchange_sync imports and build_strategy_key is available and callable."""
import pytest


def test_exchange_sync_imports_and_build_strategy_key():
    """Import exchange_sync and ensure build_strategy_key exists and returns a string."""
    import app.services.exchange_sync as exchange_sync
    assert hasattr(exchange_sync, "build_strategy_key"), "exchange_sync must expose build_strategy_key"
    build_strategy_key = exchange_sync.build_strategy_key
    result = build_strategy_key("swing", "conservative")
    assert isinstance(result, str), "build_strategy_key must return str"
    assert ":" in result, "build_strategy_key must return strategy:risk format"
