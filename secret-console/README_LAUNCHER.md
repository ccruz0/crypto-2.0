# Secret Console — macOS launcher

Two ways to start the app locally without touching application code: a shell script and an optional `.app` wrapper.

## Prerequisites

- macOS with **Python 3** available as `python3` (Xcode CLT or python.org installer).
- The `secret-console` project directory containing `app.py` and `requirements.txt` at one of:

  | Path | Notes |
  |------|--------|
  | `$HOME/secret-console` | Typical standalone clone |
  | `$HOME/automated-trading-platform/secret-console` | Monorepo layout |

  If your clone lives elsewhere, symlink it to one of these paths or copy this folder there.

## 1. Shell launcher

```bash
chmod +x secret_console_launcher.sh
./secret_console_launcher.sh
```

Or from anywhere:

```bash
~/secret-console/secret_console_launcher.sh
```

### Behavior (idempotent)

- Resolves project directory (see above).
- Creates **`$PROJECT_DIR/.venv`** if missing.
- Runs **`pip install -r requirements.txt`** every time (fast no-op when already satisfied).
- If **port 8765** is already in use (checked with `nc`), opens **http://127.0.0.1:8765/** and exits without starting a second server.
- Otherwise starts **`uvicorn app:app --host 127.0.0.1 --port 8765 --reload`** and opens the dashboard after a short delay.

### Optional environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_CONSOLE_PORT` | `8765` | Listen port |
| `SECRET_CONSOLE_HOST` | `127.0.0.1` | Bind address |

## 2. Double-click app (AppleScript)

1. Keep **`secret_console_launcher.sh`** in the same folder as your checkout (one of the paths above) and make it executable:

   ```bash
   chmod +x ~/secret-console/secret_console_launcher.sh
   ```

2. Build the application bundle from this directory:

   ```bash
   cd /path/to/secret-console
   osacompile -o "Secret Console Launcher.app" SecretConsoleLauncher.applescript
   ```

3. Move **`Secret Console Launcher.app`** to **Applications** or the Desktop and double-click it.

The applet opens **Terminal.app** and runs the launcher script with `exec zsh -lc …`, so you see logs and can stop the server with **Ctrl+C**.

To use a custom install path, either symlink your repo to `~/secret-console` or edit **`SecretConsoleLauncher.applescript`** to add another `test -f` candidate, then re-run `osacompile`.

## Troubleshooting

- **“project directory not found”** — Clone or copy `secret-console` to `~/secret-console` or `~/automated-trading-platform/secret-console`, or symlink one of those to your checkout.
- **`python3: command not found`** — Install Python 3 or ensure it is on your `PATH`.
- **Port in use** — Stop the other process or set `SECRET_CONSOLE_PORT` to a free port (and bookmark the matching URL).
