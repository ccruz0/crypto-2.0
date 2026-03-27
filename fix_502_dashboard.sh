#!/bin/bash

# Script para diagnosticar y solucionar error 502 en el dashboard
# Este script abre el navegador, ejecuta diagnósticos y abre Cursor con archivos relevantes

DASHBOARD_URL="https://dashboard.hilovivo.com"
PROJECT_PATH="/Users/carloscruz/automated-trading-platform"
CURSOR_APP="/Applications/Cursor.app"

# Función para crear archivo de comandos y ejecutar comandos en Cursor terminal
COMMANDS_FILE="$PROJECT_PATH/.502_diagnostic_commands.sh"

run_in_cursor_terminal() {
    local command="$1"
    echo ""
    echo -e "${YELLOW}📋 Comando para ejecutar en Cursor Terminal:${NC}"
    echo -e "${CYAN}$command${NC}"
    echo ""
    echo -e "${YELLOW}💡 Copia y pega este comando en la terminal de Cursor (⌘+J)${NC}"
    echo ""
    # Agregar comando al archivo
    echo "$command" >> "$COMMANDS_FILE"
}

# Crear archivo de comandos (limpiar si existe)
create_commands_file() {
    cat > "$COMMANDS_FILE" << 'EOF'
#!/bin/bash
# Comandos de diagnóstico 502 - Ejecuta estos comandos en la terminal de Cursor (⌘+J)
# O ejecuta este archivo completo: bash .502_diagnostic_commands.sh

EOF
    chmod +x "$COMMANDS_FILE"
}

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

clear
echo -e "${BLUE}=========================================="
echo "🔍 Diagnóstico Error 502 - Dashboard"
echo "==========================================${NC}"
echo ""
echo -e "${CYAN}📊 Dashboard URL:${NC} $DASHBOARD_URL"
echo -e "${CYAN}📁 Proyecto:${NC} $PROJECT_PATH"
echo ""

# Crear archivo de comandos
create_commands_file

