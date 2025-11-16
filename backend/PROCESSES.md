# Market Data Processes

Este proyecto separa la lógica en dos procesos independientes:

## 1. API Server (Proceso Rápido)

Sirve datos desde el cache compartido. **NUNCA** llama a APIs externas.

### Comando:
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-reload
```

### Características:
- Endpoint `/api/market/top-coins-data` responde rápido (<200ms)
- Solo lee del archivo compartido `market_cache.json`
- No bloquea el dashboard durante actualizaciones

## 2. Market Updater Worker (Proceso Lento)

Actualiza datos desde APIs externas (Crypto.com, CoinGecko, etc.) con delays de 3s entre monedas.
**Ahora incluye cálculo de indicadores técnicos**: RSI, MA50, MA200, EMA10, ATR, Volume.

### Comando:
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 run_updater.py
```

### Características:
- Fetcha datos de APIs externas (precios + OHLCV históricos)
- Calcula indicadores técnicos: RSI, MA50, MA200, EMA10, ATR
- Calcula volumen real desde OHLCV (no mock)
- Respeta rate limits (3s delay entre monedas)
- Actualiza cada 60 segundos
- Guarda resultados en `market_cache.json` (almacenamiento compartido)
- Toma ~40-50 segundos por actualización completa (más tiempo por incluir indicadores)

## Almacenamiento Compartido

Ambos procesos leen/escriben desde:
- **Archivo**: `backend/market_cache.json`
- **Formato**: JSON con estructura:
  ```json
  {
    "coins": [
      {
        "rank": 1,
        "instrument_name": "BTC_USDT",
        "base_currency": "BTC",
        "quote_currency": "USDT",
        "current_price": 109987.94,
        "volume_24h": 12345678.90,
        "rsi": 52.5,
        "ma50": 108000.00,
        "ma200": 105000.00,
        "ema10": 109500.00,
        "atr": 2200.00,
        "avg_volume": 12000000.00,
        "volume_ratio": 1.03,
        "updated_at": "2025-10-26 08:45:13",
        "is_custom": false
      }
    ],
    "count": 21,
    "timestamp": 1234567890.123,
    "source": "cache"
  }
  ```

### Datos Incluidos en Cache:
- ✅ **Precios**: `current_price`
- ✅ **Volumen**: `volume_24h` (real desde OHLCV), `avg_volume`, `volume_ratio`
- ✅ **Indicadores Técnicos**: `rsi`, `ma50`, `ma200`, `ema10`, `atr`

## Uso en Producción

Ejecuta ambos procesos en paralelo:

**Terminal 1 (API Server):**
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-reload
```

**Terminal 2 (Updater Worker):**
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 run_updater.py
```

## Docker Compose (opcional)

Si usas Docker, puedes añadir dos services:
- `api`: ejecuta uvicorn
- `market-updater`: ejecuta run_updater.py

 Ambos montan el mismo volumen para compartir `market_cache.json`.

