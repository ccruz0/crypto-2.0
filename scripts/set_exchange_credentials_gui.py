#!/usr/bin/env python3
"""
Pop-up to enter exchange API credentials and POST them to the backend.
- If tkinter is available: GUI window.
- Else on macOS: osascript native dialogs.
- Else: prompt in terminal.
Usage: python scripts/set_exchange_credentials_gui.py
       API_URL=https://dashboard.hilovivo.com/api python scripts/set_exchange_credentials_gui.py
"""
import os
import sys
import json
import subprocess
from typing import Optional
import urllib.request
import urllib.error
import ssl

USE_TK = False
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, font as tkfont
    USE_TK = True
except ImportError:
    pass


DEFAULT_API_URL = os.environ.get("API_URL", "https://dashboard.hilovivo.com/api")
ENDPOINT = "/settings/exchange-credentials"


def post_credentials(api_url: str, api_key: str, api_secret: str, admin_key: Optional[str]) -> tuple:
    url = api_url.rstrip("/") + ENDPOINT
    data = json.dumps({"api_key": api_key, "api_secret": api_secret}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if admin_key and admin_key.strip():
        headers["X-Admin-Key"] = admin_key.strip()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            body = resp.read().decode()
            return True, body
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()
        except Exception:
            detail = e.reason or str(e)
        return False, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return False, str(e)


def _osascript_dialog(prompt: str, title: str = "Set Exchange Credentials", hidden: bool = False) -> Optional[str]:
    """Return user input from macOS dialog; None if cancelled."""
    p = prompt.replace("\\", "\\\\").replace('"', '\\"')
    t = title.replace("\\", "\\\\").replace('"', '\\"')
    hidden_part = " with hidden answer" if hidden else ""
    # AppleScript has built-in "empty"; use it for default answer
    try:
        out = subprocess.run(
            [
                "osascript", "-e",
                f'tell application "System Events" to display dialog "{p}" with title "{t}" default answer empty with icon note{hidden_part}',
                "-e", "text returned of result",
            ],
            capture_output=True, text=True, timeout=60
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _run_popup_native():
    """Use osascript (macOS) or terminal prompts."""
    if sys.platform == "darwin":
        api_key = _osascript_dialog("Exchange API Key:")
        if api_key is None:
            return
        api_secret = _osascript_dialog("Exchange API Secret:", hidden=True)
        if api_secret is None:
            return
        admin_key = _osascript_dialog("Admin key (optional; leave empty if not set):", hidden=True) or None
        api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    else:
        print("Exchange API Key:")
        api_key = (input().strip() or None)
        print("Exchange API Secret:")
        try:
            import getpass
            api_secret = (getpass.getpass().strip() or None)
        except Exception:
            api_secret = input().strip() or None
        print("Admin key (optional):")
        admin_key = (input().strip() or None)
        api_url = os.environ.get("API_URL", DEFAULT_API_URL)
    if not api_key or not api_secret:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'display dialog "API Key and API Secret are required." with title "Error" with icon stop'], check=False)
        else:
            print("API Key and API Secret are required.", file=sys.stderr)
        return
    ok, msg = post_credentials(api_url, api_key, api_secret, admin_key)
    if sys.platform == "darwin":
        if ok:
            subprocess.run(["osascript", "-e", 'display dialog "Credentials saved. Restart the backend container for them to take effect." with title "Success" with icon note'], check=False)
        else:
            subprocess.run(["osascript", "-e", f'display dialog "{msg[:200]}" with title "Error" with icon stop'], check=False)
    else:
        if ok:
            print("Credentials saved. Restart the backend container for them to take effect.")
        else:
            print(msg, file=sys.stderr)
            sys.exit(1)


def main():
    if not USE_TK:
        _run_popup_native()
        return
    root = tk.Tk()
    root.title("Set Exchange API Credentials")
    root.geometry("520x320")
    root.resizable(True, True)

    f = tkfont.nametofont("TkDefaultFont")
    f.configure(size=10)

    ttk.Label(root, text="Exchange API Key:", font=("", 10)).grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
    api_key_var = tk.StringVar()
    api_key_entry = ttk.Entry(root, textvariable=api_key_var, width=50, show="")
    api_key_entry.grid(row=0, column=1, sticky=tk.EW, padx=8, pady=6)

    ttk.Label(root, text="Exchange API Secret:", font=("", 10)).grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
    api_secret_var = tk.StringVar()
    api_secret_entry = ttk.Entry(root, textvariable=api_secret_var, width=50, show="*")
    api_secret_entry.grid(row=1, column=1, sticky=tk.EW, padx=8, pady=6)

    ttk.Label(root, text="Admin key (optional):", font=("", 10)).grid(row=2, column=0, sticky=tk.W, padx=8, pady=6)
    admin_key_var = tk.StringVar()
    admin_key_entry = ttk.Entry(root, textvariable=admin_key_var, width=50, show="*")
    admin_key_entry.grid(row=2, column=1, sticky=tk.EW, padx=8, pady=6)

    ttk.Label(root, text="API base URL:", font=("", 10)).grid(row=3, column=0, sticky=tk.W, padx=8, pady=6)
    url_var = tk.StringVar(value=DEFAULT_API_URL)
    url_entry = ttk.Entry(root, textvariable=url_var, width=50)
    url_entry.grid(row=3, column=1, sticky=tk.EW, padx=8, pady=6)

    root.columnconfigure(1, weight=1)

    def submit():
        api_key = api_key_var.get().strip()
        api_secret = api_secret_var.get().strip()
        admin_key = admin_key_var.get().strip() or None
        api_url = url_var.get().strip()
        if not api_key or not api_secret:
            messagebox.showerror("Error", "API Key and API Secret are required.")
            return
        if not api_url:
            messagebox.showerror("Error", "API base URL is required.")
            return
        ok, msg = post_credentials(api_url, api_key, api_secret, admin_key)
        if ok:
            messagebox.showinfo("Success", "Credentials saved. Restart the backend container for them to take effect.")
            root.destroy()
        else:
            messagebox.showerror("Request failed", msg)

    btn_frame = ttk.Frame(root)
    btn_frame.grid(row=4, column=0, columnspan=2, pady=16)
    ttk.Button(btn_frame, text="Cancel", command=root.destroy).pack(side=tk.LEFT, padx=8)
    ttk.Button(btn_frame, text="Save", command=submit).pack(side=tk.LEFT, padx=8)

    root.mainloop()


if __name__ == "__main__":
    main()
