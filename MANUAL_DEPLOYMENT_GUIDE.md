# Manual Deployment Guide - All Tabs Fixes

## ✅ Code State Confirmed

All fixes are **already implemented and pushed**:

- **Frontend Submodule Commit**: `22d52ae`
- **Parent Repo Commit**: `ae17574`

### Code Verification ✅

**ExecutedOrdersTab.tsx:**
- ✅ Fetch on mount with `didFetchRef` guard
- ✅ Loading always resolves (finally block)
- ✅ Strict Mode safe

**OrdersTab.tsx:**
- ✅ No duplicate fetch (useOrders hook handles it)
- ✅ No infinite loading

**ExpectedTakeProfitTab.tsx:**
- ✅ Fetch on mount with `didFetchRef` guard
- ✅ Loading resolves
- ✅ Expected TP Details modal:
  - ✅ No placeholder text (0 matches found)
  - ✅ Summary metrics rendered (3 sections found)
  - ✅ Matched lots table rendered
  - ✅ Loading + error states implemented

---

## 🚀 Manual Deployment Instructions

**Prerequisites:**
- SSH access to AWS server (54.254.150.31)
- Docker and docker-compose installed on server
- Git access to pull latest changes

### Step-by-Step Deployment

#### Step 1: SSH into AWS Server
```bash
ssh ubuntu@54.254.150.31
```

#### Step 2: Navigate to Project Directory
```bash
cd /home/ubuntu/automated-trading-platform
```

#### Step 3: Handle Git Pull Blockers
```bash
# Create backup folder for untracked files
mkdir -p backup_markdown

# Move untracked .md files that might block git pull
find . -maxdepth 1 -name "*.md" -type f ! -path "./.git/*" -exec sh -c '
  if ! git ls-files --error-unmatch "$1" >/dev/null 2>&1; then
    echo "Moving untracked file: $1"
    mv "$1" backup_markdown/ 2>/dev/null || true
  fi
' _ {} \;
```

#### Step 4: Pull Latest Changes
```bash
git pull
```

**Expected Output:**
```
Updating ae17574..[new-commit]
Fast-forward
 frontend | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
```

#### Step 5: Update Git Submodules
```bash
git submodule sync --recursive
git submodule update --init --recursive
```

**Expected Output:**
```
Synchronizing submodule url for 'frontend'
Submodule path 'frontend': checked out '22d52ae'
```

#### Step 6: Rebuild and Restart Frontend Container
```bash
docker compose --profile aws up -d --build frontend-aws
```

**Expected Output:**
```
[+] Building [time] ...
[+] Running 2/2
 ✔ Container frontend-aws Started
```

#### Step 7: Wait for Frontend to be Ready
```bash
# Wait for Next.js to compile
sleep 20

# Check container status
docker compose --profile aws ps frontend-aws

# Check logs for "Ready" message
docker compose --profile aws logs --tail=50 frontend-aws | grep -i "ready\|compiled\|started"
```

**Expected Log Output:**
```
✓ Ready in [time]
```

#### Step 8: Verify Deployment
```bash
# Check container is running
docker compose --profile aws ps frontend-aws

# Should show: "Up [time] (healthy)" or similar
```

---

## ✅ Production Verification Checklist

After deployment, verify each tab in the live dashboard:

### A) Open Orders Tab

**Test Steps:**
1. Open dashboard in browser
2. Navigate to **Open Orders** tab
3. Wait 1-2 seconds
4. Observe result

**Expected:**
- ✅ Loads within 1-2 seconds
- ✅ Shows one of: table / "No open orders" / error message
- ❌ **MUST NOT**: Stay stuck on "Loading orders..."

**Network Check:**
- Open DevTools → Network tab
- Filter by: `api` or `dashboard`
- Look for: `GET /api/dashboard/state` or `/api/orders/open`
- Status: `200 OK`
- Response time: < 2 seconds

**Console Check:**
- Open DevTools → Console tab
- Should be: Clean (no errors)

**Result:** [ ] PASS / [ ] FAIL

---

### B) Executed Orders Tab

