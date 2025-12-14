#!/bin/bash
# Script para verificar el estado de sell_alert_enabled

echo "🔍 Verificando estado de sell_alert_enabled..."
echo ""

# Copiar script al contenedor
docker compose --profile aws cp check_sell_alert_enabled.py backend-aws:/app/ 2>/dev/null || echo "⚠️  No se pudo copiar el script (puede que ya exista)"

# Ejecutar verificación
docker compose --profile aws exec backend-aws python3 /app/check_sell_alert_enabled.py

echo ""
echo "💡 Para habilitar alertas SELL para todos los símbolos:"
echo "   docker compose --profile aws exec backend-aws python3 -c \"
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
items = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).all()
for item in items:
    item.sell_alert_enabled = True
db.commit()
print(f'✅ Habilitado sell_alert_enabled para {len(items)} símbolos')
db.close()
\""
