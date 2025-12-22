# Herramientas de Diagnóstico para DOT_USDT BUY Alert

Este directorio contiene herramientas para diagnosticar por qué DOT_USDT no envía alertas BUY aunque cumpla los parámetros.

## 📋 Scripts Disponibles

### 1. `diagnose_dot_buy_alert.sh` - Diagnóstico de Logs
Script bash que revisa los logs de Docker para encontrar información sobre el procesamiento de señales.

**Uso:**
```bash
# Ajustar el nombre del contenedor si es diferente
./diagnose_dot_buy_alert.sh

# O especificar el contenedor manualmente
CONTAINER_NAME="backend-aws" ./diagnose_dot_buy_alert.sh
```

**Qué verifica:**
- Estado del servicio SignalMonitorService
- Señales BUY detectadas
- Bloqueos por throttle
- Decisiones de alerta
- Errores relacionados

---

### 2. `diagnose_dot_buy_alert.py` - Diagnóstico Completo de Base de Datos
Script Python que verifica la configuración en la base de datos y el estado del throttle.

**Uso:**
```bash
# Desde el directorio raíz del proyecto
python3 diagnose_dot_buy_alert.py
```

**Qué verifica:**
- ✅ Flags de alerta (`alert_enabled`, `buy_alert_enabled`)
- ✅ Configuración de throttling (`min_price_change_pct`, `alert_cooldown_minutes`)
- ✅ Estado del throttle (últimas señales enviadas)
- ✅ Precio actual vs última señal (cambio de precio)
- ✅ Tiempo desde última señal (cooldown)
- ✅ Órdenes recientes
- ✅ Resumen de problemas encontrados

**Requisitos:**
- Python 3
- Acceso a la base de datos
- Variables de entorno configuradas (o ajustar conexión en el script)

---

### 3. `check_dot_config.sql` - Consultas SQL Directas
Consultas SQL que puedes ejecutar directamente en la base de datos.

**Uso:**
```bash
# Con psql
psql -U usuario -d nombre_db -f check_dot_config.sql

# O copiar y pegar las consultas en tu cliente SQL
```

**Qué verifica:**
- Configuración del watchlist
- Estado del throttle
- Duplicados en watchlist
- Órdenes recientes
- Datos de mercado

---

## 🔍 Interpretación de Resultados

### Si el script bash muestra:

**✅ "BUY signal detected" pero NO "NEW BUY signal detected"**
→ El throttle o los flags están bloqueando

**✅ "BLOQUEADO: DOT_USDT BUY - {razón}"**
→ El throttle está bloqueando. Ver la razón específica:
- `Price change X% < minimum Y% required` → Cambio de precio insuficiente
- `Cooldown not met: X minutes elapsed < Y minutes required` → Cooldown activo

**❌ No aparece "BUY signal detected"**
→ El bot puede estar detenido o las condiciones BUY no se cumplen realmente

**❌ No aparece ningún log de DOT_USDT**
→ El servicio SignalMonitorService no está procesando este símbolo (bot detenido o símbolo no en watchlist)

---

### Si el script Python muestra:

**🚫 "alert_enabled = False"**
→ Habilitar `alert_enabled` desde el dashboard

**🚫 "buy_alert_enabled = False"**
→ Habilitar `buy_alert_enabled` desde el dashboard

**⏱️ "Cooldown activo: X/Y minutos"**
→ Esperar que pase el cooldown o ajustar `alert_cooldown_minutes`

**💰 "Cambio de precio insuficiente: X% < Y%"**
→ Esperar que el precio cambie más o ajustar `min_price_change_pct`

**✅ "No se encontraron problemas obvios"**
→ Verificar logs del backend para ver si el bot está corriendo

---

## 🚀 Flujo de Diagnóstico Recomendado

### Paso 1: Verificar Logs (Rápido)
```bash
./diagnose_dot_buy_alert.sh
```

**Si ves "BLOQUEADO"** → Ir a Paso 2 para ver detalles del throttle
**Si NO ves logs de DOT_USDT** → El bot está detenido o el símbolo no está en watchlist

### Paso 2: Verificar Configuración (Completo)
```bash
python3 diagnose_dot_buy_alert.py
```

Esto te dará un resumen completo de:
- Flags habilitados/deshabilitados
- Estado del throttle
- Cooldown y cambio de precio

### Paso 3: Verificar Estado del Servicio
```bash
# Verificar si el servicio está corriendo
docker logs backend-aws | grep "SignalMonitorService.*is_running" | tail -5

# Verificar últimos ciclos
docker logs backend-aws | grep "SignalMonitorService cycle" | tail -5
```

### Paso 4: Soluciones según el Problema

#### Si el Bot Está Detenido:
```bash
# Iniciar servicios (si hay endpoint disponible)
curl -X POST http://localhost:8000/api/services/start
```

#### Si Flags Están Deshabilitados:
- Ir al dashboard
- Buscar DOT_USDT en la watchlist
- Habilitar `alert_enabled` y `buy_alert_enabled`

#### Si Throttle Está Bloqueando:
- **Cooldown activo**: Esperar o reducir `alert_cooldown_minutes`
- **Cambio de precio insuficiente**: Esperar o reducir `min_price_change_pct`
- **Forzar próxima señal**: (si está disponible) usar `force_next_signal = True`

---

## 📝 Notas Importantes

1. **El dashboard muestra señales calculadas localmente** - puede mostrar BUY aunque el backend esté bloqueando
2. **Throttling es normal** - previene spam de alertas
3. **El bot debe estar corriendo** - si `SignalMonitorService` no está activo, no se procesan alertas
4. **Los logs son la fuente de verdad** - si no aparecen logs, el servicio no está procesando

---

## 🔧 Troubleshooting

### Error: "No se puede conectar a la base de datos"
- Verificar variables de entorno
- Verificar que la base de datos esté corriendo
- Ajustar conexión en `diagnose_dot_buy_alert.py`

### Error: "Container not found"
- Ajustar `CONTAINER_NAME` en `diagnose_dot_buy_alert.sh`
- Verificar nombre del contenedor: `docker ps`

### Error: "Module not found"
- Ejecutar desde el directorio raíz del proyecto
- Verificar que `backend/app` esté en el path

---

## 📚 Documentación Relacionada

- `DOT_BUY_ALERT_DIAGNOSIS.md` - Análisis detallado del problema
- `backend/app/services/signal_monitor.py` - Código del servicio de monitoreo
- `backend/app/services/signal_throttle.py` - Lógica de throttling

