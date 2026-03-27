# 🚀 Comandos para Ejecutar Diagnósticos en AWS

## Servidor AWS
**IP:** `47.130.143.159`  
**Usuario:** `ubuntu`

## Comandos Listos para Usar

### 1. Verificar que los Scripts Funcionan

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/test_script_works.py"
```

### 2. Diagnóstico Profundo (Más Detallado)

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/deep_auth_diagnostic.py"
```

### 3. Diagnóstico Completo

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/diagnose_auth_40101.py"
```

### 4. Test de Conexión

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/test_crypto_connection.py"
```

### 5. Todo en Uno (Verificación + Diagnóstico)

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/test_script_works.py && echo '---' && python3 scripts/deep_auth_diagnostic.py"
```

## Opción Interactiva (SSH Primero)

Si prefieres conectarte primero y luego ejecutar comandos:

```bash
# 1. Conectarse a AWS
ssh ubuntu@47.130.143.159

# 2. Navegar al backend
cd ~/crypto-2.0/backend

# 3. Verificar setup
python3 scripts/test_script_works.py

# 4. Ejecutar diagnóstico
python3 scripts/deep_auth_diagnostic.py
```

## Qué Esperar

### ✅ Si Todo Está Bien:
```
✅ All checks passed! Diagnostic scripts should work.
✅ Private API works! Found X account(s)
```

### ❌ Si Hay Error de Autenticación:
```
❌ Private API error: Crypto.com API authentication failed: Authentication failure (code: 40101)
```

El diagnóstico mostrará:
- Tu IP de salida (para whitelist)
- Proceso exacto de generación de firma
- Recomendaciones específicas para arreglar

## Próximos Pasos

Si ves el error 40101:

1. **Anota la IP de salida** que muestra el diagnóstico
2. Ve a https://exchange.crypto.com/ → Settings → API Keys
3. Edita tu API key
4. **Habilita el permiso "Read"** ✅
5. Agrega la IP de salida al whitelist
6. Espera 30 segundos
7. Ejecuta el diagnóstico de nuevo

## Comando Rápido Recomendado

Ejecuta este comando para ver todo:

```bash
ssh ubuntu@47.130.143.159 "cd ~/crypto-2.0/backend && python3 scripts/test_script_works.py && echo '========================================' && python3 scripts/deep_auth_diagnostic.py"
```

