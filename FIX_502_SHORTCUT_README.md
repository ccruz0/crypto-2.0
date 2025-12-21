# Acceso Directo "Fix 502 Dashboard"

## 📋 Descripción

Se ha creado un acceso directo en el escritorio llamado **"Fix 502 Dashboard"** que facilita el diagnóstico y solución del error 502 en el dashboard.

## 🎯 ¿Qué hace el acceso directo?

Cuando haces doble clic en el acceso directo, automáticamente:

1. **🌐 Abre el navegador** con el dashboard (`https://dashboard.hilovivo.com`)
2. **🔍 Ejecuta diagnósticos automáticos** del sistema en AWS
3. **📂 Abre Cursor** con los archivos relevantes para diagnosticar el problema:
   - `backend/app/api/routes_dashboard.py`
   - `nginx/dashboard.conf`
   - `docker-compose.yml`
   - `docs/502_BAD_GATEWAY_REVIEW.md`
   - `backend/app/services/exchange_sync.py`
   - `.github/workflows/deploy.yml`

## 🚀 Uso

1. **Haz doble clic** en el icono "Fix 502 Dashboard" en tu escritorio
2. Se abrirá una ventana de terminal mostrando el diagnóstico
3. El navegador se abrirá automáticamente con el dashboard
4. Cursor se abrirá con los archivos relevantes

## 🔧 Soluciones Comunes para Error 502

Si el diagnóstico muestra un error 502, las soluciones más comunes son:

### 1. Reiniciar Nginx
```bash
ssh hilovivo-aws 'sudo systemctl restart nginx'
```

### 2. Reiniciar Backend
```bash
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

### 3. Reiniciar Todos los Servicios
```bash
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws restart && sudo systemctl restart nginx'
```

### 4. Ver Logs del Backend
```bash
ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws logs --tail=50 backend-aws'
```

### 5. Ver Logs de Nginx
```bash
ssh hilovivo-aws 'sudo tail -20 /var/log/nginx/error.log'
```

## 📁 Archivos Creados

- **Acceso directo**: `~/Desktop/Fix_502_Dashboard.app`
- **Script principal**: `fix_502_dashboard.sh`
- **Script de creación**: `create_502_shortcut.sh`

## 🔄 Recrear el Acceso Directo

Si necesitas recrear el acceso directo:

```bash
cd /Users/carloscruz/automated-trading-platform
bash create_502_shortcut.sh
```

## 📝 Notas

- El acceso directo requiere conexión SSH a `hilovivo-aws` para ejecutar diagnósticos
- Asegúrate de tener configurado el acceso SSH antes de usar el acceso directo
- El icono muestra "502" en rojo para identificar fácilmente el propósito del acceso directo

## 🐛 Troubleshooting

### El acceso directo no se ejecuta
- Verifica que el script `fix_502_dashboard.sh` tenga permisos de ejecución:
  ```bash
  chmod +x /Users/carloscruz/automated-trading-platform/fix_502_dashboard.sh
  ```

### Cursor no se abre
- Verifica que Cursor esté instalado en `/Applications/Cursor.app`
- Si está en otra ubicación, edita `fix_502_dashboard.sh` y actualiza la variable `CURSOR_APP`

### No se puede conectar a AWS
- Verifica tu configuración SSH:
  ```bash
  ssh hilovivo-aws 'echo "Conexión exitosa"'
  ```














