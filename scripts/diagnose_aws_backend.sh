#!/bin/bash
# Script de diagnóstico completo para el backend en AWS
# Verifica el estado del backend y diagnostica problemas de 502

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"
EC2_HOST="54.254.150.31"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Diagnóstico del Backend en AWS${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Cargar configuración SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Función para ejecutar comandos SSH
ssh_cmd() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$REMOTE_HOST" "$@" 2>&1
}

# 1. Verificar conectividad SSH
echo -e "${BLUE}[1/10] Verificando conectividad SSH...${NC}"
if ssh_cmd "echo 'SSH OK'" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Conexión SSH exitosa${NC}"
else
    echo -e "${RED}❌ No se puede conectar por SSH${NC}"
    echo -e "${YELLOW}   Verifica:${NC}"
    echo -e "${YELLOW}   - ssh hilovivo-aws 'echo test'${NC}"
    echo -e "${YELLOW}   - Configuración SSH en ~/.ssh/config${NC}"
    exit 1
fi
echo ""

# 2. Verificar si Docker está corriendo
echo -e "${BLUE}[2/10] Verificando Docker...${NC}"
DOCKER_STATUS=$(ssh_cmd "docker ps > /dev/null 2>&1 && echo 'running' || echo 'stopped'")
if [ "$DOCKER_STATUS" = "running" ]; then
    echo -e "${GREEN}✅ Docker está corriendo${NC}"
else
    echo -e "${RED}❌ Docker no está corriendo${NC}"
    echo -e "${YELLOW}   Ejecuta: ssh $REMOTE_HOST 'sudo systemctl start docker'${NC}"
fi
echo ""

# 3. Verificar contenedores del backend
echo -e "${BLUE}[3/10] Verificando contenedores del backend...${NC}"
BACKEND_CONTAINERS=$(ssh_cmd "cd $REMOTE_PATH && docker compose --profile aws ps --format '{{.Names}} {{.Status}}' | grep backend || docker ps --format '{{.Names}} {{.Status}}' | grep backend")
if [ -n "$BACKEND_CONTAINERS" ]; then
    echo -e "${GREEN}✅ Contenedores encontrados:${NC}"
    echo "$BACKEND_CONTAINERS" | while read line; do
        echo -e "   $line"
    done
else
    echo -e "${RED}❌ No se encontraron contenedores del backend${NC}"
    echo -e "${YELLOW}   Ejecuta: ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws up -d backend-aws'${NC}"
fi
echo ""

# 4. Verificar logs recientes del backend
echo -e "${BLUE}[4/10] Verificando logs recientes del backend (últimas 20 líneas)...${NC}"
BACKEND_LOGS=$(ssh_cmd "cd $REMOTE_PATH && docker compose --profile aws logs --tail 20 backend-aws 2>&1 || docker logs --tail 20 \$(docker ps -q --filter 'name=backend') 2>&1")
if [ -n "$BACKEND_LOGS" ]; then
    echo "$BACKEND_LOGS" | tail -20
    if echo "$BACKEND_LOGS" | grep -qi "error\|exception\|failed\|502"; then
        echo -e "${RED}⚠️  Se encontraron errores en los logs${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  No se pudieron obtener logs${NC}"
fi
echo ""

# 5. Verificar si el backend está escuchando en el puerto
echo -e "${BLUE}[5/10] Verificando si el backend está escuchando en el puerto...${NC}"
PORT_CHECK=$(ssh_cmd "netstat -tlnp 2>/dev/null | grep ':8002' || ss -tlnp 2>/dev/null | grep ':8002' || echo 'not_found'")
if echo "$PORT_CHECK" | grep -q ":8002"; then
    echo -e "${GREEN}✅ Backend está escuchando en el puerto 8002${NC}"
    echo "$PORT_CHECK"
else
    echo -e "${RED}❌ Backend NO está escuchando en el puerto 8002${NC}"
    echo -e "${YELLOW}   El backend puede no estar corriendo o estar en otro puerto${NC}"
fi
echo ""

# 6. Verificar health endpoint localmente en el servidor
echo -e "${BLUE}[6/10] Verificando health endpoint localmente en el servidor...${NC}"
HEALTH_CHECK=$(ssh_cmd "curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/health 2>&1 || curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8002/health 2>&1 || echo 'failed'")
if [ "$HEALTH_CHECK" = "200" ]; then
    echo -e "${GREEN}✅ Health endpoint responde correctamente (200)${NC}"
elif [ "$HEALTH_CHECK" = "failed" ]; then
    echo -e "${RED}❌ No se pudo conectar al health endpoint${NC}"
    echo -e "${YELLOW}   El backend puede no estar corriendo${NC}"
else
    echo -e "${YELLOW}⚠️  Health endpoint responde con código: $HEALTH_CHECK${NC}"
fi
echo ""

# 7. Verificar configuración de Nginx
echo -e "${BLUE}[7/10] Verificando configuración de Nginx...${NC}"
NGINX_STATUS=$(ssh_cmd "sudo systemctl status nginx --no-pager 2>&1 | head -3 || echo 'not_running'")
if echo "$NGINX_STATUS" | grep -q "active (running)"; then
    echo -e "${GREEN}✅ Nginx está corriendo${NC}"
