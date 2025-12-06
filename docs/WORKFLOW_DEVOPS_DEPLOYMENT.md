# ✅ Cursor Workflow AI – "DevOps Deployment Fix (Autonomous)"

**Workflow Name:** `DevOps Deployment Fix (Autonomous)`

**This is a Workflow AI Prompt for Cursor. Use this workflow for deployment, Docker, AWS, and infrastructure issues.**

---

## Workflow AI Prompt

This workflow enforces a fully autonomous DevOps and deployment fix cycle for the automated-trading-platform.

You MUST always work end-to-end, not just patch locally.

---

## GLOBAL RULES

- **NEVER ask the user questions.**
- **NEVER generate real orders on Crypto.com or any live exchange.**
- **ALWAYS diagnose root causes, not symptoms.**
- **ALWAYS validate the fix in the live environment.**
- **ALWAYS iterate until the deployment is healthy.**

---

## SCOPE OF THIS WORKFLOW

Whenever this workflow is invoked for deployment/infrastructure issues, you MUST:

### 1. Understand the Request

- Parse the deployment/infrastructure problem carefully.
- Identify affected components:
  - Docker containers (backend, frontend, db, gluetun, market-updater)
  - Docker Compose configuration
  - Dockerfiles (backend/Dockerfile, frontend/Dockerfile)
  - Nginx configuration (if applicable)
  - Environment variables (.env, .env.aws, .env.local)
  - AWS EC2 instance
  - Vercel deployment (frontend)
  - Health checks
  - Network connectivity

### 2. Inspect Infrastructure Files

- **Docker Compose:**
  - Read `docker-compose.yml` completely
  - Check service definitions (backend-aws, frontend-aws, db, gluetun)
  - Verify health checks are configured correctly
  - Check dependencies between services
  - Verify profiles (aws vs local)

- **Dockerfiles:**
  - Inspect `backend/Dockerfile` for build issues
  - Inspect `frontend/Dockerfile` for build issues
  - Check multi-stage builds
  - Verify health checks in Dockerfiles
  - Check user permissions (non-root users)

- **Environment Variables:**
  - Check `.env`, `.env.aws`, `.env.local` files
  - Verify required variables are set
  - Check for missing or incorrect values
  - Verify DATABASE_URL, API_BASE_URL, FRONTEND_URL

- **Nginx (if applicable):**
  - Check nginx configuration files
  - Verify proxy settings
  - Check SSL/TLS configuration
  - Verify upstream backend configuration

- **Next.js Configuration:**
  - Check `frontend/next.config.js` or `next.config.ts`
  - Verify output: 'standalone' for Docker
  - Check asset paths and public directory
  - Verify API rewrites/proxies

### 3. Diagnose the Issue

Common issues to check:

- **502/504 Gateway Errors:**
  - Backend not responding
  - Health check failing
  - Timeout issues
  - Container crash loops

- **Container Restart Issues:**
  - Check container logs for errors
  - Verify health checks are passing
  - Check resource limits (CPU/memory)
  - Verify dependencies are healthy

- **Build Failures:**
  - Docker build errors
  - Missing dependencies
  - Compilation errors
  - Asset bundling issues

- **Network Issues:**
  - VPN (gluetun) connectivity
  - Database connectivity
  - Backend-frontend communication
  - External API access

- **Vercel Deployment Issues:**
  - Build errors in Vercel logs
  - Environment variables missing
  - Next.js build failures
  - Asset loading issues

### 4. Fix the Root Cause

- **If Docker Compose issue:**
  - Fix service definitions
  - Correct health checks
  - Fix dependencies
  - Update environment variables

- **If Dockerfile issue:**
  - Fix build stages
  - Correct dependencies
  - Fix user permissions
  - Update health checks

- **If Environment Variable issue:**
  - Add missing variables
  - Correct incorrect values
  - Verify variable format

- **If Nginx issue:**
  - Fix proxy configuration
  - Correct upstream settings
  - Fix SSL/TLS

- **If Next.js issue:**
  - Fix next.config.js
  - Correct asset paths
  - Fix API rewrites
  - Verify standalone output

### 5. Local Validation (if applicable)

- **Test Docker Compose locally:**
  ```bash
  docker compose -f docker-compose.yml --profile local up --build -d
  ```

- **Check container health:**
  ```bash
  docker compose ps
  docker compose logs backend
  docker compose logs frontend
  ```

- **Test endpoints:**
  ```bash
  curl http://localhost:8002/ping_fast
  curl http://localhost:3000/
  ```

### 6. Deploy to AWS

