# Verificación: BTC no aparece en el Dashboard

## 🔍 Estado Actual

- **32 monedas** en la base de datos con `is_deleted=False`
- **BTC_USD**: `trade_enabled=True` (debería aparecer primero)
- **BTC_USDT**: `trade_enabled=False`
- **26 monedas** visibles en el dashboard (deberían ser 32)

## ✅ Cambios Aplicados

1. **Backend**: Ya devuelve todas las 32 monedas
2. **Frontend**: `WATCHLIST_PAGE_SIZE` aumentado a 100

## 🔧 Solución

El problema es que el frontend necesita ser **reconstruido** para aplicar los cambios:

```bash
cd frontend
npm run build
```

Luego, después de reconstruir, **limpiar el caché del navegador**:
- Presiona `Ctrl+Shift+R` (Windows/Linux) o `Cmd+Shift+R` (Mac)
- O abre las herramientas de desarrollador (F12) → Application → Clear Storage → Clear site data

## 📋 Verificación

Después de reconstruir y limpiar el caché, deberías ver:
- **32 monedas** en total
- **BTC_USD** debería aparecer **primero** (porque tiene `trade_enabled=True`)
- **BTC_USDT** debería aparecer después

## 🔍 Si BTC sigue sin aparecer

Verifica en la consola del navegador (F12 → Console):
1. Busca mensajes que digan `updateTopCoins called with X coins`
2. Verifica si BTC está en la lista de monedas recibidas del backend
3. Verifica si hay algún error de red o timeout

