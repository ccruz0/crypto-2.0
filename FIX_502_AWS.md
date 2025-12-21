# Fix 502 Error on AWS Server

## Problem
The dashboard at `https://dashboard.hilovivo.com` is returning a 502 Bad Gateway error. This means nginx (the reverse proxy) cannot connect to the backend application.

## Quick Fix

Run the automated setup script:

```bash
./setup_nginx_aws.sh
```

This script will:
1. ✅ Install nginx if not installed
2. ✅ Copy the nginx configuration
3. ✅ Test the configuration
4. ✅ Check backend/frontend connectivity
5. ✅ Start/restart nginx

## Manual Fix Steps

If you prefer to fix it manually:

### 1. SSH into the AWS server

```bash
ssh ubuntu@175.41.189.249
# or
ssh ubuntu@54.254.150.31
```

### 2. Install nginx (if not installed)

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

### 3. Copy nginx configuration

```bash
cd ~/automated-trading-platform
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard.conf
sudo ln -sf /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/dashboard.conf
sudo rm -f /etc/nginx/sites-enabled/default
```

### 4. Test nginx configuration

```bash
sudo nginx -t
```

If you see SSL certificate errors, you have two options:

**Option A: Set up SSL certificates (for production)**
```bash
sudo certbot --nginx -d dashboard.hilovivo.com
```

**Option B: Use HTTP-only config (for testing)**
```bash
# Copy the local config instead
sudo cp nginx/dashboard-local.conf /etc/nginx/sites-available/dashboard.conf
# Modify to use port 80 instead of 8080
sudo sed -i 's/listen 8080/listen 80/g' /etc/nginx/sites-available/dashboard.conf
sudo nginx -t
```

### 5. Verify backend is running

```bash
# Check if backend container is running
docker compose --profile aws ps backend-aws

# Test backend directly
curl http://localhost:8002/health
curl http://localhost:8002/ping_fast
```

If backend is not running:
```bash
docker compose --profile aws up -d backend-aws
```

### 6. Verify frontend is running

```bash
# Check if frontend container is running
docker compose --profile aws ps frontend-aws

# Test frontend directly
curl http://localhost:3000
```

If frontend is not running:
```bash
docker compose --profile aws up -d frontend-aws
```

### 7. Start/Restart nginx

```bash
sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl status nginx
```

### 8. Check nginx logs

```bash
# Check for errors
sudo tail -50 /var/log/nginx/error.log

# Check access logs
sudo tail -50 /var/log/nginx/access.log
```

## Verify the Fix

From your local machine:

```bash
# Test health endpoint
curl -k https://dashboard.hilovivo.com/api/health

# Test dashboard
curl -k https://dashboard.hilovivo.com/
```

## Common Issues

### Issue 1: SSL Certificates Missing

**Error**: `cannot load certificate "/etc/letsencrypt/live/dashboard.hilovivo.com/fullchain.pem"`

**Solution**:
```bash
sudo certbot --nginx -d dashboard.hilovivo.com
```

### Issue 2: Backend Not Running

**Error**: `502 Bad Gateway` and backend container is stopped

**Solution**:
```bash
docker compose --profile aws up -d backend-aws
# Wait for it to be healthy
docker compose --profile aws ps backend-aws
```

### Issue 3: Backend on Wrong Port

**Error**: nginx config expects port 8002 but backend is on 8000

**Check**:
```bash
# See what port backend is actually using
docker compose --profile aws ps backend-aws
docker compose --profile aws port backend-aws
```

**Fix**: Update nginx config to match the actual backend port, or update docker-compose.yml to use port 8002.

### Issue 4: Nginx Config Syntax Error

**Error**: `nginx: configuration file /etc/nginx/nginx.conf test failed`

**Solution**:
```bash
# Test config
sudo nginx -t

# Check for specific errors
sudo nginx -t 2>&1 | grep -A 5 error
```

## Troubleshooting Commands

```bash
# Check nginx status
sudo systemctl status nginx

# Check backend connectivity from host
curl -v http://localhost:8002/health

# Check frontend connectivity from host
curl -v http://localhost:3000

# View real-time nginx errors
sudo tail -f /var/log/nginx/error.log

# View real-time nginx access
sudo tail -f /var/log/nginx/access.log

# Restart nginx
sudo systemctl restart nginx

# Check Docker containers
docker compose --profile aws ps

# View backend logs
docker compose --profile aws logs backend-aws --tail=100

# View frontend logs
docker compose --profile aws logs frontend-aws --tail=100
```

## Expected Configuration

### Backend
- **Container**: `backend-aws`
- **Port**: `8002` (mapped from container)
- **Health endpoint**: `http://localhost:8002/ping_fast` or `http://localhost:8002/health`

### Frontend
- **Container**: `frontend-aws`
- **Port**: `3000` (mapped from container)
- **URL**: `http://localhost:3000`

### Nginx
- **Config**: `/etc/nginx/sites-available/dashboard.conf`
- **Enabled**: `/etc/nginx/sites-enabled/dashboard.conf` (symlink)
- **SSL**: `/etc/letsencrypt/live/dashboard.hilovivo.com/`
- **Domain**: `dashboard.hilovivo.com`

## After Fixing

Once the 502 error is resolved:

1. ✅ Dashboard should load at `https://dashboard.hilovivo.com`
2. ✅ API endpoints should work: `https://dashboard.hilovivo.com/api/health`
3. ✅ No more 502 errors in nginx logs

## Prevention

To prevent this issue in the future:

1. **Monitor backend health**: Set up health checks in docker-compose.yml
2. **Auto-restart nginx**: nginx should auto-restart on failure (systemd)
3. **Monitor logs**: Set up log monitoring for 502 errors
4. **Health checks**: Use the health monitor scripts in the project





