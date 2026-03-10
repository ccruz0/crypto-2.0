#!/usr/bin/env python3
"""Send a test Telegram message using encrypted token (stdlib + setup_telegram_token)."""
import os
import sys
import urllib.request
import urllib.error
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(REPO_ROOT, ".env")


def _load_dotenv(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)


def main() -> int:
    _load_dotenv(ENV_PATH)
    _load_dotenv(os.path.join(REPO_ROOT, ".env.local"))
    _load_dotenv(os.path.join(REPO_ROOT, ".env.aws"))
    _load_dotenv(os.path.join(REPO_ROOT, "secrets", "runtime.env"))
    if not os.environ.get("TELEGRAM_KEY_FILE") and os.path.isfile(os.path.join(REPO_ROOT, "secrets", "telegram_key")):
        os.environ["TELEGRAM_KEY_FILE"] = os.path.join(REPO_ROOT, "secrets", "telegram_key")
    sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
    sys.path.insert(0, REPO_ROOT)
    from app.core.telegram_secrets import decrypt_token
    token = decrypt_token(
        env_path=os.path.join(REPO_ROOT, ".env"),
        key_path=os.environ.get("TELEGRAM_KEY_FILE") or os.path.join(REPO_ROOT, ".telegram_key"),
    )
    if not token:
        print("No token: TELEGRAM_BOT_TOKEN_ENCRYPTED not available or decryption failed.", file=sys.stderr)
        return 1
    chat_id = (
        (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID_AWS") or os.getenv("TELEGRAM_CHAT_ID_LOCAL") or "").strip()
    )
    if not chat_id:
        print(
            "TELEGRAM_CHAT_ID not set. Add TELEGRAM_CHAT_ID=your_chat_id to .env or .env.local",
            file=sys.stderr,
        )
        return 1
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🧪 Mensaje de prueba – ATP Telegram (envío mínimo). Si ves esto, el token cifrado y el chat están bien.",
        "parse_mode": "HTML",
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            print("✅ Mensaje de prueba enviado a Telegram.")
            return 0
        print("Error API:", data, file=sys.stderr)
        return 1
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code, e.read().decode() if e.fp else "", file=sys.stderr)
        return 1
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
