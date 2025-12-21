# 📝 Instrucciones para Actualizar Permisos de API Key

## 🎯 Pasos Rápidos

### 1. Acceder a Crypto.com Exchange

1. Ve a: **https://crypto.com/exchange**
2. Inicia sesión con tu cuenta

### 2. Ir a API Management

1. Click en tu **perfil** (esquina superior derecha)
2. Selecciona **"Settings"** o **"API Management"**
3. Busca la sección **"API Keys"**

### 3. Editar tu API Key

1. **Encuentra tu API key**: La que empieza con `z3HW...XWvQ`
2. Click en **"Edit"** o el ícono de lápiz
3. **Habilita TODOS los permisos de lectura**:
   - ✅ **Can Read** (Puede leer) - **DEBE estar activado**
   - ✅ **Enable Trading** (si lo necesitas)
   - ✅ Cualquier otra opción de "Read" o "View"

### 4. Verificar IP Whitelist

1. Asegúrate de que la IP `47.130.143.159` esté en la whitelist
2. Si no está, agrégala
3. Guarda los cambios

### 5. Guardar y Confirmar

1. Click en **"Save"** o **"Update"**
2. Confirma con tu **2FA** (código de autenticación de dos factores)
3. **Espera 1-2 minutos** para que los cambios se propaguen

## ✅ Verificación Después de Actualizar

Ejecuta el script de verificación:

```bash
./verify_api_permissions.sh
```

O manualmente:

```bash
# Probar sync manual
curl -X POST https://dashboard.hilovivo.com/api/orders/sync-history

# Verificar logs
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail=50 | grep -i 'order history\|authentication\|Received.*orders'"
```

## 🔍 Qué Buscar

### ✅ Signos de Éxito:
- No hay errores "40101" en los logs
- Los logs muestran "Received X orders from API"
- Las órdenes aparecen en la base de datos

### ❌ Si Sigue Fallando:
- Puede ser un bug conocido de Crypto.com
- Considera contactar soporte
- O crear una nueva API key con todos los permisos desde el inicio

## 📞 Si Necesitas Ayuda

Si después de actualizar los permisos el problema persiste:

1. Verifica que "Can Read" esté activado
2. Verifica que la IP esté en la whitelist
3. Espera 2-3 minutos más
4. Si sigue fallando, es probablemente un bug de Crypto.com















