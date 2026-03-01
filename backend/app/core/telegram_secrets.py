"""
Resolve TELEGRAM_BOT_TOKEN from env, optionally by decrypting TELEGRAM_BOT_TOKEN_ENCRYPTED.

Used at startup so the backend can use secrets/runtime.env with encrypted token only.
Algorithm must match scripts/setup_telegram_token.py (HMAC-SHA256 keystream + optional MAC).
"""
import base64
import hmac
import hashlib
import os
from typing import Optional

IV_LEN = 16
KEY_LEN = 32
MAC_LEN = 32


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    out = []
    n = (length + 31) // 32
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


def _load_key(key_path: str) -> Optional[bytes]:
    if not os.path.isfile(key_path):
        return None
    try:
        with open(key_path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
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


def resolve_telegram_token_from_env() -> Optional[str]:
    """
    If TELEGRAM_BOT_TOKEN is set, return it. Else if TELEGRAM_BOT_TOKEN_ENCRYPTED
    is set, decrypt with key from TELEGRAM_KEY_FILE (or /app/secrets/telegram_key)
    and return. Otherwise return None. Never log or print the token.
    """
    plain = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if plain:
        return plain
    encrypted_b64 = (os.environ.get("TELEGRAM_BOT_TOKEN_ENCRYPTED") or "").strip()
    if not encrypted_b64:
        return None
    key_path = os.environ.get("TELEGRAM_KEY_FILE") or "/app/secrets/telegram_key"
    key = _load_key(key_path)
    if not key:
        return None
    pad = 4 - (len(encrypted_b64) % 4)
    if pad != 4:
        encrypted_b64 = encrypted_b64 + ("=" * pad)
    try:
        blob = base64.b64decode(encrypted_b64)
        raw = _decrypt_blob(blob, key)
        return raw.decode("utf-8")
    except Exception:
        return None
