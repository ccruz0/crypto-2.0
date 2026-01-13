# Outbound IP Configuration Report

## Executive Summary

Based on analysis of `docker-compose.yml`:

✅ **Gluetun/VPN is REMOVED** - Backend connects directly via AWS Elastic IP  
✅ **No network routing changes needed** - Backend uses default Docker bridge network  
✅ **Outbound IP should be AWS Elastic IP** - Container shares host's network stack for outbound  

## Current Configuration

### Backend Network Setup:
- **Service**: `backend-aws`
- **Network Mode**: Default bridge (not specified = uses bridge network)
- **VPN/Proxy**: ❌ None (gluetun removed per docker-compose.yml comments)
- **Outbound Connection**: Direct to Crypto.com API (USE_CRYPTO_PROXY=false)
- **Expected Outbound IP**: AWS Elastic IP `47.130.143.159` (or current EIP)

### Key Evidence:
```yaml
# From docker-compose.yml:
# "Gluetun has been removed as the system now uses direct AWS Elastic IP connection"
# "Backend connects directly from AWS Elastic IP 47.130.143.159 to api.crypto.com/exchange/v1"
```

## Verification Commands (Run on EC2 Instance)

Run these commands via SSH or AWS SSM to confirm actual outbound IPs:

```bash
cd ~/automated-trading-platform

# 1. Check outbound IP from EC2 host
echo "=== Host Outbound IP ==="
curl -s https://api.ipify.org ; echo
curl -s https://ifconfig.me ; echo
curl -s https://checkip.amazonaws.com ; echo

# 2. Check outbound IP from backend container
echo "=== Backend Container Outbound IP ==="
docker compose --profile aws exec -T backend-aws sh -c "curl -s https://api.ipify.org ; echo"
docker compose --profile aws exec -T backend-aws sh -c "curl -s https://ifconfig.me ; echo"

# 3. Verify network configuration
echo "=== Network Configuration ==="
docker network ls
docker compose --profile aws ps
docker inspect automated-trading-platform-backend-aws-1 --format='{{.HostConfig.NetworkMode}}' 2>/dev/null || echo "Container name may differ"

# 4. Verify no gluetun
echo "=== Gluetun Check ==="
docker ps -a | grep gluetun || echo "✅ No gluetun container found (expected)"
```

### Expected Results:
- ✅ Host IP == Container IP (both show AWS Elastic IP, e.g., `47.130.143.159`)
- ✅ No gluetun container running
- ✅ Network mode is "default" or "bridge"
- ✅ Crypto.com API calls use AWS Elastic IP (whitelist should work)

## Safe Access Methods (Without Changing Outbound IP)

### Option A: Cloudflare Tunnel (Recommended) ⭐

**Why Recommended:**
- ✅ Zero-trust (no inbound ports)
- ✅ HTTPS by default
- ✅ Free
- ✅ Does NOT affect outbound IP
- ✅ Works through firewalls

**Setup Steps:**

1. **Install cloudflared on EC2:**
   ```bash
   # On EC2 instance
   wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
   chmod +x cloudflared-linux-amd64
   sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
   ```

2. **Create systemd services for tunnels:**
   
   **Backend tunnel** (`/etc/systemd/system/cloudflared-backend.service`):
   ```ini
   [Unit]
   Description=Cloudflare Tunnel - Backend
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:8002
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   **Frontend tunnel** (`/etc/systemd/system/cloudflared-frontend.service`):
   ```ini
   [Unit]
   Description=Cloudflare Tunnel - Frontend
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:3000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **Start tunnels:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable cloudflared-backend cloudflared-frontend
   sudo systemctl start cloudflared-backend cloudflared-frontend
   sudo systemctl status cloudflared-backend cloudflared-frontend
   ```

4. **Access your dashboard:**
   - Backend: Use the URL shown in cloudflared output (e.g., `https://xxxx-xxx.trycloudflare.com`)
   - Frontend: Use the URL shown in cloudflared output