**Test Steps:**
1. Navigate to **Executed Orders** tab
2. Wait 1-2 seconds
3. Observe result

**Expected:**
- ✅ Never stuck on "Loading executed orders..."
- ✅ Shows one of: table / "No executed orders" / error message
- ✅ Loading resolves within 1-2 seconds

**Network Check:**
- Look for: `GET /api/orders/history?limit=100&offset=0&sync=true`
- Status: `200 OK`
- Response time: < 2 seconds
- Response includes: `orders` array

**Console Check:**
- Should be: Clean (no errors)
- May see: `🔄 Fetching executed orders...` and `✅ Loaded X executed orders`

**Result:** [ ] PASS / [ ] FAIL

---

### C) Expected Take Profit Tab

**Test Steps:**
1. Navigate to **Expected Take Profit** tab
2. Wait 1-2 seconds
3. Click **Refresh** button
4. Switch to another tab
5. Return to Expected TP tab
6. Observe result

**Expected:**
- ✅ Table loads correctly
- ✅ Refresh button works
- ✅ Tab switching works
- ✅ Loading resolves

**Network Check:**
- Look for: `GET /api/expected-take-profit/summary`
- Status: `200 OK`
- Response time: < 2 seconds
- Response includes: Array of summary items

**Console Check:**
- Should be: Clean (no errors)

**Result:** [ ] PASS / [ ] FAIL

---

### D) Expected TP – View Details Modal

**Test Steps:**
1. Navigate to **Expected Take Profit** tab
2. Click **"View Details"** on at least 3 different symbols
3. For each symbol, verify:

**Modal Opens:**
- [ ] Modal appears with symbol name
- [ ] No placeholder text visible
- [ ] Summary section visible

**Summary Section:**
- [ ] Net Qty displayed
- [ ] Position Value displayed
- [ ] Covered Qty displayed (green)
- [ ] Uncovered Qty displayed (orange)
- [ ] Expected Profit displayed (green/red)
- [ ] Current Price displayed (if available)

**Matched Lots Table:**
- [ ] Table visible with columns
- [ ] At least one row OR "No matched lots found"
- [ ] TP Status badges (color-coded)
- [ ] Expected Profit with percentage

**Modal Functionality:**
- [ ] Click X → modal closes
- [ ] Click outside → modal closes
- [ ] Switch tab → modal closes
- [ ] Return → can open again

**Network Check:**
- Look for: `GET /api/dashboard/expected-take-profit/{symbol}`
- Status: `200 OK`
- Response time: < 2 seconds
- Response includes: `matched_lots` array

**Console Check:**
- Should be: Clean (no errors)

**Result:** [ ] PASS / [ ] FAIL

---

## 🔍 DevTools Evidence Collection

### Network Tab Evidence

For each tab, capture:

1. **Screenshot or notes:**
   - Request URL
   - Status code
   - Response time
   - Response preview (first few lines)

**Template:**
```
Tab: [Open Orders / Executed Orders / Expected TP / Expected TP Details]
Endpoint: [URL]
Status: [200 / Other]
Response Time: [X seconds]
Response Preview: [First few lines of JSON]
```

### Console Tab Evidence

For each tab, capture:

1. **Screenshot or notes:**
   - Any errors (should be none)
   - Any warnings (should be none)

**Template:**
```
Tab: [Open Orders / Executed Orders / Expected TP / Expected TP Details]
Status: [Clean / Errors found]
Errors: [List if any]
Warnings: [List if any]
```

---

## 🔧 Backend Check (Only If Needed)

Only check backend if:
- Frontend request fails
- Response is missing expected fields
- Data appears incorrect

### Check Backend Logs
```bash
ssh ubuntu@54.254.150.31
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws logs -n 200 backend-aws | grep -i "orders\|expected-take-profit"
```

