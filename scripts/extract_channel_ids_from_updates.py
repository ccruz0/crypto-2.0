#!/usr/bin/env python3
"""
Extract valid Telegram channel IDs from update JSON payloads and persist to env files.
Only accepts channel IDs starting with -100 from forward_origin or forward_from_chat.

Usage (from repo root):
  python scripts/extract_channel_ids_from_updates.py <file1.json> [file2.json ...]
  python scripts/extract_channel_ids_from_updates.py tmp/telegram_updates.json
  python scripts/extract_channel_ids_from_updates.py --restart-verify tmp/telegram_updates.json

Fetch from Telegram API (requires token in env):
  python scripts/extract_channel_ids_from_updates.py --fetch

Or stdin:
  cat tmp/telegram_updates.json | python scripts/extract_channel_ids_from_updates.py -

Mapping:
  title contains "ATP Control" → TELEGRAM_ATP_CONTROL_CHAT_ID
  title contains "AWS" → TELEGRAM_ALERT_CHAT_ID
  title contains "Claw" → TELEGRAM_CLAW_CHAT_ID
  title contains "Hilo", "Trading", or "ATP Alerts" → TELEGRAM_CHAT_ID_TRADING
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load env for --fetch
for f in [".env", ".env.aws", "secrets/runtime.env", "backend/.env"]:
    p = REPO_ROOT / f
    if p.exists():
        with open(p) as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"\'')
                    if k and v and k not in os.environ:
                        os.environ[k] = v

# Title keywords → env var mapping
TITLE_TO_VAR = {
    "ATP Control": "TELEGRAM_ATP_CONTROL_CHAT_ID",
    "AWS": "TELEGRAM_ALERT_CHAT_ID",
    "Claw": "TELEGRAM_CLAW_CHAT_ID",
    "Hilo": "TELEGRAM_CHAT_ID_TRADING",
    "Trading": "TELEGRAM_CHAT_ID_TRADING",
    "HILOVIVO": "TELEGRAM_CHAT_ID_TRADING",
    "HiloVivo": "TELEGRAM_CHAT_ID_TRADING",
    "ATP Alerts": "TELEGRAM_CHAT_ID_TRADING",
}

# Valid channel ID pattern: must start with -100
CHANNEL_ID_PATTERN = re.compile(r"^-100\d+$")


def _is_valid_channel_id(chat_id) -> bool:
    """Only accept IDs that start with -100."""
    if chat_id is None:
        return False
    s = str(chat_id).strip()
    return bool(CHANNEL_ID_PATTERN.match(s))


def _extract_chat_from_origin(origin: dict) -> tuple[str | None, str | None]:
    """Extract (chat_id, title) from forward_origin. Returns (None, None) if invalid."""
    if not origin or not isinstance(origin, dict):
        return None, None
    t = (origin.get("type") or "").strip().lower()
    if t not in ("channel", "chat"):
        return None, None
    chat = origin.get("chat") or origin.get("sender_chat")
    if not chat or not isinstance(chat, dict):
        return None, None
    cid = chat.get("id")
    if not _is_valid_channel_id(cid):
        return None, None
    title = (chat.get("title") or chat.get("username") or "").strip()
    return str(cid), title or None


def _extract_chat_from_forward_from_chat(forward: dict) -> tuple[str | None, str | None]:
    """Extract (chat_id, title) from forward_from_chat. Returns (None, None) if invalid."""
    if not forward or not isinstance(forward, dict):
        return None, None
    t = (forward.get("type") or "").strip().lower()
    if t != "channel":
        return None, None
    cid = forward.get("id")
    if not _is_valid_channel_id(cid):
        return None, None
    title = (forward.get("title") or forward.get("username") or "").strip()
    return str(cid), title or None


def _map_title_to_var(title: str) -> str | None:
    """Map channel title to env var. Case-insensitive."""
    if not title:
        return None
    t = title.upper()
    for kw, var in TITLE_TO_VAR.items():
        if kw.upper() in t:
            return var
    return None


def _extract_chat_from_chat_obj(chat: dict) -> tuple[str | None, str | None]:
    """Extract (chat_id, title) from chat/sender_chat when type is channel."""
    if not chat or not isinstance(chat, dict):
        return None, None
    t = (chat.get("type") or "").strip().lower()
    if t != "channel":
        return None, None
    cid = chat.get("id")
    if not _is_valid_channel_id(cid):
        return None, None
    title = (chat.get("title") or chat.get("username") or "").strip()
    return str(cid), title or None


def _extract_from_message(msg: dict) -> list[tuple[str, str, str]]:
    """Extract (env_var, chat_id, title) from a message. Returns list of matches."""
    out = []
    if not msg or not isinstance(msg, dict):
        return out

    # chat / sender_chat (channel_post or message in channel)
    for key in ("chat", "sender_chat"):
        chat = msg.get(key)
        cid, title = _extract_chat_from_chat_obj(chat)
        if cid:
            var = _map_title_to_var(title)
            if var:
                out.append((var, cid, title or ""))

    # forward_origin (Telegram API 7.0+)
    origin = msg.get("forward_origin")
    cid, title = _extract_chat_from_origin(origin)
    if cid:
        var = _map_title_to_var(title)
        if var:
            out.append((var, cid, title or ""))

    # forward_from_chat (legacy)
    forward = msg.get("forward_from_chat")
    cid2, title2 = _extract_chat_from_forward_from_chat(forward)
    if cid2:
        var = _map_title_to_var(title2)
        if var:
            out.append((var, cid2, title2 or ""))

    return out


def _collect_updates(data) -> list[dict]:
    """Normalize input to list of update dicts."""
    if isinstance(data, list):
        return [u for u in data if isinstance(u, dict)]
    if isinstance(data, dict):
        if "result" in data:
            return [u for u in data.get("result", []) if isinstance(u, dict)]
        return [data] if data.get("update_id") is not None else []
    return []


def _get_chat_from_username(token: str, username: str) -> dict | None:
    """Call getChat with @username. Returns Chat dict or None."""
    username = username.strip()
    if not username.startswith("@"):
        username = f"@{username}"
    url = f"https://api.telegram.org/bot{token}/getChat?chat_id={urllib.parse.quote(username)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read().decode())
        if d.get("ok") and d.get("result"):
            return d["result"]
    except Exception:
        pass
    return None


def _fetch_updates_from_api() -> dict:
    """Fetch getUpdates from Telegram API. Uses TELEGRAM_BOT_TOKEN or TELEGRAM_ATP_CONTROL_BOT_TOKEN."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_ATP_CONTROL_BOT_TOKEN")
    if not token:
        raise SystemExit("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_ATP_CONTROL_BOT_TOKEN required for --fetch")
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


