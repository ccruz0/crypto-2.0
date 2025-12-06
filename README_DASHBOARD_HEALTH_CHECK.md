# Dashboard Health Check Service

## Descripción

Este servicio monitorea automáticamente que los datos del dashboard se estén cargando correctamente. Se ejecuta cada 20 minutos y verifica:

1. **Conectividad del endpoint**: Verifica que `/api/market/top-coins-data` responda correctamente
2. **Cantidad de datos**: Verifica que haya al menos 5 monedas disponibles
3. **Calidad de datos**: Verifica que las monedas tengan precios válidos (> 0)
4. **Notificaciones**: Envía alertas por Telegram si detecta problemas

## Instalación

El servicio se instala automáticamente ejecutando:

```bash
./install_dashboard_health_check.sh
```

Este script:
- Copia los archivos necesarios al servidor
- Carga las variables de entorno desde `.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
- Instala el servicio systemd y el timer
- Habilita y inicia el timer

## Archivos

- `scripts/dashboard_health_check.sh`: Script principal que realiza las verificaciones
- `scripts/dashboard_health_check.service`: Servicio systemd que ejecuta el script
- `scripts/dashboard_health_check.timer`: Timer systemd que ejecuta el servicio cada 20 minutos
- `install_dashboard_health_check.sh`: Script de instalación

## Configuración

El script usa las siguientes variables de entorno (cargadas desde `.env`):

- `API_URL`: URL del API (por defecto: `http://localhost:8002/api`)
- `TELEGRAM_BOT_TOKEN`: Token del bot de Telegram para notificaciones
- `TELEGRAM_CHAT_ID`: ID del chat de Telegram para notificaciones
- `MIN_COINS`: Número mínimo de monedas requeridas (por defecto: 5)
- `TIMEOUT`: Timeout para las peticiones HTTP (por defecto: 10 segundos)
- `LOG_FILE`: Archivo de log (por defecto: `/tmp/dashboard_health_check.log`)

## Uso

### Ver estado del timer

```bash
sudo systemctl status dashboard_health_check.timer
```

### Ver logs del servicio

```bash
sudo journalctl -u dashboard_health_check.service -f
```

### Ejecutar manualmente

```bash
sudo systemctl start dashboard_health_check.service
```

### Ver logs del script

```bash
tail -f /tmp/dashboard_health_check.log
# o desde el servidor:
tail -f /home/ubuntu/automated-trading-platform/logs/dashboard_health_check.log
```

## Notificaciones

El servicio envía notificaciones por Telegram:

- **Errores**: Se envían inmediatamente cuando se detecta un problema
- **Éxitos**: Se envían una vez por hora para evitar spam

## Verificaciones realizadas

1. **Endpoint responde**: Verifica que el endpoint HTTP responda en menos de 10 segundos
2. **JSON válido**: Verifica que la respuesta sea JSON válido
3. **Cantidad de monedas**: Verifica que haya al menos 5 monedas
4. **Calidad de datos**: Verifica que al menos 5 monedas tengan precios válidos (> 0)

## Solución de problemas

### El servicio no se ejecuta

1. Verificar que el timer esté activo:
   ```bash
   sudo systemctl status dashboard_health_check.timer
   ```

2. Verificar los logs:
   ```bash
   sudo journalctl -u dashboard_health_check.service -n 50
   ```

### Las notificaciones no llegan

1. Verificar que las variables de entorno estén configuradas:
   ```bash
   grep TELEGRAM /home/ubuntu/automated-trading-platform/.env
   ```

2. Verificar que el servicio tenga acceso a las variables:
   ```bash
   sudo systemctl show dashboard_health_check.service | grep TELEGRAM
   ```

### El endpoint no responde

1. Verificar que el backend esté funcionando:
   ```bash
   curl http://localhost:8002/api/health
   ```

2. Verificar los logs del backend:
   ```bash
   docker compose --profile aws logs backend-aws --tail 50
   ```

## Desinstalación

Para desinstalar el servicio:

```bash
sudo systemctl stop dashboard_health_check.timer
sudo systemctl disable dashboard_health_check.timer
sudo rm /etc/systemd/system/dashboard_health_check.service
sudo rm /etc/systemd/system/dashboard_health_check.timer
sudo systemctl daemon-reload
```

