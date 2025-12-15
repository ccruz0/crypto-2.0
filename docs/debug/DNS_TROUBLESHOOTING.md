# DNS Troubleshooting - DNS Aún Apunta a IP Antigua

## Problema

Después de actualizar DNS en Hostinger, el comando `dig` sigue mostrando la IP antigua:
```bash
$ dig +short dashboard.hilovivo.com A
175.41.189.249  # ❌ IP antigua (incorrecta)
```

## Posibles Causas

### 1. DNS No Ha Sido Actualizado en Hostinger

**Solución**: Verifica que realmente actualizaste el registro A en Hostinger:
- Ve a: https://hpanel.hostinger.com
- Domains → hilovivo.com → DNS Management
- Busca el registro A para "dashboard"
- Debe mostrar: `47.130.143.159` (no `175.41.189.249`)

### 2. Cache DNS Local

**Solución**: Limpia el cache DNS en tu Mac:

```bash
# macOS
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

# Luego verifica de nuevo
dig +short dashboard.hilovivo.com A
```

### 3. Propagación DNS Lenta

DNS puede tardar 5 minutos a 48 horas dependiendo del TTL.

**Verifica desde múltiples servidores DNS**:

```bash
# Google DNS
dig @8.8.8.8 +short dashboard.hilovivo.com A

# Cloudflare DNS
dig @1.1.1.1 +short dashboard.hilovivo.com A

# OpenDNS
dig @208.67.222.222 +short dashboard.hilovivo.com A
```

Si todos muestran la IP antigua, DNS aún no se ha actualizado en Hostinger.

### 4. TTL Muy Alto

Si el TTL está en 3600 (1 hora) o más, la propagación será lenta.

**Solución**: 
- En Hostinger, cambia el TTL del registro A a 300 (5 minutos)
- Esto acelera la propagación

### 5. Múltiples Registros DNS

Puede haber múltiples registros A para dashboard.hilovivo.com.

**Verifica todos los registros**:

```bash
dig dashboard.hilovivo.com A +noall +answer
```

Si ves múltiples registros, elimina los que apuntan a la IP antigua.

## Pasos de Verificación

### Paso 1: Verifica en Hostinger

1. Log in: https://hpanel.hostinger.com
2. Ve a: Domains → hilovivo.com → DNS Management
3. Busca registro A para "dashboard"
4. **Confirma que dice**: `47.130.143.159`
5. Si dice `175.41.189.249`, **cámbialo ahora**

### Paso 2: Limpia Cache Local

```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

### Paso 3: Verifica desde Servidores DNS Públicos

```bash
# Verifica desde Google DNS
dig @8.8.8.8 +short dashboard.hilovivo.com A

# Debe retornar: 47.130.143.159
```

### Paso 4: Verifica Propagación Online

Usa herramientas online para verificar desde múltiples ubicaciones:
- https://www.whatsmydns.net/#A/dashboard.hilovivo.com
- https://dnschecker.org/#A/dashboard.hilovivo.com

Si todas las ubicaciones muestran la IP antigua, DNS no se ha actualizado en Hostinger.

## Solución Rápida

Si necesitas acceso inmediato mientras DNS se propaga:

### Opción 1: Usar IP Directa (Temporal)

Edita `/etc/hosts` en tu Mac:

```bash
sudo nano /etc/hosts
```

Agrega esta línea:
```
47.130.143.159 dashboard.hilovivo.com
```

Guarda y prueba:
```bash
curl -Ik https://dashboard.hilovivo.com
```

**Nota**: Esto solo funciona en tu Mac. Otros usuarios seguirán viendo el problema hasta que DNS se propague.

### Opción 2: Esperar Propagación

Si actualizaste DNS correctamente en Hostinger:
- Espera 5-60 minutos (dependiendo del TTL)
- Verifica periódicamente: `dig +short dashboard.hilovivo.com A`
- Cuando muestre `47.130.143.159`, DNS está propagado

## Verificación Final

Una vez que DNS muestre la IP correcta:

```bash
# Debe retornar: 47.130.143.159
dig +short dashboard.hilovivo.com A

# Ejecuta script de verificación
./scripts/verify_dashboard_dns.sh

# Prueba en navegador
# https://dashboard.hilovivo.com
```

## Comandos Útiles

```bash
# Ver DNS actual
dig +short dashboard.hilovivo.com A

# Ver desde servidor DNS específico
dig @8.8.8.8 +short dashboard.hilovivo.com A

# Ver todos los registros A
dig dashboard.hilovivo.com A +noall +answer

# Limpiar cache DNS (macOS)
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

# Verificar servidor directamente (bypass DNS)
curl -Ik https://47.130.143.159 -H "Host: dashboard.hilovivo.com"
```

## Contacto Hostinger

Si no puedes actualizar DNS en Hostinger:
- Soporte: https://www.hostinger.com/contact
- Email: support@hostinger.com
- Chat en vivo: Disponible en hpanel.hostinger.com

