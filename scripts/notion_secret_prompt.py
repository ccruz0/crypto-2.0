#!/usr/bin/env python3
"""
Popup to paste Notion Internal Integration Secret and save to backend/.env.
Usage: python3 scripts/notion_secret_prompt.py
"""
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / "backend" / ".env"
KEY_NAME = "NOTION_API_KEY"


def main():
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print("tkinter not available.")
        print("Option 1: Open in browser (paste secret, then copy the line):")
        print("  open scripts/notion_secret_prompt.html")
        print("Option 2: Paste your secret and run:")
        print("  echo 'NOTION_API_KEY=<your_secret>' >> backend/.env")
        sys.exit(0)

    def save():
        secret = entry.get().strip()
        if not secret:
            messagebox.showwarning("Empty", "Please paste your Notion integration secret.")
            return
        # Remove any leading/trailing quotes or spaces
        secret = secret.strip("'\"")
        env_file = ENV_PATH
        env_file.parent.mkdir(parents=True, exist_ok=True)
        line = f"{KEY_NAME}={secret}\n"
        if env_file.exists():
            content = env_file.read_text()
            if re.search(rf"^\s*{re.escape(KEY_NAME)}\s*=", content, re.MULTILINE):
                content = re.sub(
                    rf"^\s*{re.escape(KEY_NAME)}\s*=.*$", line.rstrip(), content, count=1, flags=re.MULTILINE
                )
                env_file.write_text(content)
            else:
                with open(env_file, "a") as f:
                    f.write(line)
        else:
            env_file.write_text(line)
        messagebox.showinfo("Saved", f"Saved to {env_file.relative_to(REPO_ROOT)}.\nYou can close this window.")
        root.destroy()

    root = tk.Tk()
    root.title("Notion API secret")
    root.geometry("480x160")
    root.resizable(True, False)

    tk.Label(root, text="Paste your Notion Internal Integration Secret below:", font=("", 10)).pack(pady=(12, 4))
    entry = tk.Entry(root, show="•", width=56, font=("", 11))
    entry.pack(pady=4, padx=12, fill="x")
    tk.Button(root, text="Save to backend/.env", command=save, font=("", 10)).pack(pady=12)
    entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
