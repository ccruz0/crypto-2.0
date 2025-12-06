# Health Monitoring System

This document describes the health monitoring system for the Automated Trading Platform.

## Overview

The health monitoring system automatically checks the status of critical services (Docker containers and HTTP endpoints) and sends Telegram notifications when issues are detected. It also attempts automatic recovery by restarting failed services.

## Components

### 1. Health Monitor Script (`infra/monitor_health.py`)

The main monitoring script that:
- Checks Docker container status for critical services (`backend-aws`, `frontend-aws`, `db`, `gluetun`)
- Performs HTTP health checks on backend (`http://127.0.0.1:8002/health`) and frontend (`http://127.0.0.1:3000`)
- Sends Telegram alerts when issues are detected
- Attempts automatic recovery by restarting failed services
- Sends follow-up notifications with recovery results

### 2. Telegram Helper (`infra/telegram_helper.py`)

A lightweight helper module that reuses the same Telegram configuration (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) as the main application to send notifications.

### 3. Cron Installation Script (`infra/install_health_cron.sh`)

A helper script to install the health monitor as a cron job that runs every 5 minutes.

## Installation

### Prerequisites

1. Ensure Telegram environment variables are set:
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

   Or add them to your `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

2. Ensure you have Docker Compose installed and the project is set up at `/home/ubuntu/automated-trading-platform`

### Install Cron Job

Run the installation script:

```bash
cd /home/ubuntu/automated-trading-platform
bash infra/install_health_cron.sh
```

This will:
- Make the monitor script executable
- Create the log file at `/var/log/atp_health_monitor.log`
- Add a cron job that runs every 5 minutes

### Manual Installation (Alternative)

If you prefer to install manually:

1. Make the script executable:
   ```bash
   chmod +x infra/monitor_health.py
   ```

2. Create log file:
   ```bash
   sudo touch /var/log/atp_health_monitor.log
   sudo chmod 666 /var/log/atp_health_monitor.log
   ```

3. Add to crontab:
   ```bash
   crontab -e
   ```

   Add this line:
   ```
   */5 * * * * cd /home/ubuntu/automated-trading-platform && /usr/bin/python3 infra/monitor_health.py >> /var/log/atp_health_monitor.log 2>&1
   ```

   **Important:** Always include `cd /home/ubuntu/automated-trading-platform` before running the script to ensure Docker Compose commands work correctly.

## Manual Testing

To test the monitor script manually:

```bash
cd /home/ubuntu/automated-trading-platform
/usr/bin/python3 infra/monitor_health.py
```

The script will:
- Check all services
- If issues are found, send Telegram alerts
- Attempt recovery
- Send follow-up notifications

## Monitoring What Gets Checked

### Docker Containers

The monitor checks these critical services:
- `backend-aws`: Backend API service
- `frontend-aws`: Frontend web application
- `db`: PostgreSQL database
- `gluetun`: VPN container (AWS profile only)

### HTTP Endpoints

- **Backend**: `http://127.0.0.1:8002/health` (must return 200 OK)
- **Frontend**: `http://127.0.0.1:3000` (must return 200 OK)

## Telegram Notifications

### Initial Alert

When issues are detected, you'll receive a message like:

```
⚠️ APP DOWN

🕐 Timestamp: 2025-11-10 10:30:00 UTC
🌐 Entorno: AWS EC2 automated-trading-platform

Fallo detectado en contenedores/endpoints.

Problemas detectados:
  • backend-aws: Container 'backend-aws' is in state 'exited' (expected 'running')
  • Backend endpoint: Backend endpoint connection refused
```

### Recovery Notification

After attempting recovery, you'll receive a follow-up:

**If successful:**
```
✅ APP RECUPERADA

🕐 Timestamp: 2025-11-10 10:30:20 UTC
🌐 Entorno: AWS EC2 automated-trading-platform

Todos los checks OK después de restart.

Servicios reiniciados:
  • backend-aws
```

**If still failing:**
```
❌ APP SIGUE CAÍDA

🕐 Timestamp: 2025-11-10 10:30:20 UTC
🌐 Entorno: AWS EC2 automated-trading-platform

El intento de restart no resolvió los problemas.

Problemas detectados:
  • backend-aws: Container 'backend-aws' failed to start
```

## Logs

Monitor logs are written to `/var/log/atp_health_monitor.log`.

View recent logs:
```bash
tail -f /var/log/atp_health_monitor.log
```

View last 50 lines:
```bash
tail -50 /var/log/atp_health_monitor.log
```

## Troubleshooting

### Script Not Running

1. Check cron is installed:
   ```bash
   crontab -l | grep monitor_health
   ```

2. Check log file permissions:
   ```bash
   ls -la /var/log/atp_health_monitor.log
   ```

3. Check script permissions:
   ```bash
   ls -la infra/monitor_health.py
   ```

### Telegram Notifications Not Sending

1. Verify environment variables:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

2. Test Telegram helper manually:
   ```bash
   cd /home/ubuntu/automated-trading-platform
   python3 -c "from infra.telegram_helper import send_telegram_message; send_telegram_message('Test message')"
   ```

### Docker Compose Commands Failing

Ensure you're running from the correct directory:
```bash
cd /home/ubuntu/automated-trading-platform
docker compose ps
```

The cron job includes `cd` before running the script, but if running manually, make sure you're in the project directory.

## Removing the Monitor

To remove the cron job:

```bash
crontab -l | grep -v 'monitor_health.py' | crontab -
```

Verify removal:
```bash
crontab -l
```

## Configuration

### Adjusting Check Frequency

To change the check frequency, edit the cron schedule in `infra/install_health_cron.sh`:

- Every 5 minutes: `*/5 * * * *`
- Every 10 minutes: `*/10 * * * *`
- Every hour: `0 * * * *`

Then re-run the installation script or manually update crontab.

### Adding/Removing Services

Edit `CRITICAL_SERVICES` in `infra/monitor_health.py`:

```python
CRITICAL_SERVICES = ["backend-aws", "frontend-aws", "db", "gluetun"]
```

### Adjusting Timeouts

Edit these constants in `infra/monitor_health.py`:

```python
HEALTH_CHECK_TIMEOUT = 3  # HTTP request timeout in seconds
RECOVERY_WAIT_SECONDS = 20  # Wait time after restart before re-checking
```

## Security Notes

- The script runs with the permissions of the user who installed the cron job
- Ensure the log file has appropriate permissions (readable by the user)
- Telegram credentials are read from environment variables (same as the main app)
- The script does not require sudo privileges for normal operation

