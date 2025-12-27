#!/usr/bin/env python3
"""
Diagnostic script to check why BTC_USDT SELL alert is not triggering.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    db = SessionLocal()
    try:
        symbol = 'BTC_USDT'
        
        print(f"\n🔍 Diagnosticando por qué {symbol} no está enviando alerta SELL...\n")
        
        # 1. Check watchlist configuration
        print("=" * 60)
        print("1. CONFIGURACIÓN DE WATCHLIST")
        print("=" * 60)
        
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            print(f"❌ {symbol} no encontrado en watchlist")
            return
        
        print(f"✅ {symbol} encontrado en watchlist")
        print(f"   alert_enabled: {item.alert_enabled}")
        print(f"   buy_alert_enabled: {getattr(item, 'buy_alert_enabled', False)}")
        print(f"   sell_alert_enabled: {getattr(item, 'sell_alert_enabled', False)}")
        print(f"   trade_enabled: {item.trade_enabled}")
        print(f"   trade_amount_usd: {getattr(item, 'trade_amount_usd', None)}")
        print(f"   precio actual (price): {getattr(item, 'price', None)}")
        
        # Check for manual signals (these make the button red/green)
        manual_signals = None
        if hasattr(item, 'signals') and item.signals:
            try:
                import json
                if isinstance(item.signals, str):
                    manual_signals = json.loads(item.signals)
                elif isinstance(item.signals, dict):
                    manual_signals = item.signals
                if manual_signals:
                    print(f"   señales manuales (signals): {manual_signals}")
                    if manual_signals.get('sell'):
                        print(f"   ⚠️  SEÑAL SELL MANUAL ACTIVA (esto hace que el botón esté rojo)")
            except Exception as e:
                logger.debug(f"Could not parse signals: {e}")
        
        # Check if all required flags are enabled
        if not item.alert_enabled:
            print(f"\n❌ PROBLEMA: alert_enabled = False (requerido para alertas)")
        if not getattr(item, 'sell_alert_enabled', False):
            print(f"\n❌ PROBLEMA: sell_alert_enabled = False (requerido para alertas SELL)")
        
        # 2. Check throttling state
        print("\n" + "=" * 60)
        print("2. ESTADO DE THROTTLING (SELL)")
        print("=" * 60)
        
        # Get strategy to find throttle state
        try:
            from app.services.strategy_profiles import resolve_strategy_profile
            from app.services.signal_throttle import build_strategy_key
            
            strategy_profile = resolve_strategy_profile(symbol, db=db, watchlist_item=item)
            strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
            
            print(f"   strategy_key: {strategy_key}")
            
            throttle_state = db.query(SignalThrottleState).filter(
                SignalThrottleState.symbol == symbol,
                SignalThrottleState.strategy_key == strategy_key,
                SignalThrottleState.side == "SELL"
            ).first()
            
            if throttle_state:
                print(f"✅ Estado de throttling SELL encontrado:")
                print(f"   last_time: {throttle_state.last_time}")
                print(f"   last_price (baseline): {throttle_state.last_price}")
                print(f"   force_next_signal: {throttle_state.force_next_signal}")
                if hasattr(throttle_state, 'last_reason'):
                    print(f"   last_reason: {throttle_state.last_reason}")
                
                if throttle_state.force_next_signal:
                    print(f"\n✅ force_next_signal = True → Debería permitir bypass inmediato")
                else:
                    print(f"\n⚠️  force_next_signal = False → Necesita pasar throttling normal")
            else:
                print(f"ℹ️  No hay estado de throttling SELL (esto es OK para primera vez)")
                
        except Exception as e:
            logger.error(f"Error checking throttling: {e}", exc_info=True)
        
        # 3. Check if signal monitor is running
        print("\n" + "=" * 60)
        print("3. ESTADO DEL MONITOR DE SEÑALES")
        print("=" * 60)
        
        try:
            from app.services.signal_monitor import signal_monitor_service
            
            print(f"   is_running: {signal_monitor_service.is_running}")
            print(f"   last_run_at: {signal_monitor_service.last_run_at}")
            
            if not signal_monitor_service.is_running:
                print(f"\n❌ PROBLEMA: Signal monitor NO está corriendo")
                print(f"   El monitor debe estar corriendo para evaluar señales y enviar alertas")
            else:
                print(f"\n✅ Signal monitor está corriendo")
                
        except Exception as e:
            logger.error(f"Error checking signal monitor: {e}", exc_info=True)
        
        # 4. Check current signals
        print("\n" + "=" * 60)
        print("4. SEÑALES ACTUALES")
        print("=" * 60)
        
        try:
            from app.services.trading_signals import calculate_trading_signals
            from app.api.routes_dashboard import _get_market_data_for_symbol
            
            # Get current market data
            market_data = _get_market_data_for_symbol(db, symbol)
            
            if market_data and hasattr(market_data, 'price') and market_data.price:
                current_price = float(market_data.price)
                print(f"   Precio de mercado actual: ${current_price}")
                
                # Calculate signals directly
                signals = calculate_trading_signals(
                    symbol=symbol,
                    price=current_price,
                    rsi=float(market_data.rsi) if market_data.rsi else None,
                    ma50=float(market_data.ma50) if market_data.ma50 else None,
                    ma200=float(market_data.ma200) if market_data.ma200 else None,
                    ema10=float(market_data.ema10) if market_data.ema10 else None,
                    strategy_type=strategy_profile[0],
                    risk_approach=strategy_profile[1]
                )
                
                if signals:
                    buy_signal = signals.get('buy_signal', False)
                    sell_signal = signals.get('sell_signal', False)
                    
                    print(f"   buy_signal: {buy_signal}")
                    print(f"   sell_signal: {sell_signal}")
                    
                    # Check if there are manual signals that override
                    has_manual_sell = False
                    if manual_signals and manual_signals.get('sell'):
                        has_manual_sell = True
                        print(f"\n⚠️  SEÑAL SELL MANUAL ACTIVA (botón rojo)")
                        print(f"   Las señales manuales tienen prioridad sobre las calculadas")
                        sell_signal = True  # Override for throttling check
                    
                    if not sell_signal and not has_manual_sell:
                        print(f"\n❌ PROBLEMA: sell_signal = False")
                        print(f"   No hay señal SELL activa según los indicadores técnicos")
                        if signals.get('sell_reason'):
                            print(f"   Razón: {signals.get('sell_reason')}")
                    else:
                        if has_manual_sell:
                            print(f"\n✅ sell_signal = True (MANUAL - botón rojo)")
                        else:
                            print(f"\n✅ sell_signal = True (calculada)")
                        if signals.get('sell_reason'):
                            print(f"   Razón: {signals.get('sell_reason')}")
                        
                        # Check throttling for SELL
                        if throttle_state:
                            from datetime import datetime, timezone
                            from app.services.signal_throttle import should_emit_signal, SignalThrottleConfig
                            
                            now = datetime.now(timezone.utc)
                            time_diff = (now - throttle_state.last_time).total_seconds()
                            baseline_price = throttle_state.last_price
                            price_change_pct = abs((current_price - baseline_price) / baseline_price * 100) if baseline_price else 0
                            
                            print(f"\n📊 Análisis de Throttling:")
                            print(f"   Tiempo desde última alerta: {time_diff:.1f} segundos (requiere >= 60)")
                            print(f"   Cambio de precio desde baseline: {price_change_pct:.2f}%")
                            print(f"   Baseline price: ${baseline_price}")
                            print(f"   Precio actual: ${current_price}")
                            
                            if throttle_state.force_next_signal:
                                print(f"\n✅ force_next_signal = True → Bypass activo, alerta debería enviarse")
                            elif time_diff < 60:
                                print(f"\n⚠️  BLOQUEADO: Tiempo insuficiente ({time_diff:.1f}s < 60s)")
                            else:
                                # Need to check price gate
                                try:
                                    from app.services.config_loader import get_alert_thresholds
                                    thresholds = get_alert_thresholds(strategy_profile[0], strategy_profile[1])
                                    min_change = thresholds.get('min_price_change_pct', 3.0)
                                    print(f"   Threshold requerido: {min_change}%")
                                    if price_change_pct >= min_change:
                                        print(f"\n✅ Throttling OK: Cambio de precio suficiente ({price_change_pct:.2f}% >= {min_change}%)")
                                    else:
                                        print(f"\n⚠️  BLOQUEADO: Cambio de precio insuficiente ({price_change_pct:.2f}% < {min_change}%)")
                                except Exception as e:
                                    logger.debug(f"Could not check price threshold: {e}")
                else:
                    print(f"⚠️  No se pudieron obtener señales para {symbol}")
                    
            else:
                print(f"⚠️  No se pudo obtener datos de mercado para {symbol}")
                
        except Exception as e:
            logger.error(f"Error checking signals: {e}", exc_info=True)
        
        # 5. Summary and recommendations
        print("\n" + "=" * 60)
        print("5. RESUMEN Y RECOMENDACIONES")
        print("=" * 60)
        
        issues = []
        if not item.alert_enabled:
            issues.append("❌ alert_enabled debe ser True")
        if not getattr(item, 'sell_alert_enabled', False):
            issues.append("❌ sell_alert_enabled debe ser True")
        
        try:
            if not signal_monitor_service.is_running:
                issues.append("❌ Signal monitor debe estar corriendo")
        except:
            pass
        
        if issues:
            print("\n⚠️  PROBLEMAS ENCONTRADOS:")
            for issue in issues:
                print(f"   {issue}")
        else:
            print("\n✅ Configuración básica correcta")
            print("\n💡 NOTAS IMPORTANTES:")
            print("   1. Cambiar el precio manualmente en la watchlist NO dispara alertas automáticamente")
            print("   2. El sistema evalúa señales basándose en el precio real del mercado, no el precio guardado en watchlist")
            print("   3. Las alertas se envían cuando:")
            print("      - El signal monitor está corriendo")
            print("      - Hay una señal SELL activa (sell_signal = True)")
            print("      - Los flags están habilitados (alert_enabled, sell_alert_enabled)")
            print("      - El throttling permite el envío (o force_next_signal = True)")
        
    except Exception as e:
        logger.error(f"❌ Error durante diagnóstico: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    main()

