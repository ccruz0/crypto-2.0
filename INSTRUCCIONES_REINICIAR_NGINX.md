# Instrucciones para Reiniciar Nginx y Solucionar el Error 502

## Problema
El dashboard en AWS (https://dashboard.hilovivo.com) muestra error 502 (Bad Gateway) porque nginx no puede conectarse al backend después de que se reinició.

## Solución Rápida

### Opción 1: Ejecutar comando directo en el servidor
Si tienes acceso SSH al servidor, ejecuta:

```bash
ssh ubuntu@54.254.150.31 "sudo systemctl restart nginx"
```

### Opción 2: Usar el script automatizado
Ejecuta el script desde tu máquina local:

```bash
# Copiar el script al servidor
scp restart_nginx_on_server.sh ubuntu@54.254.150.31:~/

# Ejecutar en el servidor
ssh ubuntu@54.254.150.31 "bash ~/restart_nginx_on_server.sh"
```

### Opción 3: Ejecutar comandos manualmente en el servidor
Si estás conectado al servidor, ejecuta:

```bash
# 1. Verificar estado de nginx
sudo systemctl status nginx

# 2. Verificar que el backend está accesible
curl http://localhost:8002/health

# 3. Reiniciar nginx
sudo systemctl restart nginx

# 4. Verificar que nginx está corriendo
sudo systemctl status nginx

# 5. Verificar logs de error
sudo tail -20 /var/log/nginx/error.log
```

## Verificación

Después de reiniciar nginx, verifica que el problema está resuelto:

1. Abre el navegador en: https://dashboard.hilovivo.com
2. Abre la consola del navegador (F12)
3. Verifica que las peticiones a `/api/*` ahora devuelven 200 en lugar de 502

## Diagnóstico Adicional

Si el problema persiste después de reiniciar nginx, ejecuta el script de diagnóstico:

```bash
# En el servidor
bash diagnose_nginx_backend.sh
```

Este script verificará:
- Estado de nginx
- Conectividad al backend
- Logs de error
- Configuración de nginx

## Notas

- El backend está funcionando correctamente (puerto 8002)
- El problema es que nginx necesita reconectarse después de reinicios del backend
- Reiniciar nginx es seguro y no afecta otras conexiones activas

