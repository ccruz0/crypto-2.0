# Frontend Update Process - Quick Reference

## Why Changes Don't Appear Immediately

The frontend uses a **production Docker build** without mounted volumes. This means:
- Code changes require a **full Docker image rebuild**
- The build process takes ~5 minutes
- Browser cache can also prevent seeing updates

## Quick Update Process

### Option 1: Use the Update Script (Recommended)
```bash
./deploy_frontend_update.sh
```

This script automatically:
1. ✅ Copies updated files to AWS
2. ✅ Rebuilds the Docker image
3. ✅ Restarts the container
4. ✅ Verifies health status

### Option 2: Manual Update
```bash
# 1. Copy files
scp -i ~/.ssh/id_rsa frontend/src/app/page.tsx ubuntu@175.41.189.249:~/automated-trading-platform/frontend/src/app/page.tsx

# 2. Rebuild and restart
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose -f docker-compose.yml build frontend-aws && docker compose -f docker-compose.yml up -d frontend-aws'
```

## After Deployment

### 1. Clear Browser Cache
Users must hard refresh:
- **Windows/Linux**: `Ctrl + Shift + R`
- **Mac**: `Cmd + Shift + R`

### 2. Verify Deployment
Check that the code is in the container:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'grep -n "Minimum Price Change" ~/automated-trading-platform/frontend/src/app/page.tsx'
```

### 3. Check Container Status
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker compose -f docker-compose.yml ps frontend-aws'
```

## Prevention Checklist

Before making frontend changes:
- [ ] Test changes locally first (`npm run dev`)
- [ ] Verify no syntax errors (`npm run build`)
- [ ] Use the update script for deployment
- [ ] Always rebuild after code changes
- [ ] Clear browser cache after deployment
- [ ] Verify changes appear in the UI

## Troubleshooting

### Changes still not appearing?

1. **Verify code is on server:**
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'grep "your change" ~/automated-trading-platform/frontend/src/app/page.tsx'
   ```

2. **Check if rebuild is needed:**
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose -f docker-compose.yml build frontend-aws'
   ```

3. **Verify container is running:**
   ```bash
   ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker compose -f docker-compose.yml ps frontend-aws'
   ```

4. **Check build logs for errors:**
   ```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose -f docker-compose.yml build frontend-aws 2>&1 | grep -i error'
   ```

5. **Clear browser cache completely:**
   - Open DevTools (F12)
   - Right-click refresh button
   - Select "Empty Cache and Hard Reload"

## Development Mode (Faster Iterations)

For faster development, you can temporarily use development mode with hot reload:

**⚠️ WARNING: Only for development, not production!**

Modify `docker-compose.yml` temporarily:
```yaml
frontend-aws:
  # ... existing config ...
  volumes:
    - ./frontend:/app
    - /app/node_modules
    - /app/.next
  command: npm run dev
  # Remove: read_only: true
```

Then changes will appear immediately without rebuild. **Remember to revert before production!**

