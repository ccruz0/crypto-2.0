# 502 Bad Gateway – dashboard.hilovivo.com

Cuando Nginx devuelve **502 Bad Gateway**, el proxy no recibe respuesta del frontend (puerto 3000) o del backend (puerto 8002).

## Comprobaciones rápidas en el servidor

Con SSH al EC2 (por ejemplo `hilovivo-aws` o la IP):

```bash
# 1. Ver contenedores
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps'

# 2. Probar backend (puerto 8002)
ssh hilovivo-aws 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/ping_fast'

# 3. Probar frontend (puerto 3000)
ssh hilovivo-aws 'curl -s -o /dev/null -w "%{http_code}" http://localhost:3000'

# 4. Logs recientes del backend (por si hay crash al arrancar)
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail 80 backend-aws'

# 5. Logs del frontend
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail 40 frontend-aws'
```

## Arreglo automático (script 502)

Desde tu máquina (en el repo):

```bash
./scripts/fix-502-aws.sh
```

O pasando el host si no usas el por defecto:

```bash
./scripts/fix-502-aws.sh dashboard.hilovivo.com
```

El script comprueba Docker, backend, frontend y Nginx, y reinicia lo que haga falta.

## Arreglo manual en el servidor

```bash
ssh hilovivo-aws

cd /home/ubuntu/automated-trading-platform

# Ver estado
docker compose --profile aws ps

# Reconstruir y levantar (tras un deploy o cambio de código)
git fetch origin && git reset --hard origin/main
docker compose --profile aws up -d --build

# O solo reiniciar sin rebuild
docker compose --profile aws restart backend-aws frontend-aws

# Esperar unos segundos y comprobar
sleep 15
curl -s http://localhost:8002/ping_fast
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000
```

## Si el backend no arranca (crash al inicio)

Si `backend-aws` sale en `docker ps` como Exited o no aparece:

1. Ver el error en logs:
   ```bash
   docker compose --profile aws logs --tail 100 backend-aws
   ```
2. Causas típicas:
   - Error de import o sintaxis en el código nuevo.
   - Base de datos no lista (el servicio `db` debe estar up).
   - Variables de entorno faltantes en `.env.aws`.

## Nginx

Si los contenedores responden en 3000 y 8002 pero la web sigue en 502:

```bash
sudo nginx -t
sudo systemctl status nginx
sudo tail -20 /var/log/nginx/error.log
sudo systemctl reload nginx
```

## Referencia

- Nginx: `nginx/dashboard.conf` (frontend → `localhost:3000`, API → `localhost:8002`).
- Deploy: `.github/workflows/deploy.yml` → ejecuta `scripts/deploy_aws.sh` en el servidor.
