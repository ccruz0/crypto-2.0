"""
Buy Index Monitor Service
Calculates and sends BTC_USD buy proximity index (0-100) to Telegram every 2 minutes
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
from app.models.market_price import MarketData
from app.models.watchlist import WatchlistItem
from app.services.telegram_notifier import telegram_notifier
from app.services.trading_signals import calculate_trading_signals

logger = logging.getLogger(__name__)


class BuyIndexMonitorService:
    """Service to monitor and report BTC_USD buy proximity index"""
    
    def __init__(self):
        self.running = False
        self.interval_seconds = 120  # 2 minutes
        self.symbol = "BTC_USD"
    
    def calculate_buy_index(
        self,
        price: float,
        rsi: Optional[float],
        ma50: Optional[float],
        ema10: Optional[float],
        buy_target: Optional[float],
        rsi_buy_threshold: int = 40
    ) -> dict:
        """
        Calculate buy proximity index (0-100) based on how close conditions are to being met.
        
        Returns:
            dict with index (0-100), breakdown, and buy_signal status
        """
        index = 0
        breakdown = []
        
        # If already a buy signal, return 100
        signals = calculate_trading_signals(
            symbol=self.symbol,
            price=price,
            rsi=rsi,
            ma50=ma50,
            ema10=ema10,
            buy_target=buy_target,
            rsi_buy_threshold=rsi_buy_threshold
        )
        
        if signals.get("buy_signal"):
            return {
                "index": 100,
                "buy_signal": True,
                "breakdown": ["✅ All BUY conditions met"],
                "price": price,
                "rsi": rsi,
                "ma50": ma50,
                "ema10": ema10,
                "buy_target": buy_target
            }
        
        # Calculate proximity for each condition
        
        # 1. RSI condition (0-40 points)
        rsi_score = 0
        if rsi is not None:
            # RSI < 40 is ideal (40 points)
            # RSI between 40-50 gets partial points (linear)
            # RSI > 50 gets 0 points
            if rsi < rsi_buy_threshold:
                rsi_score = 40  # Full points
                breakdown.append(f"✅ RSI={rsi:.1f} < {rsi_buy_threshold}")
            elif rsi < 50:
                # Linear interpolation: 40 points at RSI=40, 0 points at RSI=50
                rsi_score = 40 * (1 - (rsi - rsi_buy_threshold) / (50 - rsi_buy_threshold))
                breakdown.append(f"🟡 RSI={rsi:.1f} (needs <{rsi_buy_threshold}, score: {rsi_score:.1f}/40)")
            else:
                breakdown.append(f"🔴 RSI={rsi:.1f} (too high, needs <{rsi_buy_threshold})")
        else:
            breakdown.append("⚠️ RSI not available")
        
        index += rsi_score
        
        # 2. Price <= buy_target condition (0-30 points)
        price_score = 0
        if buy_target is not None:
            if price <= buy_target:
                price_score = 30  # Full points
                breakdown.append(f"✅ Price ${price:,.2f} <= Target ${buy_target:,.2f}")
            else:
                # Calculate how close: if price is within 5% of target, give partial points
                price_diff_pct = ((price - buy_target) / buy_target) * 100
                if price_diff_pct <= 5:
                    # Linear: 30 points at 0% diff, 0 points at 5% diff
                    price_score = 30 * (1 - price_diff_pct / 5)
                    breakdown.append(f"🟡 Price ${price:,.2f} (${buy_target:,.2f} target, {price_diff_pct:.1f}% away, score: {price_score:.1f}/30)")
                else:
                    breakdown.append(f"🔴 Price ${price:,.2f} (${buy_target:,.2f} target, {price_diff_pct:.1f}% away)")
        else:
            # No buy target set - give partial points if price is reasonable
            breakdown.append("⚠️ No buy target set")
            price_score = 15  # Half points for no target
        
        index += price_score
        
        # 3. MA50 > EMA10 condition (0-30 points)
        trend_score = 0
        if ma50 is not None and ema10 is not None:
            if ma50 > ema10:
                trend_score = 30  # Full points
                breakdown.append(f"✅ MA50={ma50:,.2f} > EMA10={ema10:,.2f} (uptrend)")
            else:
                # Calculate how close: if MA50 is within 1% of EMA10, give partial points
                diff_pct = ((ema10 - ma50) / ema10) * 100
                if diff_pct <= 1:
                    # Linear: 30 points at 0% diff, 0 points at 1% diff
                    trend_score = 30 * (1 - diff_pct / 1)
                    breakdown.append(f"🟡 MA50={ma50:,.2f} vs EMA10={ema10:,.2f} (downtrend, {diff_pct:.2f}% away, score: {trend_score:.1f}/30)")
                else:
                    breakdown.append(f"🔴 MA50={ma50:,.2f} <= EMA10={ema10:,.2f} (downtrend)")
        else:
            breakdown.append("⚠️ MA50/EMA10 not available")
            trend_score = 15  # Half points for missing data
        
        index += trend_score
        
        # Ensure index is between 0-100
        index = max(0, min(100, round(index)))
        
        return {
            "index": index,
            "buy_signal": False,
            "breakdown": breakdown,
            "price": price,
            "rsi": rsi,
            "ma50": ma50,
            "ema10": ema10,
            "buy_target": buy_target,
            "scores": {
                "rsi": rsi_score,
                "price": price_score,
                "trend": trend_score
            }
        }
    
    def is_enabled(self, db: Session) -> bool:
        """Check if buy index monitoring is enabled"""
        try:
            setting = db.query(TradingSettings).filter(
                TradingSettings.setting_key == "BUY_INDEX_MONITOR_ENABLED"
            ).first()
            if setting:
                return setting.setting_value.lower() == "true"
            return False
        except Exception as e:
            logger.error(f"Error checking buy index monitor status: {e}")
            return False
    
    async def send_buy_index(self, db: Session):
        """Calculate and send buy index to Telegram"""
        try:
            # Get market data for BTC_USD
            # Use raw SQL query to avoid issues with missing columns
            from sqlalchemy import text
            try:
                result = db.execute(text(f"""
                    SELECT price, rsi, ma50, ema10, ma10w, atr, res_up, res_down
                    FROM market_data 
                    WHERE symbol = :symbol
                    LIMIT 1
                """), {"symbol": self.symbol})
                row = result.first()
                if not row:
                    logger.warning(f"No market data found for {self.symbol}")
                    return
                
                # Create a simple object to hold the data
                class MarketDataSimple:
                    def __init__(self, row):
                        self.price = row.price if row.price else None
                        self.rsi = row.rsi if row.rsi else None
                        self.ma50 = row.ma50 if row.ma50 else None
                        self.ema10 = row.ema10 if row.ema10 else None
                        self.ma10w = row.ma10w if row.ma10w else None
                        self.atr = row.atr if row.atr else None
                        self.res_up = row.res_up if row.res_up else None
                        self.res_down = row.res_down if row.res_down else None
                
                market_data = MarketDataSimple(row)
            except Exception as e:
                logger.error(f"Error querying market data: {e}")
                return
            
            if not market_data or not market_data.price:
                logger.warning(f"No market data found for {self.symbol}")
                return
            
            # Get watchlist item for buy_target
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == self.symbol,
                WatchlistItem.is_deleted == False
            ).first()
            
            buy_target = watchlist_item.buy_target if watchlist_item else None
            
            # Calculate buy index
            index_data = self.calculate_buy_index(
                price=market_data.price,
                rsi=market_data.rsi,
                ma50=market_data.ma50,
                ema10=market_data.ema10,
                buy_target=buy_target
            )
            
            # Format message
            index = index_data["index"]
            emoji = "🟢" if index >= 80 else "🟡" if index >= 50 else "🔴"
            
            message = f"""
{emoji} <b>BTC_USD BUY INDEX</b>

