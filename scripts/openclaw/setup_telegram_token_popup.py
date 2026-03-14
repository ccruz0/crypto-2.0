#!/usr/bin/env python3
"""Popup dialog to set TELEGRAM_BOT_TOKEN in secrets/runtime.env for OpenClaw on LAB."""

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SECRETS_ENV = REPO_ROOT / "secrets" / "runtime.env"

LAB_INSTANCE_ID = "i-0d82c172235770a0d"
AWS_REGION = "ap-southeast-1"
REPO_ON_LAB = "/home/ubuntu/automated-trading-platform"


def _get_token_osascript():
    """macOS native dialog via AppleScript (hidden input)."""
    script = '''
    display dialog "Paste your Telegram Bot Token (from @BotFather):" ¬
        default answer "" ¬
        with title "OpenClaw Telegram Bot Token" ¬
        with hidden answer ¬
        buttons {"Cancel", "OK"} ¬
        default button "OK"
    return text returned of result
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() if result.stdout else None


def _get_token_tkinter():
    """Tkinter popup (cross-platform)."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return None

    token = [None]

    def on_ok():
        token[0] = entry.get().strip()
        root.destroy()

    def on_cancel():
        root.destroy()

    root = tk.Tk()
    root.title("OpenClaw Telegram Bot Token")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Paste your Telegram Bot Token (from @BotFather):").pack(anchor=tk.W)
    ttk.Label(frame, text="Format: 123456789:ABCdef...").pack(anchor=tk.W)
    entry = ttk.Entry(frame, show="•", width=50)
    entry.pack(pady=(10, 20), fill=tk.X)
    entry.focus()

    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.X)
    ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=(0, 5))
    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)

    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_cancel())

    root.mainloop()
    return token[0]


def _update_local_env(token: str) -> None:
    """Write token to local secrets/runtime.env."""
    SECRETS_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if SECRETS_ENV.exists():
        for line in SECRETS_ENV.read_text().splitlines():
            if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                continue
            lines.append(line)
    lines.append(f"TELEGRAM_BOT_TOKEN={token}")
    SECRETS_ENV.write_text("\n".join(lines).rstrip() + "\n")


def _deploy_to_lab(token: str) -> bool:
    """Push token to LAB via SSM and restart OpenClaw."""
    import shlex
    cmd = (
        f'grep -v "^TELEGRAM_BOT_TOKEN=" {REPO_ON_LAB}/secrets/runtime.env 2>/dev/null > /tmp/re.env || true; '
        f'echo "TELEGRAM_BOT_TOKEN={token}" >> /tmp/re.env; '
        f'mv /tmp/re.env {REPO_ON_LAB}/secrets/runtime.env; '
        f'cd {REPO_ON_LAB} && docker compose -f docker-compose.openclaw.yml restart openclaw'
    )
    escaped = cmd.replace('"', '\\"')
    result = subprocess.run(
        [
            "aws", "ssm", "send-command",
            "--instance-ids", LAB_INSTANCE_ID,
            "--region", AWS_REGION,
            "--document-name", "AWS-RunShellScript",
            "--parameters", f'commands=["{escaped}"]',
            "--output", "text",
            "--query", "Command.CommandId",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("SSM send failed:", result.stderr or result.stdout)
        return False
    cmd_id = result.stdout.strip()
    print(f"Command sent. CommandId: {cmd_id}")
    print("Waiting 30s for restart...")
    subprocess.run(["sleep", "30"], check=True)
    inv = subprocess.run(
        [
            "aws", "ssm", "get-command-invocation",
            "--command-id", cmd_id,
            "--instance-id", LAB_INSTANCE_ID,
            "--region", AWS_REGION,
            "--query", "[Status, StandardErrorContent]",
            "--output", "text",
        ],
        capture_output=True,
        text=True,
    )
    if inv.returncode == 0:
        status, err = inv.stdout.strip().split("\t", 1) if "\t" in inv.stdout else (inv.stdout, "")
        print(f"Status: {status}")
        if err and "Failed" in status:
            print(f"Error: {err}")
            return False
    return True


def main():
    token = None
    if platform.system() == "Darwin":
        token = _get_token_osascript()
    if token is None:
        token = _get_token_tkinter()
    if token is None:
        print("No popup available. Add TELEGRAM_BOT_TOKEN to secrets/runtime.env manually.")
        sys.exit(1)

    token = token.strip()
    if not token:
        print("Cancelled or empty token.")
        sys.exit(0)

    _update_local_env(token)
    print("TELEGRAM_BOT_TOKEN written to secrets/runtime.env")

    deploy = input("Deploy to LAB and restart OpenClaw? [Y/n]: ").strip().lower()
    if deploy != "n":
        if _deploy_to_lab(token):
            print("Done. OpenClaw on LAB restarted with Telegram token.")
        else:
            print("Deploy failed. Token is in secrets/runtime.env — copy to LAB manually.")
    else:
        print("Skipped deploy. Copy secrets/runtime.env to LAB and restart OpenClaw.")


if __name__ == "__main__":
    main()
