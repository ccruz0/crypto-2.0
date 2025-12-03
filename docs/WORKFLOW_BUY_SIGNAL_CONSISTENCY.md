# BUY/SELL Signal Consistency Workflow

**Purpose:** Verificar que las señales BUY y SELL se detectan, evalúan y emiten de manera consistente en todo el sistema.

**Status:** ✅ Ready for use

---

## Overview

Este workflow valida que:
1. Las señales BUY y SELL se detectan correctamente por `calculate_trading_signals()`
2. Las señales BUY y SELL se evalúan de manera consistente entre debug script y live monitor
3. Las alertas BUY y SELL se emiten cuando `can_emit_buy_alert=True` o `can_emit_sell_alert=True`
4. Las señales BUY y SELL no se bloquean incorrectamente por flags o throttle
5. La consistencia entre Watchlist UI, debug script, y SignalMonitorService para ambas señales

---

## Cuando Usar

Usa este workflow cuando:
- Las señales BUY o SELL aparecen en el debug script pero no se emiten alertas
- El Watchlist UI muestra BUY o SELL pero no llegan alertas a Telegram
- Las señales BUY o SELL se bloquean incorrectamente
- Necesitas verificar que las señales BUY y SELL son consistentes después de cambios de código
- Hay discrepancias entre `BUY_SIGNALS_NOW` o `SELL_SIGNALS_NOW` del debug script y las alertas reales
- Necesitas verificar que SELL alerts funcionan independientemente de BUY alerts

---

## Pasos de Validación

### 1. Verificar Detección de Señales BUY y SELL

**Check:** `calculate_trading_signals()` detecta correctamente señales BUY y SELL

**Archivos a revisar:**
- `backend/app/services/trading_signals.py` - Lógica de cálculo de señales
- `backend/app/services/signal_evaluator.py` - Evaluación canónica

**Validación BUY:**
```python
# La señal BUY debe cumplir TODAS las condiciones:
# - buy_rsi_ok = True (RSI < threshold)
# - buy_ma_ok = True (MA checks según strategy)
# - buy_volume_ok = True (volume_ratio >= min_volume_ratio)
# - buy_target_ok = True (si buy_target está configurado)
# - buy_price_ok = True (precio dentro de rango)

signals = calculate_trading_signals(...)
buy_signal = signals.get("buy_signal", False)

# Si todas las condiciones se cumplen:
assert buy_signal == True
assert signals["strategy_state"]["decision"] == "BUY"
```

**Validación SELL:**
```python
# La señal SELL debe cumplir las condiciones:
# - sell_rsi_ok = True (RSI > threshold, típicamente 70)
# - sell_trend_ok = True (tendencia bajista detectada)
# - sell_volume_ok = True (volume_ratio >= min_volume_ratio)

signals = calculate_trading_signals(...)
sell_signal = signals.get("sell_signal", False)

# Si todas las condiciones se cumplen:
assert sell_signal == True
# Nota: decision puede ser "SELL" solo si buy_signal=False
```

**Log markers a verificar:**
- `[DEBUG_BUY_FLAGS]` - Muestra estado de cada flag BUY
- `[DEBUG_STRATEGY_FINAL]` - Muestra decisión final y flags (BUY y SELL)

---

### 2. Verificar Evaluación Consistente

**Check:** Debug script y live monitor usan la misma evaluación para BUY y SELL

**Validación:**
- Ambos usan `evaluate_signal_for_symbol()` (helper canónico)
- Ambos obtienen el mismo `decision`, `buy_signal`, `sell_signal`, `can_emit_buy_alert`, `can_emit_sell_alert`

**Comandos:**
```bash
# 1. Ejecutar debug script
docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py" | grep "SYMBOL_NAME"

# 2. Verificar logs del live monitor para el mismo símbolo
docker compose logs backend-aws | grep "SYMBOL_NAME" | grep "LIVE_ALERT_DECISION"

# 3. Comparar resultados BUY:
# - Debug script: DECISION=BUY, CAN_BUY=✓
# - Live monitor: decision=BUY, can_emit_buy=True

# 4. Comparar resultados SELL:
# - Debug script: DECISION=SELL, CAN_SELL=✓
# - Live monitor: decision=SELL, can_emit_sell=True
```

**Esperado:**
- Si debug script muestra `CAN_BUY=✓`, live monitor debe mostrar `can_emit_buy=True`
- Si debug script muestra `DECISION=BUY`, live monitor debe mostrar `decision=BUY`
- Si debug script muestra `CAN_SELL=✓`, live monitor debe mostrar `can_emit_sell=True`
- Si debug script muestra `DECISION=SELL`, live monitor debe mostrar `decision=SELL`

