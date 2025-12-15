# Solución Rápida - Cache DNS

## Problema
Tu Mac tiene la IP antigua en cache DNS:
```bash
dig +short dashboard.hilovivo.com A
# Muestra: 175.41.189.249 (antigua)
```

Pero Cloudflare DNS ya tiene la IP correcta:
```bash
dig @1.1.1.1 +short dashboard.hilovivo.com A
# Muestra: 47.130.143.159 (correcta) ✅
```

## Solución: Limpiar Cache DNS

Ejecuta estos comandos (te pedirá tu contraseña):

```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

## Verificar

Después de limpiar el cache:

```bash
dig +short dashboard.hilovivo.com A
# Debe mostrar: 47.130.143.159
```

## Acceso Inmediato (Alternativa)

Si quieres acceso inmediato sin esperar a que se limpie el cache:

### Opción 1: Usar Cloudflare DNS temporalmente

1. System Preferences → Network
2. Selecciona tu conexión (Wi-Fi o Ethernet)
3. Click "Advanced" → pestaña "DNS"
4. Agrega estos servidores DNS:
   - `1.1.1.1`
   - `1.0.0.1`
5. Click "OK" → "Apply"

Ahora tu Mac usará Cloudflare DNS que ya tiene la IP correcta.

### Opción 2: Editar /etc/hosts (Temporal)

```bash
sudo nano /etc/hosts
```

Agrega esta línea al final:
```
47.130.143.159 dashboard.hilovivo.com
```

Guarda (Ctrl+O, Enter, Ctrl+X)

**Nota**: Esto solo funciona en tu Mac. Otros usuarios seguirán viendo el problema hasta que DNS se propague completamente.

## Verificar Dashboard

Después de limpiar cache o cambiar DNS:

```bash
# Verificar DNS
dig +short dashboard.hilovivo.com A

# Probar en navegador
# https://dashboard.hilovivo.com
```

## Estado Actual

✅ **DNS actualizado en Hostinger**  
✅ **Cloudflare DNS tiene IP correcta**  
⏳ **Tu Mac tiene IP antigua en cache** (normal, se soluciona limpiando cache)