**Note:** Cloudflare free tunnels have temporary URLs that change on restart. For permanent URLs, use Cloudflare Tunnel with a domain (requires Cloudflare account).

---

### Option B: Nginx Reverse Proxy + Security Group IP Restriction

**Why This Option:**
- ✅ Standard HTTP/HTTPS setup
- ✅ Control over domain/SSL
- ✅ IP-based access control
- ✅ Does NOT change backend container network

**Setup Steps:**

1. **Install nginx on EC2:**
   ```bash
   sudo apt update
   sudo apt install -y nginx certbot python3-certbot-nginx
   ```

2. **Configure nginx** (`/etc/nginx/sites-available/trading-platform`):
   ```nginx
   # Backend API
   server {
       listen 80;
       server_name _;  # Or your domain

       location /api/ {
           proxy_pass http://localhost:8002/api/;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }

       # Frontend
       location / {
           proxy_pass http://localhost:3000/;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }
   }
   ```

3. **Enable site:**
   ```bash
   sudo ln -s /etc/nginx/sites-available/trading-platform /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

4. **Set up SSL (optional but recommended):**
   ```bash
   # If you have a domain:
   sudo certbot --nginx -d yourdomain.com
   
   # Or use self-signed cert for testing:
   sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout /etc/ssl/private/nginx-selfsigned.key \
     -out /etc/ssl/certs/nginx-selfsigned.crt
   ```

5. **Configure Security Group:**
   - Open port 80 (HTTP) and 443 (HTTPS)
   - **Restrict source IP to your laptop's public IP only**
   - Keep port 22 (SSH) restricted to your IP

   AWS Security Group Rules:
   ```
   Inbound Rules:
     - Type: SSH (22)
       Source: Your Laptop IP/32
     
     - Type: HTTP (80)
       Source: Your Laptop IP/32
     
     - Type: HTTPS (443)
       Source: Your Laptop IP/32

   Outbound Rules:
     - All traffic (unchanged - backend uses this for Crypto.com API)
   ```

6. **Find your laptop's public IP:**
   ```bash
   # Run this on your laptop
   curl -s https://api.ipify.org
   ```

7. **Access dashboard:**
   - Frontend: `http://EC2_PUBLIC_IP/` or `https://EC2_PUBLIC_IP/`
   - Backend API: `http://EC2_PUBLIC_IP/api/health`

## Important Security Notes

⚠️ **DO NOT:**
- ❌ Change `network_mode` for backend-aws container
- ❌ Route backend through VPN/proxy for outbound traffic
- ❌ Open ports 8002/3000 to 0.0.0.0/0 (insecure)
- ❌ Modify backend container's outbound routing

✅ **SAFE TO:**
- ✅ Use Cloudflare Tunnel (no network changes to containers)
- ✅ Use nginx reverse proxy on host (containers unchanged)
- ✅ Restrict security group to your IP only
- ✅ Access via HTTPS reverse proxy

## Verification After Setup

1. **Verify outbound IP unchanged:**
   ```bash
   # Should still show AWS Elastic IP
   docker compose --profile aws exec -T backend-aws sh -c "curl -s https://api.ipify.org"
   ```

2. **Test Crypto.com API access:**
   ```bash
   # Should work if whitelist has AWS Elastic IP
   docker compose --profile aws exec -T backend-aws sh -c "curl -s https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT | head -20"
   ```

3. **Test dashboard access:**
   - Access frontend URL
   - Check backend health endpoint
   - Verify API calls work

## Recommendation

**Use Cloudflare Tunnel (Option A)** because:
1. ✅ No security group changes needed
2. ✅ No inbound ports exposed
3. ✅ HTTPS by default
4. ✅ Free and easy to set up
5. ✅ Zero impact on backend outbound IP

If you need a custom domain or more control, use Option B with strict IP restrictions.