---

### 3. Verificar Flags de Alertas BUY y SELL

**Check:** Los flags `alert_enabled`, `buy_alert_enabled`, y `sell_alert_enabled` permiten emisión

**Validación BUY:**
```python
# Flags deben permitir emisión BUY:
alert_enabled = True
buy_alert_enabled = True (o None cuando alert_enabled=True)

# Si alert_enabled=True pero buy_alert_enabled=None:
# → buy_alert_enabled debe default a True

# can_emit_buy_alert = buy_allowed (throttle) AND buy_flag_allowed (flags)
can_emit_buy_alert = buy_allowed and (alert_enabled and buy_alert_enabled)
```

**Validación SELL:**
```python
# Flags deben permitir emisión SELL:
alert_enabled = True
sell_alert_enabled = True (o None cuando alert_enabled=True)

# Si alert_enabled=True pero sell_alert_enabled=None:
# → sell_alert_enabled debe default a True

# can_emit_sell_alert = sell_allowed (throttle) AND sell_flag_allowed (flags)
can_emit_sell_alert = sell_allowed and (alert_enabled and sell_alert_enabled)
```

**Código a revisar:**
- `backend/app/services/signal_evaluator.py` - Lógica de flags
- `backend/app/services/signal_monitor.py` - Uso de flags

**Log markers:**
- `[LIVE_ALERT_DECISION]` - Muestra `buy_flag_allowed`, `sell_flag_allowed`, `can_emit_buy`, `can_emit_sell`
- `[LIVE_BUY_SKIPPED]` - Muestra razón si alerta BUY no se emite
- `[LIVE_SELL_SKIPPED]` - Muestra razón si alerta SELL no se emite

---

### 4. Verificar Throttle para BUY y SELL

**Check:** El throttle permite emisión cuando las condiciones se cumplen (independiente para BUY y SELL)

**Validación BUY:**
```python
# Throttle debe permitir BUY si:
# - No hay señal BUY reciente (cooldown pasado)
# - O precio cambió suficiente (min_price_change_pct)
# - O tiempo suficiente desde última señal BUY (min_interval_minutes)

buy_allowed, buy_reason = should_emit_signal(
    symbol=symbol,
    side="BUY",
    current_price=current_price,
    current_time=now_utc,
    config=throttle_config,
    last_same_side=signal_snapshots.get("BUY"),
    last_opposite_side=signal_snapshots.get("SELL"),
)

# Si buy_allowed=True:
assert can_emit_buy_alert == True (si flags también permiten)
```

**Validación SELL:**
```python
# Throttle debe permitir SELL si:
# - No hay señal SELL reciente (cooldown pasado)
# - O precio cambió suficiente (min_price_change_pct)
# - O tiempo suficiente desde última señal SELL (min_interval_minutes)
# IMPORTANTE: Throttle SELL es independiente de throttle BUY

sell_allowed, sell_reason = should_emit_signal(
    symbol=symbol,
    side="SELL",
    current_price=current_price,
    current_time=now_utc,
    config=throttle_config,
    last_same_side=signal_snapshots.get("SELL"),
    last_opposite_side=signal_snapshots.get("BUY"),
)

# Si sell_allowed=True:
assert can_emit_sell_alert == True (si flags también permiten)
```

**Log markers:**
- `[ALERT_THROTTLE_DECISION] side=BUY` - Muestra decisión de throttle BUY
- `[ALERT_THROTTLE_DECISION] side=SELL` - Muestra decisión de throttle SELL
- `[LIVE_ALERT_DECISION]` - Muestra `buy_thr=SENT/BLOCKED` y `sell_thr=SENT/BLOCKED`

---

### 5. Verificar Emisión de Alertas BUY y SELL

**Check:** Las alertas BUY y SELL se envían cuando `can_emit_buy_alert=True` o `can_emit_sell_alert=True`

**Validación BUY:**
```python
# Si can_emit_buy_alert=True:
if can_emit_buy_alert:
    # Debe llamar send_buy_signal()
    result = telegram_notifier.send_buy_signal(...)
    
    # Debe registrar en Monitoring
    add_telegram_message(..., blocked=False)
    
    # Debe loggear emisión
    logger.info("[ALERT_EMIT_FINAL] side=BUY sent=True")
```

