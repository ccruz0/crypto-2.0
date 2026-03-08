#!/usr/bin/env bash
# Configure Docker daemon-level log rotation.
# Run once on the EC2 instance (requires sudo).
# After running, restart Docker: sudo systemctl restart docker
set -euo pipefail

DAEMON_JSON="/etc/docker/daemon.json"

if [ -f "$DAEMON_JSON" ]; then
  echo "Existing $DAEMON_JSON found — merging log config..."
  EXISTING=$(cat "$DAEMON_JSON")
else
  EXISTING="{}"
fi

MERGED=$(echo "$EXISTING" | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
cfg['log-driver'] = 'json-file'
cfg['log-opts'] = {'max-size': '20m', 'max-file': '3'}
json.dump(cfg, sys.stdout, indent=2)
")

echo "$MERGED" | sudo tee "$DAEMON_JSON" > /dev/null
echo "Wrote $DAEMON_JSON:"
cat "$DAEMON_JSON"

echo ""
echo "Restarting Docker daemon to apply..."
sudo systemctl restart docker
sleep 5

echo "Docker log rotation configured: max-size=20m, max-file=3"
echo "Each container log is capped at ~60MB total."
