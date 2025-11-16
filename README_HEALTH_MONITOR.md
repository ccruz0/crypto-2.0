# Health Monitor y Auto-Recovery

## Descripción

El sistema de monitoreo de salud (`health_monitor.sh`) es un servicio que se ejecuta en background y monitorea constantemente todos los servicios Docker de la plataforma de trading automatizado. Detecta fallos automáticamente y los corrige sin intervención manual.

## Características

### ✅ Monitoreo Continuo
- Verifica el estado de salud de todos los servicios cada 60 segundos
- Detecta servicios que están:
  - Detenidos (not running)
  - Ejecutándose pero no saludables (unhealthy)
  - En estado desconocido

### ✅ Auto-Recovery
- **Reinicio automático**: Intenta reiniciar servicios fallidos hasta 3 veces
- **Rebuild automático**: Si el reinicio falla, reconstruye la imagen del servicio
- **Recuperación de base de datos**: Verifica y reinicia la base de datos si no está lista
- **Monitoreo de Nginx**: Verifica y reinicia Nginx si está caído

### ✅ Logging Detallado
- Todos los eventos se registran en `/home/ubuntu/automated-trading-platform/logs/health_monitor.log`
- Errores se registran en `/home/ubuntu/automated-trading-platform/logs/health_monitor.error.log`
- Logs incluyen timestamps y niveles de severidad (INFO, WARN, ERROR)

## Instalación

El monitor se instala automáticamente ejecutando:

```bash
./install_health_monitor.sh
```

Este script:
1. Copia `health_monitor.sh` al servidor
2. Crea el servicio systemd `health_monitor.service`
3. Habilita el servicio para que inicie automáticamente en el boot
4. Inicia el servicio inmediatamente

## Verificación del Estado

### Ver estado del servicio:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'sudo systemctl status health_monitor'
```

### Ver logs en tiempo real:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'tail -f /home/ubuntu/automated-trading-platform/logs/health_monitor.log'
```

### Ver errores:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'tail -f /home/ubuntu/automated-trading-platform/logs/health_monitor.error.log'
```

## Configuración

El script se puede configurar editando las variables al inicio de `health_monitor.sh`:

```bash
MAX_RESTART_ATTEMPTS=3      # Intentos de reinicio antes de rebuild
CHECK_INTERVAL=60           # Intervalo entre checks (segundos)
```

## Servicios Monitoreados

El monitor verifica automáticamente todos los servicios con perfil `aws`:
- `backend-aws` - Backend API
- `frontend-aws` - Frontend Next.js
- `market-updater` - Actualizador de datos de mercado
- `db` - Base de datos PostgreSQL
- `gluetun` - VPN/Túnel (se omite en checks críticos)
- `aws-backup` - Backup de base de datos

## Comportamiento del Monitor

### Ciclo de Verificación:
1. **Check de salud**: Verifica el estado de cada servicio
2. **Detección de problemas**: Identifica servicios con problemas
3. **Recuperación**: Intenta recuperar servicios fallidos
4. **Logging**: Registra todas las acciones

### Estrategia de Recuperación:
1. **Primer intento**: Reinicio simple del servicio
2. **Segundo intento**: Reinicio con stop/start
3. **Tercer intento**: Rebuild completo de la imagen
4. **Después de rebuild**: Reinicia el contador y vuelve a intentar

### Protecciones:
- No reinicia servicios más de 3 veces seguidas sin rebuild
- Resetea contadores después de rebuild exitoso
- No falla si no puede escribir logs (usa stdout como fallback)
- Maneja errores gracefully sin detener el monitor

## Troubleshooting

### El monitor no está corriendo:
```bash
sudo systemctl start health_monitor
sudo systemctl enable health_monitor  # Para iniciar en boot
```

### El monitor está fallando:
```bash
# Ver logs detallados
sudo journalctl -u health_monitor -n 50 --no-pager

# Verificar permisos
ls -la /home/ubuntu/automated-trading-platform/scripts/health_monitor.sh
ls -la /home/ubuntu/automated-trading-platform/logs/
```

### Un servicio sigue fallando:
El monitor intentará recuperarlo automáticamente. Si después de múltiples rebuilds sigue fallando, puede requerir intervención manual:
1. Revisar logs del servicio: `docker compose --profile aws logs <service>`
2. Verificar configuración en `docker-compose.yml`
3. Verificar recursos del servidor: `docker stats`

## Integración con Deploy

El monitor funciona independientemente del proceso de deploy. Cuando ejecutas `./deploy_aws.sh`, el monitor:
- Detectará cuando los servicios se detengan durante el deploy
- Intentará recuperar servicios que no inicien correctamente
- Continuará monitoreando después del deploy

## Notas Importantes

- El monitor se ejecuta como servicio systemd en el servidor AWS
- No requiere acceso SSH desde fuera (corre localmente)
- Los logs se rotan automáticamente por systemd
- El monitor no modifica archivos de configuración, solo reinicia servicios

