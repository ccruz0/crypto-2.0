# Dashboard Domain Setup for Hilo Vivo

This guide explains how to configure the trading dashboard to be accessible on your Hilo Vivo website.

## Quick Setup

1. **Ensure DNS is configured**:
   - Create an A record: `dashboard.hilovivo.com` → `47.130.143.159`
   - Wait for DNS propagation (can take up to 24 hours)

2. **Run the setup script**:
   ```bash
   ./setup_dashboard_domain.sh
   ```

3. **Access your dashboard**:
   - https://dashboard.hilovivo.com

## What the Script Does

1. **Installs and configures Nginx** as a reverse proxy
2. **Sets up SSL certificate** using Let's Encrypt (free HTTPS)
3. **Configures automatic SSL renewal**
4. **Updates backend CORS** to allow requests from your domain
5. **Restarts services** to apply changes

## Manual Setup (Alternative)

If you prefer to set up manually:

### 1. Install Nginx and Certbot

```bash
ssh -i ~/.ssh/id_rsa ubuntu@47.130.143.159
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

### 2. Copy Nginx Configuration

```bash
# From your local machine
scp -i ~/.ssh/id_rsa nginx/dashboard.conf ubuntu@47.130.143.159:/tmp/

# On the server
sudo cp /tmp/dashboard.conf /etc/nginx/sites-available/dashboard.conf
sudo ln -s /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 3. Obtain SSL Certificate

```bash
sudo certbot --nginx -d dashboard.hilovivo.com --non-interactive --agree-tos --email your-email@hilovivo.com
```

### 4. Update Backend CORS (if needed)

The backend code already includes `hilovivo.com` domains in the CORS whitelist. If you need additional domains, add them to `.env.aws`:

```bash
CORS_ORIGINS=https://dashboard.hilovivo.com,https://www.dashboard.hilovivo.com
```

Then restart the backend:

```bash
docker compose --profile aws restart backend-aws
```

## Configuration Options

### Option 1: Subdomain (Recommended)
- URL: `https://dashboard.hilovivo.com`
- Uses the provided `nginx/dashboard.conf` as-is
- Clean and professional

### Option 2: Path-based Routing
- URL: `https://hilovivo.com/dashboard`
- Uncomment the path-based section in `nginx/dashboard.conf`
- Requires additional Nginx configuration for your main site

## How It Works

1. **Nginx** receives requests on port 80/443
2. **SSL/TLS** is handled by Let's Encrypt certificates
3. **Frontend requests** (`/`) are proxied to `localhost:3000` (frontend container)
4. **API requests** (`/api/*`) are proxied to `localhost:8002` (backend container)
5. **Frontend code** automatically detects the `hilovivo.com` domain and uses `/api` for backend calls

## Troubleshooting

### DNS Not Resolving
```bash
# Check DNS propagation
dig dashboard.hilovivo.com
nslookup dashboard.hilovivo.com

# Should return: 47.130.143.159
```

### SSL Certificate Issues
```bash
# Check certificate status
sudo certbot certificates

# Renew manually if needed
sudo certbot renew --dry-run
```

### Nginx Not Starting
```bash
# Check Nginx configuration
sudo nginx -t

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
```

### Backend Not Accessible
```bash
# Check if backend is running
docker compose --profile aws ps backend-aws

# Check backend logs
docker compose --profile aws logs backend-aws

# Test backend directly
curl http://localhost:8002/health
```

### Frontend Not Loading
```bash
# Check if frontend is running
docker compose --profile aws ps frontend-aws

# Check frontend logs
docker compose --profile aws logs frontend-aws

# Test frontend directly
curl http://localhost:3000
```

## Security Notes

- ✅ HTTPS is enforced (HTTP redirects to HTTPS)
- ✅ SSL certificates auto-renew via Certbot
- ✅ CORS is configured to only allow your domain
- ✅ Security headers are included in Nginx config
- ⚠️ Consider adding authentication if the dashboard should be private

## Updating the Dashboard

After making changes to the frontend or backend:

```bash
# Deploy updates
./deploy_aws.sh

# The domain configuration persists, so your dashboard will automatically use the new version
```

## Support

If you encounter issues:
1. Check DNS propagation: https://www.whatsmydns.net/#A/dashboard.hilovivo.com
2. Verify SSL: https://www.ssllabs.com/ssltest/analyze.html?d=dashboard.hilovivo.com
3. Check server logs: `docker compose --profile aws logs`

