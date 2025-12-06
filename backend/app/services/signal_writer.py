"""Signal writer service
Writes trade signals to database instead of Google Sheets
"""
import logging
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.models.trade_signal import (
    TradeSignal, PresetEnum, RiskProfileEnum, SignalStatusEnum
)
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)


def upsert_trade_signal(
    db: Session,
    symbol: str,
    preset: str = "swing",
    sl_profile: str = "conservative",
    rsi: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ema10: Optional[float] = None,
    ma10w: Optional[float] = None,
    atr: Optional[float] = None,
    resistance_up: Optional[float] = None,
    resistance_down: Optional[float] = None,
    current_price: Optional[float] = None,
    entry_price: Optional[float] = None,  # Price when signal was created
    volume_24h: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    should_trade: bool = False,
    status: str = "pending",
    exchange_order_id: Optional[str] = None,
    notes: Optional[str] = None
) -> TradeSignal:
    """
    Upsert a trade signal to the database
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "BTC_USDT")
        preset: Trading preset ("swing", "intraday", "scalp")
        sl_profile: Risk profile ("conservative", "aggressive")
        rsi: RSI value
        ma50: MA50 value
        ma200: MA200 value
        ema10: EMA10 value
        ma10w: MA10w value
        atr: ATR value
        resistance_up: Upper resistance
        resistance_down: Lower resistance
        current_price: Current price
        volume_24h: 24-hour volume
        volume_ratio: Volume ratio (current vs average)
        should_trade: Whether this signal should trigger trading
        status: Signal status ("pending", "order_placed", "filled", "closed", "archived")
        exchange_order_id: Exchange order ID if order placed
        notes: Additional notes
    
    Returns:
        TradeSignal object
    """
    try:
        # Map preset string to enum
        preset_enum = PresetEnum.SWING
        if preset.lower() == "intraday":
            preset_enum = PresetEnum.INTRADAY
        elif preset.lower() == "scalp":
            preset_enum = PresetEnum.SCALP
        
        # Map risk profile to enum
        risk_profile_enum = RiskProfileEnum.CONSERVATIVE
        if sl_profile.lower() == "aggressive":
            risk_profile_enum = RiskProfileEnum.AGGRESSIVE
        
        # Map status to enum
        status_enum = SignalStatusEnum.PENDING
        status_map = {
            "pending": SignalStatusEnum.PENDING,
            "order_placed": SignalStatusEnum.ORDER_PLACED,
            "filled": SignalStatusEnum.FILLED,
            "closed": SignalStatusEnum.CLOSED,
            "archived": SignalStatusEnum.ARCHIVED
        }
        status_enum = status_map.get(status.lower(), SignalStatusEnum.PENDING)
        
        # Check if signal already exists
        existing = db.query(TradeSignal).filter(
            TradeSignal.symbol == symbol
        ).first()
        
        if existing:
            # Update existing signal
            existing.preset = preset_enum
            existing.sl_profile = risk_profile_enum
            existing.rsi = rsi
            existing.ma50 = ma50
            existing.ma200 = ma200
            existing.ema10 = ema10
            existing.ma10w = ma10w
            existing.atr = atr
            existing.resistance_up = resistance_up
            existing.resistance_down = resistance_down
            existing.current_price = current_price
            # Only set entry_price if it's not already set (preserve original)
            if entry_price and not existing.entry_price:
                existing.entry_price = entry_price
            existing.volume_24h = volume_24h
            existing.volume_ratio = volume_ratio
            existing.should_trade = should_trade
            existing.status = status_enum
            if exchange_order_id:
                existing.exchange_order_id = exchange_order_id
            if notes:
                existing.notes = notes
            existing.last_update_at = datetime.utcnow()
            
            db.commit()
            logger.debug(f"Updated trade signal for {symbol}")
            return existing
        else:
            # Create new signal
            new_signal = TradeSignal(
                symbol=symbol,
                preset=preset_enum,
                sl_profile=risk_profile_enum,
                rsi=rsi,
                ma50=ma50,
                ma200=ma200,
                ema10=ema10,
                ma10w=ma10w,
                atr=atr,
                resistance_up=resistance_up,
                resistance_down=resistance_down,
                entry_price=entry_price or current_price,  # Set entry_price to current_price on creation
                current_price=current_price,
                volume_24h=volume_24h,
                volume_ratio=volume_ratio,
                should_trade=should_trade,
                status=status_enum,
                exchange_order_id=exchange_order_id,
                notes=notes
            )
            
            db.add(new_signal)
            db.commit()
            db.refresh(new_signal)
            logger.debug(f"Created new trade signal for {symbol}")
            return new_signal
            
    except Exception as e:
        logger.error(f"Error upserting trade signal for {symbol}: {e}", exc_info=True)
        db.rollback()
        raise


def sync_watchlist_to_signals(db: Session):
    """
    Sync watchlist items to trade signals
    This migrates existing watchlist data to the new signals table
    """
    try:
        watchlist_items = db.query(WatchlistItem).all()
        
        for item in watchlist_items:
            # Determine preset and risk profile from watchlist item
            preset = "swing"  # Default
            sl_profile = item.sl_tp_mode or "conservative"
            
            # Determine should_trade from trade_enabled
            should_trade = item.trade_enabled or False
            
            # Determine status from order_status
            status = "pending"
            if item.order_status == "PURCHASED":
                status = "filled"
            elif item.order_status == "SOLD":
                status = "closed"
            elif item.order_status == "PENDING" and item.purchase_price:
                status = "order_placed"
            
            upsert_trade_signal(
                db=db,
                symbol=item.symbol,
                preset=preset,
                sl_profile=sl_profile,
                rsi=item.rsi,
                ma50=item.ma50,
                ma200=item.ma200,
                ema10=item.ema10,
                atr=item.atr,
                resistance_up=item.res_up,
                resistance_down=item.res_down,
                current_price=item.price,
                should_trade=should_trade,
                status=status,
                notes=item.notes
            )
        
        db.commit()
        logger.info(f"Synced {len(watchlist_items)} watchlist items to trade signals")
        
    except Exception as e:
        logger.error(f"Error syncing watchlist to signals: {e}", exc_info=True)
        db.rollback()
        raise