else
    echo -e "${RED}❌ Nginx no está corriendo${NC}"
    echo -e "${YELLOW}   Ejecuta: ssh $REMOTE_HOST 'sudo systemctl start nginx'${NC}"
fi

# Verificar logs de error de Nginx
echo -e "${BLUE}   Revisando logs de error de Nginx (últimas 10 líneas)...${NC}"
NGINX_ERRORS=$(ssh_cmd "sudo tail -10 /var/log/nginx/error.log 2>&1 || echo 'no_logs'")
if [ "$NGINX_ERRORS" != "no_logs" ] && [ -n "$NGINX_ERRORS" ]; then
    echo "$NGINX_ERRORS"
    if echo "$NGINX_ERRORS" | grep -qi "502\|bad gateway\|upstream"; then
        echo -e "${RED}⚠️  Se encontraron errores 502 en los logs de Nginx${NC}"
    fi
else
    echo -e "${YELLOW}   No se pudieron obtener logs de Nginx${NC}"
fi
echo ""

# 8. Verificar configuración del proxy de Nginx
echo -e "${BLUE}[8/10] Verificando configuración del proxy de Nginx...${NC}"
NGINX_CONFIG=$(ssh_cmd "sudo cat /etc/nginx/sites-available/default 2>&1 | grep -A 5 'location /api' || sudo cat /etc/nginx/nginx.conf 2>&1 | grep -A 5 'location /api' || echo 'not_found'")
if echo "$NGINX_CONFIG" | grep -q "proxy_pass"; then
    echo -e "${GREEN}✅ Configuración del proxy encontrada:${NC}"
    echo "$NGINX_CONFIG" | head -10
    if echo "$NGINX_CONFIG" | grep -q "localhost:8002\|127.0.0.1:8002"; then
        echo -e "${GREEN}   ✅ Proxy apunta al puerto 8002${NC}"
    else
        echo -e "${YELLOW}   ⚠️  Verifica que el proxy apunte al puerto correcto${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  No se encontró configuración del proxy${NC}"
fi
echo ""

# 9. Verificar desde fuera (público)
echo -e "${BLUE}[9/10] Verificando endpoint público...${NC}"
PUBLIC_CHECK=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 10 "https://dashboard.hilovivo.com/api/dashboard/snapshot" -H "X-API-Key: demo-key" 2>&1 || echo "failed")
if [ "$PUBLIC_CHECK" = "200" ]; then
    echo -e "${GREEN}✅ Endpoint público responde correctamente (200)${NC}"
elif [ "$PUBLIC_CHECK" = "502" ]; then
    echo -e "${RED}❌ Endpoint público devuelve 502 (Bad Gateway)${NC}"
    echo -e "${YELLOW}   Esto confirma que Nginx no puede conectarse al backend${NC}"
else
    echo -e "${YELLOW}⚠️  Endpoint público responde con código: $PUBLIC_CHECK${NC}"
fi
echo ""

# 10. Resumen y recomendaciones
echo -e "${BLUE}[10/10] Resumen y recomendaciones${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Determinar el problema principal
if [ "$HEALTH_CHECK" != "200" ]; then
    echo -e "${RED}🔴 PROBLEMA PRINCIPAL: El backend no está respondiendo localmente${NC}"
    echo -e "${YELLOW}   Solución:${NC}"
    echo -e "${YELLOW}   1. Verificar logs: ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs backend-aws'${NC}"
    echo -e "${YELLOW}   2. Reiniciar backend: ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws restart backend-aws'${NC}"
    echo -e "${YELLOW}   3. Si no funciona, reiniciar todo: ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws down && docker compose --profile aws up -d'${NC}"
elif [ "$PUBLIC_CHECK" = "502" ]; then
    echo -e "${RED}🔴 PROBLEMA PRINCIPAL: Nginx no puede conectarse al backend${NC}"
    echo -e "${YELLOW}   Solución:${NC}"
    echo -e "${YELLOW}   1. Verificar que el backend esté escuchando: ssh $REMOTE_HOST 'netstat -tlnp | grep 8002'${NC}"
    echo -e "${YELLOW}   2. Verificar configuración de Nginx: ssh $REMOTE_HOST 'sudo cat /etc/nginx/sites-available/default | grep proxy_pass'${NC}"
    echo -e "${YELLOW}   3. Reiniciar Nginx: ssh $REMOTE_HOST 'sudo systemctl restart nginx'${NC}"
    echo -e "${YELLOW}   4. Verificar logs de Nginx: ssh $REMOTE_HOST 'sudo tail -20 /var/log/nginx/error.log'${NC}"
else
    echo -e "${GREEN}✅ Todo parece estar funcionando correctamente${NC}"
fi

echo ""
echo -e "${BLUE}Comandos útiles para diagnóstico adicional:${NC}"
echo -e "${YELLOW}  # Ver todos los contenedores:${NC}"
echo -e "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws ps'"
echo ""
echo -e "${YELLOW}  # Ver logs del backend en tiempo real:${NC}"
echo -e "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs -f backend-aws'"
echo ""
echo -e "${YELLOW}  # Ver logs de Nginx:${NC}"
echo -e "  ssh $REMOTE_HOST 'sudo tail -f /var/log/nginx/error.log'"
echo ""
echo -e "${YELLOW}  # Reiniciar todo el stack:${NC}"
echo -e "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker compose --profile aws restart'"
echo ""

