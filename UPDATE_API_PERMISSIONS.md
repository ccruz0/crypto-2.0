# 🔐 Guía para Actualizar Permisos de API Key en Crypto.com

**Fecha**: 16 de Diciembre, 2025

## 📋 Pasos para Actualizar Permisos

### Paso 1: Acceder a la Configuración de API

1. Inicia sesión en **Crypto.com Exchange** (no la app móvil)
   - URL: https://crypto.com/exchange
   
2. Ve a **Settings** (Configuración)
   - Click en tu perfil (esquina superior derecha)
   - Selecciona "Settings" o "API Management"

3. Navega a **API Management**
   - Busca la sección "API Keys" o "API Management"
   - Deberías ver una lista de tus API keys

### Paso 2: Editar la API Key

1. **Encuentra tu API key**: Busca la key que empieza con `z3HW...XWvQ`
2. **Click en "Edit"** o el ícono de edición
3. **Verifica los permisos disponibles**:
   - Busca opciones como:
     - ✅ Read Balance
     - ✅ Read Orders
     - ✅ Place Orders
     - ✅ Cancel Orders
     - ❓ **Read Order History** (puede estar deshabilitado)
     - ❓ **Read Trade History** (puede estar deshabilitado)
     - ❓ **View Orders** (puede incluir historial)

### Paso 3: Habilitar Permisos de Lectura

1. **Habilita TODOS los permisos de lectura disponibles**:
   - Cualquier opción que diga "Read", "View", o "Get"
   - Especialmente cualquier opción relacionada con:
     - Order History
     - Trade History
     - Executed Orders
     - Past Orders

2. **Si no ves una opción específica de "Order History"**:
   - Habilitar "Read Orders" puede incluir el historial
   - O puede que el endpoint tenga un bug conocido

3. **Guarda los cambios**

### Paso 4: Verificar Cambios

Después de actualizar los permisos, espera 1-2 minutos y prueba:

```bash
# Probar el sync manual
curl -X POST https://dashboard.hilovivo.com/api/orders/sync-history

# Verificar logs
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail=50 | grep -i 'order history\|authentication'"
```

## 🔍 Verificación de Permisos Actuales

Si Crypto.com no muestra claramente los permisos, puedes verificar probando diferentes endpoints:

### Endpoints que Funcionan (Confirman permisos básicos):
- ✅ `private/get-open-orders` - Funciona
- ✅ `private/user-balance` - Funciona  
- ✅ `private/create-order` - Funciona (puedes enviar órdenes)

### Endpoint que NO Funciona:
- ❌ `private/get-order-history` - Devuelve 40101

## ⚠️ Notas Importantes

1. **Algunos exchanges no muestran permisos específicos**: Puede que Crypto.com no tenga una opción explícita de "Read Order History" en la interfaz

2. **Puede ser un bug de Crypto.com**: Si no hay opción para habilitar "Order History" y otros endpoints funcionan, puede ser un bug conocido del endpoint

3. **Regenerar API Key**: Si no puedes encontrar la opción, considera:
   - Crear una nueva API key con TODOS los permisos habilitados
   - Actualizar las credenciales en `.env.aws`
   - Reiniciar los servicios

## 🔄 Después de Actualizar Permisos

1. **Esperar 1-2 minutos** para que los cambios se propaguen
2. **Probar el sync manual**:
   ```bash
   curl -X POST https://dashboard.hilovivo.com/api/orders/sync-history
   ```
3. **Verificar logs** para ver si ahora funciona
4. **Si sigue fallando**, contactar soporte de Crypto.com con el ticket de `CRYPTO_API_ISSUE_REPORT.md`

## 📞 Contactar Soporte (Si no funciona)

Si después de habilitar todos los permisos el endpoint sigue fallando:

1. Ir a Crypto.com Support
2. Mencionar que `private/get-order-history` devuelve 40101
3. Explicar que otros endpoints funcionan correctamente
4. Preguntar si se requieren permisos específicos o si es un bug conocido
5. Solicitar una solución o endpoint alternativo















