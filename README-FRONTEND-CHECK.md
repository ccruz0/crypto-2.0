# Frontend Error Checker - Guía de Uso

Este proyecto incluye un script automatizado para verificar errores del frontend que pueden impedir que el dashboard funcione correctamente.

## Archivos

- `check-frontend-errors.sh`: Script principal que verifica errores
- `setup-hourly-check.sh`: Script para configurar la ejecución automática cada hora

## Uso Manual

Ejecutar el check manualmente:

```bash
./check-frontend-errors.sh
```

## Configuración Automática (Cada Hora)

Para configurar la ejecución automática cada hora:

```bash
./setup-hourly-check.sh
```

Esto creará un cron job que ejecutará el script cada hora a la hora en punto (1:00, 2:00, 3:00, etc.).

## Ver Logs

Los logs se guardan en:

- **Log detallado**: `frontend-error-check.log` - Contiene toda la salida de cada ejecución
- **Log de cron**: `frontend-error-check-cron.log` - Contiene solo la salida cuando se ejecuta via cron

Para ver el último log:

```bash
tail -f frontend-error-check.log
```

## Qué Verifica el Script

1. ✅ Verificación de Node.js y npm instalados
2. ✅ Instalación de dependencias (node_modules)
3. ✅ Verificación de tipos TypeScript
4. ✅ Verificación de ESLint (errores y warnings)
5. ✅ Verificación de build de Next.js
6. ✅ Verificación de patrones comunes de errores:
   - Inputs sin atributos de accesibilidad
   - Selects sin atributos de accesibilidad
   - Funciones async sin manejo de errores
7. ✅ Verificación de configuración (package.json, .env)

## Desinstalar Cron Job

Para remover el cron job:

```bash
crontab -l | grep -v "check-frontend-errors.sh" | crontab -
```

## Ejecución Manual del Cron Job

Si quieres ejecutar manualmente el check programado:

```bash
0 * * * * ./check-frontend-errors.sh
```

Esto ejecutará el script cada hora en el minuto 0.

## Notas

- El script no detiene el proceso si encuentra errores, solo los reporta
- Los warnings no bloquean el proceso pero se reportan
- Los errores críticos (como errores de compilación) se reportan como ERROR
- El script es idempotente: puede ejecutarse múltiples veces sin problemas

## Troubleshooting

Si el script no funciona:

1. Verifica que tenga permisos de ejecución: `chmod +x check-frontend-errors.sh`
2. Verifica que Node.js y npm estén instalados: `node --version` y `npm --version`
3. Verifica que el directorio frontend existe
4. Revisa el log para más detalles: `cat frontend-error-check.log`

