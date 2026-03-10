#!/usr/bin/env python3
"""
Rotate the Telegram token encryption key (.telegram_key).

HOW TO RUN:
  From the project root:
    python scripts/rotate_telegram_key.py

  Uses repo root .env and .telegram_key. Decrypts with current key,
  generates a new key, re-encrypts, and updates .env atomically.
  Does not print or log the token.
"""

import base64
import hmac
import hashlib
import os
import secrets
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_ENV_PATH = os.path.join(REPO_ROOT, ".env")
DEFAULT_KEY_PATH = os.path.join(REPO_ROOT, ".telegram_key")

IV_LEN = 16
KEY_LEN = 32
MAC_LEN = 32
ENV_KEY_ENCRYPTED = "TELEGRAM_BOT_TOKEN_ENCRYPTED"
# Deprecated: plaintext env key (do not set); used only to detect/remove from .env
ENV_KEY_LEGACY = "TELEGRAM_" + "BOT_TOKEN"


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    n = (length + 31) // 32
    out = []
    for i in range(n):
        block = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
        out.append(block)
    return b"".join(out)[:length]


def _decrypt_blob(blob: bytes, key: bytes) -> bytes:
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


def _encrypt_plaintext(plaintext: bytes, key: bytes) -> bytes:
    iv = secrets.token_bytes(IV_LEN)
    stream = _keystream(key, iv, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()[:MAC_LEN]
    return iv + ciphertext + mac


def _load_key(key_path: str) -> bytes | None:
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


def _read_env_lines(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def main() -> None:
    env_path = os.environ.get("TELEGRAM_ENV_FILE", DEFAULT_ENV_PATH)
    key_path = os.environ.get("TELEGRAM_KEY_FILE", DEFAULT_KEY_PATH)

    if not os.path.isfile(env_path):
        print("Cannot rotate key: .env not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(key_path):
        print("Cannot rotate key: .telegram_key not found.", file=sys.stderr)
        sys.exit(1)

    lines = _read_env_lines(env_path)
    encrypted_b64 = None
    for line in lines:
        s = line.strip()
        if s.startswith(ENV_KEY_ENCRYPTED + "="):
            encrypted_b64 = s.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not encrypted_b64:
        print("Cannot rotate key: TELEGRAM_BOT_TOKEN_ENCRYPTED not found in .env.", file=sys.stderr)
        sys.exit(1)

    key_old = _load_key(key_path)
    if key_old is None:
        print("Cannot rotate key: could not read .telegram_key.", file=sys.stderr)
        sys.exit(1)
    try:
        blob = base64.b64decode(encrypted_b64)
        token_bytes = _decrypt_blob(blob, key_old)
    except Exception:
        print("Cannot rotate key: decryption failed. Ensure .env and .telegram_key match.", file=sys.stderr)
        sys.exit(1)

    key_new = secrets.token_bytes(KEY_LEN)
    with open(key_path, "wb") as f:
        f.write(key_new)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    encrypted_new = _encrypt_plaintext(token_bytes, key_new)
    encrypted_b64_new = base64.b64encode(encrypted_new).decode("ascii")
    new_line = f"{ENV_KEY_ENCRYPTED}={encrypted_b64_new}\n"

    out_lines = []
    for line in lines:
        if line.strip().startswith(ENV_KEY_ENCRYPTED + "="):
            out_lines.append(new_line)
        elif line.strip().startswith(ENV_KEY_LEGACY + "="):
            continue
        else:
            out_lines.append(line)

    env_dir = os.path.dirname(os.path.abspath(env_path))
    fd, tmp = tempfile.mkstemp(dir=env_dir or ".", prefix=".env.rotate.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(out_lines)
        os.replace(tmp, env_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    print("Rotated Telegram key successfully")
    print("Updated TELEGRAM_BOT_TOKEN_ENCRYPTED in .env")


if __name__ == "__main__":
    main()
