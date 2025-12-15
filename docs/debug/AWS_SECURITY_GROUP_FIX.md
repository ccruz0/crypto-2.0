# Fix: AWS Security Group - Puertos 80 y 443

## Problema Identificado

El dashboard no carga porque los **puertos 80 y 443 no están abiertos** en el Security Group de AWS.

## Síntomas

- ✅ DNS resuelve correctamente (`47.130.143.159`)
- ✅ Nginx está corriendo en el servidor
- ✅ SSL certificado válido
- ❌ **Puertos 80/443 no accesibles desde fuera** (timeout)
- ❌ Nginx no puede conectar al backend (problema secundario)

## Solución: Abrir Puertos en AWS Security Group

### Paso 1: Identificar el Security Group

1. Ve a **AWS Console**: https://console.aws.amazon.com/ec2/
2. **EC2** → **Instances**
3. Busca tu instancia con IP `47.130.143.159`
4. Selecciona la instancia
5. En la pestaña **Security**, verás el **Security Group**

### Paso 2: Editar Inbound Rules

1. Click en el **Security Group** (o ve a **Security Groups** en el menú izquierdo)
2. Click en **Edit inbound rules**
3. Click **Add rule**

#### Agregar Regla para Puerto 80 (HTTP):

- **Type**: HTTP
- **Protocol**: TCP
- **Port range**: 80
- **Source**: 0.0.0.0/0 (o Custom → 0.0.0.0/0)
- **Description**: Allow HTTP from anywhere
- Click **Save rules**

#### Agregar Regla para Puerto 443 (HTTPS):

- **Type**: HTTPS
- **Protocol**: TCP
- **Port range**: 443
- **Source**: 0.0.0.0/0 (o Custom → 0.0.0.0/0)
- **Description**: Allow HTTPS from anywhere
- Click **Save rules**

### Paso 3: Verificar

Después de guardar, espera 30 segundos y prueba:

```bash
# Debe retornar 301 (redirect)
curl -I http://dashboard.hilovivo.com

# Debe retornar 200
curl -I https://dashboard.hilovivo.com
```

## Verificación Actual

Para verificar qué puertos están abiertos actualmente:

```bash
# Desde el servidor
ssh hilovivo-aws 'sudo iptables -L -n | grep -E "80|443"'

# O verificar Security Group desde AWS CLI (si tienes configurado)
aws ec2 describe-security-groups --group-ids <SECURITY_GROUP_ID> --query 'SecurityGroups[0].IpPermissions'
```

## Problema Secundario: Backend

Los logs de nginx también muestran que el backend no responde correctamente:

```
connect() failed (111: Connection refused) while connecting to upstream
upstream: "http://127.0.0.1:8002/..."
```

**Verificar backend**:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps backend-aws'
```

Si el backend no está corriendo, reinícialo:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

## Resumen

**Acción Requerida**:
1. ✅ Abrir puertos 80 y 443 en AWS Security Group
2. ✅ Verificar que backend esté corriendo
3. ✅ Probar acceso: `https://dashboard.hilovivo.com`

**Una vez abiertos los puertos, el dashboard debería cargar inmediatamente.**

