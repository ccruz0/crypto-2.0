# Solución: Solo se Ven 18 Monedas en el Dashboard

## 🔍 Problema Identificado

El frontend tenía un límite de `WATCHLIST_PAGE_SIZE = 30`, pero solo mostraba 18 monedas. Esto podría deberse a:

1. **Caché del navegador**: El frontend podría estar usando datos cacheados antiguos
2. **Límite del frontend**: Aunque el límite era 30, solo se mostraban 18

## ✅ Solución Aplicada

### 1. Backend (Ya aplicado)
- ✅ Modificado `/api/market/top-coins-data` para devolver TODAS las monedas con `is_deleted=False`
- ✅ Modificado `market_updater.py` para actualizar TODAS las monedas del watchlist

### 2. Frontend (Aplicado ahora)
- ✅ Aumentado `WATCHLIST_PAGE_SIZE` de 30 a 100 para mostrar todas las monedas

## 📋 Próximos Pasos

1. **Reconstruir el frontend** para aplicar los cambios:
   ```bash
   cd frontend
   npm run build
   ```

2. **Limpiar caché del navegador**:
   - Presiona `Ctrl+Shift+R` (Windows/Linux) o `Cmd+Shift+R` (Mac) para hacer un hard refresh
   - O abre las herramientas de desarrollador (F12) y limpia el caché

3. **Verificar**:
   - El dashboard debería mostrar todas las 32 monedas (o el número que tengas con `is_deleted=False`)
   - Las monedas deberían actualizarse automáticamente cada 60 segundos

## 🔧 Verificación

Para verificar que el backend está devolviendo todas las monedas:

```bash
curl -H "x-api-key: demo-key" http://175.41.189.249:8002/api/market/top-coins-data | python3 -m json.tool | grep -c "instrument_name"
```

Esto debería mostrar 32 (o el número de monedas no eliminadas que tengas).

