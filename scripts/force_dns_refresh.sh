#!/usr/bin/env bash
# Force DNS refresh on macOS

echo "Limpiando cache DNS en macOS..."
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

echo ""
echo "Cache DNS limpiado. Verificando..."
sleep 2

echo ""
echo "DNS desde diferentes servidores:"
echo ""
echo "Cloudflare (1.1.1.1):"
dig @1.1.1.1 +short dashboard.hilovivo.com A
echo ""
echo "Google (8.8.8.8):"
dig @8.8.8.8 +short dashboard.hilovivo.com A
echo ""
echo "Local (después de limpiar cache):"
dig +short dashboard.hilovivo.com A
echo ""

EXPECTED_IP="47.130.143.159"
CLOUDFLARE_IP=$(dig @1.1.1.1 +short dashboard.hilovivo.com A)

if [ "$CLOUDFLARE_IP" = "$EXPECTED_IP" ]; then
    echo "✅ DNS está actualizado (Cloudflare ya muestra la IP correcta)"
    echo "⏳ Algunos servidores DNS aún tienen la IP antigua en cache"
    echo "   Esto es normal durante la propagación DNS"
    echo ""
    echo "Para acceso inmediato, puedes usar:"
    echo "  dig @1.1.1.1 +short dashboard.hilovivo.com A"
    echo "  (Usa Cloudflare DNS que ya tiene la IP correcta)"
else
    echo "❌ DNS aún no se ha actualizado en Hostinger"
    echo "   Por favor verifica en Hostinger que el registro A esté actualizado"
fi

