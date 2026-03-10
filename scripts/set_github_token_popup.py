#!/usr/bin/env python3
"""Popup dialog to set GITHUB_TOKEN in secrets/runtime.env and restart backend."""

import os
import platform
import subprocess
import sys
from pathlib import Path

# Repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_ENV = REPO_ROOT / "secrets" / "runtime.env"


def _get_token_osascript():
    """macOS native dialog via AppleScript (hidden input)."""
    script = '''
    display dialog "Enter your GitHub PAT (ghp_...):" ¬
        default answer "" ¬
        with title "GitHub PAT" ¬
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
    root.title("GitHub PAT")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Enter your GitHub Personal Access Token (ghp_...):").pack(anchor=tk.W)
    ttk.Label(frame, text="Used for deploy trigger.").pack(anchor=tk.W)
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


def main():
    token = None
    if platform.system() == "Darwin":
        token = _get_token_osascript()
    if token is None:
        token = _get_token_tkinter()
    if token is None and platform.system() == "Darwin":
        print("Run: GITHUB_TOKEN=ghp_xxx ./scripts/set_github_token_for_deploy.sh")
        sys.exit(1)
    if token is None:
        print("tkinter not available. Use: GITHUB_TOKEN=ghp_xxx ./scripts/set_github_token_for_deploy.sh")
        sys.exit(1)

    if not token:
        print("Cancelled or empty token.")
        sys.exit(0)

    token = token.strip()

    SECRETS_ENV.parent.mkdir(parents=True, exist_ok=True)

    if SECRETS_ENV.exists():
        content = SECRETS_ENV.read_text()
        if "GITHUB_TOKEN=" in content:
            lines = []
            for line in content.splitlines():
                if line.strip().startswith("GITHUB_TOKEN="):
                    lines.append(f"GITHUB_TOKEN={token}")
                else:
                    lines.append(line)
            SECRETS_ENV.write_text("\n".join(lines) + "\n")
        else:
            with SECRETS_ENV.open("a") as f:
                f.write(f"GITHUB_TOKEN={token}\n")
    else:
        SECRETS_ENV.write_text(f"GITHUB_TOKEN={token}\n")

    print("Token written to secrets/runtime.env")

    # Restart backend
    os.chdir(REPO_ROOT)
    subprocess.run(
        ["docker", "compose", "stop", "backend-dev"],
        capture_output=True,
    )
    result = subprocess.run(
        ["docker", "compose", "--profile", "aws", "restart", "backend-aws"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Warning: backend restart failed:", result.stderr or result.stdout, file=sys.stderr)
    else:
        print("Backend restarted. Deploy trigger should now work.")


if __name__ == "__main__":
    main()
