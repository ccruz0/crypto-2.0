#!/usr/bin/env python3
"""
Production-only: unify Telegram bot token across active env files, recreate backend-aws, validate.

- Prompts via tkinter (GUI) when available, else getpass (terminal).
- Never logs or prints the full token; only masked prefix + suffix.
- Does not write plaintext backups of old tokens.
- Refuses to run when .env.aws does not look like AWS production (LAB guard).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


# Keys that must hold the same bot token in production (docker env_file chain).
UNIFIED_TOKEN_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN_AWS",
    "TELEGRAM_ATP_CONTROL_BOT_TOKEN",
    "TELEGRAM_CLAW_BOT_TOKEN",
)

# Remove encrypted token so runtime uses plaintext from env files only.
REMOVE_KEYS = frozenset({"TELEGRAM_BOT_TOKEN_ENCRYPTED"})

# Optional: strip dev token from prod files to avoid accidental drift.
STRIP_DRIFT_KEYS = frozenset({"TELEGRAM_BOT_TOKEN_DEV"})


def _repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(20):
        if (cur / "docker-compose.yml").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    print("ERROR: repo root not found (docker-compose.yml missing)", file=sys.stderr)
    sys.exit(2)


def _mask_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return "(empty)"
    if len(t) <= 14:
        return "*" * min(len(t), 8) + "…"
    return f"{t[:8]}…{t[-4:]}"


def _looks_like_bot_token(token: str) -> bool:
    t = (token or "").strip()
    if len(t) < 40 or ":" not in t:
        return False
    left, _, right = t.partition(":")
    if not left.isdigit() or not right:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", right))


def _prompt_token_gui(title: str, prompt: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        class PasswordDialog(simpledialog.Dialog):
            def __init__(self, parent, dialog_title: str, dialog_prompt: str):
                self.dialog_prompt = dialog_prompt
                self.result_value: str | None = None
                super().__init__(parent, dialog_title)

            def body(self, master):
                tk.Label(master, text=self.dialog_prompt, justify="left").grid(row=0, column=0, padx=5, pady=5)
                self.entry = tk.Entry(master, width=55, show="*")
                self.entry.grid(row=1, column=0, padx=5, pady=5)
                return self.entry

            def apply(self):
                self.result_value = self.entry.get().strip()

        dlg = PasswordDialog(root, title=title, dialog_prompt=prompt)
        root.destroy()
        return dlg.result_value if dlg.result_value else None
    except Exception:
        return None


def _prompt_token_terminal() -> str | None:
    import getpass

    try:
        v = getpass.getpass("Paste Telegram bot token (BotFather): ").strip()
        return v or None
    except Exception:
        return None


def _read_token(args: argparse.Namespace) -> str:
    if args.token_stdin:
        raw = sys.stdin.read().strip()
        if not raw:
            print("ERROR: stdin empty", file=sys.stderr)
            sys.exit(2)
        return raw
    t = _prompt_token_gui(
        "ATP — production Telegram token",
        "Paste the single production bot token (same bot for control + alerts).\n"
        "This will update .env.aws and secrets/runtime.env only.",
    )
    if not t:
        t = _prompt_token_terminal()
    if not t:
        print("ERROR: no token provided", file=sys.stderr)
        sys.exit(2)
    if not _looks_like_bot_token(t):
        print("ERROR: token shape invalid (expected 123456789:AA…)", file=sys.stderr)
        sys.exit(2)
    return t


def _parse_env_line(line: str) -> tuple[str, str] | None:
    s = line.rstrip("\n")
    if not s.strip() or s.lstrip().startswith("#"):
        return None
    if "=" not in s:
        return None
    k, _, v = s.partition("=")
    key = k.strip()
    if not key:
        return None
    return key, v


def merge_env_file(
    content: str,
    set_vars: dict[str, str],
    drop_keys: frozenset[str],
) -> str:
    lines = content.splitlines()
    out: list[str] = []
    seen = set()
    for line in lines:
        parsed = _parse_env_line(line)
        if not parsed:
            out.append(line)
            continue
        key, _ = parsed
        if key in drop_keys:
            continue
        if key in set_vars:
            out.append(f"{key}={set_vars[key]}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in set_vars.items():
        if k not in seen:
            out.append(f"{k}={v}")
    body = "\n".join(out)
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def _env_aws_is_prod(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    if "runtime_origin=aws" in text or "runtime_origin = aws" in text:
        return True
    if "environment=aws" in text or "environment = aws" in text:
        return True
    if "app_env=aws" in text or "app_env = aws" in text:
        return True
    return False


def _lab_guard(root: Path) -> None:
    aws = root / ".env.aws"
    if not aws.is_file():
        print("ERROR: .env.aws missing — cannot verify production target.", file=sys.stderr)
        sys.exit(2)
    if not _env_aws_is_prod(aws):
        print(
            "ERROR: .env.aws does not declare AWS production "
            "(expected ENVIRONMENT=aws, APP_ENV=aws, or RUNTIME_ORIGIN=AWS).",
            file=sys.stderr,
        )
        sys.exit(2)


def _docker_compose_cmd() -> list[str]:
    if shutil.which("docker"):
        return ["docker", "compose"]
    return ["docker-compose"]


def _compose_run(
    root: Path,
    args: list[str],
    *,
    dry_run: bool,
) -> int:
    cmd = _docker_compose_cmd() + ["--profile", "aws"] + args
    if dry_run:
        print("[dry-run] would run:", " ".join(cmd))
        return 0
    env = os.environ.copy()
    env.setdefault("COMPOSE_PROFILES", "aws")
    try:
        r = subprocess.run(cmd, cwd=root, env=env, check=False)
        return r.returncode
    except FileNotFoundError:
        sudo_cmd = ["sudo"] + cmd
        r = subprocess.run(sudo_cmd, cwd=root, env=env, check=False)
        return r.returncode


def _container_exec(
    root: Path,
    inner: str,
    *,
    dry_run: bool,
) -> subprocess.CompletedProcess[str]:
    base = _docker_compose_cmd() + ["--profile", "aws", "exec", "-T", "backend-aws", "sh", "-lc", inner]
    if dry_run:
        print("[dry-run] would exec:", " ".join(base[:6]), "...")
        return subprocess.CompletedProcess(base, 0, stdout="", stderr="")
    try:
        return subprocess.run(
            base,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.run(
            ["sudo"] + base,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )


def _validation_script() -> bytes:
    return b"""import json,os,urllib.request
