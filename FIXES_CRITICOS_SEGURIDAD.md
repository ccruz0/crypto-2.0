# Correcciones Críticas de Seguridad - Guía de Implementación

**Fecha:** 2025-01-27  
**Prioridad:** 🔴 CRÍTICA - Implementar inmediatamente

---

## 🚨 Problema 1: Credenciales Hardcodeadas en docker-compose.yml

### Archivo: `docker-compose.yml`

### Cambios Requeridos:

#### 1.1. Credenciales de OpenVPN (Líneas 16-17)

**ANTES:**
```yaml
- OPENVPN_USER=Jy4gvM3reuQn4FywkvSdfDBq
- OPENVPN_PASSWORD=VJy8dMvnvjdNERQQar8v5ESm
```

**DESPUÉS:**
```yaml
- OPENVPN_USER=${OPENVPN_USER}
- OPENVPN_PASSWORD=${OPENVPN_PASSWORD}
```

#### 1.2. Credenciales de Telegram (Líneas 114-115)

**ANTES:**
```yaml
- TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-8408220395:AAEJAZcUEy4-9rfEsqKtfR0tHskL4vM4pew}
- TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:--5033055655}
```

**DESPUÉS:**
```yaml
- TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
- TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
```

### Pasos de Implementación:

1. **Agregar variables a `.env.aws`:**
```bash
# OpenVPN Credentials
OPENVPN_USER=Jy4gvM3reuQn4FywkvSdfDBq
OPENVPN_PASSWORD=VJy8dMvnvjdNERQQar8v5ESm

# Telegram Credentials
TELEGRAM_BOT_TOKEN=8408220395:AAEJAZcUEy4-9rfEsqKtfR0tHskL4vM4pew
TELEGRAM_CHAT_ID=-5033055655
```

2. **Verificar que `.env.aws` esté en `.gitignore`** (✅ Ya está)

3. **Aplicar cambios en docker-compose.yml**

4. **Rotar las credenciales expuestas:**
   - Generar nuevas credenciales de OpenVPN
   - Generar nuevo token de Telegram bot (opcional, pero recomendado)

---

## 🚨 Problema 2: SECRET_KEY por Defecto

### Archivo: `backend/app/core/config.py`

### Cambio Requerido:

**ANTES:**
```python
SECRET_KEY: str = "your-secret-key-here"
```

**DESPUÉS:**
```python
SECRET_KEY: str  # Sin valor por defecto - debe venir de variable de entorno
```

O mejor aún:
```python
from typing import Optional

SECRET_KEY: Optional[str] = None

# Agregar validación en __init__ o método de validación
```

### Pasos de Implementación:

1. **Agregar SECRET_KEY a `.env.aws`:**
```bash
SECRET_KEY=<generar_clave_secreta_fuerte_de_al_menos_32_caracteres>
```

2. **Generar una clave secreta segura:**
```python
# En Python:
import secrets
print(secrets.token_urlsafe(32))
```

3. **Actualizar config.py para validar que SECRET_KEY esté presente**

---

## 🔧 Script de Validación

Crear un script que valide que todas las variables requeridas estén presentes:

```python
#!/usr/bin/env python3
"""Script para validar que todas las variables de entorno requeridas estén configuradas"""

import os
from pathlib import Path

REQUIRED_VARS = [
    "OPENVPN_USER",
    "OPENVPN_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "CRYPTO_API_KEY",
    "CRYPTO_API_SECRET",
]

def validate_env_file(env_file: Path):
    """Validar que un archivo .env tenga todas las variables requeridas"""
    if not env_file.exists():
        print(f"❌ Archivo {env_file} no existe")
        return False
    
    with open(env_file, 'r') as f:
        content = f.read()
    
    missing = []
    for var in REQUIRED_VARS:
        if f"{var}=" not in content:
            missing.append(var)
    
    if missing:
        print(f"❌ Variables faltantes en {env_file}: {', '.join(missing)}")
        return False
    
    print(f"✅ Todas las variables requeridas están en {env_file}")
    return True

if __name__ == "__main__":
    base_dir = Path(__file__).parent
    env_aws = base_dir / ".env.aws"
    
    if validate_env_file(env_aws):
        print("\n✅ Validación exitosa")
    else:
        print("\n❌ Validación fallida - revisa las variables faltantes")
        exit(1)
```

---

## 📋 Checklist de Implementación

### Fase 1: Preparación (Hacer primero)
- [ ] Crear backup de `docker-compose.yml`
- [ ] Verificar que `.env.aws` existe y está en `.gitignore`
- [ ] Generar nuevas credenciales (especialmente si las actuales están comprometidas)

### Fase 2: Actualización de Archivos
- [ ] Actualizar `docker-compose.yml` para usar variables de entorno
- [ ] Actualizar `backend/app/core/config.py` para SECRET_KEY
- [ ] Agregar todas las variables a `.env.aws`
- [ ] Crear script de validación

### Fase 3: Verificación
- [ ] Ejecutar script de validación
- [ ] Verificar que no hay credenciales hardcodeadas en el código
- [ ] Probar que los servicios inician correctamente con las nuevas variables

### Fase 4: Limpieza
- [ ] Rotar credenciales expuestas
- [ ] Verificar que no hay credenciales en el historial de git (usar `git log -p`)
- [ ] Si hay credenciales en el historial, considerar usar `git filter-branch` o `git filter-repo`

### Fase 5: Deployment
- [ ] Aplicar cambios en servidor AWS
- [ ] Verificar que los servicios funcionan correctamente
- [ ] Monitorear logs por errores relacionados con credenciales

---

## 🔍 Comando para Verificar Credenciales en Git

```bash
# Buscar credenciales hardcodeadas en el repositorio
cd /Users/carloscruz/automated-trading-platform
grep -r "OPENVPN_USER=\|OPENVPN_PASSWORD=\|TELEGRAM_BOT_TOKEN=" --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=.git .

# Verificar historial de git
git log -p --all -S "OPENVPN_PASSWORD" | head -50
git log -p --all -S "TELEGRAM_BOT_TOKEN" | head -50
```

---

## ⚠️ Notas Importantes

1. **NO hacer commit de `.env.aws`** - Ya está en `.gitignore`, pero verificar
2. **Rotar credenciales expuestas** - Las credenciales en el código pueden estar comprometidas
3. **Comunicar cambios al equipo** - Si otros desarrolladores usan estas credenciales
4. **Documentar el proceso** - Para futuras referencias

---

## 📞 Próximos Pasos Después de las Correcciones

1. Revisar otros archivos por credenciales hardcodeadas
2. Implementar secret management más robusto (AWS Secrets Manager, HashiCorp Vault, etc.)
3. Configurar pre-commit hooks para prevenir commits con credenciales
4. Implementar escaneo automático de secretos en CI/CD

---

**Fin de la Guía de Correcciones**











