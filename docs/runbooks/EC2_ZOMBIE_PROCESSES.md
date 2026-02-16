# EC2 zombie processes – diagnose and mitigate

When many zombie processes share one parent PID, the parent is not calling `wait()`, so the kernel cannot reap them. Zombies don’t use CPU but consume PID slots and can lead to "cannot fork" if they keep growing.

**Run all commands on the EC2 instance** (e.g. SSH into the host). Replace `2226091` with the actual parent PID if different.

---

## 1) Identify the exact parent process

```bash
cd /home/ubuntu/automated-trading-platform

echo "== parent full cmdline =="
tr '\0' ' ' < /proc/2226091/cmdline; echo

echo "== parent exe path =="
readlink -f /proc/2226091/exe || true

echo "== parent status (name, ppid) =="
grep -E '^(Name|Pid|PPid|State|Uid|Gid):' /proc/2226091/status || true

echo "== systemd unit owning that PID (if any) =="
systemctl status --pid=2226091 --no-pager || true

echo "== cgroup (often shows the service name) =="
cat /proc/2226091/cgroup || true
```

---

## 2) Confirm zombies are children of that parent (sample)

```bash
cd /home/ubuntu/automated-trading-platform

echo "== children of parent (how many) =="
ps --ppid 2226091 -o pid= | wc -l

echo "== sample children (should show <defunct>) =="
ps --ppid 2226091 -o pid,ppid,stat,etime,cmd --sort=etime | head -n 30

echo "== what is the parent's parent =="
PARENT_PPID=$(grep '^PPid:' /proc/2226091/status | awk '{print $2}')
ps -p "$PARENT_PPID" -o pid,ppid,user,stat,etime,cmd --no-headers 2>/dev/null || true
```

---

## 3) Mitigation – restart the owning service

After `systemctl status --pid=2226091` shows the unit name, restart that unit.

If the parent is dhcpcd-related, try (one will usually exist):

```bash
cd /home/ubuntu/automated-trading-platform

sudo systemctl restart dhcpcd || true
sudo systemctl restart dhcpcd.service || true
sudo systemctl restart dhcpcd5 || true
```

Then re-check:

```bash
cd /home/ubuntu/automated-trading-platform
ps -eo stat | grep -c Z || true
```

Expected: zombie count drops to 0 or near 0.

---

## 4) If there is no systemd unit – restart the parent process only

Killing the parent usually causes zombies to be re-parented to PID 1 and reaped. Do this only if you're OK with that process being restarted by whatever launched it.

```bash
cd /home/ubuntu/automated-trading-platform

echo "== snapshot before kill =="
ps -p 2226091 -o pid,ppid,user,stat,etime,cmd

sudo kill -TERM 2226091
sleep 2
ps -p 2226091 -o pid,ppid,user,stat,etime,cmd || echo "parent exited"

echo "== zombie count after =="
ps -eo stat | grep -c Z || true
```

If TERM doesn't work, last resort:

```bash
cd /home/ubuntu/automated-trading-platform
sudo kill -KILL 2226091
ps -eo stat | grep -c Z || true
```

---

## 5) Root cause (after you have section 1 output)

With the output from section 1 (cmdline, exe, systemd unit/cgroup), you can pinpoint:

- Buggy long-running helper that spawns processes and never `wait()`s
- Wrapper script using `&` without proper `wait`
- Service with `Restart=always` accumulating defunct children after repeated failures
- Misbehaving network hook script (e.g. dhcpcd)

---

## Paste back (for diagnosis)

After running **1** and **2** on EC2, paste:

1. The full output of **section 1** (parent cmdline, exe, status, systemd unit, cgroup).
2. The full output of **section 2** (child count, sample children, parent’s parent).
3. Whether restarting the unit (section 3) dropped the zombie count to 0 (or near 0).

Then the exact fix path (e.g. fix the hook script, change service config, or add a cron reaper) can be decided.
