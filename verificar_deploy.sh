#!/bin/bash
# Script para verificar el estado del deploy

set -e

echo "🔍 Verificando estado del deploy..."
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Verificar commit
COMMIT_HASH=$(git log -1 --oneline | cut -d' ' -f1)
print_info "Último commit: $COMMIT_HASH"
echo ""

# Verificar GitHub Actions (si hay token configurado)
if [ -n "$GITHUB_TOKEN" ]; then
    print_info "Verificando estado del workflow en GitHub Actions..."
    WORKFLOW_RUNS=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/ccruz0/crypto-2.0/actions/workflows/deploy.yml/runs?per_page=1")
    
    STATUS=$(echo "$WORKFLOW_RUNS" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
    CONCLUSION=$(echo "$WORKFLOW_RUNS" | grep -o '"conclusion":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    if [ -n "$STATUS" ]; then
        print_info "Estado del workflow: $STATUS"
        if [ -n "$CONCLUSION" ]; then
            if [ "$CONCLUSION" = "success" ]; then
                print_status "Workflow completado exitosamente"
            elif [ "$CONCLUSION" = "failure" ]; then
                print_error "Workflow falló"
            else
                print_warning "Conclusión: $CONCLUSION"
            fi
        fi
    else
        print_warning "No se pudo obtener el estado del workflow"
    fi
    echo ""
else
    print_warning "GITHUB_TOKEN no configurado. Para verificar el workflow, configura:"
    echo "  export GITHUB_TOKEN=tu_token"
    echo ""
    print_info "O visita: https://github.com/ccruz0/crypto-2.0/actions"
    echo ""
fi

# Verificar directamente en AWS (si SSH está disponible)
print_info "Intentando verificar servicios en AWS..."
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no hilovivo-aws "echo 'Connected'" > /dev/null 2>&1; then
    print_status "Conexión SSH exitosa"
    echo ""
    
    # Verificar servicios
    print_info "Estado de los servicios:"
    ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws ps' || print_warning "No se pudo obtener estado de servicios"
    echo ""
    
    # Verificar que el fix de Telegram está aplicado
    print_info "Verificando que el fix de Telegram está aplicado..."
    if ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws exec -T backend-aws python3 -c "from app.services.telegram_notifier import TelegramNotifier; import inspect; src = inspect.getsource(TelegramNotifier.send_sl_tp_orders); exit(0 if \"origin=get_runtime_origin()\" in src or \"origin=origin\" in src else 1)"' 2>/dev/null; then
        print_status "✅ Fix de Telegram aplicado correctamente"
    else
        print_warning "⚠️  No se pudo verificar el fix de Telegram (puede que el servicio aún no se haya reiniciado)"
    fi
    echo ""
    
    # Verificar logs recientes
    print_info "Últimos logs del backend (últimas 10 líneas):"
    ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail 10' 2>/dev/null || print_warning "No se pudieron obtener logs"
else
    print_warning "No se pudo conectar a AWS vía SSH"
    print_info "Verifica manualmente:"
    echo "  ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws ps'"
fi

echo ""
print_info "Para ver el progreso completo del deploy:"
echo "  https://github.com/ccruz0/crypto-2.0/actions"
