#!/bin/bash

echo "========================================="
echo "Testing Dashboard Connectivity"
echo "========================================="

# Test 1: Backend API
echo "1. Testing Backend API..."
if curl -s -H "X-API-Key: demo-key" http://localhost:8000/api/dashboard | jq -r '.[0].symbol' 2>/dev/null; then
    echo "✅ Backend API working - Found crypto data"
else
    echo "❌ Backend API not working"
fi

# Test 2: Frontend
echo "2. Testing Frontend..."
if curl -s http://localhost:3000 | grep -q "Trading Dashboard"; then
    echo "✅ Frontend accessible"
else
    echo "❌ Frontend not accessible"
fi

# Test 3: Check if data is being loaded
echo "3. Checking if data is being loaded..."
if curl -s http://localhost:3000 | grep -q "Loading portfolio data"; then
    echo "⚠️  Frontend shows 'Loading portfolio data' - API calls may be failing"
else
    echo "✅ Frontend not showing loading message - data may be loaded"
fi

# Test 4: Direct API call from frontend container
echo "4. Testing API from frontend container..."
if docker compose exec frontend wget -qO- --header="X-API-Key: demo-key" http://backend:8000/api/dashboard | jq -r '.[0].symbol' 2>/dev/null; then
    echo "✅ Frontend container can access backend"
else
    echo "❌ Frontend container cannot access backend"
fi

echo ""
echo "========================================="
echo "Summary"
echo "========================================="
echo "If you see 'Loading portfolio data' in the browser:"
echo "1. Open browser DevTools (F12)"
echo "2. Check Console tab for errors"
echo "3. Check Network tab for failed API requests"
echo "4. Look for CORS errors or connection refused errors"