📊 <b>Index: {index}/100</b>
{'✅ BUY SIGNAL ACTIVE' if index_data['buy_signal'] else '⏳ Approaching BUY conditions'}

💵 Price: ${index_data['price']:,.2f}
📈 RSI: {index_data['rsi']:.1f if index_data['rsi'] is not None else 'N/A'}
📊 MA50: ${index_data['ma50']:,.2f if index_data['ma50'] is not None else 'N/A'}
📊 EMA10: ${index_data['ema10']:,.2f if index_data['ema10'] is not None else 'N/A'}
🎯 Buy Target: ${index_data['buy_target']:,.2f if index_data['buy_target'] is not None else 'Not set'}

<b>Breakdown:</b>
{chr(10).join(index_data['breakdown'])}

⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
            
            # Send to Telegram
            telegram_notifier.send_message(message.strip())
            logger.info(f"Sent BTC_USD buy index: {index}/100")
            
        except Exception as e:
            logger.error(f"Error sending buy index: {e}", exc_info=True)
    
    async def run(self):
        """Main monitoring loop"""
        logger.info(f"🚀 Buy Index Monitor Service started for {self.symbol}")
        self.running = True
        
        while self.running:
            try:
                db = SessionLocal()
                try:
                    if self.is_enabled(db):
                        await self.send_buy_index(db)
                    else:
                        logger.debug(f"Buy index monitor is disabled, skipping...")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Error in buy index monitor loop: {e}", exc_info=True)
            
            # Wait 2 minutes
            await asyncio.sleep(self.interval_seconds)
    
    def stop(self):
        """Stop the monitoring service"""
        logger.info("Stopping Buy Index Monitor Service")
        self.running = False


# Global instance
buy_index_monitor = BuyIndexMonitorService()

