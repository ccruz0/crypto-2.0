# Start OpenClaw on LAB from AWS Console (504 fix)

**When:** You still get **504** on https://dashboard.hilovivo.com/openclaw/ and SSM to LAB is ConnectionLost.

**Why:** PROD nginx must proxy to the port OpenClaw listens on LAB (compose default **8080**). If OpenClaw is not running on LAB, you get 504/502. LAB's security group has **port 22 open** so you can connect via EC2 Instance Connect in the browser.

---

## Do this (2 minutes)

1. **AWS Console** → **EC2** → **Instances**.
2. Select **LAB** (`atp-lab-ssm-clean`, ID `i-0d82c172235770a0d`).
3. Click **Connect** → **EC2 Instance Connect** → **Connect** (browser tab opens).
4. In the terminal, paste and run:

```bash
cd /home/ubuntu/automated-trading-platform && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

5. Wait for “OpenClaw already running” or “Started and enabled openclaw.service”.
6. Open **https://dashboard.hilovivo.com/openclaw/** — you should get **401** (Basic Auth), not 504.

---

## If the repo or script is missing on LAB

```bash
cd /home/ubuntu
git clone https://github.com/ccruz0/automated-trading-platform.git 2>/dev/null || (cd automated-trading-platform && git pull)
cd automated-trading-platform && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

---

## One-liner (copy-paste)

```bash
cd /home/ubuntu/automated-trading-platform && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh
```
