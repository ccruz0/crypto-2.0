# Remote Debug Strategy Script Usage

**Purpose:** Run backend debug scripts from laptop via SSH

## Quick Start

```bash
# Debug ALGO_USDT with last 20 entries
bash scripts/debug_strategy_remote.sh ALGO_USDT 20

# Debug BTC_USDT with last 50 entries
bash scripts/debug_strategy_remote.sh BTC_USDT 50

# Default: ALGO_USDT, last 20 entries
bash scripts/debug_strategy_remote.sh
```

## Configuration

**⚠️ IMPORTANT:** Before first use, edit `scripts/debug_strategy_remote.sh` and set the configuration variables at the top:

```bash
REMOTE_USER="ubuntu"
REMOTE_HOST="REPLACE_ME"              # ⚠️ Change this to your server IP or hostname
REMOTE_PROJECT_DIR="/home/ubuntu/automated-trading-platform"
BACKEND_SERVICE_NAME="backend-aws"
```

Set `REMOTE_HOST` to your actual server IP (e.g., `123.45.67.89`) or hostname from `~/.ssh/config` (e.g., `hilovivo-aws`).

## How It Works

1. SSH into the production server
2. Change to the project directory
3. Run `debug_strategy.py` inside the backend Docker container
4. Pass symbol and `--last N` parameter
5. Always include `--compare` flag
6. Print results (especially FLIP DETECTED blocks)

## Examples

```bash
# Basic usage
bash scripts/debug_strategy_remote.sh ALGO_USDT 20

# Different symbol
bash scripts/debug_strategy_remote.sh BTC_USDT 50

# More entries
bash scripts/debug_strategy_remote.sh ALGO_USDT 100

# Default symbol (ALGO_USDT) and default count (20)
bash scripts/debug_strategy_remote.sh
```

## Output

The script will show:
- Configuration summary
- Strategy log entries with raw numeric values
- Buy flags status
- **FLIP DETECTED blocks** when BUY→WAIT transitions occur

Example output:

```
[REMOTE DEBUG] Running on ubuntu@123.45.67.89
[REMOTE DEBUG] Symbol: ALGO_USDT
[REMOTE DEBUG] Last N: 20
[REMOTE DEBUG] Command: cd "/home/ubuntu/automated-trading-platform" && docker compose exec "backend-aws" python3 backend/scripts/debug_strategy.py "ALGO_USDT" --compare --last "20"

⚠️  FLIP DETECTED between Entry #1 and Entry #2
   BUY → WAIT
   buy_target_ok: True → False
     ⚠️  This flag going False caused BUY → WAIT!
     Entry #1: price=0.14280500, buy_target=0.14281000, diff=-0.00000500
     Entry #2: price=0.14282100, buy_target=0.14281000, diff=+0.00001100
```

## Troubleshooting

- **"REMOTE_HOST is not configured"**: Edit the script and set `REMOTE_HOST`
- **SSH connection errors**: Verify SSH access: `ssh $REMOTE_USER@$REMOTE_HOST`
- **"No such service"**: Check `docker-compose.yml` for correct service name
- **"No logs found"**: Try increasing `LAST_N` or check backend is running
