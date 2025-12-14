# Deploy: Fix Margin Trading + PENDING Status

## ✅ Commit y Push Completados

- **Commit**: `e381051` - "Fix: PENDING status for TP orders + Margin trading balance check fix"
- **Push**: ✅ Completado a `origin main`
- **GitHub Actions**: Debería ejecutarse automáticamente

## 📋 Cambios Incluidos

### 1. Fix: PENDING Status para Órdenes TP
- **Archivo**: `backend/app/api/routes_dashboard.py`
- **Cambio**: Agregado "PENDING" a `active_statuses` para órdenes TP
- **Razón**: Algunos exchanges/APIs usan PENDING como equivalente a ACTIVE
- **Impacto**: El dashboard ahora cuenta correctamente órdenes TP con status PENDING

### 2. Fix Crítico: Margin Trading Balance Check
- **Archivo**: `backend/app/services/signal_monitor.py`
- **Cambio**: Lectura de `trade_on_margin` **ANTES** del balance check
- **Líneas afectadas**: 
  - BUY orders: ~2306
  - SELL orders: ~3095
- **Razón crítica**: 
  - Para margin trading, el balance se calcula de manera diferente
  - Si verificamos balance SPOT antes de saber si es margin, bloqueamos órdenes de margen incorrectamente
  - El exchange manejará la verificación de margen disponible
- **Impacto**: 
  - ✅ Órdenes de margen ya no serán bloqueadas por verificación de balance SPOT
  - ✅ Balance check solo se ejecuta para órdenes SPOT (`if not user_wants_margin`)
  - ✅ Permite trading con leverage correctamente

## 🔄 Deploy Automático

El workflow `.github/workflows/deploy.yml` debería ejecutarse automáticamente y:
1. Hacer checkout del código
2. Ejecutar audit de trading pairs
3. Sincronizar archivos a AWS
4. Reiniciar servicios con `docker compose --profile aws`

## ✅ Verificación Post-Deploy

Una vez que el deploy termine, verifica:

```bash
# Verificar que el fix de margin trading está aplicado
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws exec -T backend-aws python3 -c "
from app.services.signal_monitor import SignalMonitorService
import inspect
src = inspect.getsource(SignalMonitorService._create_buy_order)
print(\"✅ Margin fix aplicado\" if \"user_wants_margin = watchlist_item.trade_on_margin\" in src and \"if not user_wants_margin:\" in src else \"❌ No encontrado\")
"'

# Verificar servicios
ssh hilovivo-aws 'docker compose --profile aws ps'

# Ver logs
ssh hilovivo-aws 'docker compose --profile aws logs backend-aws --tail 50'
```

## 🔗 Enlaces

- **GitHub Actions**: https://github.com/ccruz0/crypto-2.0/actions
- **Commit**: https://github.com/ccruz0/crypto-2.0/commit/e381051

## 📝 Notas

- **Importante**: Este fix es crítico para margin trading. Sin él, las órdenes de margen pueden ser bloqueadas incorrectamente.
- **Testing**: Verifica que las órdenes de margen se creen correctamente después del deploy.