**Validación SELL:**
```python
# Si can_emit_sell_alert=True:
if can_emit_sell_alert:
    # Debe llamar send_sell_signal()
    result = telegram_notifier.send_sell_signal(...)
    
    # Debe registrar en Monitoring
    add_telegram_message(..., blocked=False)
    
    # Debe loggear emisión
    logger.info("[ALERT_EMIT_FINAL] side=SELL sent=True")
```

**Log markers a verificar BUY:**
- `[LIVE_BUY_CALL]` - Alerta BUY está por enviarse
- `[ALERT_EMIT_FINAL] side=BUY sent=True` - Alerta BUY enviada exitosamente
- `[LIVE_BUY_MONITORING]` - Registro en Monitoring

**Log markers a verificar SELL:**
- `[LIVE_SELL_CALL]` - Alerta SELL está por enviarse
- `[ALERT_EMIT_FINAL] side=SELL sent=True` - Alerta SELL enviada exitosamente
- `[LIVE_SELL_MONITORING]` - Registro en Monitoring

**Si NO se emite:**
- `[LIVE_BUY_SKIPPED]` - Muestra razón si alerta BUY no se emite
- `[LIVE_SELL_SKIPPED]` - Muestra razón si alerta SELL no se emite

---

### 6. Verificar Consistencia Watchlist UI

**Check:** El Watchlist UI muestra las mismas señales BUY y SELL que el backend

**Validación:**
1. Abrir Watchlist en dashboard
2. Verificar que símbolo muestra chip BUY (verde) o SELL (rojo)
3. Verificar tooltip muestra `decision=BUY/SELL` y `index=X`
4. Comparar con debug script y logs del live monitor

**API endpoint:**
```bash
# Obtener señal desde API
curl http://localhost:8002/api/market/dashboard | jq '.watchlist[] | select(.symbol == "SYMBOL_NAME") | {symbol, decision, index, buy_signal, sell_signal}'
```

**Esperado BUY:**
- UI muestra `decision="BUY"` → Backend debe mostrar `decision=BUY`
- UI muestra `index=80` → Backend debe mostrar `index=80`
- UI muestra `buy_signal=true` → Backend debe mostrar `buy_signal=True`

**Esperado SELL:**
- UI muestra `decision="SELL"` → Backend debe mostrar `decision=SELL`
- UI muestra `sell_signal=true` → Backend debe mostrar `sell_signal=True`
- UI muestra chip rojo → Backend debe mostrar `decision=SELL`

---

## Script de Auditoría

```bash
#!/usr/bin/env bash
# scripts/audit_buy_sell_signals.sh

SYMBOL="${1:-ALGO_USDT}"  # Símbolo a verificar (default: ALGO_USDT)

echo "=== BUY/SELL Signal Consistency Audit for $SYMBOL ==="
echo ""

# 1. Debug script
echo "1. Debug Script Result:"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws bash -c 'cd /app && python scripts/debug_live_signals_all.py'" | \
  grep -A 1 "$SYMBOL" | head -2

echo ""
echo "2. Live Monitor Logs (BUY and SELL):"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose logs backend-aws --tail 500 | grep '$SYMBOL' | grep -E 'LIVE_ALERT_DECISION|LIVE_BUY_CALL|LIVE_SELL_CALL|ALERT_EMIT_FINAL|LIVE_BUY_SKIPPED|LIVE_SELL_SKIPPED'" | \
  tail -15

echo ""
echo "3. Recent BUY Alerts in Monitoring:"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws python -c \"
from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from datetime import datetime, timedelta, timezone
db = SessionLocal()
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
alerts = db.query(TelegramMessage).filter(
    TelegramMessage.symbol == '$SYMBOL',
    TelegramMessage.timestamp >= cutoff,
    TelegramMessage.message.like('%BUY%')
).order_by(TelegramMessage.timestamp.desc()).limit(5).all()
for a in alerts:
    status = 'BLOCKED' if a.blocked else 'SENT'
    print(f'{a.timestamp} | {status} | {a.message[:80]}')
\""

echo ""
echo "4. Recent SELL Alerts in Monitoring:"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws python -c \"
from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from datetime import datetime, timedelta, timezone
db = SessionLocal()
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
alerts = db.query(TelegramMessage).filter(
    TelegramMessage.symbol == '$SYMBOL',
    TelegramMessage.timestamp >= cutoff,
    TelegramMessage.message.like('%SELL%')
).order_by(TelegramMessage.timestamp.desc()).limit(5).all()
for a in alerts:
    status = 'BLOCKED' if a.blocked else 'SENT'
    print(f'{a.timestamp} | {status} | {a.message[:80]}')
\""

echo ""
echo "5. Watchlist Item Flags:"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws python -c \"
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == '$SYMBOL').first()
if item:
    print(f'alert_enabled={item.alert_enabled}')
    print(f'buy_alert_enabled={getattr(item, \"buy_alert_enabled\", None)}')
    print(f'sell_alert_enabled={getattr(item, \"sell_alert_enabled\", None)}')
    print(f'trade_enabled={item.trade_enabled}')
\""
```

