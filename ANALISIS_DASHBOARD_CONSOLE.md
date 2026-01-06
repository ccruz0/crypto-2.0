# Análisis de Consola del Navegador - Dashboard

## Problema Identificado

El dashboard muestra **"No portfolio data available"** debido a que **todos los endpoints del backend están devolviendo error 503 (Service Unavailable)**.

## Errores en la Consola

### Errores HTTP 503 (Service Unavailable)

Los siguientes endpoints están fallando con código 503:

1. **`/api/config`** - Error 503
   - Mensaje: "Backend service temporarily unavailable. Please ensure services are running."

2. **`/api/dashboard/snapshot`** - Error 503
   - Mensaje: "Backend service temporarily unavailable. Please ensure services are running."
   - Se intenta múltiples veces (polling)

3. **`/api/market/top-coins-data`** - Error 503
   - Mensaje: "Backend service temporarily unavailable. Please ensure services are running."
   - Se intenta múltiples veces (polling)

4. **`/api/dashboard/state`** - Error 503
   - Mensaje: "Backend service temporarily unavailable. Please ensure services are running."
   - Este es el endpoint principal que proporciona los datos del portfolio

### Mensajes de Error Específicos

```
[ERROR] API Error: /config
[ERROR] API Error: /dashboard/snapshot
[ERROR] API Error: /market/top-coins-data
[ERROR] API Error: /dashboard/state
[ERROR] ❌ getDashboardState: Error fetching dashboard state: Backend service temporarily unavailable
[ERROR] Dashboard state fetch failure: Backend service temporarily unavailable
```

### Warnings

```
[WARNING] ⚠️ Missing data for potential P/L: portfolio.assets=0, topCoins=0, executedOrders=0
```

Este warning es consecuencia de los errores 503 - no hay datos porque el backend no responde.

## Causa Raíz

El backend (servicio `backend-aws`) **no está disponible o no está respondiendo correctamente**. Esto puede deberse a:

1. **Backend no está corriendo** - El contenedor puede estar detenido
2. **Backend está reiniciando** - Puede estar en un loop de reinicio
3. **Backend está caído** - Error fatal que impide que responda
4. **Problema de red/proxy** - Nginx o proxy no puede alcanzar el backend
5. **Backend está sobrecargado** - Timeouts o recursos agotados

## Impacto

- **Portfolio**: No se muestra (muestra "No portfolio data available")
- **Watchlist**: Probablemente no carga
- **Signals**: Probablemente no carga
- **Orders**: Probablemente no carga
- **Top Coins**: No carga
- **Config**: No carga

## Solución Recomendada

### Paso 1: Verificar Estado del Backend

```bash
# En el servidor AWS
docker compose --profile aws ps backend-aws
docker compose --profile aws logs backend-aws --tail=50
```

### Paso 2: Verificar Health Check

```bash
# Verificar si el backend responde localmente
curl http://localhost:8002/ping_fast
curl http://localhost:8002/api/monitoring/summary
```

### Paso 3: Verificar Nginx/Proxy

```bash
# Verificar logs de nginx
docker compose --profile aws logs nginx --tail=50

# Verificar configuración de proxy
# El proxy debe estar configurado para pasar requests a backend-aws:8002
```

### Paso 4: Reiniciar Backend si es Necesario

```bash
# Reiniciar backend
docker compose --profile aws restart backend-aws

# Esperar 30-60 segundos y verificar logs
docker compose --profile aws logs backend-aws --tail=50 --follow
```

### Paso 5: Verificar que Gunicorn Está Corriendo

```bash
# Verificar que gunicorn está instalado y corriendo
docker compose --profile aws exec backend-aws ps aux | grep gunicorn
docker compose --profile aws exec backend-aws pip list | grep gunicorn
```

## Código Relevante

### Frontend - Manejo de Errores

El frontend maneja estos errores en:
- `frontend/src/app/page.tsx` - Función `fetchPortfolio()`
- `frontend/src/app/api.ts` - Funciones de API que manejan errores 503

### Backend - Endpoints Afectados

- `backend/app/api/routes_dashboard.py` - `/api/dashboard/state`
- `backend/app/api/routes_dashboard.py` - `/api/dashboard/snapshot`
- `backend/app/api/routes_account.py` - `/api/config`
- `backend/app/api/routes_signals.py` - `/api/market/top-coins-data`

## Próximos Pasos

1. ✅ Verificar estado del backend en el servidor
2. ✅ Revisar logs del backend para identificar el problema
3. ✅ Verificar que gunicorn está corriendo (problema corregido anteriormente)
4. ✅ Verificar conectividad entre nginx y backend
5. ✅ Reiniciar servicios si es necesario

## Nota

Este problema está relacionado con el **Docker Build Fix** que corregimos anteriormente. Si el backend no está corriendo, puede ser porque:
- El contenedor no se inició después del rebuild
- Gunicorn no está instalado (aunque esto ya fue corregido)
- Hay un error en el startup del backend que impide que responda




