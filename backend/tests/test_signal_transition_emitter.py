"""
Tests for signal transition emitter service
"""
import pytest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from app.database import Base
from app.models.watchlist import WatchlistItem
from app.services.signal_transition_emitter import check_and_emit_on_transition


@pytest.fixture
def db_session():
    """Provide an isolated in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create tables manually, skipping indexes to avoid conflicts
    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_check_and_emit_on_transition_no_watchlist_item(db_session):
    """check_and_emit_on_transition handles missing watchlist item gracefully."""
    with patch('app.services.signal_transition_emitter.get_canonical_watchlist_item') as mock_get_item:
        mock_get_item.return_value = None

        transition_detected, result = check_and_emit_on_transition(
            db=db_session,
            symbol="BTC_USD",
            current_buy_signal=True,
            current_sell_signal=False,
            current_price=50000.0
        )

        assert transition_detected is False
        assert result["symbol"] == "BTC_USD"
        assert result["buy_transition"] is False
        assert result["sell_transition"] is False
        assert result["telegram_sent"] is False
        assert result["order_placed"] is False
        assert len(result["errors"]) == 0


def test_check_and_emit_on_transition_disabled_alerts(db_session):
    """check_and_emit_on_transition skips when alerts are disabled."""
    # Create a mock watchlist item with alerts disabled
    mock_item = Mock(spec=WatchlistItem)
    mock_item.alert_enabled = False
    mock_item.trade_enabled = False

    with patch('app.services.signal_transition_emitter.get_canonical_watchlist_item') as mock_get_item, \
         patch('app.services.signal_transition_emitter.resolve_strategy_profile') as mock_resolve, \
         patch('app.services.signal_transition_emitter.fetch_signal_states') as mock_fetch:

        mock_get_item.return_value = mock_item
        mock_resolve.return_value = ("conservative", "swing")
        mock_fetch.return_value = {}

        transition_detected, result = check_and_emit_on_transition(
            db=db_session,
            symbol="BTC_USD",
            current_buy_signal=True,
            current_sell_signal=False,
            current_price=50000.0
        )

        assert transition_detected is False
        assert result["symbol"] == "BTC_USD"
        assert len(result["errors"]) == 0


def test_check_and_emit_on_transition_emission_failure_handled(db_session):
    """check_and_emit_on_transition handles emission failures without crashing."""
    # Create a mock watchlist item with alerts enabled
    mock_item = Mock(spec=WatchlistItem)
    mock_item.alert_enabled = True
    mock_item.buy_alert_enabled = True
    mock_item.sell_alert_enabled = False
    mock_item.trade_enabled = False
    mock_item.symbol = "BTC_USD"

    with patch('app.services.signal_transition_emitter.get_canonical_watchlist_item') as mock_get_item, \
         patch('app.services.signal_transition_emitter.resolve_strategy_profile') as mock_resolve, \
         patch('app.services.signal_transition_emitter.fetch_signal_states') as mock_fetch, \
         patch('app.services.signal_transition_emitter.should_emit_signal') as mock_should_emit, \
         patch('app.services.signal_transition_emitter.get_alert_thresholds') as mock_thresholds, \
         patch('app.services.signal_transition_emitter.signal_monitor_service') as mock_monitor:

        mock_get_item.return_value = mock_item
        mock_resolve.return_value = ("conservative", "swing")
        mock_fetch.return_value = {}
        mock_thresholds.return_value = (0.01, 60.0)  # 1% price change, 60 min cooldown
        mock_should_emit.return_value = (True, "throttle allows")

        # Make signal_monitor_service._check_signal_for_coin_sync raise an exception
        mock_monitor._check_signal_for_coin_sync.side_effect = Exception("Emission failed")

        transition_detected, result = check_and_emit_on_transition(
            db=db_session,
            symbol="BTC_USD",
            current_buy_signal=True,
            current_sell_signal=False,
            current_price=50000.0,
            watchlist_item=mock_item
        )

        # Should detect transition but emission should fail gracefully
        assert transition_detected is True
        assert result["buy_transition"] is True
        assert result["sell_transition"] is False
        assert result["telegram_sent"] is False  # Failed to send
        assert result["order_placed"] is False
        assert len(result["errors"]) == 1
        assert "Emission failed" in result["errors"][0]


def test_check_and_emit_on_transition_success(db_session):
    """check_and_emit_on_transition works successfully when all components succeed."""
    # Create a mock watchlist item with alerts enabled
    mock_item = Mock(spec=WatchlistItem)
    mock_item.alert_enabled = True
    mock_item.buy_alert_enabled = True
    mock_item.sell_alert_enabled = False
    mock_item.trade_enabled = True
    mock_item.symbol = "BTC_USD"

    with patch('app.services.signal_transition_emitter.get_canonical_watchlist_item') as mock_get_item, \
         patch('app.services.signal_transition_emitter.resolve_strategy_profile') as mock_resolve, \
         patch('app.services.signal_transition_emitter.fetch_signal_states') as mock_fetch, \
         patch('app.services.signal_transition_emitter.should_emit_signal') as mock_should_emit, \
         patch('app.services.signal_transition_emitter.get_alert_thresholds') as mock_thresholds, \
         patch('app.services.signal_transition_emitter.signal_monitor_service') as mock_monitor:

        mock_get_item.return_value = mock_item
        mock_resolve.return_value = ("conservative", "swing")
        mock_fetch.return_value = {}
        mock_thresholds.return_value = (0.01, 60.0)  # 1% price change, 60 min cooldown
        mock_should_emit.return_value = (True, "throttle allows")

        # Make signal_monitor_service._check_signal_for_coin_sync succeed
        mock_monitor._check_signal_for_coin_sync.return_value = None

        transition_detected, result = check_and_emit_on_transition(
            db=db_session,
            symbol="BTC_USD",
            current_buy_signal=True,
            current_sell_signal=False,
            current_price=50000.0,
            watchlist_item=mock_item
        )

        # Should detect transition and emission should succeed
        assert transition_detected is True
        assert result["buy_transition"] is True
        assert result["sell_transition"] is False
        assert result["telegram_sent"] is True
        assert result["order_placed"] is True  # trade_enabled=True
        assert len(result["errors"]) == 0