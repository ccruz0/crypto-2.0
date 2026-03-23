#!/usr/bin/env python3
"""
Script to find symbols with active BUY or SELL signals
Uses the same logic as signal_monitor to ensure consistency
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import create_db_session
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData
import logging

logging.basicConfig(level=logging.WARNING)  # Reduce noise
logger = logging.getLogger(__name__)

def main():
    db = create_db_session()
    try:
        print("\n🔍 Buscando monedas con señales BUY/SELL activas...\n")
        
        # Get all active watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.alert_enabled == True
        ).all()
        
        active_signals = []
        
        for item in items:
            try:
                # Get market data from database (same as signal_monitor does)
                market_data = db.query(MarketData).filter(
                    MarketData.symbol == item.symbol
                ).first()
                
                if not market_data or not market_data.price or market_data.price <= 0:
                    continue
                
                # Get signals using calculate_trading_signals (same as signal_monitor)
                from app.services.trading_signals import calculate_trading_signals
                from app.services.strategy_profiles import resolve_strategy_profile
                
                strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
                strategy_type, risk_approach = strategy_profile
                
                signals_result = calculate_trading_signals(
                    symbol=item.symbol,
                    market_data=market_data,
                    strategy_type=strategy_type,
                    risk_approach=risk_approach,
                    watchlist_item=item,
                    db=db
                )
                
                buy_signal = signals_result.get('buy_signal', False) if signals_result else False
                sell_signal = signals_result.get('sell_signal', False) if signals_result else False
                
                if buy_signal or sell_signal:
                    active_signals.append({
                        'symbol': item.symbol,
                        'buy_signal': buy_signal,
                        'sell_signal': sell_signal,
                        'price': market_data.price,
                        'buy_alert_enabled': getattr(item, 'buy_alert_enabled', False),
                        'sell_alert_enabled': getattr(item, 'sell_alert_enabled', False),
                        'alert_enabled': item.alert_enabled,
                    })
                    
            except Exception as e:
                logger.debug(f"Error checking {item.symbol}: {e}")
                continue
        
        if active_signals:
            print("=" * 80)
            print(f"✅ Encontradas {len(active_signals)} moneda(s) con señales activas:\n")
            print("=" * 80)
            for sig in active_signals:
                signal_types = []
                if sig['buy_signal']:
                    signal_types.append("BUY")
                if sig['sell_signal']:
                    signal_types.append("SELL")
                
                alert_status = []
                if sig['buy_signal'] and sig['buy_alert_enabled']:
                    alert_status.append("✅ BUY alert enabled")
                elif sig['buy_signal'] and not sig['buy_alert_enabled']:
                    alert_status.append("❌ BUY alert disabled")
                    
                if sig['sell_signal'] and sig['sell_alert_enabled']:
                    alert_status.append("✅ SELL alert enabled")
                elif sig['sell_signal'] and not sig['sell_alert_enabled']:
                    alert_status.append("❌ SELL alert disabled")
                
                print(f"\n📊 {sig['symbol']}")
                print(f"   Señales: {', '.join(signal_types)}")
                print(f"   Precio: ${sig['price']:.4f}")
                print(f"   Estado: {', '.join(alert_status) if alert_status else 'N/A'}")
                print(f"   alert_enabled: {sig['alert_enabled']}")
            print("\n" + "=" * 80)
            print("\n💡 Recomendación: Usar la primera moneda de la lista para la prueba")
            if active_signals:
                print(f"   Ejemplo: {active_signals[0]['symbol']}\n")
        else:
            print("❌ No se encontraron monedas con señales BUY/SELL activas en este momento")
            print("\n💡 Las señales cambian dinámicamente basándose en condiciones del mercado")
            print("   Intenta ejecutar este script más tarde o verifica manualmente en el dashboard\n")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    main()
