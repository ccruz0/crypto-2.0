# 502 Bad Gateway Diagnostic Commands

## Immediate Diagnostic Steps

### 1. Check Backend Container Status

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws ps backend-aws\"'"
```

### 2. Check Backend Container Logs (Last 100 lines)

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws logs --tail=100 backend-aws\"'"
```

### 3. Check if Backend is Responding Internally

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws exec backend-aws curl -sS http://localhost:8002/ping_fast || echo \\\"Backend not responding internally\\\"'"
```

### 4. Check Backend Health Check

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws exec backend-aws python -c \\\"import urllib.request;urllib.request.urlopen('http://localhost:8002/ping_fast', timeout=10)\\\" && echo \\\"Health check passed\\\" || echo \\\"Health check failed\\\"'"
```

### 5. Check All Container Statuses

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws ps\"'"
```

### 6. Check Nginx/Proxy Status (if applicable)

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws ps | grep -E \\\"nginx|proxy|frontend\\\"'"
```

### 7. Check Backend Startup Errors

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws logs backend-aws | grep -i -E \\\"error|exception|traceback|failed|crash\\\" | tail -50'"
```

### 8. Check Dependencies (Gluetun VPN and Database)

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws ps gluetun db\"'"
```

## Common Fixes

### If Backend Container is Stopped/Crashed:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws up -d backend-aws && docker compose --profile aws logs -f backend-aws'"
```

### If Backend is Running but Not Healthy:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws restart backend-aws && sleep 30 && docker compose --profile aws logs --tail=50 backend-aws'"
```

### If Dependencies (Gluetun/DB) are Down:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws up -d gluetun db && sleep 10 && docker compose --profile aws up -d backend-aws'"
```

### Full Restart of All Services:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws down && docker compose --profile aws up -d && sleep 30 && docker compose --profile aws ps'"
```

## Expected Outputs

### Healthy Backend:
- Container status: `Up (healthy)` or `Up`
- Health check: `Health check passed`
- Internal curl: Returns HTTP 200
- Logs: No errors, shows "Application startup complete" or similar

### Unhealthy Backend:
- Container status: `Up (unhealthy)` or `Restarting` or `Exited`
- Health check: `Health check failed`
- Internal curl: Connection refused or timeout
- Logs: Show errors, exceptions, or tracebacks
