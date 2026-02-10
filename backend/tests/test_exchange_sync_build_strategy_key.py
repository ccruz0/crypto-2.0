"""Minimal unit test: exchange_sync exposes callable build_strategy_key returning non-empty string."""
# No DB, network, or other services required.


def test_exchange_sync_build_strategy_key_callable_and_returns_string():
    import app.services.exchange_sync as m
    assert hasattr(m, "build_strategy_key") and callable(m.build_strategy_key)
    # With no args (fallback returns "default:default")
    result_empty = m.build_strategy_key()
    assert isinstance(result_empty, str) and len(result_empty) > 0
    # With args
    result_xy = m.build_strategy_key("x", "y")
    assert isinstance(result_xy, str) and len(result_xy) > 0
