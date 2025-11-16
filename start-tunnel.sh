#!/bin/bash
# Cloudflare Tunnel script for external access to the trading platform
# This creates public URLs for both frontend and backend

echo "🚀 Starting Cloudflare Tunnels..."
echo "📊 Frontend will be available at a public URL"
echo "🔧 Backend API will be available at a public URL"
echo ""
echo "⚠️  Note: Enable external access by setting ENABLE_EXTERNAL_ACCESS=true in your .env file"
echo "   Then restart the backend service."
echo ""

# Start tunnels in parallel
echo "Starting frontend tunnel (port 3000)..."
cloudflared tunnel --url http://localhost:3000 &
FRONTEND_TUNNEL_PID=$!

sleep 2

echo "Starting backend tunnel (port 8000)..."
cloudflared tunnel --url http://localhost:8000 &
BACKEND_TUNNEL_PID=$!

echo ""
echo "✅ Tunnels started!"
echo "📝 Frontend PID: $FRONTEND_TUNNEL_PID"
echo "📝 Backend PID: $BACKEND_TUNNEL_PID"
echo ""
echo "💡 URLs will be displayed above. Copy the URLs and share them."
echo ""
echo "Press Ctrl+C to stop the tunnels"

# Wait for user interrupt
trap "kill $FRONTEND_TUNNEL_PID $BACKEND_TUNNEL_PID 2>/dev/null; exit" INT TERM
wait

