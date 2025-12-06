# Problema: SL/TP No Se Están Actualizando

## 🔍 Diagnóstico

### Problema Identificado
Los campos SL Price y TP Price en el dashboard muestran "Calculating..." y no se actualizan con valores numéricos.

### Causa Raíz
1. **Signals sin datos**: El endpoint `/api/signals` devuelve:
   - `current_price: null`
   - `res_up: null` (resistance_up)
   - `res_down: null` (resistance_down)

2. **Market-updater usando SQLite**: El servicio `market-updater` está usando SQLite en lugar de PostgreSQL, por lo que no está actualizando los signals en la base de datos correcta.

3. **Signal writer no disponible**: Hay un error en el signal writer que impide sincronizar los signals desde el watchlist.

### Verificación
```bash
# Verificar signals en el endpoint
curl "http://localhost:8002/api/signals?exchange=CRYPTO_COM&symbol=ETH_USDT"
# Resultado: current_price: null, res_up: null, res_down: null

# Verificar logs del market-updater
docker logs automated-trading-platform-market-updater-1
# Muestra: "Database engine configured for SQLite"
# Muestra: "Signal writer not available: invalid decimal literal"
```

## 🔧 Solución

### Paso 1: Verificar Configuración de Base de Datos
El `market-updater` debe usar PostgreSQL, no SQLite. Verificar que la variable de entorno `DATABASE_URL` esté configurada correctamente en el contenedor.

### Paso 2: Corregir Signal Writer
El error "invalid decimal literal" en `signal_writer.py` línea 257 debe ser corregido para que los signals se sincronicen correctamente.

### Paso 3: Verificar que los Signals se Actualicen
Una vez corregido, los signals deberían tener:
- `current_price`: Precio actual del activo
- `res_up`: Nivel de resistencia superior
- `res_down`: Nivel de resistencia inferior

## 📋 Próximos Pasos

1. **Verificar DATABASE_URL en market-updater**
   ```bash
   docker exec automated-trading-platform-market-updater-1 env | grep DATABASE_URL
   ```

2. **Revisar error en signal_writer.py línea 257**
   - El error "invalid decimal literal" sugiere un problema al parsear un valor decimal
   - Necesita ser corregido para que los signals se sincronicen

3. **Verificar que los signals se actualicen después de corregir**
   ```bash
   # Esperar unos minutos y verificar
   curl "http://localhost:8002/api/signals?exchange=CRYPTO_COM&symbol=ETH_USDT" | jq '{current_price, res_up, res_down}'
   ```

## 🎯 Estado Actual

- ✅ Market-updater: Iniciado
- ❌ Database: Usando SQLite (debería ser PostgreSQL)
- ❌ Signal Writer: No disponible (error en línea 257)
- ❌ Signals: Sin datos (current_price, res_up, res_down son null)
- ❌ SL/TP: No se calculan (porque faltan datos en signals)

## 📝 Notas

El cálculo de SL/TP en el frontend (`calculateSLTPValues`) requiere:
- `current_price` del coin
- `signal` con `res_up` y `res_down`
- Si faltan estos datos, retorna `{ sl: 0, tp: 0 }` y muestra "Calculating..."

