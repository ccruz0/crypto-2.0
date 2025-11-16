# External Network Access Guide

This guide explains how to access your trading dashboard from a different network (not just your local network).

## Option 1: Cloudflare Tunnel (Recommended - Free, No Signup)

Cloudflare Tunnel is free and doesn't require signup. It creates secure public URLs.

### Setup:

1. **Install Cloudflare Tunnel** (if not already installed):
   ```bash
   brew install cloudflared
   ```

2. **Enable external access in your backend**:
   Add to your `.env` file:
   ```
   ENABLE_EXTERNAL_ACCESS=true
   ```
   Then restart the backend:
   ```bash
   docker compose restart backend
   ```

3. **Start the tunnels**:
   Run the provided script:
   ```bash
   ./start-tunnel.sh
   ```
   
   Or manually:
   ```bash
   # Frontend tunnel
   cloudflared tunnel --url http://localhost:3000
   
   # Backend tunnel (in another terminal)
   cloudflared tunnel --url http://localhost:8000
   ```

4. **Copy the public URLs** shown in the terminal output and access your dashboard from anywhere!

---

## Option 2: ngrok (Easy - Requires Free Signup)

ngrok is very popular and user-friendly.

### Setup:

1. **Install ngrok**:
   ```bash
   brew install ngrok/ngrok/ngrok
   ```

2. **Sign up for free account** at https://dashboard.ngrok.com/signup

3. **Authenticate**:
   ```bash
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

4. **Enable external access**:
   Add to your `.env` file:
   ```
   ENABLE_EXTERNAL_ACCESS=true
   ```
   Then restart the backend:
   ```bash
   docker compose restart backend
   ```

5. **Start tunnels**:
   ```bash
   # Frontend (in one terminal)
   ngrok http 3000
   
   # Backend (in another terminal)
   ngrok http 8000
   ```

6. **Update frontend to use ngrok backend URL**:
   When you start ngrok, it will give you URLs like:
   - Frontend: `https://xxxx-xxx-xxx.ngrok-free.app`
   - Backend: `https://yyyy-yyy-yyy.ngrok-free.app`
   
   You'll need to update your frontend environment to point to the ngrok backend URL, or use ngrok's domain forwarding feature.

---

## Option 3: Port Forwarding (Advanced - Requires Router Access)

This method exposes your local server directly to the internet.

### Requirements:
- Router admin access
- Static public IP (or use Dynamic DNS)
- Firewall configuration

### Setup:

1. **Find your public IP**:
   ```bash
   curl ifconfig.me
   ```

2. **Configure router port forwarding**:
   - Forward port 3000 → Your Mac's local IP (e.g., 172.20.10.2)
   - Forward port 8000 → Your Mac's local IP (e.g., 172.20.10.2)

3. **Configure firewall** (macOS):
   - System Preferences → Security & Privacy → Firewall
   - Allow incoming connections on ports 3000 and 8000

4. **Enable external access**:
   Add to your `.env` file:
   ```
   ENABLE_EXTERNAL_ACCESS=true
   ```
   Then restart the backend:
   ```bash
   docker compose restart backend
   ```

5. **Access from anywhere**:
   - Frontend: `http://YOUR_PUBLIC_IP:3000`
   - Backend: `http://YOUR_PUBLIC_IP:8000`

### Security Warning:
⚠️ Port forwarding exposes your server directly to the internet. Make sure you:
- Use HTTPS (set up reverse proxy with SSL)
- Implement authentication
- Use strong passwords
- Regularly update your system

---

## Recommended: Cloudflare Tunnel

For most users, **Cloudflare Tunnel is the best option** because:
- ✅ Free
- ✅ No signup required
- ✅ Secure (encrypted)
- ✅ Easy to use
- ✅ Works through firewalls and NAT

### Quick Start with Cloudflare Tunnel:

```bash
# 1. Enable external access
echo "ENABLE_EXTERNAL_ACCESS=true" >> .env
docker compose restart backend

# 2. Start tunnels
./start-tunnel.sh

# 3. Copy the public URLs and share them!
```

---

## Troubleshooting

### CORS Errors:
If you see CORS errors, make sure:
1. `ENABLE_EXTERNAL_ACCESS=true` is set in your `.env`
2. Backend service has been restarted: `docker compose restart backend`

### Connection Issues:
- Make sure both frontend and backend services are running
- Check that ports 3000 and 8000 are accessible locally
- Verify tunnel URLs are correct

### Frontend Can't Connect to Backend:
- Update the frontend environment to use the tunnel backend URL
- Or configure the tunnel to forward both frontend and backend under the same domain

