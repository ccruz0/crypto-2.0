#!/bin/bash
# Script para ejecutar DIRECTAMENTE en el servidor AWS
# Uso: ssh ubuntu@54.254.150.31 "bash -s" < restart_nginx_on_server.sh

set -e

echo "🔄 Reiniciando nginx para solucionar el problema 502..."
echo ""

echo "📊 Estado actual de nginx:"
sudo systemctl status nginx --no-pager | head -5 || echo "⚠️  nginx no está corriendo"
echo ""

echo "🔍 Verificando conectividad al backend:"
if curl -f --connect-timeout 3 http://localhost:8002/health >/dev/null 2>&1; then
    echo "✅ Backend está accesible en localhost:8002"
    curl -s http://localhost:8002/health | head -1
else
    echo "⚠️  Backend no responde en localhost:8002"
    echo "   Verificando contenedores Docker..."
    docker ps --filter "name=backend-aws" --format "{{.Names}}: {{.Status}}" || echo "   No se encontró contenedor backend-aws"
fi
echo ""

echo "🔄 Reiniciando nginx..."
sudo systemctl restart nginx
echo ""

echo "⏳ Esperando 2 segundos..."
sleep 2
echo ""

echo "📊 Verificando estado de nginx después del reinicio:"
if sudo systemctl is-active --quiet nginx; then
    echo "✅ nginx está corriendo"
else
    echo "❌ nginx no está corriendo"
    exit 1
fi
echo ""

echo "🔍 Verificando configuración de nginx:"
sudo nginx -t
echo ""

echo "🧪 Probando conectividad desde nginx al backend:"
if curl -f --connect-timeout 3 http://localhost:8002/health >/dev/null 2>&1; then
    echo "✅ Backend accesible desde el host"
    echo "   Respuesta: $(curl -s http://localhost:8002/health)"
else
    echo "⚠️  Backend no accesible - puede necesitar más tiempo para iniciar"
fi
echo ""

echo "📋 Últimos errores de nginx (si hay):"
sudo tail -10 /var/log/nginx/error.log 2>/dev/null | grep -E "502|upstream|connect|failed" || echo "   No hay errores recientes relacionados"
echo ""

echo "📋 Últimas peticiones a /api:"
sudo tail -5 /var/log/nginx/access.log 2>/dev/null | grep "/api" || echo "   No hay peticiones recientes"
echo ""

echo "✅ Reinicio de nginx completado!"
echo ""
echo "🌐 Verifica el dashboard en: https://dashboard.hilovivo.com"
echo "   El problema 502 debería estar resuelto ahora."

