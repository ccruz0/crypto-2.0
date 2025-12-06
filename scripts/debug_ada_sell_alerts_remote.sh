#!/usr/bin/env bash
# Debug script for ADA SELL alerts on AWS
# Usage: bash scripts/debug_ada_sell_alerts_remote.sh

set -euo pipefail

cd /Users/carloscruz/automated-trading-platform

echo "=========================================="
echo " ADA SELL ALERT DEBUG - AWS BACKEND"
echo "=========================================="
echo ""

echo "[1] Recent SELL decisions for ADA_USDT / ADA_USD"
echo "-------------------------------------------------"
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E 'ADA_USDT|ADA_USD' | grep 'DEBUG_STRATEGY_FINAL.*SELL' | tail -20
echo ""

echo "[2] SELL alert emissions and throttling"
echo "-------------------------------------------------"
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E 'ADA_USDT|ADA_USD' | grep -E 'ALERT_EMIT_FINAL.*SELL|ALERT_THROTTLE_DECISION.*SELL|send_sell_signal|SELL.*alert' | tail -30
echo ""

echo "[3] SELL signal detection"
echo "-------------------------------------------------"
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E 'ADA_USDT|ADA_USD' | grep -E 'SELL signal detected|NEW SELL signal|DEBUG_ALERT_FLOW.*SELL' | tail -20
echo ""

echo "[4] Throttle state for ADA (from database)"
echo "-------------------------------------------------"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && BACKEND_CONTAINER=\$(docker ps --format '{{.Names}}' | grep backend | head -1) && docker exec \$BACKEND_CONTAINER python3 -c \"
from app.database import SessionLocal
from app.models.signal_throttle import SignalThrottleState
db = SessionLocal()
states = db.query(SignalThrottleState).filter(SignalThrottleState.symbol.in_(['ADA_USDT', 'ADA_USD'])).all()
for s in states:
    print(f'{s.symbol} | {s.strategy_key} | {s.side} | last_price={s.last_price} | last_time={s.last_time} | source={s.last_source}')
\""
echo ""

echo "[5] Recent Monitoring entries for ADA"
echo "-------------------------------------------------"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && BACKEND_CONTAINER=\$(docker ps --format '{{.Names}}' | grep backend | head -1) && docker exec \$BACKEND_CONTAINER python3 -c \"
from app.database import SessionLocal
from app.models.monitoring import TelegramMessage
from datetime import datetime, timedelta, timezone
db = SessionLocal()
recent = datetime.now(timezone.utc) - timedelta(hours=2)
msgs = db.query(TelegramMessage).filter(
    TelegramMessage.message.like('%ADA%'),
    TelegramMessage.created_at >= recent
).order_by(TelegramMessage.created_at.desc()).limit(20).all()
for m in msgs:
    print(f'{m.created_at} | blocked={m.blocked} | {m.message[:100]}')
\""
echo ""

echo "=========================================="
echo " DEBUG COMPLETE"
echo "=========================================="

