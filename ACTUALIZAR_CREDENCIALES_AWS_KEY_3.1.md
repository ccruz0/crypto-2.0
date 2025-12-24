# 🔑 Actualizar Credenciales a AWS KEY 3.1

## ⚠️ IMPORTANTE

Para actualizar las credenciales, necesito el **Secret Key** de "AWS KEY 3.1".

**API Key**: `raHZAk1MDkAWviDpcBxAWU` ✅ (ya la tenemos)

**Secret Key**: ❓ (necesito que me lo proporciones)

## 📋 Archivos a Actualizar

### En el Servidor AWS:
1. `~/automated-trading-platform/.env.local`
2. Posiblemente `.env.aws` (si se usa)

### En Local:
1. `.env.local` (si existe)
2. Otros archivos `.env*` si tienen credenciales de Crypto.com

## 🔍 Cómo Obtener el Secret Key

Si no tienes el Secret Key de "AWS KEY 3.1":

1. Ve a https://exchange.crypto.com/ → Settings → API Keys
2. Encuentra "AWS KEY 3.1" (`raHZAk1MDkAWviDpcBxAWU`)
3. Si el secret está oculto (mostrando `****`):
   - **Opción 1**: Regenera la key (creará nuevo secret)
   - **Opción 2**: Si tienes el secret guardado en otro lugar, úsalo
   - **Opción 3**: Verifica si hay otra API key que funcione

## ✅ Una vez que tengas el Secret Key

Proporcióname el Secret Key y actualizaré:
- ✅ `.env.local` en el servidor AWS
- ✅ `.env.local` local (si existe)
- ✅ Cualquier otro archivo .env que tenga credenciales de Crypto.com

## 🔧 Comando para Actualizar Manualmente

Si prefieres hacerlo manualmente:

```bash
# En el servidor AWS
ssh ubuntu@47.130.143.159 "nano ~/automated-trading-platform/.env.local"

# Actualizar estas líneas:
EXCHANGE_CUSTOM_API_KEY=raHZAk1MDkAWviDpcBxAWU
EXCHANGE_CUSTOM_API_SECRET=<secret_key_aqui>

# Guardar y reiniciar
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose restart backend-aws"
```

