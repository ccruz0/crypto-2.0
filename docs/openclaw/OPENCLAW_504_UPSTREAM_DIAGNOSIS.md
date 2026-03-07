# 504 en /openclaw — upstream OpenClaw no alcanzable

**If SSM is ConnectionLost:** run `./scripts/openclaw/print_504_manual_commands.sh` and execute the blocks via EC2 Instance Connect.

Un **504** significa: la petición **llega** al Nginx del Dashboard, pero Nginx **no puede conectar** con el upstream OpenClaw.

No es problema de iframe ni de auth. Es uno de estos:

- Nginx sigue haciendo proxy hacia la IP equivocada
- OpenClaw no escucha en la IP:8080 de destino
- SG/NACL/routing bloquean TCP 8080
- El proceso OpenClaw está caído o colgado

**Nota:** `curl -I` sin auth puede devolver **401**; en el navegador, al enviar Basic Auth, Nginx intenta hacer proxy al upstream y entonces puede devolver **504**. Si ves 504 en el navegador, sigue este runbook.

**Haz esto en este orden.**

---

## Invariantes (no debugging, validación)

Un 504 **solo existe** si una de estas **tres realidades físicas** es falsa:

1. Nginx apunta a una **IP alcanzable**
2. El host del Dashboard puede **abrir TCP** a `<IP>:8080`
3. OpenClaw está ligado a una **interfaz de red** (0.0.0.0 o 172.31.x.x), no solo a 127.0.0.1

Cuando las tres son verdaderas, el 504 desaparece. **Todo lo demás es ruido.**

No estás “debugueando”. Estás **validando invariantes**. Ejecuta los pasos, pega los tres outputs y se reduce a **un solo cambio**.

**Comportamiento determinista:**

| Invariante que falla | Conclusión |
|----------------------|------------|
| #2 (Dashboard no abre TCP a &lt;IP&gt;:8080) | Es **red** (SG/NACL/routing). |
| #3 (OpenClaw no escucha en interfaz de red) | Es **bind/servicio**. |
| #2 y #3 OK pero sigue 504 | **Bloque Nginx equivocado** (no está usando el server que crees). |
| Las tres verdaderas | El 504 **no puede existir**. |

Ese marco evita debugging circular. Lo único que importa es lo que digan los comandos en el servidor.

**Al ejecutar los tres comandos: no interpretes. Solo pega.** Se colapsa a un cambio y se sigue. Sin especulación. Solo invariantes.

---

## Flujo en la práctica (realidad, no teoría)

1. Abre el **host del Dashboard**. Ejecuta el **paso 1**.
2. **Si `proxy_pass` sigue mostrando una IP pública** → ya sabes el fix (cambiar a IP privada y recargar Nginx).
3. **Si muestra 172.31.x.x** → ejecuta el **paso 2**.
   - **`curl` hace timeout** → en el 90% de los casos es **Security Group** (falta regla Dashboard → OpenClaw 8080).
   - **`curl` dice connection refused** → es **bind/servicio** (nada escuchando en esa IP:8080).
   - **`curl` devuelve HTTP** pero el navegador sigue mostrando 504 → Nginx **no** está haciendo proxy donde crees (server block equivocado).
4. Pega los **tres outputs** cuando los tengas; con eso se colapsa a **un solo cambio**.

---

## 1) Confirmar a qué hace proxy Nginx (fuente de verdad)

En **52.220.32.147** (host del Dashboard):

```bash
sudo nginx -T 2>/dev/null | sed -n '/server_name dashboard.hilovivo.com/,/^}/p' | sed -n '/location \^~ \/openclaw\//,/}/p'
```

Revisa la línea exacta `proxy_pass ...;`.

- Si ves **`proxy_pass http://52.77.216.100:8080/;`** → sigues en IP pública; el 504 seguirá hasta que se arregle la conectividad pública (o migres a IP privada).
- Si ves **`proxy_pass http://172.31.x.x:8080/;`** → estás en IP privada; lo siguiente a revisar es solo VPC/SG/bind.

---

## 2) Probar conectividad desde el Dashboard al upstream exacto

En **52.220.32.147**, sustituye la IP por la que haya salido en `proxy_pass`:

```bash
curl -sv --max-time 3 http://<UPSTREAM_IP>:8080/ >/dev/null
echo $?
```

**Interpretación:**

| Resultado | Significado |
|-----------|-------------|
| Cualquier HTTP (200/301/302/401) | Red OK; si sigue 504, Nginx está haciendo proxy a otro sitio |
| Timeout | SG/NACL/routing (o IP incorrecta) |
| Connection refused | Nada escuchando en 8080 en ese host/IP |

---

## 3) En el host OpenClaw: verificar que escucha en la interfaz correcta

En la instancia OpenClaw (la que debe servir 8080):

```bash
sudo ss -lntp | grep ':8080' || true
curl -sv --max-time 3 http://127.0.0.1:8080/ >/dev/null
```

Queremos ver:

- **0.0.0.0:8080** o **172.31.x.x:8080** → bien.
- Si **solo** ves **127.0.0.1:8080**, el Dashboard no podrá alcanzarlo por red.

Si está ligado a 127.0.0.1, hay que configurar OpenClaw para que escuche en **0.0.0.0** (o en la IP privada) y reiniciar el servicio.

---

## 4) Confirmar la causa del 504 en los logs de Nginx

En **52.220.32.147**:

```bash
sudo tail -n 80 /var/log/nginx/error.log | tail -n 30
```

Busca una línea del estilo:

