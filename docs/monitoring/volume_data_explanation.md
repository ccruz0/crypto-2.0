# Volume Data Explanation

**Date:** 2025-12-01  
**Question:** ¿Qué significa "Volume (último período): 0.00"?

## Definiciones

### "Volume (último período)"
- **Significado**: Volumen de la última vela/candela de 1 hora
- **Fuente**: `MarketData.current_volume` en la base de datos
- **Cálculo**: `volumes[-1]` (último elemento del array de volúmenes de velas OHLCV de 1h)
- **Propósito**: Representa el volumen negociado en la última hora

### "Promedio (5 períodos)"
- **Significado**: Promedio de volumen de las últimas 5 velas de 1 hora
- **Fuente**: `MarketData.avg_volume` en la base de datos
- **Cálculo**: Promedio de los últimos 5 períodos de volumen
- **Propósito**: Línea base para comparar el volumen actual

### "Ratio actual"
- **Significado**: `current_volume / avg_volume`
- **Fuente**: `MarketData.volume_ratio` (pre-calculado) o calculado en tiempo real
- **Propósito**: Indica si el volumen actual es mayor/menor que el promedio

## ¿Por qué puede ser 0.00?

### Posibles Causas

1. **Vela actual sin volumen**
   - La última vela de 1 hora realmente tiene volumen 0
   - Puede ocurrir en pares poco líquidos o durante períodos de baja actividad

2. **Datos no actualizados**
   - `MarketData.current_volume` no se ha actualizado recientemente
   - El `market_updater.py` no ha ejecutado para este símbolo

3. **Problema con la fuente de datos**
   - La API de Crypto.com o Binance no devolvió datos de volumen
   - El símbolo no está disponible en la fuente de datos

4. **Vela incompleta**
   - La vela actual aún está en progreso y no tiene volumen acumulado
   - Esto es normal para la vela más reciente

### Inconsistencia Detectada

Si el tooltip muestra:
- `Volume (último período): 0.00`
- `Promedio (5 períodos): 534.70`
- `Ratio actual: 0.70x`

Esto es **inconsistente** porque:
- Si `current_volume = 0` y `avg_volume = 534.70`
- Entonces `ratio = 0 / 534.70 = 0`, no `0.70x`

**Posibles explicaciones:**
1. El `volume_ratio` viene de una fuente diferente (pre-calculado y desactualizado)
2. El `current_volume` mostrado es incorrecto (debería ser diferente de 0)
3. Hay un problema con la actualización de datos en `MarketData`

## Cómo se Calcula

### En `market_updater.py`:
```python
# Obtener datos OHLCV (velas de 1 hora)
ohlcv_data = fetch_ohlcv_data(symbol, "1h", limit=200)

# Extraer volúmenes
volumes = [candle["v"] for candle in ohlcv_data]

# Calcular índice de volumen
volume_index = calculate_volume_index(volumes, period=5)

# current_volume = último volumen de la vela más reciente
current_volume = volume_index.get("current_volume", volumes[-1] if volumes else 0)

# avg_volume = promedio de los últimos 5 períodos
avg_volume = volume_index.get("average_volume", 0)

# volume_ratio = current_volume / avg_volume
volume_ratio = volume_index.get("volume_ratio", 0)
```

### En `calculate_volume_index()`:
```python
def calculate_volume_index(volumes: List[float], period: int = 5) -> Dict:
    if not volumes or len(volumes) < period:
        return {
            "current_volume": volumes[-1] if volumes else 0,
            "average_volume": 0,
            "volume_ratio": 0
        }
    
    # Último período = última vela
    current_volume = volumes[-1]
    
    # Promedio de los últimos N períodos
    avg_volume = sum(volumes[-period:]) / period
    
    # Ratio
    volume_ratio = (current_volume / avg_volume) if avg_volume > 0 else 0
    
    return {
        "current_volume": current_volume,
        "average_volume": avg_volume,
        "volume_ratio": volume_ratio
    }
```

## Solución

Si ves `Volume (último período): 0.00` pero el ratio es `0.70x`:

1. **Verificar actualización de datos:**
   - El `market_updater.py` debería ejecutarse periódicamente
   - Verificar logs del backend para ver si hay errores

2. **Verificar fuente de datos:**
   - Crypto.com o Binance pueden no tener datos para ese símbolo
   - Verificar en `/api/data-sources/status`

3. **Verificar base de datos:**
   - `MarketData.current_volume` puede estar desactualizado
   - Forzar actualización ejecutando `market_updater.py`

4. **Vela incompleta:**
   - Si es la vela actual (en progreso), es normal que tenga volumen bajo o 0
   - El ratio puede venir de una vela anterior

## Recomendación

Si el volumen muestra 0.00 pero el ratio es > 0:
- **No es crítico** - El ratio es lo que importa para las señales
- El backend usa `volume_ratio` para decisiones, no `current_volume` directamente
- Si `volume_ratio >= 0.5`, la condición de volumen se cumple independientemente del valor absoluto

## Referencias

- `backend/app/models/market_price.py` - Modelo MarketData
- `backend/market_updater.py` - Actualización de datos de mercado
- `backend/app/api/routes_signals.py` - Función `calculate_volume_index()`












