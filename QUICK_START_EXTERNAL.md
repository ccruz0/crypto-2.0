# Quick Start: External Access from Any Network

## 🚀 Fastest Option: Cloudflare Tunnel (No Signup Required)

### Step 1: Enable External Access

Add this to your `.env` file:
```bash
echo "ENABLE_EXTERNAL_ACCESS=true" >> .env
```

Then restart the backend:
```bash
docker compose restart backend
```

### Step 2: Install & Run Cloudflare Tunnel

If not already installed:
```bash
brew install cloudflared
```

Then start tunnels:
```bash
./start-tunnel.sh
```

This will create **public URLs** that you can access from anywhere!

---

## 📱 Alternative: ngrok (Requires Free Signup)

1. **Install**: `brew install ngrok/ngrok/ngrok`
2. **Sign up** at https://dashboard.ngrok.com (free)
3. **Authenticate**: `ngrok config add-authtoken YOUR_TOKEN`
4. **Start tunnels**:
   ```bash
   # Terminal 1: Frontend
   ngrok http 3000
   
   # Terminal 2: Backend  
   ngrok http 8000
   ```
5. **Copy the URLs** and access from anywhere!

---

## ⚙️ Manual Port Forwarding (Advanced)

1. Find your public IP: `curl ifconfig.me`
2. Configure router port forwarding (ports 3000, 8000 → your Mac IP)
3. Enable external access: `ENABLE_EXTERNAL_ACCESS=true` in `.env`
4. Access: `http://YOUR_PUBLIC_IP:3000`

⚠️ **Security Warning**: Port forwarding exposes your server directly. Consider using a VPN or tunnel instead.

---

## 💡 Recommended Setup

**For most users, Cloudflare Tunnel is the easiest:**

```bash
# 1. Enable external access
echo "ENABLE_EXTERNAL_ACCESS=true" >> .env
docker compose restart backend

# 2. Start tunnels (creates public URLs automatically)
./start-tunnel.sh

# 3. Share the public URLs with anyone, anywhere!
```

See `EXTERNAL_ACCESS.md` for detailed instructions.

