"""
Store the Fernet master key in the system secret store.

On macOS this uses Keychain via the keyring library. On Linux, Secret Service
or other backends are used. For CI/headless, set SECRET_CONSOLE_MASTER_KEY
(base64 urlsafe 32-byte key as produced by Fernet.generate_key()).
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

KEYRING_SERVICE = "secret-console"
KEYRING_USERNAME = "fernet-master-key"
_ENV_MASTER = "SECRET_CONSOLE_MASTER_KEY"


def _fernet_from_key_bytes(key: bytes) -> Fernet:
    return Fernet(key)


def get_or_create_fernet() -> Fernet:
    env_key = os.environ.get(_ENV_MASTER, "").strip()
    if env_key:
        log.info("using master key from %s", _ENV_MASTER)
        return Fernet(env_key.encode("ascii"))

    import keyring

    existing = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if existing:
        log.info("loaded master key from system keyring (%s)", KEYRING_SERVICE)
        return Fernet(existing.encode("ascii"))

    new_key = Fernet.generate_key()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, new_key.decode("ascii"))
    log.info("generated new master key and stored in system keyring (%s)", KEYRING_SERVICE)
    return Fernet(new_key)
