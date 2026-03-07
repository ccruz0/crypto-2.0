# EC2 SSH timeout – diagnóstico en 2 minutos

Cuando antes conectabas por SSH y ahora no, casi siempre es uno de estos cambios. **No tiene que ver con la app** (p. ej. executed orders); es conectividad a la instancia.

---

## Causa muy frecuente: IP incorrecta (alias o comando apuntan a instancia vieja)

**Síntoma:** `ssh` hace timeout a una IP (p. ej. `47.130.143.159`) pero en AWS Console la instancia activa tiene **otra** IP (p. ej. `52.220.32.147` para **atp-rebuild-2026**).

**Por qué pasa:** Destruiste/recreaste la instancia, reasignaste Elastic IP, o el alias en `~/.ssh/config` sigue con la IP antigua. No has cambiado código, pero sí la IP del servidor respecto a la que usas en el comando SSH.

**Solución inmediata:**

1. **Probar con la IP actual** (consulta AWS Console → EC2 → tu instancia → Public IPv4 / Elastic IP):
   ```bash
   ssh ubuntu@52.220.32.147
   ```
   Si conecta, el problema era la IP.

2. **Si usas alias** (p. ej. `ssh hilovivo-aws`), actualizar `~/.ssh/config`:
   ```bash
   cat ~/.ssh/config
   ```
   Busca algo como:
   ```
   Host hilovivo-aws
     HostName 47.130.143.159
   ```
   Cámbialo a la IP actual de la instancia:
   ```
   HostName 52.220.32.147
   ```

**Referencia:** PROD actual = **atp-rebuild-2026** (i-087953603011543c5), IP **52.220.32.147**. Ver `docs/aws/AWS_PROD_QUICK_REFERENCE.md`.

Si con la IP correcta **sigue** sin conectar, el siguiente paso es revisar el Security Group (puerto 22).

---

## Otras causas típicas

- **Tu IP pública cambió** y el Security Group solo permite 22 desde la IP antigua.
- **Estás en otra red** (oficina, hotel, tethering) o con VPN. La IP de salida cambia.
- **Cambiaste el Security Group** o la regla inbound y ya no permite 22.
- **La instancia perdió o cambió la IP pública** (si no usa Elastic IP).
- **La instancia está en subnet privada**, o cambió route table / IGW / NACL.
- **Fail2ban/ufw** bloqueó tu IP o el `sshd` se cayó.
- **Estás usando una IP que ya no es la de esa instancia** (otra instancia, IP vieja).

---

## Cómo aislarlo en 2 minutos

### 1. Confirma que esa IP sigue siendo la de tu instancia

En AWS Console → EC2 → tu instancia:

- **Public IPv4 address**
- **Elastic IP** asociado (si lo usas)

Si no coincide con la IP que usas en `ssh` (p. ej. tenías `47.130.143.159` y la instancia activa es `52.220.32.147`), ya tienes la explicación.

### 2. Revisa el Security Group – inbound

Tiene que existir algo como:

- **Type:** SSH  
- **Protocol:** TCP  
- **Port:** 22  
- **Source:** tu IP actual `/32`

Tu IP actual desde el Mac:

```bash
curl -s https://api.ipify.org ; echo
```

### 3. Diferencia "timeout" vs "permission denied"

- **Timeout** = no llega el tráfico → SG / NACL / routing / IP incorrecta.
- **Permission denied (publickey)** = llega al servidor, pero la clave SSH no es la que tiene la instancia en `authorized_keys`.

**Si ves Permission denied**, prueba en este orden:

1. **Usar la clave explícita** (si tienes el `.pem` que usaste al crear la instancia):
   ```bash
   ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147
   ```
   (Sustituye la ruta por donde guardes el `.pem` de la instancia atp-rebuild-2026.)

2. **Ver si tienes un alias en `~/.ssh/config`** que ya apunte a la clave correcta:
   ```bash
   cat ~/.ssh/config | grep -A5 "52.220.32.147\|hilovivo-aws\|atp"
   ```
   Si hay `IdentityFile`, usa ese host: `ssh hilovivo-aws` (o el nombre que salga).

3. **Añadir la clave al agente** (si la tienes pero no se usa por defecto):
   ```bash
   ssh-add -l
   ssh-add ~/.ssh/atp-rebuild-2026.pem   # o la ruta de tu clave
   ssh ubuntu@52.220.32.147
   ```

Si ninguna clave funciona, la instancia tiene en `~/.ssh/authorized_keys` otra clave (p. ej. de otro equipo o de EC2 Instance Connect). Opciones: usar **EC2 Instance Connect** desde la consola AWS, o inyectar tu clave vía SSM (ver `scripts/aws/inject_ssh_key_via_ssm.sh` si SSM está Online).

### 4. Prueba rápida desde tu Mac

```bash
nc -vz <IP_QUE_USAS_EN_SSH> 22
# Ejemplo: nc -vz 52.220.32.147 22
```

Si falla igual, es 100% reglas/ruta/IP (o IP incorrecta; ver sección anterior).

---

## Qué hacer (orden sugerido)

1. Verificar **IP pública actual de la instancia** en la consola.
2. Abrir **inbound 22 solo para tu IP actual** (`/32`).
3. Si tu IP cambia mucho: usar **Session Manager** para administración y dejar 22 cerrado, o bastion/VPN fija.
4. Asignar **Elastic IP** a la instancia si necesitas estabilidad.

---

## Si pegas 3 cosas, se puede precisar la causa

1. **Public IPv4** que ves en la consola de AWS para esa instancia.
2. **Tu IP actual:** salida de `curl -s https://api.ipify.org`.
3. **Regla inbound del SG para el puerto 22** (captura o texto).

Con eso se puede decir exactamente cuál de las causas aplica.