def mask(t):
    t=(t or '').strip()
    if not t:
        return '(empty)'
    return t[:8]+'...'+t[-4:] if len(t)>14 else '***'
atp=os.environ.get('TELEGRAM_ATP_CONTROL_BOT_TOKEN','').strip()
bot=os.environ.get('TELEGRAM_BOT_TOKEN','').strip()
aws=os.environ.get('TELEGRAM_BOT_TOKEN_AWS','').strip()
out={}
out['mask_atp']=mask(atp)
out['mask_bot']=mask(bot)
out['mask_aws']=mask(aws)
out['atp_present']=bool(atp)
out['bot_present']=bool(bot)
out['all_match']=bool(atp and atp==bot==aws)
t=atp or bot or aws or ''
if t:
    for path in ('getMe','getWebhookInfo'):
        url='https://api.telegram.org/bot'+t+'/'+path
        try:
            r=urllib.request.urlopen(url,timeout=20)
            out[path]=json.load(r)
        except Exception as e:
            out[path]={'ok':False,'error':str(e)[:120]}
print(json.dumps(out))
"""


def _validate(root: Path, expected_mask: str, *, dry_run: bool) -> None:
    print("\n=== Validation ===")
    import base64

    b64 = base64.b64encode(_validation_script()).decode("ascii")
    inner = f"echo {b64} | base64 -d | python3"
    proc = _container_exec(root, inner, dry_run=dry_run)
    if dry_run:
        print("masked_target_token:", expected_mask)
        return
    if proc.returncode != 0:
        print("exec_failed:", proc.stderr[:500] if proc.stderr else proc.stdout[:500])
        return
    try:
        data = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        print("parse_error", proc.stdout[:300])
        return
    print("masked_TELEGRAM_ATP_CONTROL_BOT_TOKEN:", data.get("mask_atp"))
    print("masked_TELEGRAM_BOT_TOKEN:", data.get("mask_bot"))
    print("masked_TELEGRAM_BOT_TOKEN_AWS:", data.get("mask_aws"))
    print("TELEGRAM_ATP_CONTROL_BOT_TOKEN_present:", data.get("atp_present"))
    print("TELEGRAM_BOT_TOKEN_present:", data.get("bot_present"))
    print("all_three_match:", data.get("all_match"))
    gm = data.get("getMe") or {}
    wh = data.get("getWebhookInfo") or {}
    print("getMe_ok:", gm.get("ok"), "username:", (gm.get("result") or {}).get("username"))
    print("getWebhookInfo_ok:", wh.get("ok"), "url:", (wh.get("result") or {}).get("url", ""))


def main() -> None:
    ap = argparse.ArgumentParser(description="Unify production Telegram token and recreate backend-aws.")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only; do not write files or restart.")
    ap.add_argument("--token-stdin", action="store_true", help="Read token from stdin (no prompt).")
    ap.add_argument(
        "--force-lab",
        action="store_true",
        help="Danger: skip .env.lab presence check (still requires .env.aws AWS markers).",
    )
    ap.add_argument("--yes", action="store_true", help="Skip typing PROD confirmation.")
    args = ap.parse_args()

    root = _repo_root(Path.cwd())
    if not args.force_lab and (root / ".env.lab").is_file():
        print(
            "ERROR: .env.lab exists — refusing (production-only). "
            "Remove .env.lab or pass --force-lab if you still intend to update prod files here.",
            file=sys.stderr,
        )
        sys.exit(2)
    _lab_guard(root)

    token = _read_token(args)
    mask = _mask_token(token)
    print("Using token (masked):", mask)

    if not args.yes and not args.dry_run:
        confirm = input('Type PROD and press Enter to write files and recreate backend-aws: ').strip()
        if confirm != "PROD":
            print("Aborted.")
            sys.exit(1)

    assignments = {k: token for k in UNIFIED_TOKEN_KEYS}
    drop_all = REMOVE_KEYS | STRIP_DRIFT_KEYS

    paths = [root / ".env.aws", root / "secrets" / "runtime.env"]
    optional_dotenv = root / ".env"
    has_telegram_in_dotenv = False
    if optional_dotenv.is_file():
        txt = optional_dotenv.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*TELEGRAM_(BOT_TOKEN|ATP_CONTROL_BOT_TOKEN|BOT_TOKEN_AWS)\s*=", txt, re.M):
            has_telegram_in_dotenv = True
            paths.append(optional_dotenv)

    secrets_dir = root / "secrets"
    if not args.dry_run:
        secrets_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== Active token sources updated ===")
    for p in paths:
        print(" -", p.relative_to(root))
    if not has_telegram_in_dotenv:
        print(" - (.env has no TELEGRAM_* keys; skipped)")

    for p in paths:
        prev = ""
        if p.is_file():
            prev = p.read_text(encoding="utf-8", errors="replace")
        merged = merge_env_file(prev, assignments, drop_all)
        if args.dry_run:
            print(f"[dry-run] would write {p.name}: {len(merged)} bytes")
            continue
        p.write_text(merged, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    rc = _compose_run(
        root,
        ["up", "-d", "--force-recreate", "backend-aws"],
        dry_run=args.dry_run,
    )
    if rc != 0:
        print("ERROR: docker compose recreate failed, code=", rc, file=sys.stderr)
        sys.exit(rc)

    if not args.dry_run:
        print("Waiting for container health (up to 120s)…")
        import time

        for _ in range(24):
            try:
                urllib.request.urlopen("http://127.0.0.1:8002/ping_fast", timeout=3)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(5)
        else:
            print("WARNING: health check did not pass quickly; validation may fail.")

    _validate(root, mask, dry_run=args.dry_run)
    print("\nDone.")


if __name__ == "__main__":
    main()
