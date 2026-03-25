"""
Resolve TELEGRAM_BOT_TOKEN from env, optionally by decrypting TELEGRAM_BOT_TOKEN_ENCRYPTED.

Used at startup so the backend can use secrets/runtime.env with encrypted token only.
Algorithm must match scripts/setup_telegram_token.py (HMAC-SHA256 keystream + optional MAC).
"""
import base64
import hmac
import hashlib
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

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


def _looks_like_placeholder_token(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    if "YOUR_PRODUCTION" in t or "your_production" in t.lower():
        return True
    if t.upper() in ("CHANGE_ME", "CHANGE-ME", "CHANGEME"):
        return True
    return False


def _looks_like_telegram_bot_token(token: str) -> bool:
    """Shape check only (digits:secret); never logs the token."""
    t = (token or "").strip()
    if len(t) < 40 or ":" not in t:
        return False
    left, _, right = t.partition(":")
    if not left.isdigit() or not right:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", right))


def resolve_telegram_token_from_env() -> Optional[str]:
    """
    If TELEGRAM_BOT_TOKEN is set, return it. Else if TELEGRAM_BOT_TOKEN_ENCRYPTED
    is set, decrypt with key from TELEGRAM_KEY_FILE (or /app/secrets/telegram_key)
    and return. Otherwise return None. Never log or print the token.
    """
    plain = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if plain:
        if _looks_like_placeholder_token(plain):
            logger.warning(
                "[TG][CONFIG] TELEGRAM_BOT_TOKEN appears to be a placeholder; "
                "use a real token or TELEGRAM_BOT_TOKEN_ENCRYPTED + TELEGRAM_KEY_FILE"
            )
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_BOT_TOKEN_AWS", None)
            plain = ""
        elif not _looks_like_telegram_bot_token(plain):
            logger.warning(
                "[TG][CONFIG] TELEGRAM_BOT_TOKEN has invalid shape (expected 123456789:AA...); ignoring"
            )
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_BOT_TOKEN_AWS", None)
            plain = ""
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
        decoded = raw.decode("utf-8").strip()
        if not _looks_like_telegram_bot_token(decoded):
            logger.warning(
                "[TG][CONFIG] Decrypted TELEGRAM_BOT_TOKEN_ENCRYPTED is not a valid bot token shape; "
                "check TELEGRAM_KEY_FILE matches the key used to encrypt (or use plaintext token in runtime.env)"
            )
            return None
        return decoded
    except Exception:
        return None
