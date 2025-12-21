#!/usr/bin/env python3
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData
from app.services.config_loader import get_strategy_rules
from app.services.strategy_profiles import resolve_strategy_profile

db = SessionLocal()
# Handle both cases: with and without is_deleted column
try:
    if hasattr(WatchlistItem, 'is_deleted'):
        items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).order_by(WatchlistItem.symbol).all()
    else:
        items = db.query(WatchlistItem).order_by(WatchlistItem.symbol).all()
except Exception as e:
    # Fallback: query without filter if column doesn't exist
    items = db.query(WatchlistItem).order_by(WatchlistItem.symbol).all()

print('=' * 120)
print(f'REVISIÓN COMPLETA DE SÍMBOLOS - Total: {len(items)}')
print('=' * 120)

for item in items:
    symbol = item.symbol
    md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
    
    try:
        strategy_type, risk_approach = resolve_strategy_profile(symbol, item)
        rules = get_strategy_rules(strategy_type.value.lower(), risk_approach.value.capitalize())
        rsi_threshold = rules.get('rsi', {}).get('buyBelow', 'N/A')
        volume_ratio = rules.get('volumeMinRatio', 'N/A')
    except Exception as e:
        rsi_threshold = f'ERROR: {e}'
        volume_ratio = 'ERROR'
        strategy_type = None
        risk_approach = None
    
    print(f'\n{symbol}:')
    print(f'  Strategy: {strategy_type.value if strategy_type else "N/A"}/{risk_approach.value if risk_approach else "N/A"}')
    print(f'  Config: RSI BUY < {rsi_threshold}, Volume Ratio >= {volume_ratio}')
    
    if md:
        rsi_val = md.rsi if md.rsi is not None else 'None'
        ma50_val = md.ma50 if md.ma50 is not None else 'None'
        ema10_val = md.ema10 if md.ema10 is not None else 'None'
        vol_curr = md.current_volume if md.current_volume else 'None'
        vol_avg = md.avg_volume if md.avg_volume else 'None'
        vol_ratio = md.volume_ratio if md.volume_ratio else 'None'
        
        print(f'  MarketData: price={md.price}, rsi={rsi_val}, ma50={ma50_val}, ema10={ema10_val}')
        print(f'  Volume: current={vol_curr}, avg={vol_avg}, ratio={vol_ratio}')
        
        if md.rsi is not None and isinstance(rsi_threshold, (int, float)):
            rsi_ok = md.rsi < rsi_threshold
            status = '✅' if rsi_ok else '❌'
            print(f'  {status} RSI Check: {md.rsi:.2f} < {rsi_threshold} = {rsi_ok}')
        else:
            print(f'  ⚠️  RSI Check: Cannot evaluate (rsi={rsi_val}, threshold={rsi_threshold})')
    else:
        print(f'  ❌ MarketData: NOT FOUND')
    
    flags = []
    if item.alert_enabled: flags.append('alert')
    if item.buy_alert_enabled: flags.append('buy')
    if item.sell_alert_enabled: flags.append('sell')
    if item.trade_enabled: flags.append('trade')
    flags_str = ', '.join(flags) if flags else 'NONE'
    print(f'  Flags: {flags_str}')

db.close()




