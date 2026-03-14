# PROD access when SSM is Offline and Instance Connect fails

When **atp-rebuild-2026** (i-087953603011543c5) has SSM **Offline**, reboot didn’t fix it, and **EC2 Instance Connect** shows “Error establishing SSH connection”, common causes are:

- **Disk full** — the root filesystem has no free space, so the SSM agent and/or sshd can’t write logs or start properly.
- **sshd or SSM agent not running** — services stopped or failed to start after reboot.

### Why does this keep happening?

SSM **Offline** / **ConnectionLost** and **instance reachability check failed** often recur for the same reasons:

| Cause | What happens | How to prevent / fix |
|-------|------------------------|----------------------|
| **Disk full** | Root volume fills (Docker, logs, journal). SSM agent and/or sshd can't write logs and crash. After reboot they fail again. | Free space from Serial Console (§3a). Add log rotation, periodic `docker system prune`, or **increase EBS** and grow FS. See [PROD_DISK_RESIZE.md](../runbooks/PROD_DISK_RESIZE.md). |
| **No outbound HTTPS** | SSM agent must reach AWS endpoints on 443. Blocked egress → agent never registers. | Ensure SG/NACL allow 443 to SSM endpoints (or use VPC endpoints). |
| **SSM agent not running** | Agent crashed or was stopped and doesn't restart. | From Serial Console: `sudo systemctl start amazon-ssm-agent` and `enable` it. |
| **Instance role** | Instance has no role or role lacks SSM permissions. | Attach `EC2_SSM_Role` (or role with `AmazonSSMManagedInstanceCore`). |
| **Reachability check** | EC2 status check fails (hypervisor/OS). SSM can still work if agent + network are OK. | Reboot; if it persists, use Serial Console to check disk and services. |

**Most common recurring cause:** **disk full**. Logs and Docker fill the root volume; after reboot the agent starts then crashes again. Fix by freeing space (and resizing EBS if needed) and reducing log growth.

---

The only way in without SSH/SSM is the **EC2 Serial Console**. Once in, check disk first; if it’s full, free space (or resize EBS) before starting services.

---

## 1. One-time: allow Serial Console (account level)

1. In **AWS Console** go to **EC2** → **Settings** (left sidebar, bottom).
2. Under **EC2 Serial Console**, choose **Enable**.
3. (Optional) Restrict access with an IAM policy; by default it can be enabled for the account.

If you don’t see “Settings” or “EC2 Serial Console”, your region/account may use a different path: search the console for “Serial Console” or see [AWS docs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-serial-console.html).

---

## 2. Connect via Serial Console

1. **EC2** → **Instances** → select **atp-rebuild-2026**.
2. **Connect** → open the **EC2 serial console** tab.
3. Click **Connect**. A terminal session opens (no SSH, no SSM).

You may need to press **Enter** once to get a login prompt.

---

## 3. Log in, check disk, then start SSH + SSM

- Log in as **ubuntu** (password if you set one; otherwise use the **Send serial console SSH public key** flow from the Serial Console UI so you can use key-based login).

**3a. Check if disk is full (do this first)**

```bash
df -h /
```

If **Use%** is 100% or **Avail** is 0 (or very small), the disk is full. Free space before starting services:

```bash
# Quick cleanup (from Serial Console)
sudo journalctl --vacuum-time=2d
sudo apt-get clean
docker system prune -a -f 2>/dev/null || true
df -h /
```

If that’s not enough, **increase the EBS volume** then grow the filesystem (you can run `growpart` and `resize2fs` from Serial Console after resizing the volume in the AWS Console). Full steps: **[../runbooks/PROD_DISK_RESIZE.md](../runbooks/PROD_DISK_RESIZE.md)**.

**3b. Start SSH and SSM**

Once you have some free space (or if disk wasn’t full), run:

```bash
sudo systemctl start ssh
sudo systemctl enable ssh
sudo systemctl start amazon-ssm-agent 2>/dev/null || sudo systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null
sudo systemctl enable amazon-ssm-agent 2>/dev/null || true
```

Wait 1–2 minutes. Then try **Session Manager** or **EC2 Instance Connect** again; they should work.

---

## 4. Fix OpenClaw proxy (once you have a shell)

From Session Manager or Instance Connect (or Serial Console if you prefer), run:

```bash
LAB=172.31.3.214
PORT=8080
PP="proxy_pass http://${LAB}:${PORT}/;"
for f in /etc/nginx/sites-enabled/*; do
  [ -f "$f" ] || continue
  grep -q openclaw "$f" 2>/dev/null || continue
  sudo sed -i \
    -e "s|proxy_pass http://52.77.216.100:8080/;|$PP|g" \
    -e "s|proxy_pass http://52.77.216.100:8081/;|$PP|g" \
    -e "s|proxy_pass http://${LAB}:8081/;|$PP|g" \
    "$f" 2>/dev/null || true
done
sudo nginx -t && sudo systemctl reload nginx
```

Then test: https://dashboard.hilovivo.com/openclaw/

---

## 5. Optional: ensure Instance Connect can reach port 22

If the **browser** Instance Connect still fails after sshd is running, ensure the **EC2 Instance Connect** CIDR for your region is allowed on port 22. From your Mac (AWS CLI configured):

```bash
./scripts/aws/open_prod_access.sh
```

That script adds the official EC2 Instance Connect range for ap-southeast-1 to the PROD security group if it’s missing. Your PROD SG may already allow 0.0.0.0/0 on 22; this just makes the Instance Connect range explicit.

---

**Summary:** Enable EC2 Serial Console → Connect to PROD via Serial Console → **check disk (`df -h /`)** and free space if full → start `ssh` and `amazon-ssm-agent` → use Session Manager or Instance Connect for the nginx/OpenClaw fix.