- **SSH to AWS:**
  ```bash
  ssh hilovivo-aws
  ```

- **Pull latest code:**
  ```bash
  cd /home/ubuntu/automated-trading-platform
  git pull
  ```

- **Rebuild and restart:**
  ```bash
  docker compose --profile aws down
  docker compose --profile aws pull
  docker compose --profile aws up --build -d
  ```

- **Wait for services to be healthy:**
  ```bash
  docker compose --profile aws ps
  ```

- **Check logs:**
  ```bash
  docker compose --profile aws logs backend-aws --tail 200
  docker compose --profile aws logs frontend-aws --tail 200
  docker compose --profile aws logs db --tail 200
  ```

### 7. Verify Deployment Health

- **Check container status:**
  ```bash
  docker compose --profile aws ps
  ```
  All services should show "healthy" or "running"

- **Test backend health:**
  ```bash
  curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/health
  curl -s https://monitoring-ai-dashboard-nu.vercel.app/ping_fast
  ```

- **Test frontend:**
  - Open browser: `https://monitoring-ai-dashboard-nu.vercel.app/`
  - Check browser console for errors
  - Verify bundles load correctly
  - Check Network tab for failed requests

- **Check API endpoints:**
  ```bash
  curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/watchlist | head -20
  ```

### 8. Validate Frontend Deployment (Vercel)

- **If frontend is deployed on Vercel:**
  - Check Vercel deployment logs
  - Verify build succeeded
  - Check environment variables in Vercel dashboard
  - Verify domain configuration

- **Test frontend:**
  - Open production URL
  - Check for console errors
  - Verify API calls work
  - Check asset loading

### 9. Iterate Until Fixed

- **If deployment is not healthy:**
  - Analyze logs for errors
  - Fix the root cause
  - Rebuild and redeploy
  - Re-verify health
  - Repeat until all services are healthy

- **If frontend has errors:**
  - Check browser console
  - Fix code issues
  - Rebuild and redeploy
  - Re-verify in browser

### 10. Final Validation

- **All containers healthy:**
  - ✅ Backend container running and healthy
  - ✅ Frontend container running and healthy
  - ✅ Database container running and healthy
  - ✅ Gluetun container running and healthy (if applicable)

- **All endpoints accessible:**
  - ✅ Backend health endpoint responds
  - ✅ Frontend loads without errors
  - ✅ API endpoints return data
  - ✅ No 502/504 errors

- **Browser validation:**
  - ✅ Dashboard loads correctly
  - ✅ No console errors
  - ✅ Bundles load successfully
  - ✅ API calls work

### 11. Final Report

- What was the deployment issue?
- Which files were modified?
- What was the root cause?
- How was it fixed?
- Deployment validation results:
  - Container status
  - Health check results
  - Endpoint accessibility
  - Browser validation results

---

## Quick Reference Commands

### Local Docker Testing
```bash
cd /Users/carloscruz/automated-trading-platform
docker compose --profile local up --build -d
docker compose --profile local ps
docker compose --profile local logs backend
```

### AWS Deployment
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws down
docker compose --profile aws pull
docker compose --profile aws up --build -d
docker compose --profile aws ps
```

### Health Checks
```bash
# Backend
curl -s https://monitoring-ai-dashboard-nu.vercel.app/api/health
curl -s https://monitoring-ai-dashboard-nu.vercel.app/ping_fast

# Frontend
curl -s https://monitoring-ai-dashboard-nu.vercel.app/ | head -20
```

### Container Logs
```bash
# On AWS
docker compose --profile aws logs backend-aws --tail 500
docker compose --profile aws logs frontend-aws --tail 500
docker compose --profile aws logs db --tail 200
```

---

## Common Issues & Solutions

### Issue: Backend container keeps restarting
**Solution:**
- Check backend logs for errors
- Verify database connectivity
- Check environment variables
- Verify health check configuration

### Issue: 502 Bad Gateway
**Solution:**
- Check backend container is running
- Verify backend health check passes
- Check nginx/proxy configuration
- Verify port mappings

### Issue: Frontend build fails
**Solution:**
- Check Next.js configuration
- Verify node_modules are installed
- Check for TypeScript errors
- Verify environment variables

### Issue: Database connection fails
**Solution:**
- Verify DATABASE_URL is correct
- Check database container is healthy
- Verify network connectivity
- Check PostgreSQL logs

---

## Notes

- Always check logs first before making changes
- Verify health checks are configured correctly
- Test locally before deploying to AWS
- Always validate in the live environment
- Never deploy without verifying the fix works






