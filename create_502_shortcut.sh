#!/bin/bash

# Script para crear un acceso directo en el escritorio con icono "502"
# para diagnosticar y solucionar el error 502 del dashboard

DESKTOP_PATH="$HOME/Desktop"
SCRIPT_PATH="/Users/carloscruz/automated-trading-platform/fix_502_dashboard.sh"
SHORTCUT_NAME="Fix 502 Dashboard"
APP_NAME="Fix_502_Dashboard.app"
APP_PATH="$DESKTOP_PATH/$APP_NAME"

echo "🔧 Creando acceso directo en el escritorio..."
echo "📁 Ubicación: $APP_PATH"
echo ""

# Crear el directorio de la aplicación
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Crear el script ejecutable dentro de la app que abre una terminal
SCRIPT_CONTENT='#!/bin/bash
# Abrir una terminal y ejecutar el script principal
SCRIPT_PATH="/Users/carloscruz/automated-trading-platform/fix_502_dashboard.sh"

# Abrir Terminal.app con el script
osascript -e "tell application \"Terminal\"" -e "activate" -e "do script \"cd /Users/carloscruz/automated-trading-platform && bash $SCRIPT_PATH\"" -e "end tell"'

echo "$SCRIPT_CONTENT" > "$APP_PATH/Contents/MacOS/Fix_502_Dashboard"

chmod +x "$APP_PATH/Contents/MacOS/Fix_502_Dashboard"

# Crear el Info.plist
cat > "$APP_PATH/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Fix_502_Dashboard</string>
    <key>CFBundleIdentifier</key>
    <string>com.hilovivo.fix502dashboard</string>
    <key>CFBundleName</key>
    <string>Fix 502 Dashboard</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
</dict>
</plist>
EOF

# Crear un icono simple con "502" usando Python
ICON_PNG="/tmp/icon_502.png"

# Verificar si PIL está disponible
if python3 -c "from PIL import Image" 2>/dev/null; then
    python3 << 'PYTHON_SCRIPT'
from PIL import Image, ImageDraw, ImageFont
import os

# Crear una imagen de 512x512
img = Image.new('RGB', (512, 512), color='#FF4444')  # Rojo para error
draw = ImageDraw.Draw(img)

# Intentar usar una fuente del sistema, o usar la fuente por defecto
try:
    # Intentar diferentes fuentes comunes en macOS
    font_paths = [
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Arial.ttf',
        '/Library/Fonts/Arial.ttf',
    ]
    font = None
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, 200)
                break
            except:
                continue
    if font is None:
        font = ImageFont.load_default()
except:
    font = ImageFont.load_default()

# Dibujar "502" en el centro
text = "502"
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
x = (512 - text_width) / 2
y = (512 - text_height) / 2 - 50

# Dibujar sombra
draw.text((x+5, y+5), text, fill='#CC0000', font=font)
# Dibujar texto principal
draw.text((x, y), text, fill='white', font=font)

# Guardar como PNG temporal
icon_path = '/tmp/icon_502.png'
img.save(icon_path, 'PNG')
print(f"Icono creado en: {icon_path}")
PYTHON_SCRIPT
else
    # Si PIL no está disponible, crear un icono simple usando sips y texto
    echo "⚠️  PIL no está disponible, creando icono alternativo..."
    # Crear un icono simple con sips (herramienta nativa de macOS)
    sips -c "#FF4444" --setProperty format png /System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericDocumentIcon.icns --out "$ICON_PNG" 2>/dev/null || {
        # Si sips falla, crear un archivo de texto simple que se puede convertir
        echo "502" > /tmp/icon_text.txt
    }
fi

# Convertir PNG a ICNS (si sips está disponible)
ICON_ICNS="$APP_PATH/Contents/Resources/icon.icns"

if [ -f "$ICON_PNG" ]; then
    # Usar sips para crear icono (macOS)
    if command -v sips &> /dev/null; then
        # Crear un icono temporal en diferentes tamaños
        ICONSET_PATH="/tmp/icon_502.iconset"
        mkdir -p "$ICONSET_PATH"
        
        # Generar diferentes tamaños requeridos para .icns
        sizes=(16 32 64 128 256 512)
        for size in "${sizes[@]}"; do
            sips -z $size $size "$ICON_PNG" --out "$ICONSET_PATH/icon_${size}x${size}.png" &> /dev/null
            sips -z $((size*2)) $((size*2)) "$ICON_PNG" --out "$ICONSET_PATH/icon_${size}x${size}@2x.png" &> /dev/null
        done
        
        # Convertir iconset a icns
        iconutil -c icns "$ICONSET_PATH" -o "$ICON_ICNS" 2>/dev/null || {
            # Si iconutil falla, usar el PNG directamente
            cp "$ICON_PNG" "$APP_PATH/Contents/Resources/icon.png"
            # Actualizar Info.plist para usar PNG
            sed -i '' 's/icon.icns/icon.png/' "$APP_PATH/Contents/Info.plist"
        }
        
        rm -rf "$ICONSET_PATH"
    else
        # Si no hay sips, copiar el PNG
        cp "$ICON_PNG" "$APP_PATH/Contents/Resources/icon.png"
        sed -i '' 's/icon.icns/icon.png/' "$APP_PATH/Contents/Info.plist"
    fi
    
    # Limpiar PNG temporal
    rm -f "$ICON_PNG"
fi

# Si no se pudo crear el icono, crear uno simple con texto
if [ ! -f "$APP_PATH/Contents/Resources/icon.icns" ] && [ ! -f "$APP_PATH/Contents/Resources/icon.png" ]; then
    echo "⚠️  No se pudo crear icono personalizado, usando icono por defecto"
fi

# Establecer el icono de la aplicación
if [ -f "$ICON_ICNS" ] || [ -f "$APP_PATH/Contents/Resources/icon.png" ]; then
    # Usar Rez/SetFile si está disponible, o usar un método alternativo
    if command -v SetFile &> /dev/null; then
        SetFile -a C "$APP_PATH"
    fi
fi

echo "✅ Acceso directo creado: $APP_PATH"
echo ""
echo "📝 Para usar:"
echo "   1. Haz doble clic en '$SHORTCUT_NAME' en el escritorio"
echo "   2. Se abrirá el navegador con el dashboard"
echo "   3. Se ejecutarán diagnósticos automáticos"
echo "   4. Se abrirán los archivos relevantes en Cursor"
echo ""














