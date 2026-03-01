#!/usr/bin/env python3
"""
Setup Telegram Bot token securely (interactive popup).

HOW TO RUN:
  From the project root:
    python scripts/setup_telegram_token.py

  Or with Python 3 explicitly:
    python3 scripts/setup_telegram_token.py

  The script opens a small window to paste your token. The token is never
  printed to the terminal or logs. If valid, it is encrypted and stored
  in .env as TELEGRAM_BOT_TOKEN_ENCRYPTED.

  ENCRYPTION:
    - Symmetric encryption using a key derived from the file .telegram_key.
    - Cipher: HMAC-SHA256 in counter mode (keystream XOR plaintext); IV is
      prepended to the ciphertext. Standard library only (hmac, hashlib, secrets).
    - Stored value in .env is base64(IV || ciphertext).

  KEY STORAGE:
    - The encryption key is stored in .telegram_key (project root, next to .env).
    - If the file does not exist, a 32-byte secure random key is generated
      and written; file mode is set to 0o600 (owner read/write only).
    - Keep .telegram_key secret and out of version control.
    - For production: store key outside repo, e.g.
      TELEGRAM_KEY_FILE=~/.atp_secrets/.telegram_key

  KEY ROTATION:
    - To rotate safely: (1) Run this script again and paste the same token
      (re-encrypts with existing key), or (2) Delete .telegram_key, run the
      script and paste the token (new key is generated; old encrypted value
      in .env becomes unusable). Ensure no process still relies on the old
      .env before rotating.
"""

import base64
import hmac
import hashlib
import re
import os
import secrets
import sys
import urllib.request
import urllib.error

# Default paths: project root (parent of scripts/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_ENV_PATH = os.path.join(REPO_ROOT, ".env")
# Encryption key file: 32 bytes binary. Create with restricted permissions if missing.
DEFAULT_KEY_PATH = os.path.join(REPO_ROOT, ".telegram_key")

IV_LEN = 16
KEY_LEN = 32
MAC_LEN = 32  # HMAC-SHA256 for ciphertext authentication
ENV_KEY_ENCRYPTED = "TELEGRAM_BOT_TOKEN_ENCRYPTED"
# Deprecated: plaintext env key (do not set); used only to detect/remove from .env
ENV_KEY_LEGACY = "TELEGRAM_" + "BOT_TOKEN"


