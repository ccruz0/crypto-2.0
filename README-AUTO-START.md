# Auto-Start Configuration

This configuration ensures that your Docker services start automatically when your Mac boots up and verifies they are running every hour.

## Files Created

1. **`scripts/check-and-start-services.sh`**: Script that checks if services are running and starts them if needed
2. **`com.automated-trading-platform.start.plist`**: LaunchAgent configuration file

## Installation

1. **Copy the LaunchAgent to your user's LaunchAgents directory:**
   ```bash
   cp com.automated-trading-platform.start.plist ~/Library/LaunchAgents/
   ```

2. **Load the LaunchAgent:**
   ```bash
   launchctl load ~/Library/LaunchAgents/com.automated-trading-platform.start.plist
   ```

3. **Verify it's loaded:**
   ```bash
   launchctl list | grep automated-trading-platform
   ```
   You should see `com.automated-trading-platform.start` in the list.

## How It Works

- **On Startup**: The LaunchAgent runs the script immediately when your Mac starts
- **Every Hour**: The LaunchAgent automatically runs the script every hour (3600 seconds) to verify services are running
- **Health Checks**: The script checks:
  - If Docker is running (starts it if not)
  - If all 3 services (frontend, backend, db) are running
  - If services respond to HTTP requests

## Monitoring

**View logs:**
```bash
tail -f ~/Library/Logs/automated-trading-platform/services.log
```

**View errors:**
```bash
tail -f ~/Library/Logs/automated-trading-platform/start.error.log
```

**Check status:**
```bash
launchctl list | grep automated-trading-platform
docker compose ps
```

## Manual Control

**Stop the auto-start:**
```bash
launchctl unload ~/Library/LaunchAgents/com.automated-trading-platform.start.plist
```

**Start it again:**
```bash
launchctl load ~/Library/LaunchAgents/com.automated-trading-platform.start.plist
```

**Run the check script manually:**
```bash
./scripts/check-and-start-services.sh
```

## Troubleshooting

If services don't start automatically:

1. Check Docker is installed and running:
   ```bash
   docker info
   ```

2. Check the logs:
   ```bash
   tail -50 ~/Library/Logs/automated-trading-platform/services.log
   ```

3. Verify the script has execute permissions:
   ```bash
   chmod +x scripts/check-and-start-services.sh
   ```

4. Test the script manually:
   ```bash
   ./scripts/check-and-start-services.sh
   ```
