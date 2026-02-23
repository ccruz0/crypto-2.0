"""
Resolve Telegram bot token from TELEGRAM_BOT_TOKEN_ENCRYPTED only.
Decrypt using key from TELEGRAM_KEY_FILE (default /run/secrets/telegram_key).
Deprecated: TELEGRAM_BOT_TOKEN (plaintext) is not supported.
Algorithm must match scripts/setup_telegram_token.py (HMAC-SHA256 counter mode).
Never log or print the decrypted token.
"""

import base64
import hmac
import hashlib
import os
from typing import Tuple

# Repo root: backend/app/core -> backend -> repo
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_ROOT = os.path.dirname(_BACKEND_ROOT)
DEFAULT_ENV_PATH = os.path.join(REPO_ROOT, ".env")

IV_LEN = 16
KEY_LEN = 32
MAC_LEN = 32  # HMAC-SHA256 truncated to 32 bytes for ciphertext authentication
ENV_KEY_ENCRYPTED = "TELEGRAM_BOT_TOKEN_ENCRYPTED"

# Default key path for production (Docker); override with TELEGRAM_KEY_FILE
DEFAULT_KEY_PATH = "/run/secrets/telegram_key"


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    """Generate keystream (must match script)."""
    out = []
    n = (length + 31) // 32
    for i in range(n):
        block = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
        out.append(block)
    return b"".join(out)[:length]


def _decrypt_blob(blob: bytes, key: bytes) -> bytes:
    """Decrypt blob: (IV || ciphertext) legacy, or (IV || ciphertext || MAC) with auth."""
    if len(blob) < IV_LEN:
        raise ValueError("Invalid encrypted blob")
    iv = blob[:IV_LEN]
    if len(blob) > IV_LEN + MAC_LEN:
        ct = blob[IV_LEN:-MAC_LEN]
        mac = blob[-MAC_LEN:]
        expected = hmac.new(key, iv + ct, hashlib.sha256).digest()[:MAC_LEN]
        if not hmac.compare_digest(expected, mac):
            raise ValueError("Telegram token ciphertext authentication failed (MAC mismatch)")
    else:
        ct = blob[IV_LEN:]
    stream = _keystream(key, iv, len(ct))
    return bytes(a ^ b for a, b in zip(ct, stream))


def _load_key(key_path: str) -> bytes | None:
    """Load 32-byte key from file. None if missing or invalid."""
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


def get_telegram_token(
    env_path: str | None = None,
    key_path: str | None = None,
) -> str | None:
    """
    Read TELEGRAM_BOT_TOKEN_ENCRYPTED from os.environ, decrypt with key from TELEGRAM_KEY_FILE.
    key_path defaults to os.environ.get("TELEGRAM_KEY_FILE") or /run/secrets/telegram_key.
    Raises RuntimeError if encrypted value is present but key file is missing. Returns None if no encrypted value.
    Never logs the token.
    """
    encrypted_b64 = (os.environ.get(ENV_KEY_ENCRYPTED) or "").strip().strip('"').strip("'")
    if not encrypted_b64:
        env_path = env_path or DEFAULT_ENV_PATH
        if os.path.isfile(env_path):
            for line in _read_env_lines(env_path):
                s = line.strip()
                if s.startswith(ENV_KEY_ENCRYPTED + "="):
                    encrypted_b64 = s.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not encrypted_b64:
        return None
    key_path = key_path or os.environ.get("TELEGRAM_KEY_FILE") or DEFAULT_KEY_PATH
    key = _load_key(key_path)
    if key is None:
        raise RuntimeError(
            f"Telegram key file missing or invalid: {key_path}. "
            "Set TELEGRAM_KEY_FILE or create the key file (e.g. run scripts/setup_telegram_token.py)."
        )
    try:
        blob = base64.b64decode(encrypted_b64)
        plain = _decrypt_blob(blob, key)
        return plain.decode("utf-8")
    except Exception as e:
        raise RuntimeError("Telegram token decryption failed. Check key file and TELEGRAM_BOT_TOKEN_ENCRYPTED.") from e


def resolve_telegram_token(
    env_path: str | None = None,
    key_path: str | None = None,
) -> Tuple[str | None, bool]:
    """
    Resolve bot token from TELEGRAM_BOT_TOKEN_ENCRYPTED only (decrypt with key file).
    Returns (token, True). Raises if key file missing or decryption fails.
    Never logs the token.
    """
    # Deprecated: plaintext TELEGRAM_BOT_TOKEN must not be set in environment (injection risk).
    _plaintext_key = "TELEGRAM_" + "BOT_TOKEN"
    if _plaintext_key in os.environ:
        raise RuntimeError(
            "Plaintext bot token must not be set in env. Use TELEGRAM_BOT_TOKEN_ENCRYPTED and TELEGRAM_KEY_FILE only."
        )
    token = get_telegram_token(env_path=env_path, key_path=key_path)
    if token is None:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN_ENCRYPTED is required. Run scripts/setup_telegram_token.py and set TELEGRAM_BOT_TOKEN_ENCRYPTED."
        )
    return (token, True)


def decrypt_token(
    env_path: str | None = None,
    key_path: str | None = None,
) -> str | None:
    """
    Read TELEGRAM_BOT_TOKEN_ENCRYPTED from environment or .env file, decrypt with key from file.
    Key path: TELEGRAM_KEY_FILE env or key_path arg or default /run/secrets/telegram_key.
    Raises RuntimeError if key file missing. Returns None if no encrypted value present.
    """
    return get_telegram_token(env_path=env_path, key_path=key_path)
