# Deploy TP/SL Value Fix to Production

## Status
✅ **Code changes complete and verified locally**
- Headers updated to "TP Value" and "SL Value"
- Values calculated as total USD (quantity × price)
- Backend API verified to calculate correctly

❌ **Not yet deployed to production server**

## Deployment Steps

### Option 1: Automated Deployment (when SSH is available)

```bash
cd /Users/carloscruz/automated-trading-platform
./deploy_frontend_tp_sl_fix.sh
```

### Option 2: Manual Deployment on Server

SSH into the AWS server and run:

```bash
# 1. Navigate to project directory
cd /home/ubuntu/automated-trading-platform

# 2. Pull latest code (if using git)
git pull origin main  # or your branch name

# 3. Rebuild Docker image with latest code
docker-compose build --no-cache frontend-aws

# 4. Restart container
docker-compose stop frontend-aws
docker-compose rm -f frontend-aws
docker-compose up -d frontend-aws

# 5. Verify container is running
docker ps --filter "name=frontend-aws"
docker logs automated-trading-platform-frontend-aws-1 --tail 20
```

### Option 3: Copy Files and Rebuild

If you need to copy files manually:

```bash
# From local machine
rsync -avz --exclude 'node_modules' --exclude '.next' \
  frontend/ ubuntu@54.254.150.31:/home/ubuntu/automated-trading-platform/frontend/

# Then on server, rebuild:
cd /home/ubuntu/automated-trading-platform
docker-compose build --no-cache frontend-aws
docker-compose restart frontend-aws
```

## Verification After Deployment

1. Go to `https://dashboard.hilovivo.com`
2. Hard refresh: `Cmd + Shift + R` (Mac) or `Ctrl + Shift + R` (Windows/Linux)
3. Check:
   - ✅ Headers show "TP Value" and "SL Value" (not "TP" and "SL")
   - ✅ Values are total USD amounts (e.g., $1,234.56), not per-coin prices
   - ✅ Tooltips say "Take Profit value: $X (value to be received when TP orders are executed)"

## What Changed

### Headers
- **Before:** "TP" and "SL"
- **After:** "TP Value" and "SL Value"

### Values
- **Before:** Per-coin prices (e.g., $0.169300 for ALGO)
- **After:** Total USD values from orders (quantity × price)

### Code Locations
- Headers: `frontend/src/app/page.tsx` lines 6396-6397
- Display logic: `frontend/src/app/page.tsx` lines 6823-6844 and 7091-7110
- Calculation: `frontend/src/app/page.tsx` lines 6569-6626 (getOpenOrdersInfo function)

## Troubleshooting

If changes don't appear after deployment:

1. **Clear browser cache completely:**
   - Chrome: Settings → Privacy → Clear browsing data → Cached images and files
   - Or use Incognito/Private window

2. **Check container logs:**
   ```bash
   docker logs automated-trading-platform-frontend-aws-1 --tail 50
   ```

3. **Verify build included changes:**
   ```bash
   docker exec automated-trading-platform-frontend-aws-1 sh -c "grep 'TP Value' /app/.next/static/chunks/*.js 2>/dev/null | head -1"
   ```

4. **Restart nginx (if needed):**
   ```bash
   sudo systemctl restart nginx
   ```

