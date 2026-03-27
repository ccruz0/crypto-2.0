#!/bin/bash
# Deploy Crypto.com Signer Proxy to trade_Bot instance

echo "🚀 Deploying Crypto.com Signer Proxy to trade_Bot instance"
echo "=========================================================="

# Configuration
TRADE_BOT_IP="13.215.235.23"  # Public IP of trade_Bot instance
PROXY_TOKEN="CRYPTO_PROXY_SECURE_TOKEN_2024"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "📋 Configuration:"
echo "  Trade Bot IP: $TRADE_BOT_IP"
echo "  Proxy Token: $PROXY_TOKEN"
echo ""

# Copy files to trade_Bot instance
echo "📁 Copying files to trade_Bot..."
scp_cmd crypto_proxy.py ubuntu@$TRADE_BOT_IP:~/crypto-2.0/
scp_cmd requirements.txt ubuntu@$TRADE_BOT_IP:~/crypto-2.0/
scp_cmd crypto-proxy.service ubuntu@$TRADE_BOT_IP:~/crypto-2.0/

echo "✅ Files copied successfully"
echo ""

# Deploy and configure on trade_Bot
echo "🔧 Configuring proxy on trade_Bot..."
ssh_cmd ubuntu@$TRADE_BOT_IP << 'EOF'
cd ~/crypto-2.0

# Install dependencies
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt

# Create environment file
echo "🔐 Creating environment file..."
sudo tee /etc/crypto.env > /dev/null << 'ENVEOF'
CRYPTO_API_KEY=HsTZb9EM1hNmJUyNJ19frs
CRYPTO_API_SECRET=cxakp_QSGZ6uCQdMEqgpQ8dYZbvc
CRYPTO_PROXY_TOKEN=CRYPTO_PROXY_SECURE_TOKEN_2024
ENVEOF

# Install systemd service
echo "⚙️ Installing systemd service..."
sudo cp crypto-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-proxy
sudo systemctl start crypto-proxy

# Check status
echo "📊 Checking service status..."
sudo systemctl status crypto-proxy --no-pager

echo "✅ Proxy deployed successfully!"
echo "🌐 Proxy running on: 127.0.0.1:9000"
echo "🔑 Token: CRYPTO_PROXY_SECURE_TOKEN_2024"
EOF

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "📋 Next steps:"
echo "1. Test the proxy with:"
echo "   curl -s -H \"X-Proxy-Token: CRYPTO_PROXY_SECURE_TOKEN_2024\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"method\":\"private/get-account-summary\",\"params\":{}}' \\"
echo "     http://127.0.0.1:9000/proxy/private"
echo ""
echo "2. Create SSH tunnel from crypto 2.0:"
echo "   ssh -N -L 9000:127.0.0.1:9000 ubuntu@172.31.31.103"
echo ""
echo "3. Test from crypto 2.0:"
echo "   curl -s -H \"X-Proxy-Token: CRYPTO_PROXY_SECURE_TOKEN_2024\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"method\":\"private/get-account-summary\",\"params\":{}}' \\"
echo "     http://127.0.0.1:9000/proxy/private"
