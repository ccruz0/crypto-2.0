# 🔑 Instrucciones para Actualizar Credenciales a AWS KEY 3.1

## ⚠️ IMPORTANTE: Necesitas el Secret Key

Para actualizar las credenciales, necesitas el **Secret Key** de "AWS KEY 3.1".

**API Key**: `raHZAk1MDkAWviDpcBxAWU` ✅ (ya la tenemos)

**Secret Key**: ❓ (necesitas obtenerlo de Crypto.com Exchange)

## 📋 Cómo Obtener el Secret Key

### Opción 1: Si el Secret está Visible en Crypto.com

1. Ve a https://exchange.crypto.com/ → Settings → API Keys
2. Encuentra "AWS KEY 3.1" (`raHZAk1MDkAWviDpcBxAWU`)
3. Si el secret está visible, cópialo

### Opción 2: Si el Secret está Oculto (mostrando `****`)

Tienes estas opciones:

**A. Regenerar la Key** (creará nuevo secret):
1. Elimina "AWS KEY 3.1" actual
2. Crea nueva "AWS KEY 3.1"
3. Copia el nuevo API Key y Secret Key
4. Agrega IP `47.130.143.159` al whitelist
5. Habilita permiso "Read"

**B. Usar otra API Key**:
- Si tienes otra API key con secret conocido, úsala
- Asegúrate de que tenga IP `47.130.143.159` whitelisted
- Asegúrate de que tenga permiso "Read" habilitado

**C. Verificar si está guardado en otro lugar**:
- Busca en gestores de contraseñas
- Busca en otros archivos de configuración
- Busca en notas/documentación

## 🚀 Actualizar con el Script

Una vez que tengas el Secret Key:

```bash
# Ejecutar el script
./actualizar_credenciales_aws_key_3.1.sh

# Te pedirá el Secret Key de forma segura (no se mostrará en pantalla)
# Ingresa el Secret Key cuando te lo pida
```

El script actualizará:
- ✅ `.env.local` en AWS
- ✅ `.env.local` local (si existe)
- ✅ Otros archivos `.env*` que tengan credenciales

## 🔧 Actualizar Manualmente

Si prefieres hacerlo manualmente:

### En AWS:

```bash
# Conectarse al servidor
ssh ubuntu@47.130.143.159

# Editar .env.local
nano ~/automated-trading-platform/.env.local

# Actualizar estas líneas:
EXCHANGE_CUSTOM_API_KEY=raHZAk1MDkAWviDpcBxAWU
EXCHANGE_CUSTOM_API_SECRET=<tu_secret_key_aqui>

# Guardar (Ctrl+X, luego Y, luego Enter)

# Reiniciar backend
cd ~/automated-trading-platform
docker compose restart backend-aws
```

### En Local:

```bash
# Editar .env.local local
nano .env.local

# Actualizar las mismas líneas
EXCHANGE_CUSTOM_API_KEY=raHZAk1MDkAWviDpcBxAWU
EXCHANGE_CUSTOM_API_SECRET=<tu_secret_key_aqui>

# Guardar
```

## ✅ Verificación

Después de actualizar:

```bash
# Verificar en AWS
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform/backend && python3 scripts/deep_auth_diagnostic.py"
```

Deberías ver:
```
✅ SUCCESS! Authentication worked!
```

## 📝 Notas

- El script crea backups automáticos antes de actualizar
- Los backups tienen timestamp: `.bak.YYYYMMDD_HHMMSS`
- Puedes restaurar desde backup si algo sale mal

## 🔒 Seguridad

- El Secret Key se solicita de forma segura (no se muestra en pantalla)
- No se guarda en logs ni historial
- Los backups contienen credenciales, mantenlos seguros