---

## Problemas Comunes

### Problema 1: Debug Script Muestra BUY/SELL pero No Hay Alertas

**Síntomas:**
- `debug_live_signals_all.py` muestra `CAN_BUY=✓` o `CAN_SELL=✓` para un símbolo
- No aparecen alertas BUY o SELL en Telegram o Monitoring

**Causas Posibles:**
1. Flags bloquean: `alert_enabled=False` o `buy_alert_enabled=False` / `sell_alert_enabled=False`
2. Throttle bloquea: Cooldown activo o precio no cambió suficiente
3. Live monitor no está corriendo o tiene error
4. Origin bloquea: `origin=LOCAL` en lugar de `origin=AWS`
5. **Para SELL:** Señal SELL anidada incorrectamente dentro de bloque BUY (bug corregido)

**Verificación:**
```bash
# 1. Verificar flags
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == 'SYMBOL').first()
print(f'alert_enabled={item.alert_enabled}')
print(f'buy_alert_enabled={getattr(item, \"buy_alert_enabled\", None)}')
print(f'sell_alert_enabled={getattr(item, \"sell_alert_enabled\", None)}')
"

# 2. Verificar throttle BUY
docker compose logs backend-aws | grep "SYMBOL" | grep "ALERT_THROTTLE_DECISION side=BUY"

# 3. Verificar throttle SELL
docker compose logs backend-aws | grep "SYMBOL" | grep "ALERT_THROTTLE_DECISION side=SELL"

# 4. Verificar live monitor
docker compose logs backend-aws | grep "LIVE_ALERT_DECISION" | grep "SYMBOL" | tail -5

# 5. Verificar origin
docker compose logs backend-aws | grep "SYMBOL" | grep "origin=" | tail -5
```

---

### Problema 2: Watchlist UI Muestra BUY/SELL pero Debug Script Muestra WAIT

**Síntomas:**
- Dashboard muestra chip BUY verde o SELL rojo
- Debug script muestra `DECISION=WAIT`

**Causas Posibles:**
1. UI usa datos cacheados/stale
2. UI y backend usan diferentes fuentes de indicadores
3. Timing: UI muestra señal anterior, debug script evalúa ahora
4. **Para SELL:** Señal SELL no se evalúa independientemente de BUY (bug corregido)

**Verificación:**
```bash
# 1. Forzar refresh en UI (recargar página)
# 2. Comparar timestamp de datos
curl http://localhost:8002/api/market/dashboard | jq '.watchlist[] | select(.symbol == "SYMBOL") | {symbol, decision, buy_signal, sell_signal, updated_at}'

# 3. Ejecutar debug script inmediatamente
docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py" | grep "SYMBOL"

# 4. Verificar que SELL se evalúa independientemente
docker compose logs backend-aws | grep "SYMBOL" | grep "LIVE_SELL_DECISION"
```

---

### Problema 3: Señales BUY/SELL se Bloquean por Throttle Incorrectamente

**Síntomas:**
- `buy_signal=True` pero `buy_allowed=False`
- `sell_signal=True` pero `sell_allowed=False`
- Throttle bloquea aunque no hay señal reciente

**Causas Posibles:**
1. Throttle state corrupto en base de datos
2. `min_price_change_pct` o `min_interval_minutes` muy restrictivos
3. Última señal tiene timestamp incorrecto
4. **Para SELL:** Throttle SELL usa estado de throttle BUY incorrectamente (bug corregido)

