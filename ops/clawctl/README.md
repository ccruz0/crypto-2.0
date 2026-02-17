# clawctl — approval runner for EC2 (read-only)

Claw proposes commands; you approve; SSH runs as `ubuntu` with the dedicated key. Nothing runs without typing `YES`.

**Triple containment:** denylist blocks dangerous patterns → allowlist permits only read-only diagnostics → you approve with `YES` → audit + log.

## One-time setup (you do this on your Mac / EC2)

1. **Create SSH key** (does not touch existing keys):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/claw_ro_ec2 -C "claw-readonly-ec2"
   ```

2. **Add public key to EC2** (`ubuntu` user):
   - `cat ~/.ssh/claw_ro_ec2.pub`
   - SSH to EC2, then: `mkdir -p ~/.ssh && chmod 700 ~/.ssh`
   - Append the public key to `~/.ssh/authorized_keys`, then `chmod 600 ~/.ssh/authorized_keys`

3. **Set EC2 host** in this repo:
   - Edit `clawctl.sh` and replace `YOUR_EC2_IP` with your EC2 IP (or hostname).

## Usage

```bash
./ops/clawctl/clawctl.sh "ps -eo ppid=,stat= | awk '\$2 ~ /^Z/ {print \$1}' | sort | uniq -c | sort -nr | head -20"
```

- **Denylist** blocks dangerous commands (exit 2). **Allowlist** permits only diagnostic commands (exit 3 if outside scope).
- Script shows the command and asks for `YES`.
- On `YES`, it SSHs to EC2, runs the command, and saves output under `ops/clawctl/logs/`.
- Requests and approved commands are stored under `requests/` and `approved/`. Approved runs are appended to `audit.md`.
- Each run is also appended as one JSON line to `logs/ec2_exec.jsonl` (ts, host, cmd, rc, duration_s, request, approved, log) for search, dashboards, and scripting. The script exits with the remote command’s exit code.

## Workflow with Claw

- You ask Claw: “Propose read-only diagnostics to …” (e.g. identify zombie parent PIDs and the systemd unit responsible).
- Claw outputs one line; you run: `./ops/clawctl/clawctl.sh "<paste>"`
- Claw never gets SSH; execution is only after your confirmation.

## Optional next steps

- Wire as an official OpenClaw tool.
- Structured JSON logging for analytics.
- Dry-run diff mode for docker/systemd.
- Auto-batching for long investigations.
