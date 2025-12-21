#!/bin/bash
# Script para reiniciar nginx en el servidor AWS y solucionar el problema 502

set -e

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔄 Reiniciando nginx en AWS para solucionar el problema 502..."
echo "📍 Servidor: $EC2_USER@$EC2_HOST"
echo ""

# Test SSH connection
echo "🔍 Probando conexión SSH..."
if ! ssh_cmd "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ No se pudo conectar a AWS"
    echo "🔧 Verifica tu configuración SSH o conectividad de red"
    exit 1
fi

echo "✅ Conexión SSH exitosa"
echo ""

# Execute commands on remote server
echo "🔧 Ejecutando diagnóstico y reinicio de nginx..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'REMOTE_SCRIPT'
set -e

echo "📊 Estado actual de nginx:"
sudo systemctl status nginx --no-pager | head -5 || echo "⚠️  nginx no está corriendo"
echo ""

echo "🔍 Verificando conectividad al backend:"
if curl -f --connect-timeout 3 http://localhost:8002/health >/dev/null 2>&1; then
    echo "✅ Backend está accesible en localhost:8002"
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
else
    echo "⚠️  Backend no accesible - puede necesitar más tiempo para iniciar"
fi
echo ""

echo "📋 Últimos errores de nginx (si hay):"
sudo tail -5 /var/log/nginx/error.log 2>/dev/null | grep -E "502|upstream|connect" || echo "   No hay errores recientes"
echo ""

echo "✅ Reinicio de nginx completado!"
REMOTE_SCRIPT

echo ""
echo "✅ Proceso completado!"
echo ""
echo "🌐 Verifica el dashboard en: https://dashboard.hilovivo.com"
echo "   El problema 502 debería estar resuelto ahora."
echo ""