- `upstream timed out ... while connecting to upstream ... upstream: "http://<IP>:8080/"`

Esa IP debe coincidir con la que esperas (pública o privada).

---

## Causas más probables (resumen)

- **`proxy_pass`** sigue apuntando a **52.77.216.100** y esa IP ya no es correcta, o el 8080 sigue bloqueado desde fuera.
- Cambiaste a **IP privada** pero OpenClaw sigue escuchando solo en **127.0.0.1:8080**.
- Añadiste regla en el SG pero usaste **IP como source** en vez del **SG del Dashboard** (SG-to-SG), o editaste otro SG que no está en la instancia OpenClaw.

---

## Paste estos 3 outputs (diagnóstico en un paso)

Pega **solo** estos tres resultados; con ellos se indica el **siguiente cambio exacto**.

### Quick copy-paste (cuando tengas SSH/SSM o EC2 Instance Connect)

Si SSM está ConnectionLost en el Dashboard: `./scripts/openclaw/print_504_manual_commands.sh` imprime los 3 comandos para pegar. Conéctate por **EC2 Instance Connect** (runbook PROD) y pega cada bloque.

**Dashboard (52.220.32.147) — paso 1:**
```bash
sudo nginx -T 2>/dev/null \
| sed -n '/server_name dashboard.hilovivo.com/,/^}/p' \
| sed -n '/location \^~ \/openclaw\//,/}/p'
```
Anota la IP que aparece en `proxy_pass http://<IP>:8080/`.

**Dashboard — paso 2** (sustituye `UPSTREAM_IP` por esa IP):
```bash
curl -sv --max-time 3 http://UPSTREAM_IP:8080/
```

**Host OpenClaw — paso 3:**
```bash
sudo ss -lntp | grep ':8080' || true
```

---

### 1) ¿A qué hace proxy Nginx de verdad?

En **52.220.32.147**:

```bash
sudo nginx -T 2>/dev/null \
| sed -n '/server_name dashboard.hilovivo.com/,/^}/p' \
| sed -n '/location \^~ \/openclaw\//,/}/p'
```

### 2) ¿El Dashboard alcanza el upstream?

En **52.220.32.147** (usa la IP que salió en `proxy_pass`):

```bash
curl -sv --max-time 3 http://<UPSTREAM_IP>:8080/ >/dev/null
```

### 3) ¿OpenClaw escucha en la interfaz de red?

En el **host OpenClaw**:

```bash
sudo ss -lntp | grep ':8080' || true
```

---

### Qué se deduce de esos 3 (siguiente cambio exacto)

| Si… | Siguiente cambio |
|-----|-------------------|
| `proxy_pass` sigue apuntando a **52.77...** | Cambiarlo a la **IP privada** de OpenClaw y hacer `reload` de Nginx. |
| El `curl` desde el Dashboard hace **timeout** | SG/NACL/routing (casi siempre: falta regla SG “Dashboard SG → OpenClaw 8080”). |
| `ss` muestra **solo 127.0.0.1:8080** | Ajustar el **bind** de OpenClaw a **0.0.0.0** y reiniciar el servicio. |

---

## Referencia: modelo v1.1 (IP privada + SG-to-SG)

En estado objetivo ([ARCHITECTURE_V1_1_INTERNAL_SERVICE.md](ARCHITECTURE_V1_1_INTERNAL_SERVICE.md)):

- `proxy_pass` usa la **IP privada** de OpenClaw (ej. 172.31.x.x).
- El SG de OpenClaw permite TCP 8080 solo desde el **SG del Dashboard** (referencia SG-to-SG), no desde 0.0.0.0/0.

Migración a ese modelo: [OPENCLAW_PRIVATE_NETWORK_MIGRATION.md](OPENCLAW_PRIVATE_NETWORK_MIGRATION.md).

---

## Fixes concretos (después de identificar la causa)

### A) OpenClaw solo escucha en 127.0.0.1

En el host OpenClaw: cambiar la configuración del servicio para que escuche en **0.0.0.0:8080** (o en la IP privada), reiniciar y volver a comprobar con `ss -lntp | grep ':8080'`.

### B) SG bloquea el tráfico

- **Si usas IP pública como upstream:** el SG de la instancia OpenClaw debe permitir TCP 8080 desde la IP de salida del Dashboard. En el Dashboard: `curl -s https://ifconfig.me`; en el SG, Source = esa IP/32.
- **Si usas IP privada (v1.1):** el SG de OpenClaw debe permitir TCP 8080 con **Source = SG del Dashboard** (referencia por ID o nombre del SG), no por IP.

Comprobar que la regla está en el **SG que tiene asociado la instancia OpenClaw**.

### C) NACL

Si el SG está bien y el servicio escucha en 0.0.0.0 y sigue timeout: revisar el NACL del subnet de OpenClaw. Inbound: permitir TCP 8080 desde el Dashboard (o su subnet). Outbound: permitir puertos efímeros de vuelta.

### D) Misma máquina (Dashboard = OpenClaw)

Si OpenClaw corre en la **misma** instancia que Nginx: `proxy_pass http://127.0.0.1:8080/;`. Comprobar con `curl -I http://127.0.0.1:8080/` en esa máquina. No hace falta abrir 8080 al exterior.

---

## Comprobación final

Cuando desde el Dashboard funcione:

```bash
curl -I http://<UPSTREAM_IP>:8080/
```

el 504 en la URL pública debería desaparecer:

```bash
curl -I https://dashboard.hilovivo.com/openclaw/
```

(401 sin 504 = correcto.)
