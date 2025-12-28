# Instrucciones para Probar la Persistencia de Valores de Watchlist

## ✅ Estado Actual

1. **Backend iniciado** - Corriendo en `http://localhost:8002`
2. **Base de datos migrada** - Columna `is_deleted` agregada
3. **Código actualizado** - Todas las correcciones aplicadas

## 🧪 Pasos para Probar

### 1. Abrir el Dashboard

Abre tu navegador y ve a:
```
http://localhost:3000
```
o
```
https://dashboard.hilovivo.com
```

### 2. Establecer Valores en la Watchlist

1. Ve a la pestaña **"Watchlist"**
2. Encuentra un símbolo (ej: BTC_USDT, ETH_USDT, etc.)
3. **Establece valores:**
   - **Amount USD**: Escribe un valor (ej: `150.50`)
   - **SL Price** o **SL %**: Escribe un porcentaje (ej: `2.5`)
   - **TP Price** o **TP %**: Escribe un porcentaje (ej: `5.0`)
4. Haz clic fuera del campo o presiona Enter
5. Deberías ver el mensaje **"✓ New value saved"**

### 3. Verificar que se Guardaron (Paso 1)

**Opción A: Verificar en el navegador**
- Los valores deberían permanecer visibles en los campos
- No deberían desaparecer

**Opción B: Verificar vía API**
```bash
cd /Users/carloscruz/automated-trading-platform
curl -s http://localhost:8002/api/dashboard | python3 -m json.tool | grep -A 10 "BTC_USDT"
```

### 4. Refrescar la Página

1. Presiona **F5** o **Cmd+R** (Mac) / **Ctrl+R** (Windows/Linux)
2. La página se recargará
3. **Verifica:** Los valores que estableciste deberían **persistir** y aparecer de nuevo

### 5. Revisar Logs del Backend

Abre una terminal y ejecuta:
```bash
cd /Users/carloscruz/automated-trading-platform
./check_watchlist_logs.sh
```

O manualmente:
```bash
cd backend
tail -f backend.log | grep -E "WATCHLIST_UPDATE|WATCHLIST_PROTECT"
```

Deberías ver logs como:
```
[WATCHLIST_UPDATE] PUT /dashboard/123 for BTC_USDT: updating fields ['trade_amount_usd', 'sl_percentage']
[WATCHLIST_UPDATE] BTC_USDT.trade_amount_usd: None → 150.5
[WATCHLIST_UPDATE] Successfully committed update for BTC_USDT
```

### 6. Reiniciar el Backend

**Opción A: Si está corriendo directamente**
```bash
# Encontrar el proceso
ps aux | grep "uvicorn app.main:app" | grep -v grep

# Matar el proceso (reemplaza PID con el número del proceso)
kill <PID>

# Reiniciar
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload > backend.log 2>&1 &
```

**Opción B: Si está en Docker**
```bash
cd /Users/carloscruz/automated-trading-platform
docker-compose restart backend
```

### 7. Verificar Persistencia Después del Reinicio

1. **Espera 5-10 segundos** para que el backend se inicie completamente
2. **Refresca el dashboard** en el navegador (F5)
3. **Verifica:** Los valores que estableciste deberían **seguir ahí**

### 8. Verificar en la Base de Datos Directamente

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
items = db.query(WatchlistItem).filter(WatchlistItem.symbol == 'BTC_USDT').all()
for item in items:
    print(f'Symbol: {item.symbol}')
    print(f'  Trade Amount USD: {item.trade_amount_usd}')
    print(f'  SL Percentage: {item.sl_percentage}')
    print(f'  TP Percentage: {item.tp_percentage}')
    print(f'  SL Price: {item.sl_price}')
    print(f'  TP Price: {item.tp_price}')
db.close()
"
```

## 🔍 Qué Buscar en los Logs

### Logs de Actualización Exitosa
```
[WATCHLIST_UPDATE] PUT /dashboard/123 for BTC_USDT: updating fields ['trade_amount_usd']
[WATCHLIST_UPDATE] BTC_USDT.trade_amount_usd: None → 150.5
[WATCHLIST_UPDATE] Successfully committed update for BTC_USDT
```

### Logs de Protección (cuando se preservan valores)
```
[WATCHLIST_PROTECT] Preserving user-set trade_amount_usd=150.5 for BTC_USDT (frontend tried to clear)
```

### Logs de Auto-recalculo Omitido
```
⏭️ Skipping auto-save for BTC_USDT - user has manually set percentages
```

## ❌ Si los Valores Aún Desaparecen

1. **Revisa los logs** para ver si hay errores:
   ```bash
   tail -50 backend/backend.log | grep -i error
   ```

2. **Verifica la base de datos** directamente (ver paso 8 arriba)

3. **Verifica que el backend esté usando la base de datos correcta:**
   ```bash
   cd backend
   python3 -c "from app.database import database_url; print(f'Database: {database_url}')"
   ```

4. **Revisa si hay múltiples instancias del backend corriendo:**
   ```bash
   ps aux | grep uvicorn
   ```

## 📝 Notas

- Los valores se guardan en la base de datos PostgreSQL/SQLite
- El frontend también guarda en `localStorage` como respaldo temporal
- Los valores en la base de datos tienen prioridad sobre `localStorage`
- Si el backend se reconstruye pero la base de datos persiste, los valores deberían mantenerse

## ✅ Checklist de Prueba

- [ ] Backend iniciado y respondiendo
- [ ] Valores establecidos en la watchlist
- [ ] Mensaje "✓ New value saved" aparece
- [ ] Valores persisten después de refrescar la página
- [ ] Logs muestran `[WATCHLIST_UPDATE]`
- [ ] Backend reiniciado
- [ ] Valores persisten después del reinicio
- [ ] Valores verificados en la base de datos directamente









