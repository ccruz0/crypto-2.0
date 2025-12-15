# Verificar DNS - Instrucciones Rápidas

## Desde el directorio del proyecto

```bash
cd ~/automated-trading-platform
./scripts/verify_dashboard_dns.sh
```

## Desde cualquier directorio

```bash
cd /Users/carloscruz/automated-trading-platform && ./scripts/verify_dashboard_dns.sh
```

## Comandos rápidos de verificación

### Verificar DNS actual
```bash
dig +short dashboard.hilovivo.com A
```

### Verificar desde Cloudflare DNS (ya actualizado)
```bash
dig @1.1.1.1 +short dashboard.hilovivo.com A
```

### Limpiar cache DNS (macOS)
```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

### Verificar servidor directamente
```bash
curl -Ik https://47.130.143.159 -H "Host: dashboard.hilovivo.com"
```