# Función para abrir Cursor con archivos específicos
open_cursor_files() {
    echo -e "${BLUE}📂 Abriendo archivos relevantes en Cursor...${NC}"
    
    # Archivos clave para diagnosticar 502
    FILES=(
        "$PROJECT_PATH/backend/app/api/routes_dashboard.py"
        "$PROJECT_PATH/nginx/dashboard.conf"
        "$PROJECT_PATH/docker-compose.yml"
        "$PROJECT_PATH/docs/502_BAD_GATEWAY_REVIEW.md"
        "$PROJECT_PATH/backend/app/services/exchange_sync.py"
        "$PROJECT_PATH/.github/workflows/deploy.yml"
    )
    
    # Verificar qué archivos existen
    EXISTING_FILES=()
    for file in "${FILES[@]}"; do
        if [ -f "$file" ]; then
            EXISTING_FILES+=("$file")
            echo -e "  ${GREEN}✓${NC} $file"
        else
            echo -e "  ${YELLOW}⚠${NC} $file (no encontrado)"
        fi
    done
    
    # Abrir Cursor con los archivos
    if [ -d "$CURSOR_APP" ]; then
        if [ ${#EXISTING_FILES[@]} -gt 0 ]; then
            # Abrir Cursor con el workspace primero, luego los archivos
            open -a "Cursor" "$PROJECT_PATH"
            sleep 1
            for file in "${EXISTING_FILES[@]}"; do
                open -a "Cursor" "$file"
            done
            echo -e "${GREEN}✅ Archivos abiertos en Cursor${NC}"
        else
            echo -e "${YELLOW}⚠️  No se encontraron archivos para abrir${NC}"
            open -a "Cursor" "$PROJECT_PATH"
        fi
    else
        echo -e "${YELLOW}⚠️  Cursor no encontrado en $CURSOR_APP${NC}"
        echo "   Abriendo archivos con editor por defecto..."
        for file in "${EXISTING_FILES[@]}"; do
            open "$file"
        done
    fi
}

# Función para ejecutar diagnóstico remoto
run_diagnostics() {
    echo -e "${BLUE}🔧 Diagnóstico del error 502${NC}"
    echo ""
    
    # Verificar si hay script de diagnóstico
    if [ -f "$PROJECT_PATH/scripts/debug_dashboard_remote.sh" ]; then
        echo -e "${CYAN}📋 Script de diagnóstico disponible:${NC}"
        echo -e "${GREEN}   scripts/debug_dashboard_remote.sh${NC}"
        echo ""
        run_in_cursor_terminal "bash scripts/debug_dashboard_remote.sh"
        
        echo -e "${YELLOW}🔄 Ejecutando diagnóstico ahora (puedes cancelar y ejecutarlo en Cursor)...${NC}"
        echo ""
        cd "$PROJECT_PATH"
        bash scripts/debug_dashboard_remote.sh
    else
        echo -e "${YELLOW}⚠️  Script de diagnóstico no encontrado${NC}"
        echo ""
        echo -e "${CYAN}📊 Comandos de diagnóstico disponibles:${NC}"
        echo ""
        
        # Mostrar comandos para ejecutar en Cursor
        run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws ps'"
        
        run_in_cursor_terminal "ssh hilovivo-aws 'curl -s http://localhost:8002/health || echo \"Backend no responde\"'"
        
        run_in_cursor_terminal "ssh hilovivo-aws 'sudo systemctl status nginx --no-pager | head -5'"
        
        echo -e "${YELLOW}🔄 Ejecutando comandos básicos ahora...${NC}"
        echo ""
        
        # Ejecutar comandos básicos de diagnóstico
        echo -e "${CYAN}📊 Verificando estado de servicios en AWS...${NC}"
        ssh hilovivo-aws "cd ~/crypto-2.0 && docker compose --profile aws ps" 2>/dev/null || echo -e "${RED}❌ No se pudo conectar a AWS${NC}"
        
        echo ""
        echo -e "${CYAN}🌐 Verificando backend...${NC}"
        ssh hilovivo-aws "curl -s http://localhost:8002/health || echo 'Backend no responde'" 2>/dev/null || echo -e "${RED}❌ No se pudo verificar backend${NC}"
        
        echo ""
        echo -e "${CYAN}🔧 Verificando nginx...${NC}"
        ssh hilovivo-aws "sudo systemctl status nginx --no-pager | head -5" 2>/dev/null || echo -e "${RED}❌ No se pudo verificar nginx${NC}"
    fi
}

# Abrir Cursor PRIMERO para que el usuario pueda ver y ejecutar comandos
echo ""
echo -e "${BLUE}📂 Abriendo Cursor con el proyecto...${NC}"
if [ -d "$CURSOR_APP" ]; then
    open -a "Cursor" "$PROJECT_PATH"
    echo -e "${GREEN}✅ Cursor abierto${NC}"
    echo ""
    echo -e "${YELLOW}💡 Abre la terminal en Cursor con ⌘+J (Cmd+J) para ejecutar los comandos${NC}"
    sleep 3
else
    echo -e "${YELLOW}⚠️  Cursor no encontrado, abriendo archivos con editor por defecto...${NC}"
fi

# Abrir el dashboard en el navegador (en segundo plano para no bloquear)
echo ""
echo -e "${BLUE}🌐 Abriendo dashboard en el navegador...${NC}"
open "$DASHBOARD_URL" &

# Esperar un momento para que el navegador se abra
sleep 2

# Ejecutar diagnósticos
run_diagnostics

# Abrir archivos específicos
echo ""
open_cursor_files

# Abrir el archivo de comandos en Cursor
if [ -f "$COMMANDS_FILE" ]; then
    echo ""
    echo -e "${BLUE}📝 Abriendo archivo de comandos en Cursor...${NC}"
    open -a "Cursor" "$COMMANDS_FILE"
    echo -e "${GREEN}✅ Archivo de comandos abierto: .502_diagnostic_commands.sh${NC}"
    echo -e "${YELLOW}💡 Puedes ejecutar este archivo completo en la terminal de Cursor:${NC}"
    echo -e "${CYAN}   bash .502_diagnostic_commands.sh${NC}"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "✅ Diagnóstico completado"
echo "==========================================${NC}"
echo ""
echo -e "${CYAN}📝 Próximos pasos:${NC}"
echo "   1. Revisa el dashboard en el navegador"
echo "   2. Abre la terminal en Cursor (⌘+J)"
echo "   3. Ejecuta los comandos del archivo .502_diagnostic_commands.sh"
echo "   4. O copia y pega los comandos mostrados arriba"
echo "   5. Revisa los archivos abiertos en Cursor"
echo ""
echo -e "${YELLOW}🔧 Comandos rápidos para ejecutar en Cursor Terminal:${NC}"
echo ""
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws ps frontend-aws'"
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws up -d frontend-aws'"
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws restart && sudo systemctl restart nginx'"
echo ""
echo -e "${CYAN}💡 Otros comandos útiles:${NC}"
run_in_cursor_terminal "ssh hilovivo-aws 'sudo systemctl restart nginx'"
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws restart backend-aws'"
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws logs --tail=50 frontend-aws'"
run_in_cursor_terminal "ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws logs --tail=50 backend-aws'"
echo ""
echo -e "${GREEN}💡 Tip: Todos los comandos están guardados en .502_diagnostic_commands.sh${NC}"
echo ""














