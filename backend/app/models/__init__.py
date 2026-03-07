from importlib import import_module

from app.models.watchlist import WatchlistItem
from app.models.watchlist_master import WatchlistMaster
from app.models.trade_signal import TradeSignal, PresetEnum, RiskProfileEnum, SignalStatusEnum
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.market_price import MarketPrice, MarketData
from app.models.trading_settings import TradingSettings
from app.models.dashboard_cache import DashboardCache
from app.models.telegram_message import TelegramMessage
from app.models.signal_throttle import SignalThrottleState
from app.models.telegram_state import TelegramState
from app.models.portfolio import PortfolioBalance, PortfolioSnapshot
from app.models.order_intent import OrderIntent
# fill_events_dedup may be absent in some deployments; avoid boot failure if missing.
try:
    FillEventDedup = getattr(import_module("app.models.fill_events_dedup"), "FillEventDedup")
except ModuleNotFoundError as e:
    if e.name == "app.models.fill_events_dedup":
        FillEventDedup = None
    else:
        raise
except AttributeError:
    FillEventDedup = None
from app.models.dedup_events_week5 import DedupEventWeek5
from app.models.agent_approval_state import AgentApprovalState

__all__ = [
    "WatchlistItem",
    "WatchlistMaster",
    "TradeSignal",
    "PresetEnum",
    "RiskProfileEnum",
    "SignalStatusEnum",
    "ExchangeBalance",
    "ExchangeOrder",
    "OrderSideEnum",
    "OrderStatusEnum",
    "MarketPrice",
    "MarketData",
    "TradingSettings",
    "DashboardCache",
    "TelegramMessage",
    "SignalThrottleState",
    "TelegramState",
    "PortfolioBalance",
    "PortfolioSnapshot",
    "OrderIntent",
    "FillEventDedup",
    "DedupEventWeek5",
    "AgentApprovalState",
]















