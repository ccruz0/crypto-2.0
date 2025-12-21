# Verificación: Estado de sell_alert_enabled

## 🔍 Script de Verificación

Se creó un script para verificar el estado de `sell_alert_enabled` en todos los símbolos de la watchlist.

### Ejecutar Verificación:

```bash
./verificar_sell_alerts.sh
```

O manualmente:

```bash
# Copiar script al contenedor
docker compose --profile aws cp check_sell_alert_enabled.py backend-aws:/app/

# Ejecutar verificación
docker compose --profile aws exec backend-aws python3 /app/check_sell_alert_enabled.py
```

## 📊 Qué Verifica

El script muestra:
- ✅ Símbolos con `sell_alert_enabled=True` (recibirán alertas SELL)
- ❌ Símbolos con `sell_alert_enabled=False` (NO recibirán alertas SELL)
- Resumen de cuántos símbolos tienen alertas SELL habilitadas

## 🔧 Solución Rápida

Si todos los símbolos tienen `sell_alert_enabled=False`, puedes habilitarlos todos:

```bash
docker compose --profile aws exec backend-aws python3 -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
items = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).all()
for item in items:
    item.sell_alert_enabled = True
db.commit()
print(f'✅ Habilitado sell_alert_enabled para {len(items)} símbolos')
db.close()
"
```

## 📝 Notas

- `sell_alert_enabled` controla si se envían alertas SELL cuando se detecta una señal SELL
- `alert_enabled` es el switch maestro (debe ser True)
- `buy_alert_enabled` controla alertas BUY (independiente de sell_alert_enabled)