def _is_encryption_required() -> bool:
    v = (os.environ.get("TELEGRAM_ENCRYPTION_REQUIRED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_has_plaintext_token(env_path: str) -> bool:
    if (os.environ.get(ENV_KEY_LEGACY) or "").strip():
        return True
    if not os.path.isfile(env_path):
        return False
    for line in read_env_lines(env_path):
        s = line.strip()
        if s.startswith(ENV_KEY_LEGACY + "="):
            val = s.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(val)
    return False


# Telegram token format: digits, colon, then alphanumeric/underscore/dash
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]+$")
GET_ME_URL = "https://api.telegram.org/bot{token}/getMe"


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    """Generate deterministic keystream via HMAC-SHA256 in counter mode (stdlib only)."""
    out = []
    n = (length + 31) // 32
    for i in range(n):
        block = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
        out.append(block)
    return b"".join(out)[:length]


def _encrypt_plaintext(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt: IV || ciphertext || MAC (HMAC-SHA256 of IV||ciphertext)."""
    iv = secrets.token_bytes(IV_LEN)
    stream = _keystream(key, iv, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()[:MAC_LEN]
    return iv + ciphertext + mac


def _decrypt_blob(blob: bytes, key: bytes) -> bytes:
    """Decrypt: legacy (IV||ct) or authenticated (IV||ct||MAC)."""
    if len(blob) < IV_LEN:
        raise ValueError("Invalid encrypted blob")
    iv = blob[:IV_LEN]
    if len(blob) > IV_LEN + MAC_LEN:
        ct = blob[IV_LEN:-MAC_LEN]
        mac = blob[-MAC_LEN:]
        expected = hmac.new(key, iv + ct, hashlib.sha256).digest()[:MAC_LEN]
        if not hmac.compare_digest(expected, mac):
            raise ValueError("Ciphertext authentication failed (MAC mismatch)")
    else:
        ct = blob[IV_LEN:]
    stream = _keystream(key, iv, len(ct))
    return bytes(a ^ b for a, b in zip(ct, stream))


def _load_key(key_path: str) -> bytes | None:
    """Load 32-byte key from key_path. Returns None if file missing or invalid."""
    if not os.path.isfile(key_path):
        return None
    raw = open(key_path, "rb").read()
    if len(raw) == KEY_LEN:
        return raw
    if len(raw) >= 64:
        try:
            hex_part = raw.decode("ascii").strip()
            if len(hex_part) == 64:
                return bytes.fromhex(hex_part)
        except (ValueError, UnicodeDecodeError):
            pass
    if len(raw) >= KEY_LEN:
        return raw[:KEY_LEN]
    return None


def get_or_create_key(key_path: str) -> bytes:
    """
    Load 32-byte key from key_path. If file does not exist, generate a secure
    random key, write it with mode 0o600, and return it.
    """
    key = _load_key(key_path)
    if key is not None:
        return key
    key = secrets.token_bytes(KEY_LEN)
    with open(key_path, "wb") as f:
        f.write(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


def decrypt_token(env_path: str | None = None, key_path: str | None = None) -> str | None:
    """
    Read TELEGRAM_BOT_TOKEN_ENCRYPTED from .env, decrypt with the key from
    .telegram_key, and return the raw token. Returns None if env/key/value
    is missing or decryption fails.
    """
    env_path = env_path or DEFAULT_ENV_PATH
    key_path = key_path or DEFAULT_KEY_PATH
    key = _load_key(key_path)
    if key is None or not os.path.isfile(env_path):
        return None
    lines = read_env_lines(env_path)
    encrypted_b64 = None
    for line in lines:
        s = line.strip()
        if s.startswith(ENV_KEY_ENCRYPTED + "="):
            encrypted_b64 = s.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not encrypted_b64:
        return None
    # Ensure valid base64 length (multiple of 4) so decode never fails on padding
    pad = 4 - (len(encrypted_b64) % 4)
    if pad != 4:
        encrypted_b64 = encrypted_b64 + ("=" * pad)
    try:
        blob = base64.b64decode(encrypted_b64)
        plain = _decrypt_blob(blob, key)
        return plain.decode("utf-8")
    except Exception:
        return None


def _get_token_via_gui():
    """Show a small GUI window to paste the token; never print it."""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    token = simpledialog.askstring(
        "Telegram Bot Token",
        "Please paste your Telegram Bot API token",
        show="*",
        parent=root,
    )
    root.destroy()
    return (token or "").strip()


def _get_token_fallback():
    """Fallback: read from terminal with a warning (no echo)."""
    try:
        import getpass
        return (getpass.getpass("Paste your Telegram Bot API token: ") or "").strip()
    except Exception:
        return ""


def get_token():
    """Obtain token via GUI if possible, else secure terminal input."""
    token = _get_token_via_gui()
    if token is None:
        print("GUI not available. Using terminal input (token will be hidden).")
        token = _get_token_fallback()
    return token


def validate_format(token):
    """Check token matches Telegram format (numbers:letters)."""
    return bool(token and TELEGRAM_TOKEN_PATTERN.match(token))


def test_telegram_token(token):
    """
    Call Telegram getMe API. Returns (ok: bool, data: dict or None).
    Never logs or prints the token.
    """
    url = GET_ME_URL.format(token=token)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        return False, {"description": body or str(e)}
    except Exception as e:
        return False, {"description": str(e)}

    try:
        import json
        out = json.loads(data)
        return out.get("ok") is True, out.get("result") if out.get("ok") else out
    except Exception:
        return False, {"description": "Invalid API response"}


def read_env_lines(path):
    """Read .env lines; return list of lines."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def write_env_with_token(env_path: str, token: str, key_path: str | None = None) -> bool:
    """
    Encrypt the token with the key from key_path, then update or add
    TELEGRAM_BOT_TOKEN_ENCRYPTED in .env. Removes any existing TELEGRAM_BOT_TOKEN
    line so the raw token is never stored in plaintext.
    Returns True if a plaintext TELEGRAM_BOT_TOKEN line was removed.
    """
    key_path = key_path or DEFAULT_KEY_PATH
    key = get_or_create_key(key_path)
    encrypted = _encrypt_plaintext(token.encode("utf-8"), key)
    encrypted_b64 = base64.b64encode(encrypted).decode("ascii")
    new_line = f"{ENV_KEY_ENCRYPTED}={encrypted_b64}\n"

    lines = read_env_lines(env_path)
    found_encrypted = False
    removed_legacy = False
    out = []
    for line in lines:
        if line.strip().startswith(ENV_KEY_ENCRYPTED + "="):
            out.append(new_line)
            found_encrypted = True
        elif line.strip().startswith(ENV_KEY_LEGACY + "="):
            removed_legacy = True
            continue
        else:
            out.append(line)
    if not found_encrypted:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"\n# Telegram (encrypted)\n{new_line}")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(out)
    return removed_legacy


def main():
    env_path = os.environ.get("TELEGRAM_ENV_FILE", DEFAULT_ENV_PATH)
    key_path = os.environ.get("TELEGRAM_KEY_FILE", DEFAULT_KEY_PATH)

    if _is_encryption_required() and _env_has_plaintext_token(env_path):
        print(
            "Encrypted Telegram token required. Remove plaintext token from env and .env, then run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    token = get_token()
    if not token:
        print("No token provided. Exiting.")
        sys.exit(1)

    if not validate_format(token):
        print("Invalid token format. Expected format: numbers:letters (e.g. 123456789:ABCdef...)")
        sys.exit(1)

    ok, result = test_telegram_token(token)
    if not ok:
        err = result.get("description", "Unknown error") if isinstance(result, dict) else str(result)
        print("Token validation failed:", err)
        sys.exit(1)

    # result is the getMe "result" object: id, is_bot, first_name, username, etc.
    bot_id = result.get("id", "")
    username = result.get("username", "")
    first_name = result.get("first_name", "")

    removed_legacy = write_env_with_token(env_path, token, key_path)
    if removed_legacy:
        print("Removed plaintext token from .env")
    print("Token is valid.")
    print("Bot username:", username or "(none)")
    print("Bot ID:", bot_id)
    if first_name:
        print("Bot name:", first_name)
    print("Token stored encrypted as", ENV_KEY_ENCRYPTED, "in:", env_path)
    print("Encryption key file:", key_path)
    print("Bot is ready.")


if __name__ == "__main__":
    main()