### Verify Endpoints Directly
```bash
# Open Orders
curl http://localhost:8002/api/dashboard/state | jq '.open_orders | length'

# Executed Orders
curl "http://localhost:8002/api/orders/history?limit=100&offset=0&sync=true" | jq '.orders | length'

# Expected TP Summary
curl http://localhost:8002/api/expected-take-profit/summary | jq 'length'

# Expected TP Details (replace SYMBOL)
curl "http://localhost:8002/api/dashboard/expected-take-profit/BTC_USDT" | jq '.matched_lots | length'
```

---

## 📊 Final Verification Report Template

After completing all verification, fill out this report:

### Deployment Status
- [ ] **Status**: DEPLOYED / BLOCKED (SSH)
- [ ] **Deployment Time**: [Timestamp]
- [ ] **Frontend Container**: [Running / Stopped]
- [ ] **Frontend Logs Show Ready**: [YES / NO]

### Per-Tab Status

**Open Orders:**
- [ ] **Status**: PASS / FAIL
- [ ] **What is visible**: [table / empty / error]
- [ ] **Loading resolves**: YES / NO
- [ ] **Network**: [endpoint, status, response time]
- [ ] **Console**: [clean / errors listed]

**Executed Orders:**
- [ ] **Status**: PASS / FAIL
- [ ] **What is visible**: [table / empty / error]
- [ ] **Never stuck loading**: YES / NO
- [ ] **Network**: [endpoint, status, response time]
- [ ] **Console**: [clean / errors listed]

**Expected Take Profit:**
- [ ] **Status**: PASS / FAIL
- [ ] **What is visible**: [table / empty / error]
- [ ] **Refresh works**: YES / NO
- [ ] **Tab switching works**: YES / NO
- [ ] **Network**: [endpoint, status, response time]
- [ ] **Console**: [clean / errors listed]

**Expected TP Details Modal:**
- [ ] **Status**: PASS / FAIL
- [ ] **Placeholder text**: GONE / Still present
- [ ] **Summary section**: Visible / Missing
- [ ] **Matched lots table**: Visible / Missing
- [ ] **Modal closes**: Works / Broken
- [ ] **Network**: [endpoint, status, response time]
- [ ] **Console**: [clean / errors listed]

### Network Proof Summary

**Open Orders:**
- Endpoint: [URL]
- Status: [200 / Other]
- Response time: [X seconds]

**Executed Orders:**
- Endpoint: [URL]
- Status: [200 / Other]
- Response time: [X seconds]

**Expected Take Profit:**
- Endpoint: [URL]
- Status: [200 / Other]
- Response time: [X seconds]

**Expected TP Details:**
- Endpoint: [URL]
- Status: [200 / Other]
- Response time: [X seconds]
- Response includes matched_lots: [YES / NO]

### Console Status
- **Overall**: [Clean / Issues found]
- **Errors**: [List if any]
- **Warnings**: [List if any]

### Final Verdict
- [ ] **SAFE TO SHIP** - All tabs verified and working
- [ ] **BLOCKED** - Issues found, deployment blocked

**Verdict Details:**
- [ ] All tabs tested: YES / NO
- [ ] All tabs load within 1-2 seconds: YES / NO
- [ ] No infinite loading observed: YES / NO
- [ ] Expected TP Details modal works: YES / NO
- [ ] No console errors: YES / NO
- [ ] All network requests succeed: YES / NO

---

## 🚨 Troubleshooting

### Issue: Deployment fails at git pull

**Solution:**
- Check for untracked files blocking pull
- Move them to backup_markdown folder
- Retry git pull

### Issue: Frontend container doesn't start

**Solution:**
- Check docker-compose logs: `docker compose --profile aws logs frontend-aws`
- Verify submodules updated: `git submodule status`
- Rebuild: `docker compose --profile aws build --no-cache frontend-aws`

### Issue: Tab still shows infinite loading

**Solution:**
- Hard refresh browser: `Cmd+Shift+R` / `Ctrl+Shift+R`
- Check console for errors
- Check network tab for hanging requests
- Verify fix deployed: `docker exec <container> grep -A 5 "didFetchRef" /app/src/app/components/tabs/ExecutedOrdersTab.tsx`

---

**Status**: ✅ Code verified. Ready for manual deployment.




