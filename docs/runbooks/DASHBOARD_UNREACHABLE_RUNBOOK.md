# Dashboard & SSH unreachable – runbook

When **dashboard.hilovivo.com** times out (ERR_TIMED_OUT) and **EC2 Instance Connect** fails with "Error establishing SSH connection", use this runbook.

## Quick checks (AWS Console)

1. **EC2 → Instances**  
   - Instance **i-087953603011543c5**  
   - **State**: should be **Running**.  
   - If **Stopped**, start it and wait 2–3 minutes.

2. **Instance status checks**  
   - Select the instance → **Status** tab.  
   - **System status** and **Instance status** should be **Passed**.  
   - If **Impaired** or **Initializing**, wait or reboot from the console.

3. **Public IP**  
   - In the instance list, note **Public IPv4 address** (e.g. **52.220.32.147**).  
   - After a **stop/start** the IP changes unless you use an **Elastic IP**.  
   - If the IP changed, update DNS for **dashboard.hilovivo.com** to point to the new IP, or attach an Elastic IP to this instance and point DNS to it.

## What was verified (automated)

- **Instance state**: Running  
- **Public IP**: 52.220.32.147  
- **DNS**: dashboard.hilovivo.com → 52.220.32.147  
- **Security group (sg-07f5b0221b7e69efe)**:
  - Port **22** (SSH): 0.0.0.0/0
  - Port **80**: 0.0.0.0/0
  - Port **443**: 0.0.0.0/0
- **VPC**: Subnet is public (route to IGW), NACL allows traffic.

So firewall and routing are open; the problem is likely **reachability** or **instance health**.

## What to try

### 1. Try from another network

- Use **mobile hotspot** or another Wi‑Fi.
- In a browser: `http://52.220.32.147` and `https://dashboard.hilovivo.com`.
- If it works from hotspot but not from home/office, the issue is **your network** (firewall, ISP, or corporate proxy).

### 2. Reboot the instance (no IP change if no Elastic IP)

- EC2 → Instances → select **i-087953603011543c5**.
- **Instance state** → **Reboot instance**.
- Wait 3–5 minutes, then try the dashboard and EC2 Instance Connect again.

### 3. Attach an Elastic IP (recommended for production)

- So the public IP does not change after stop/start:
  - EC2 → **Elastic IPs** → **Allocate Elastic IP address**.
  - **Associate** it with instance **i-087953603011543c5**.
- Point **dashboard.hilovivo.com** to this Elastic IP in your DNS.
- Then you can stop/start the instance without losing the same public IP.

### 4. Get a shell when Instance Connect works again

Once SSH or Instance Connect works:

```bash
# Restart services
sudo systemctl restart nginx
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws up -d
```

### 5. If Instance Connect still fails after reboot

- Try again in a few minutes (instance or agent may still be starting).
- Use **Session Manager** if the instance has the right IAM role and SSM agent:
  - EC2 → Instances → select instance → **Connect** → **Session Manager** tab → **Connect**.

## Summary

- **Dashboard timeout** and **SSH/Instance Connect failure** with **instance Running** and **open security group** usually mean:
  - Your network cannot reach the instance, or
  - Instance/OS is slow or stuck (reboot often helps), or
  - DNS points to an old IP after a stop/start (fix DNS or use Elastic IP).

Run the **Quick checks** first, then **Reboot** and **try from another network**. Use the **Elastic IP** step so future stop/start doesn’t break DNS.
