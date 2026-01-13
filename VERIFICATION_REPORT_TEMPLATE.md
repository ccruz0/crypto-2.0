# Outbound IP & Access Verification Report

## A) Command Execution Location Proof

### Mac Terminal Results:
- **Mac Public IP**: `<FILL_IN>`
- **docker compose --profile aws ps on Mac**: 
  - Result: `<FILL_IN>`
  - Explanation: Running `docker compose --profile aws ps` on Mac shows local containers (if any) or errors. This proves commands are running on Mac, not EC2. To access EC2 containers, we must use AWS SSM Session Manager.

---

## B) EC2 Outbound IP (Source of Truth)

### EC2 Host Outbound IP:
- **IP Address**: `<FILL_IN>`
- **Command**: `curl -s https://api.ipify.org` (run on EC2 host)

### Backend Container Outbound IP:
- **IP Address**: `<FILL_IN>`
- **Command**: `docker compose --profile aws exec -T backend-aws python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())"` (run on EC2 host)

### Comparison:
- **Host IP == Container IP**: `<YES/NO>`
- **Conclusion**: 
  - ✅ If MATCH: Backend uses EC2's public IP for outbound (Crypto.com whitelist should use this IP)
  - ⚠️ If MISMATCH: Backend may be routing through VPN/proxy (investigate further)

---

## C) Backend Health Verification

### Localhost Health Check (on EC2):
- **Command**: `curl -m 5 -v http://localhost:8002/api/health`
- **Status Code**: `<FILL_IN>`
- **Response**: `<FILL_IN>`
- **Container Status**: 
  ```
  <FILL_IN - output of docker compose --profile aws ps>
  ```

### External Health Check (from Mac):
- **Command**: `curl -m 5 -v http://<EC2_PUBLIC_IP>:8002/api/health`
- **Status Code**: `<FILL_IN>`
- **Response**: `<FILL_IN>`
- **Before Security Group Fix**: `<TIMEOUT/CONNECTION_REFUSED/etc>`
- **After Security Group Fix**: `<200 OK/etc>`

---

## D) Security Group Configuration

### Current Inbound Rules:
```
<FILL_IN - list current rules>
```

### Changes Made:
1. **Port 8002 (Backend API)**:
   - **Action**: `<ADDED/MODIFIED/NO_CHANGE>`
   - **Source**: `<MY_IP>/32`
   - **Protocol**: TCP
   - **Rule ID**: `<FILL_IN if modified>`

2. **Port 3000 (Frontend)**:
   - **Action**: `<ADDED/MODIFIED/NO_CHANGE>`
   - **Source**: `<MY_IP>/32`
   - **Protocol**: TCP
   - **Rule ID**: `<FILL_IN if modified>`

### Security Group Details:
- **Security Group ID**: `<FILL_IN>`
- **Region**: `ap-southeast-1`
- **Instance ID**: `i-08726dc37133b2454`

---

## E) Summary & Verification

### Outbound IP Summary:
- **Mac Public IP**: `<FILL_IN>` (for Security Group rules)
- **EC2 Host Outbound IP**: `<FILL_IN>` (used for Crypto.com whitelist)
- **Backend Container Outbound IP**: `<FILL_IN>`
- **IPs Match**: `<YES/NO>`
- **Crypto.com Whitelist IP**: `<FILL_IN>` (should be EC2 host IP)

### Access Status:
- **Localhost Health**: `<HEALTHY/UNHEALTHY>`
- **External Health (Before Fix)**: `<ACCESSIBLE/BLOCKED>`
- **External Health (After Fix)**: `<ACCESSIBLE/BLOCKED>`

### Remaining Blockers:
- `<NONE or list any issues>`

### Recommendations:
1. ✅ Outbound IP confirmed: Use `<EC2_HOST_IP>` for Crypto.com whitelist
2. ✅ Security Group configured: Ports 8002 and 3000 restricted to `<MY_IP>/32`
3. ✅ External access working: Backend health endpoint accessible from Mac
4. ⚠️ Any remaining issues: `<FILL_IN>`

---

## Commands Reference

### On EC2 (via AWS SSM Session Manager):
```bash
# Get host IP
curl -s https://api.ipify.org

# Get container IP
cd ~/automated-trading-platform
docker compose --profile aws exec -T backend-aws python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())"

# Check health
curl -m 5 -v http://localhost:8002/api/health

# Check containers
docker compose --profile aws ps
```

### On Mac:
```bash
# Get Mac IP
curl -s https://api.ipify.org

# Test external access
curl -m 5 -v http://<EC2_PUBLIC_IP>:8002/api/health

# Check Security Group (requires AWS CLI)
./check_security_group.sh i-08726dc37133b2454 <MY_IP>
```