**Verificación:**
```bash
# 1. Verificar throttle state BUY
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.signal_state import SignalState
from datetime import datetime, timezone
db = SessionLocal()
state_buy = db.query(SignalState).filter(
    SignalState.symbol == 'SYMBOL',
    SignalState.side == 'BUY'
).order_by(SignalState.timestamp.desc()).first()
if state_buy:
    print(f'Last BUY: {state_buy.timestamp}, price={state_buy.price}')
"

# 2. Verificar throttle state SELL
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.signal_state import SignalState
from datetime import datetime, timezone
db = SessionLocal()
state_sell = db.query(SignalState).filter(
    SignalState.symbol == 'SYMBOL',
    SignalState.side == 'SELL'
).order_by(SignalState.timestamp.desc()).first()
if state_sell:
    print(f'Last SELL: {state_sell.timestamp}, price={state_sell.price}')
"

# 3. Verificar configuración throttle
docker compose logs backend-aws | grep "SYMBOL" | grep "min_price_change_pct\|min_interval_minutes"
```

---

## Comandos de Verificación Rápida

### 1. Verificar Señales BUY y SELL Activas

```bash
# Debug script - ver todos los BUY y SELL signals
docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py" | grep -E "BUY_SIGNALS_NOW|SELL_SIGNALS_NOW|CAN_BUY.*✓|CAN_SELL.*✓"

# Live monitor - ver decisiones BUY recientes
docker compose logs backend-aws --tail 1000 | grep "LIVE_ALERT_DECISION" | grep "decision=BUY" | tail -10

# Live monitor - ver decisiones SELL recientes
docker compose logs backend-aws --tail 1000 | grep "LIVE_ALERT_DECISION" | grep "decision=SELL" | tail -10
```

### 2. Verificar Emisión de Alertas BUY y SELL

```bash
# Ver alertas BUY enviadas
docker compose logs backend-aws --tail 1000 | grep "ALERT_EMIT_FINAL side=BUY sent=True" | tail -10

# Ver alertas SELL enviadas
docker compose logs backend-aws --tail 1000 | grep "ALERT_EMIT_FINAL side=SELL sent=True" | tail -10

# Ver alertas BUY bloqueadas
docker compose logs backend-aws --tail 1000 | grep "LIVE_BUY_SKIPPED" | tail -10

# Ver alertas SELL bloqueadas
docker compose logs backend-aws --tail 1000 | grep "LIVE_SELL_SKIPPED" | tail -10
```

### 3. Verificar Flags para Símbolo Específico

```bash
SYMBOL="ALGO_USDT"
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == '$SYMBOL').first()
if item:
    print(f'Symbol: {item.symbol}')
    print(f'alert_enabled: {item.alert_enabled}')
    print(f'buy_alert_enabled: {getattr(item, \"buy_alert_enabled\", None)}')
    print(f'sell_alert_enabled: {getattr(item, \"sell_alert_enabled\", None)}')
"
```

### 4. Verificar Independencia de SELL

```bash
# Verificar que SELL se evalúa independientemente de BUY
docker compose logs backend-aws --tail 1000 | grep "LIVE_SELL_DECISION" | tail -10

# Verificar que SELL tiene su propio throttle
docker compose logs backend-aws --tail 1000 | grep "ALERT_THROTTLE_DECISION side=SELL" | tail -10

# Verificar que SELL tiene su propia llamada
docker compose logs backend-aws --tail 1000 | grep "LIVE_SELL_CALL" | tail -10
```

---

## Criterios de Éxito

✅ **BUY/SELL Signal Consistency es VÁLIDA cuando:**
1. Debug script y live monitor muestran el mismo `decision=BUY/SELL` para el mismo símbolo
2. `can_emit_buy_alert=True` o `can_emit_sell_alert=True` cuando todas las condiciones se cumplen
3. Alertas BUY y SELL se emiten cuando `can_emit_buy_alert=True` o `can_emit_sell_alert=True`
4. Watchlist UI muestra BUY/SELL cuando backend detecta `buy_signal=True` o `sell_signal=True`
5. Throttle solo bloquea cuando realmente hay cooldown activo (independiente para BUY y SELL)
6. Flags permiten emisión cuando `alert_enabled=True` y `buy_alert_enabled=True` / `sell_alert_enabled=True` (o None)
7. **SELL se evalúa independientemente de BUY** (no anidado dentro de bloque BUY)
8. **SELL tiene su propio throttle** (independiente del throttle BUY)

---

## Documentación Relacionada

- **Signal Evaluation Unification:** `docs/monitoring/SIGNAL_EVALUATION_UNIFICATION.md`
- **Signal Flow Overview:** `docs/monitoring/signal_flow_overview.md`
- **Business Rules:** `docs/monitoring/business_rules_canonical.md`
- **Alert Origin Audit:** `docs/monitoring/ALERT_ORIGIN_AUDIT.md`

