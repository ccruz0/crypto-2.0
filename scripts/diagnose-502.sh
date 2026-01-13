#!/bin/bash
# Diagnostic script for 502 Bad Gateway errors

echo "🔍 Diagnosing 502 Bad Gateway Error..."
echo ""

# Check if services are running
echo "1. Checking if backend service is running on port 8002..."
if lsof -i :8002 > /dev/null 2>&1; then
    echo "   ✅ Backend service is running on port 8002"
    BACKEND_PID=$(lsof -ti :8002 | head -1)
    echo "   PID: $BACKEND_PID"
else
    echo "   ❌ Backend service is NOT running on port 8002"
    echo "   💡 Start backend: cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002"
fi

echo ""
echo "2. Checking if frontend service is running on port 3000..."
if lsof -i :3000 > /dev/null 2>&1; then
    echo "   ✅ Frontend service is running on port 3000"
    FRONTEND_PID=$(lsof -ti :3000 | head -1)
    echo "   PID: $FRONTEND_PID"
else
    echo "   ❌ Frontend service is NOT running on port 3000"
    echo "   💡 Start frontend: cd frontend && npm run dev"
fi

echo ""
echo "3. Testing backend connectivity..."
if curl -s -f http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "   ✅ Backend is responding to health checks"
    BACKEND_HEALTH=$(curl -s http://localhost:8002/ping_fast)
    echo "   Response: $BACKEND_HEALTH"
else
    echo "   ❌ Backend is NOT responding to health checks"
    echo "   💡 Check backend logs for errors"
fi

echo ""
echo "4. Testing frontend connectivity..."
if curl -s -f http://localhost:3000 > /dev/null 2>&1; then
    echo "   ✅ Frontend is responding"
else
    echo "   ❌ Frontend is NOT responding"
    echo "   💡 Check frontend logs for errors"
fi

echo ""
echo "5. Checking nginx status..."
if pgrep -x nginx > /dev/null; then
    echo "   ✅ Nginx is running"
    echo "   PIDs: $(pgrep nginx | tr '\n' ' ')"
else
    echo "   ❌ Nginx is NOT running"
    echo "   💡 Start nginx: sudo nginx or brew services start nginx"
fi

echo ""
echo "6. Testing nginx proxy to backend..."
if curl -s -f http://localhost/api/health > /dev/null 2>&1 || curl -s -f http://localhost:8080/api/health > /dev/null 2>&1; then
    echo "   ✅ Nginx can proxy to backend"
else
    echo "   ❌ Nginx cannot proxy to backend (this is likely the 502 source)"
    echo "   💡 Check nginx error logs: sudo tail -f /var/log/nginx/error.log"
fi

echo ""
echo "7. Testing nginx proxy to frontend..."
if curl -s -f http://localhost/ > /dev/null 2>&1 || curl -s -f http://localhost:8080/ > /dev/null 2>&1; then
    echo "   ✅ Nginx can proxy to frontend"
else
    echo "   ❌ Nginx cannot proxy to frontend (this is likely the 502 source)"
    echo "   💡 Check nginx error logs: sudo tail -f /var/log/nginx/error.log"
fi

echo ""
echo "📋 Summary:"
echo "   - If backend/frontend are not running, start them first"
echo "   - If services are running but nginx can't connect, check:"
echo "     * Firewall rules"
echo "     * Nginx configuration (nginx -t)"
echo "     * Service binding (should be 0.0.0.0, not 127.0.0.1)"
echo "   - Check nginx error logs for detailed error messages"







