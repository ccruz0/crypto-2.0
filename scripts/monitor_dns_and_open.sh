#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Monitor DNS Propagation and Open Browser
# ============================================
# Checks DNS every 5 minutes
# When DNS resolves correctly and dashboard is accessible,
# opens browser maximized
# ============================================

DOMAIN="dashboard.hilovivo.com"
EXPECTED_IP="47.130.143.159"
URL="https://dashboard.hilovivo.com"
CHECK_INTERVAL=300  # 5 minutes in seconds

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

header() {
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}==========================================${NC}"
}

check_dns() {
    # Use Cloudflare DNS for faster propagation check
    local ip=$(dig @1.1.1.1 +short "$DOMAIN" A | head -1)
    if [ "$ip" = "$EXPECTED_IP" ]; then
        return 0
    else
        return 1
    fi
}

check_https() {
    # Check if HTTPS is accessible
    local status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL" 2>&1)
    if [ "$status" = "200" ]; then
        return 0
    else
        return 1
    fi
}

open_browser_maximized() {
    info "¡DNS propagado y dashboard accesible!"
    info "Abriendo navegador maximizado..."
    
    # Open Chrome in maximized window (macOS)
    if command -v open >/dev/null 2>&1; then
        # Open Chrome maximized
        osascript <<EOF
tell application "Google Chrome"
    activate
    set bounds of window 1 to {0, 0, 1920, 1080}
    open location "$URL"
end tell
EOF
        # If Chrome not available, try Safari
        if [ $? -ne 0 ]; then
            osascript <<EOF
tell application "Safari"
    activate
    set bounds of window 1 to {0, 0, 1920, 1080}
    open location "$URL"
end tell
EOF
        fi
    else
        # Fallback: just open URL
        open "$URL"
    fi
    
    info "Navegador abierto en: $URL"
}

header "Monitor de Propagación DNS"
echo "Dominio: $DOMAIN"
echo "IP esperada: $EXPECTED_IP"
echo "Verificando cada 5 minutos..."
echo "Presiona Ctrl+C para cancelar"
echo ""

ATTEMPT=1

while true; do
    CURRENT_TIME=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$CURRENT_TIME] Intento #$ATTEMPT: Verificando..."
    
    # Check DNS
    if check_dns; then
        info "✓ DNS resuelve correctamente a $EXPECTED_IP"
        
        # Check HTTPS
        if check_https; then
            info "✓ HTTPS accesible (200 OK)"
            echo ""
            header "¡Dashboard Listo!"
            open_browser_maximized
            echo ""
            info "Monitorización completada. Dashboard accesible."
            exit 0
        else
            warn "DNS correcto pero HTTPS aún no accesible. Esperando..."
        fi
    else
        CURRENT_IP=$(dig @1.1.1.1 +short "$DOMAIN" A | head -1 || echo "unknown")
        warn "DNS aún no propagado. IP actual: $CURRENT_IP (esperada: $EXPECTED_IP)"
    fi
    
    echo ""
    info "Esperando 5 minutos antes del siguiente intento..."
    echo ""
    
    sleep "$CHECK_INTERVAL"
    ((ATTEMPT++))
done