def extract_from_payloads(sources: list[str | Path]) -> dict[str, str]:
    """
    Extract env_var -> chat_id mapping from payloads.
    Returns dict: env_var -> chat_id (last wins for duplicates).
    """
    collected: dict[str, tuple[str, str]] = {}  # var -> (chat_id, title)

    for src in sources:
        if src == "-":
            raw = sys.stdin.read()
            data = json.loads(raw)
        else:
            p = Path(src)
            if not p.exists():
                print(f"⚠️  File not found: {src}", file=sys.stderr)
                continue
            with open(p) as f:
                data = json.load(f)

        for u in _collect_updates(data):
            for msg in [u.get("message"), u.get("channel_post")]:
                for var, cid, title in _extract_from_message(msg or {}):
                    collected[var] = (cid, title)

    return {k: v[0] for k, v in collected.items()}


def _update_env_file(path: Path, updates: dict[str, str]) -> bool:
    """Update or append env vars. Returns True if file was modified."""
    lines = []
    updated_vars = set()
    if path.exists():
        with open(path) as f:
            for line in f:
                stripped = line.rstrip("\n")
                replaced = False
                for var, val in updates.items():
                    if stripped.startswith(f"{var}="):
                        lines.append(f"{var}={val}\n")
                        updated_vars.add(var)
                        replaced = True
                        break
                if not replaced:
                    lines.append(stripped + "\n")

    for var, val in updates.items():
        if var not in updated_vars:
            lines.append(f"{var}={val}\n")
            updated_vars.add(var)

    if not updated_vars:
        return False

    with open(path, "w") as f:
        f.writelines(lines)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Telegram channel IDs from update JSON and persist to env")
    parser.add_argument("files", nargs="*", help="JSON file(s) or - for stdin")
    parser.add_argument("--restart-verify", action="store_true", help="Restart backend-aws and run verification")
    parser.add_argument("--dry-run", action="store_true", help="Extract and print only; do not write env files")
    parser.add_argument("--fetch", action="store_true", help="Fetch updates from Telegram API (getUpdates) and extract")
    parser.add_argument("--from-usernames", metavar="USERNAMES", help="Comma-separated @usernames (e.g. @ATPControlAlerts,@AWS_alerts,@Claw,@HILOVIVO30)")
    args = parser.parse_args()

    sources = args.files
    if args.from_usernames:
        token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_ATP_CONTROL_BOT_TOKEN")
        if not token:
            print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_ATP_CONTROL_BOT_TOKEN required for --from-usernames", file=sys.stderr)
            return 1
        usernames = [u.strip() for u in args.from_usernames.split(",") if u.strip()]
        extracted = {}
        for username in usernames:
            chat = _get_chat_from_username(token, username)
            if not chat:
                print(f"⚠️  Could not get chat for {username}", file=sys.stderr)
                continue
            cid = chat.get("id")
            if not _is_valid_channel_id(cid):
                t = chat.get("type", "")
                print(f"⚠️  {username}: not a channel (type={t}, id={cid})", file=sys.stderr)
                continue
            title = (chat.get("title") or chat.get("username") or "").strip()
            var = _map_title_to_var(title)
            if var:
                extracted[var] = str(cid)
                print(f"  {username} → {var}={cid}")
            else:
                print(f"⚠️  {username}: title '{title}' did not match any channel mapping", file=sys.stderr)
    elif args.fetch:
        print("Fetching updates from Telegram API...")
        data = _fetch_updates_from_api()
        out_path = REPO_ROOT / "tmp" / "telegram_updates.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved to {out_path}")
        sources = [str(out_path)]
    elif not sources:
        # Default: look for common paths
        for p in ["tmp/telegram_updates.json", "tmp/telegram_updates"]:
            full = REPO_ROOT / p
            if full.exists():
                sources = [str(full)]
                break
        if not sources:
            print("Usage: python scripts/extract_channel_ids_from_updates.py <file1.json> [file2.json ...] | -", file=sys.stderr)
            return 1

    do_restart_verify = args.restart_verify
    dry_run = args.dry_run
    if not args.from_usernames:
        extracted = extract_from_payloads(sources) if sources else {}

    if not extracted:
        print("❌ No valid channel IDs extracted. Ensure payloads contain forward_origin.type == 'channel' or forward_from_chat.type == 'channel' with IDs starting with -100.", file=sys.stderr)
        return 1

    print("Extracted channel IDs:")
    for var, cid in sorted(extracted.items()):
        print(f"  {var}={cid}")

    # Persist (unless dry-run)
    modified = []
    if not dry_run:
        env_files = [
            REPO_ROOT / "secrets" / "runtime.env",
            REPO_ROOT / ".env.aws",
        ]
        for p in env_files:
            if not p.exists() and p.name == ".env.aws":
                continue  # Only update .env.aws if it exists
            if p.parent != p and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            if _update_env_file(p, extracted):
                modified.append(str(p))

    if modified:
        print(f"\n✅ Updated: {', '.join(modified)}")
    else:
        print("\n⚠️  No env files modified (secrets/runtime.env may not exist).")

    # Print final routing table
    print("\nFinal routing table:")
    print("-" * 50)
    VAR_TO_NAME = {
        "TELEGRAM_ATP_CONTROL_CHAT_ID": "ATP Control",
        "TELEGRAM_ALERT_CHAT_ID": "AWS Alerts",
        "TELEGRAM_CLAW_CHAT_ID": "Claw",
        "TELEGRAM_CHAT_ID_TRADING": "ATP Alerts",
    }
    for var, cid in sorted(extracted.items()):
        name = VAR_TO_NAME.get(var, var.replace("TELEGRAM_", "").replace("_CHAT_ID", ""))
        print(f"  {name} → {cid}")
    print("-" * 50)

    if do_restart_verify and not dry_run:
        print("\nRestarting backend-aws...")
        r = subprocess.run(
            ["docker", "compose", "--profile", "aws", "restart", "backend-aws"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"⚠️  Restart failed: {r.stderr or r.stdout}", file=sys.stderr)
        else:
            print("✅ Backend restarted.")

        print("\nRunning verification...")
        for script in ["verify_telegram_destinations.py", "validate_telegram_routing.py"]:
            p = REPO_ROOT / "scripts" / script
            if p.exists():
                r2 = subprocess.run([sys.executable, str(p)], cwd=REPO_ROOT)
                if r2.returncode != 0:
                    print(f"⚠️  {script} exited {r2.returncode}", file=sys.stderr)
    else:
        print("\n✅ Success. Run verification:")
        print("  python scripts/verify_telegram_destinations.py")
        print("  python scripts/validate_telegram_routing.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
