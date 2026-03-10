#!/usr/bin/env python3
"""
Lee TELEGRAM_BOT_TOKEN del .env.aws, lo cifra y escribe TELEGRAM_BOT_TOKEN_ENCRYPTED
en el mismo archivo y borra el token en claro. Sin dependencias externas (cifrado inline).
Ejecutar EN LA INSTANCIA EC2. No imprime el token.

Uso:
  cd /home/ubuntu/crypto-2.0 && python3 ops/encrypt_telegram_on_server.py
"""
import base64
import hmac
import hashlib
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IV_LEN = 16
KEY_LEN = 32
MAC_LEN = 32
ENV_KEY_LEGACY = "TELEGRAM_" + "BOT_TOKEN"
ENV_KEY_ENCRYPTED = "TELEGRAM_BOT_TOKEN_ENCRYPTED"
ENV_KEY_FILE = "TELEGRAM_KEY_FILE"


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    out = []
    n = (length + 31) // 32
    for i in range(n):
        block = hmac.new(key, iv + i.to_bytes(4, "big"), hashlib.sha256).digest()
        out.append(block)
    return b"".join(out)[:length]


def _encrypt_plaintext(plaintext: bytes, key: bytes) -> bytes:
    iv = secrets.token_bytes(IV_LEN)
    stream = _keystream(key, iv, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()[:MAC_LEN]
    return iv + ciphertext + mac


def _load_key(key_path: Path) -> bytes | None:
    if not key_path.is_file():
        return None
    raw = key_path.read_bytes()
    if len(raw) == KEY_LEN:
        return raw
    if len(raw) >= 64:
        try:
            hex_part = raw.decode("ascii").strip()
            if len(hex_part) == 64:
                return bytes.fromhex(hex_part)
        except (ValueError, UnicodeDecodeError):
            pass
    return raw[:KEY_LEN] if len(raw) >= KEY_LEN else None


def get_or_create_key(key_path: Path) -> bytes:
    key = _load_key(key_path)
    if key is not None:
        return key
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_LEN)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key


def main():
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / ".env.aws"
    if not env_path.is_file():
        print(f"Archivo no encontrado: {env_path}", file=sys.stderr)
        sys.exit(1)

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    token = None
    for line in lines:
        s = line.strip()
        if s.startswith(ENV_KEY_LEGACY + "="):
            token = s.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not token:
        print("No hay TELEGRAM_BOT_TOKEN en el archivo. Nada que cifrar.", file=sys.stderr)
        sys.exit(0)

    key_file = REPO_ROOT / "secrets" / "telegram_key"
    key = get_or_create_key(key_file)
    encrypted = _encrypt_plaintext(token.encode("utf-8"), key)
    encrypted_b64 = base64.b64encode(encrypted).decode("ascii")
    key_file_str = str(key_file)

    out = []
    found_encrypted = False
    has_key_file = False
    for line in lines:
        s = line.strip()
        if s.startswith(ENV_KEY_LEGACY + "="):
            continue
        if s.startswith(ENV_KEY_ENCRYPTED + "="):
            out.append(f"{ENV_KEY_ENCRYPTED}={encrypted_b64}\n")
            found_encrypted = True
            continue
        if s.startswith(ENV_KEY_FILE + "="):
            out.append(f"{ENV_KEY_FILE}={key_file_str}\n")
            has_key_file = True
            continue
        out.append(line)
    if not found_encrypted:
        out.append(f"{ENV_KEY_ENCRYPTED}={encrypted_b64}\n")
    if not has_key_file:
        out.append(f"{ENV_KEY_FILE}={key_file_str}\n")

    env_path.write_text("".join(out), encoding="utf-8")
    print("Listo: token cifrado. TELEGRAM_BOT_TOKEN eliminado del archivo.")
    print("Reinicia el backend: docker compose --profile aws up -d backend-aws")


if __name__ == "__main__":
    main()
