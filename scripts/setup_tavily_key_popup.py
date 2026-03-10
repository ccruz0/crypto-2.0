#!/usr/bin/env python3
"""Popup dialog to set TAVILY_API_KEY in secrets/runtime.env for OpenClaw web search."""

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_ENV = REPO_ROOT / "secrets" / "runtime.env"


def _get_key_osascript():
    """macOS native dialog via AppleScript (hidden input)."""
    script = '''
    display dialog "Paste your Tavily API key (for OpenClaw web search):" ¬
        default answer "" ¬
        with title "Tavily API Key" ¬
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


def _get_key_tkinter():
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
    root.title("Tavily API Key")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Paste your Tavily API key (for OpenClaw web search):").pack(anchor=tk.W)
    ttk.Label(frame, text="Get a key at https://tavily.com").pack(anchor=tk.W)
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


def _update_env(key: str) -> None:
    SECRETS_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if SECRETS_ENV.exists():
        for line in SECRETS_ENV.read_text().splitlines():
            if line.strip().startswith("TAVILY_API_KEY=") or line.strip().startswith("SEARCH_PROVIDER="):
                continue
            lines.append(line)
    lines.append(f"TAVILY_API_KEY={key}")
    lines.append("SEARCH_PROVIDER=tavily")
    SECRETS_ENV.write_text("\n".join(lines) + "\n")


def main():
    key = None
    if platform.system() == "Darwin":
        key = _get_key_osascript()
    if key is None:
        key = _get_key_tkinter()
    if key is None:
        print("No popup available. Run: bash scripts/setup_tavily_key.sh")
        sys.exit(1)

    if not key.strip():
        print("Cancelled or empty key.")
        sys.exit(0)

    key = key.strip()
    _update_env(key)
    print("TAVILY_API_KEY and SEARCH_PROVIDER=tavily written to secrets/runtime.env")
    print("Restart OpenClaw: docker compose -f docker-compose.openclaw.yml restart openclaw")


if __name__ == "__main__":
    main()
