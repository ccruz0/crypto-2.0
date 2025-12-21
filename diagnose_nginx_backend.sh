#!/bin/bash
# Script de diagnóstico para el problema 502 entre nginx y backend

echo "🔍 Diagnóstico de conectividad nginx -> backend"
echo "================================================"
echo ""

# 1. Verificar si nginx está corriendo
echo "1. Estado de nginx:"
sudo systemctl status nginx --no-pager | head -10
echo ""

# 2. Verificar si el backend está escuchando en el puerto
echo "2. Verificando puerto 8002:"
sudo netstat -tlnp | grep 8002 || sudo ss -tlnp | grep 8002
echo ""

# 3. Probar conectividad desde el host
echo "3. Probando conectividad desde el host:"
curl -v --connect-timeout 5 http://localhost:8002/health 2>&1 | head -20
echo ""

# 4. Ver logs de nginx error
echo "4. Últimos errores de nginx:"
sudo tail -20 /var/log/nginx/error.log | grep -E "502|upstream|connect|failed|refused"
echo ""

# 5. Ver logs de nginx access para /api
echo "5. Últimas peticiones a /api en nginx:"
sudo tail -20 /var/log/nginx/access.log | grep "/api"
echo ""

# 6. Verificar configuración de nginx
echo "6. Verificando configuración de nginx:"
sudo nginx -t
echo ""

# 7. Verificar si hay procesos escuchando en 8002
echo "7. Procesos escuchando en puerto 8002:"
sudo lsof -i :8002 || sudo netstat -tlnp | grep 8002
echo ""

# 8. Probar conexión directa con telnet/nc
echo "8. Probando conexión TCP directa:"
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/localhost/8002' && echo "✅ Conexión TCP exitosa" || echo "❌ No se puede conectar"
echo ""

echo "================================================"
echo "✅ Diagnóstico completo"
echo ""
echo "Si nginx no puede conectarse, intenta:"
echo "  sudo systemctl restart nginx"
echo "  sudo systemctl restart docker  # Si el backend está en Docker"






