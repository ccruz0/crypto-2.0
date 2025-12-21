# Investigación: Problemas de Conectividad del Backend

## Resumen
El frontend está funcionando correctamente y el error de React #310 está resuelto. Sin embargo, hay problemas de conectividad con el backend que causan timeouts y errores "Failed to fetch".

## Arquitectura Identificada

### Frontend
- **URL**: `https://dashboard.hilovivo.com`
- **Configuración**: Usa ruta relativa `/api` para llamadas al backend
- **Archivo**: `frontend/src/lib/environment.ts` - Detecta automáticamente el entorno

### Backend
- **Puerto**: `8002` (expuesto en Docker)
- **Servicio**: `backend-aws` (Docker Compose profile: aws)
- **Health Check**: `/health` y `/ping_fast`

### Nginx (Proxy Reverso)
- **Función**: Enruta peticiones `/api/*` al backend en `localhost:8002`
- **Problema**: Necesita reiniciarse después de que el backend se reinicia

## Problemas Identificados

1. **Nginx no puede conectarse al backend** después de reinicios
   - Error: 502 Bad Gateway
   - Causa: Nginx mantiene conexiones antiguas al backend
   - Solución: Reiniciar nginx después de reiniciar el backend

2. **Timeouts en peticiones API**
   - Las peticiones a `/api/*` están fallando con "Failed to fetch"
   - Posible causa: Backend no está respondiendo o nginx no está enrutando correctamente

## Scripts Disponibles

1. **`restart_nginx_aws.sh`**: Reinicia nginx en el servidor AWS
2. **`diagnose_nginx_backend.sh`**: Diagnostica problemas de conectividad

## Acciones Recomendadas

1. **Verificar estado del backend en AWS**:
   ```bash
   # Verificar contenedores Docker
   docker compose --profile aws ps
   
   # Verificar logs del backend
   docker compose --profile aws logs backend-aws --tail 50
   ```

2. **Reiniciar nginx**:
   ```bash
   ./restart_nginx_aws.sh
   ```

3. **Verificar conectividad**:
   ```bash
   # Desde el servidor AWS
   curl http://localhost:8002/health
   curl http://localhost:8002/api/health
   ```

4. **Verificar configuración de nginx**:
   - Archivo de configuración: `/etc/nginx/sites-available/dashboard.hilovivo.com`
   - Debe tener proxy_pass a `http://localhost:8002`

## Estado Actual

- ✅ Frontend: Funcionando correctamente
- ✅ React Error #310: Resuelto
- ⚠️ Backend: Problemas de conectividad (timeouts)
- ⚠️ Nginx: Puede necesitar reinicio

## Próximos Pasos

1. Ejecutar diagnóstico en el servidor AWS
2. Reiniciar nginx si es necesario
3. Verificar que el backend está respondiendo
4. Probar las peticiones API desde el navegador
