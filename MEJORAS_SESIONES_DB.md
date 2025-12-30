# Mejoras Recomendadas para Manejo de Sesiones de DB

**Fecha:** 2025-01-27  
**Prioridad:** 🟡 ALTA

---

## ✅ VERIFICACIÓN COMPLETADA

### Errores de Sintaxis
- ✅ **Corregido:** Error de indentación en `telegram_commands.py:1414`
- ✅ **Verificado:** Todos los archivos principales compilan correctamente

### Revisión de Sesiones
- ✅ **Revisadas:** 6 lugares donde se crean sesiones manualmente
- ✅ **Estado:** Todas las sesiones se cierran correctamente
- ⚠️ **Mejora:** Algunas no hacen rollback explícito en caso de error

---

## 🔧 MEJORAS ESPECÍFICAS RECOMENDADAS

### 1. main.py (Línea 254)

**Código actual:**
```python
db = SessionLocal()
try:
    # ... código ...
    db.commit()
except Exception as e:
    logger.error(f"Error: {e}")
finally:
    db.close()
```

**Código mejorado:**
```python
db = SessionLocal()
try:
    # ... código ...
    db.commit()
except Exception as e:
    logger.error(f"Error ensuring watchlist is not empty: {e}", exc_info=True)
    db.rollback()  # ✅ Agregar rollback
finally:
    db.close()
```

---

### 2. telegram_commands.py (Línea 3464)

**Código actual:**
```python
if not db:
    try:
        db = SessionLocal()
        db_created = True
    except Exception as e:
        logger.error(f"[TG] Cannot create DB session: {e}")
        return
else:
    db_created = False

try:
    # ... código ...
finally:
    if db_created and db:
        db.close()
```

**Código mejorado:**
```python
if not db:
    try:
        db = SessionLocal()
        db_created = True
    except Exception as e:
        logger.error(f"[TG] Cannot create DB session: {e}")
        return
else:
    db_created = False

try:
    # ... código ...
    if db_created:
        db.commit()  # ✅ Agregar commit explícito
except Exception as e:
    logger.error(f"[TG] Error processing commands: {e}", exc_info=True)
    if db_created and db:
        db.rollback()  # ✅ Agregar rollback
    raise
finally:
    if db_created and db:
        db.close()
```

---

### 3. signal_monitor.py (Línea 3553)

**Código actual:**
```python
db = SessionLocal()
try:
    await self.monitor_signals(db)
finally:
    db.close()
```

**Código mejorado:**
```python
db = SessionLocal()
try:
    await self.monitor_signals(db)
    db.commit()  # ✅ Agregar commit si hay cambios
except Exception as e:
    logger.error(f"Error in signal monitor cycle: {e}", exc_info=True)
    db.rollback()  # ✅ Agregar rollback
    raise
finally:
    db.close()
```

---

### 4. daily_summary.py (Línea 295)

**Código actual:**
```python
if db is None:
    db = SessionLocal()
    should_close = True
else:
    should_close = False

try:
    # ... código ...
finally:
    if should_close:
        db.close()
```

**Código mejorado:**
```python
if db is None:
    db = SessionLocal()
    should_close = True
else:
    should_close = False

try:
    # ... código ...
    if should_close:
        db.commit()  # ✅ Agregar commit explícito
except Exception as e:
    logger.error(f"Error sending sell orders report: {e}", exc_info=True)
    if should_close:
        db.rollback()  # ✅ Agregar rollback
    raise
finally:
    if should_close:
        db.close()
```

---

## 📋 PATRÓN RECOMENDADO (Template)

Para código nuevo o refactorización, usar este patrón:

```python
from app.database import SessionLocal

# Crear sesión
db = SessionLocal()
db_created = True  # O False si se pasa como parámetro

try:
    # ... operaciones de base de datos ...
    
    # Commit explícito si hay cambios
    db.commit()
    
except Exception as e:
    # Log del error
    logger.error(f"Error description: {e}", exc_info=True)
    
    # Rollback explícito
    db.rollback()
    
    # Re-raise o manejar apropiadamente
    raise
    
finally:
    # Siempre cerrar la sesión
    if db_created:
        db.close()
```

---

## 🎯 IMPLEMENTACIÓN

### Opción 1: Correcciones Manuales (Recomendado)

Aplicar las mejoras específicas mencionadas arriba en cada archivo.

**Tiempo estimado:** 1-2 horas

### Opción 2: Context Manager (Para código nuevo)

Crear un context manager para simplificar el manejo:

```python
# backend/app/utils/db_session.py
from contextlib import contextmanager
from app.database import SessionLocal
import logging

logger = logging.getLogger(__name__)

@contextmanager
def db_session(commit_on_success=True):
    """
    Context manager para sesiones de base de datos.
    
    Usage:
        with db_session() as db:
            # ... operaciones ...
            # Commit automático al salir (si no hay error)
    """
    db = SessionLocal()
    try:
        yield db
        if commit_on_success:
            db.commit()
    except Exception as e:
        logger.error(f"Database error: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()
```

**Uso:**
```python
from app.utils.db_session import db_session

with db_session() as db:
    # ... operaciones ...
    # Commit y close automáticos
```

**Tiempo estimado:** 2-3 horas (crear utilidad + migrar código)

---

## ✅ CHECKLIST DE IMPLEMENTACIÓN

### Correcciones Inmediatas
- [x] Corregir error de sintaxis en telegram_commands.py
- [ ] Agregar rollback en main.py
- [ ] Agregar rollback en telegram_commands.py
- [ ] Agregar rollback en signal_monitor.py
- [ ] Agregar rollback en daily_summary.py

### Mejoras Adicionales
- [ ] Agregar commit explícito donde falte
- [ ] Considerar crear context manager
- [ ] Documentar patrón recomendado
- [ ] Agregar tests para manejo de sesiones

---

## 📊 IMPACTO ESPERADO

### Antes
- Sesiones se cierran correctamente ✅
- Rollback en errores: 33% de casos
- Commit explícito: 50% de casos

### Después (objetivo)
- Sesiones se cierran correctamente ✅
- Rollback en errores: 100% de casos
- Commit explícito: 100% de casos
- Mejor manejo de transacciones
- Menor riesgo de inconsistencias

---

## 🚀 PRÓXIMOS PASOS

1. **Aplicar correcciones de rollback** (1-2 horas)
2. **Agregar commits explícitos** (1 hora)
3. **Probar que no se rompa nada** (1 hora)
4. **Considerar context manager para futuro** (opcional)

---

**Fin del Documento**











