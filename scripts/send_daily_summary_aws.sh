#!/bin/bash
# Script para ejecutar el resumen diario en AWS
# Uso: ./scripts/send_daily_summary_aws.sh [--local|--aws]

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Función para mostrar ayuda
show_help() {
    echo "Uso: $0 [OPCIONES]"
    echo ""
    echo "Ejecuta el resumen diario del trading bot."
    echo ""
    echo "Opciones:"
    echo "  --local     Forzar ejecución en contenedor local (backend)"
    echo "  --aws       Forzar ejecución en contenedor AWS (backend-aws)"
    echo "  --help      Mostrar esta ayuda"
    echo ""
    echo "Si no se especifica opción, detecta automáticamente el entorno."
}

# Parsear argumentos
FORCE_LOCAL=false
FORCE_AWS=false

for arg in "$@"; do
    case $arg in
        --local)
            FORCE_LOCAL=true
            shift
            ;;
        --aws)
            FORCE_AWS=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo -e "${YELLOW}⚠️  Argumento desconocido: $arg${NC}"
            show_help
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🚀 Ejecutando resumen diario...${NC}"

# Detectar si estamos en Docker o en el servidor
if [ -f /.dockerenv ] || [ -n "$DOCKER_CONTAINER" ]; then
    # Estamos dentro del contenedor Docker
    echo -e "${GREEN}📦 Ejecutando desde dentro del contenedor Docker...${NC}"
    cd /app || cd /backend || { echo -e "${RED}❌ No se pudo encontrar el directorio /app o /backend${NC}"; exit 1; }
    
    # Verificar que el script existe
    if [ ! -f "scripts/send_daily_summary.py" ]; then
        echo -e "${RED}❌ No se encontró el script scripts/send_daily_summary.py${NC}"
        echo "Directorio actual: $(pwd)"
        echo "Archivos en scripts/:"
        ls -la scripts/ 2>/dev/null || echo "Directorio scripts/ no existe"
        exit 1
    fi
    
    python3 scripts/send_daily_summary.py
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✅ Resumen diario ejecutado exitosamente${NC}"
    else
        echo -e "${RED}❌ Error ejecutando resumen diario (código: $EXIT_CODE)${NC}"
        exit $EXIT_CODE
    fi
else
    # Estamos en el servidor, ejecutar dentro del contenedor
    echo -e "${BLUE}🖥️  Ejecutando desde el servidor, accediendo al contenedor Docker...${NC}"
    
    # Verificar que Docker está disponible
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker no está instalado o no está en el PATH${NC}"
        exit 1
    fi
    
    # Verificar que Docker está corriendo
    if ! docker ps &> /dev/null; then
        echo -e "${RED}❌ Docker no está corriendo o no tienes permisos${NC}"
        exit 1
    fi
    
    CONTAINER_NAME=""
    
    # Buscar contenedor según la opción forzada o automáticamente
    if [ "$FORCE_AWS" = true ]; then
        echo -e "${YELLOW}🔍 Buscando contenedor backend-aws (forzado)...${NC}"
        CONTAINER_NAME=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
    elif [ "$FORCE_LOCAL" = true ]; then
        echo -e "${YELLOW}🔍 Buscando contenedor backend (forzado)...${NC}"
        CONTAINER_NAME=$(docker ps --filter "name=backend" --filter "name!=backend-aws" --format "{{.Names}}" | head -1)
    else
        # Detección automática: preferir backend-aws si existe, sino backend
        echo -e "${YELLOW}🔍 Detectando contenedor automáticamente...${NC}"
        CONTAINER_NAME=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
        
        if [ -z "$CONTAINER_NAME" ]; then
            CONTAINER_NAME=$(docker ps --filter "name=backend" --filter "name!=backend-aws" --format "{{.Names}}" | head -1)
        fi
    fi
    
    if [ -z "$CONTAINER_NAME" ]; then
        echo -e "${RED}❌ No se encontró el contenedor del backend${NC}"
        echo ""
        echo "Contenedores disponibles:"
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" || true
        echo ""
        echo "Sugerencias:"
        echo "  - Usa --local para forzar búsqueda de contenedor local"
        echo "  - Usa --aws para forzar búsqueda de contenedor AWS"
        echo "  - Verifica que el contenedor esté corriendo: docker ps -a"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Contenedor encontrado: ${CONTAINER_NAME}${NC}"
    
    # Verificar que el contenedor está corriendo
    CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")
    if [ "$CONTAINER_STATUS" != "running" ]; then
        echo -e "${RED}❌ El contenedor $CONTAINER_NAME no está corriendo (estado: $CONTAINER_STATUS)${NC}"
        echo "Inicia el contenedor con: docker start $CONTAINER_NAME"
        exit 1
    fi
    
    echo -e "${BLUE}📤 Ejecutando resumen diario en $CONTAINER_NAME...${NC}"
    echo ""
    
    # Ejecutar el script dentro del contenedor
    docker exec "$CONTAINER_NAME" python3 /app/scripts/send_daily_summary.py
    EXIT_CODE=$?
    
    echo ""
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✅ Resumen diario ejecutado exitosamente${NC}"
    else
        echo -e "${RED}❌ Error ejecutando resumen diario (código: $EXIT_CODE)${NC}"
        echo ""
        echo "Para ver los logs del contenedor:"
        echo "  docker logs $CONTAINER_NAME --tail 50"
        exit $EXIT_CODE
    fi
fi







