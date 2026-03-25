"""AES encryption for secret values using Fernet (cryptography)."""

from __future__ import annotations

import logging
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


def encrypt_value(fernet: Fernet, plaintext: str) -> str:
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_value(fernet: Fernet, ciphertext: str) -> str:
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        log.error("decrypt failed: invalid token or wrong key")
        raise ValueError("Could not decrypt secret (wrong master key or corrupt data)") from e
