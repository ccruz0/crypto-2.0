# EC2 Automatic Recovery for PROD

**Purpose:** Trigger AWS-level automatic recovery of the PROD EC2 instance when EC2 status checks fail, without adding application-layer watchdogs.

**Instance:** i-087953603011543c5 (atp-rebuild-2026)  
**Region:** ap-southeast-1

---

## Why This Protection Is Needed

During the **2026-03-11 PROD incident**:

- The EC2 instance remained "running" in the console.
- EC2 reachability check failed; SSM went ConnectionLost; dashboard.hilovivo.com became unreachable.
- A manual reboot fixed the issue; console logs showed EXT4 filesystem recovery and orphan inode cleanup.
- Once the instance recovered, the ATP stack (nginx, docker, backend) worked normally with no app or config changes.

**Conclusion:** The failure was **below the ATP application layer** (instance/OS or hardware). The correct first protection is **AWS-level automatic recovery** when EC2 status checks fail, not another application watchdog.

See **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md** for the full incident summary, confirmed facts, and recommendations.

---

## How the CloudWatch Alarm Works

1. **Metric:** `StatusCheckFailed_Instance` (namespace `AWS/EC2`), dimension `InstanceId = i-087953603011543c5`.  
   This metric is 1 when the **instance status check** fails (guest/OS unreachable). Our incident showed instance-level failure (EXT4 recovery, SSM/API unreachable). AWS also documents recovery for `StatusCheckFailed_System`; we use Instance to align with the observed failure mode.

2. **Alarm condition:** The metric is **>= 1** for **2 consecutive evaluation periods** of **60 seconds** (i.e. status check failed for at least 2 minutes). This avoids single glitch false positives.

3. **Alarm action:** `arn:aws:automate:ap-southeast-1:ec2:recover`.  
   When the alarm enters `ALARM` state, AWS runs the **EC2 instance recovery** action: the instance is migrated to a new host (equivalent to a reboot from the guest’s perspective), which restores reachability when the failure is due to a bad host or guest state.

4. **Result:** No manual reboot or SSH/SSM required; AWS performs recovery automatically when the status check fails, reducing downtime and operator load.

---

## Deploying the Alarm Safely

1. **Prerequisites**
   - AWS CLI configured with credentials that have:
     - `cloudwatch:PutMetricAlarm`
     - `cloudwatch:DescribeAlarms`
     - (Optional) `cloudwatch:DeleteAlarms` if you need to remove it later)
   - The PROD instance must support [EC2 instance recovery](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html) (e.g. t3.small is supported).

2. **Deploy**
   ```bash
   cd infra/aws/ec2_auto_recovery_prod
   ./setup_auto_recovery.sh
   ```

3. **Verify**
   - The script prints confirmation and the alarm ARN.
   - In AWS Console: **CloudWatch → Alarms** → find the alarm named for PROD instance recovery.
   - Optionally: **EC2 → Instances → atp-rebuild-2026 → Status checks** to see current state.

4. **Optional: add SNS notification**
   - To get notified when recovery is triggered, create an SNS topic, subscribe your email (or other endpoint), and add that topic ARN to `AlarmActions` in the script (or via Console by editing the alarm).

---

## What Is Not Changed

- No ATP health scripts, docker configs, nginx configs, backend code, or systemd timers are modified. This is an **infrastructure-only** addition.
