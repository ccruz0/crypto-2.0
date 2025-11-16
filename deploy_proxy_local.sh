#!/bin/bash
# Deploy Crypto.com Signer Proxy locally on current instance

echo "🚀 Deploying Crypto.com Signer Proxy locally"
echo "============================================="

# Configuration
PROXY_TOKEN="CRYPTO_PROXY_SECURE_TOKEN_2024"

echo "📋 Configuration:"
echo "  Local deployment on: $(curl -s ifconfig.me)"
echo "  Proxy Token: $PROXY_TOKEN"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip3 install fastapi uvicorn requests pydantic

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
echo ""

# Test the proxy
echo "🧪 Testing proxy..."
sleep 3
python3 test_proxy.py

echo ""
echo "📋 Next steps:"
echo "1. Test the proxy with:"
echo "   curl -s -H \"X-Proxy-Token: CRYPTO_PROXY_SECURE_TOKEN_2024\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"method\":\"private/get-account-summary\",\"params\":{}}' \\"
echo "     http://127.0.0.1:9000/proxy/private"
echo ""
echo "2. Use from your application:"
echo "   PROXY_URL = \"http://127.0.0.1:9000\""
echo "   TOKEN = \"CRYPTO_PROXY_SECURE_TOKEN_2024\""


