# Deploy Docs Endpoint Fix - Manual Instructions

This document provides instructions to deploy the fix for the 404 error when accessing:
`dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md`

## Changes Made

1. **Backend API Endpoint** (`backend/app/api/routes_monitoring.py`):
   - Added endpoint: `/api/monitoring/reports/watchlist-consistency/latest`
   - Serves the markdown file from `docs/monitoring/watchlist_consistency_report_latest.md`

2. **Nginx Configuration** (`nginx/dashboard.conf`):
   - Added location block for `/docs/monitoring/`
   - Rewrites requests to the backend API endpoint

## Deployment Steps

### Option 1: Via SSH (if available)

```bash
# 1. Sync the backend file
rsync -avz -e "ssh -i ~/.ssh/id_rsa -o StrictHostKeyChecking=no" \
  ./backend/app/api/routes_monitoring.py \
  ubuntu@175.41.189.249:~/automated-trading-platform/backend/app/api/routes_monitoring.py

# 2. Sync the nginx config
rsync -avz -e "ssh -i ~/.ssh/id_rsa -o StrictHostKeyChecking=no" \
  ./nginx/dashboard.conf \
  ubuntu@175.41.189.249:~/automated-trading-platform/nginx/dashboard.conf

# 3. SSH into server and reload services
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 << 'EOF'
  cd ~/automated-trading-platform
  
  # Test nginx config
  sudo nginx -t
  
  # Reload nginx
  sudo systemctl reload nginx
  
  # Restart backend (adjust service name as needed)
  sudo systemctl restart trading-backend || \
  sudo systemctl restart backend || \
  docker restart $(docker ps -q -f name=backend) || \
  echo "Backend restart - check your service name"
EOF
```

### Option 2: Via AWS SSM Session Manager

1. **Start an SSM Session:**
   ```bash
   aws ssm start-session --target i-08726dc37133b2454 --region ap-southeast-1
   ```

2. **On the server, upload the files:**
   
   You'll need to get the files to the server first. Options:
   - Use `scp` if you have network access
   - Use S3 to upload, then download on server
   - Copy-paste the file contents manually
   - Use git pull if changes are committed

3. **Once files are on server, run:**
   ```bash
   cd ~/automated-trading-platform
   
   # Verify files are updated
   grep -A 5 "watchlist-consistency/latest" backend/app/api/routes_monitoring.py
   grep -A 5 "/docs/monitoring/" nginx/dashboard.conf
   
   # Test nginx config
   sudo nginx -t
   
   # Reload nginx
   sudo systemctl reload nginx
   
   # Restart backend service
   # (Adjust based on how your backend runs)
   sudo systemctl restart trading-backend || \
   docker compose restart backend || \
   docker restart $(docker ps -q -f name=backend)
   ```

### Option 3: Manual File Edit (if files are already on server)

If you can access the server via SSM or another method:

1. **Edit `backend/app/api/routes_monitoring.py`:**
   
   Add this endpoint after line 1059 (after the `get_latest_sl_tp_check_report` function):
   
   ```python
   @router.get("/monitoring/reports/watchlist-consistency/latest")
   async def get_watchlist_consistency_report_latest():
       """
       Serve the latest watchlist consistency report as markdown.
       
       This endpoint serves the file at docs/monitoring/watchlist_consistency_report_latest.md
       """
       try:
           # Resolve project root
           current_file = Path(__file__).resolve()
           backend_root = str(current_file.parent.parent.parent)
           project_root = _resolve_project_root_from_backend_root(backend_root)
           
           # Build file path
           report_path = Path(project_root) / "docs" / "monitoring" / "watchlist_consistency_report_latest.md"
           
           if not report_path.exists():
               raise HTTPException(
                   status_code=404,
                   detail=f"Report not found at {report_path}. Run the watchlist_consistency workflow first."
               )
           
           # Read and return the file
           content = report_path.read_text(encoding='utf-8')
           
           return Response(
               content=content,
               media_type="text/markdown",
               headers={
                   "Content-Disposition": f'inline; filename="watchlist_consistency_report_latest.md"',
                   **{k: v for k, v in _NO_CACHE_HEADERS.items()}
               }
           )
       except HTTPException:
           raise
       except Exception as e:
           log.error(f"Error serving watchlist consistency report: {e}", exc_info=True)
           raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")
   ```

2. **Edit `nginx/dashboard.conf`:**
   
   Add this location block before the closing `}` of the server block (around line 118):
   
   ```nginx
   # Proxy /docs/monitoring/ requests to backend API
   # This allows direct access to markdown reports like:
   # /docs/monitoring/watchlist_consistency_report_latest.md
   location ^~ /docs/monitoring/ {
       # Rewrite /docs/monitoring/watchlist_consistency_report_latest.md 
       # to /api/monitoring/reports/watchlist-consistency/latest
       rewrite ^/docs/monitoring/watchlist_consistency_report_latest\.md$ /api/monitoring/reports/watchlist-consistency/latest break;
       
       # For other /docs/monitoring/ requests, proxy to backend
       # (backend can handle other report types if needed)
       proxy_pass http://localhost:8002;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       
       # Set proper headers for markdown content
       proxy_hide_header Content-Type;
       add_header Content-Type "text/markdown; charset=utf-8" always;
       add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
   }
   ```

3. **Reload services:**
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   # Restart your backend service
   ```

## Verification

After deployment, test the endpoint:

```bash
# Test the direct URL
curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md

# Test the API endpoint
curl -I https://dashboard.hilovivo.com/api/monitoring/reports/watchlist-consistency/latest

# Both should return 200 OK with Content-Type: text/markdown
```

## Troubleshooting

- **404 Error persists**: Check that the report file exists at `docs/monitoring/watchlist_consistency_report_latest.md` on the server
- **502 Bad Gateway**: Backend might not be running or the endpoint has an error - check backend logs
- **Nginx config error**: Run `sudo nginx -t` to see the exact error
- **Backend not restarting**: Check your backend service name with `sudo systemctl list-units | grep backend`





