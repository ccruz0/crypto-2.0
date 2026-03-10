#!/usr/bin/env python3
"""
Cifra el token de Telegram para usar en AWS (TELEGRAM_BOT_TOKEN_ENCRYPTED + clave).

Uso (desde la raíz del repo):
  python3 ops/encrypt_telegram_for_aws.py

  - Pide el token por terminal (no se muestra).
  - Crea secrets/telegram_key si no existe.
  - Escribe la línea TELEGRAM_BOT_TOKEN_ENCRYPTED=... para que la copies a .env.aws.
  - En EC2: copia secrets/telegram_key y esa línea; pon TELEGRAM_KEY_FILE apuntando a la clave.
  - Borra TELEGRAM_BOT_TOKEN (texto plano) de .env.aws y secrets/runtime.env.
"""
import base64
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Añadir repo root para importar scripts
sys.path.insert(0, str(REPO_ROOT))

# Reutilizar cifrado del script oficial
from scripts.setup_telegram_token import (
    get_or_create_key,
    _encrypt_plaintext,
    validate_format,
    ENV_KEY_ENCRYPTED,
)

KEY_FILE = REPO_ROOT / "secrets" / "telegram_key"


def main():
    print("Token de Telegram (se usará solo para cifrarlo; no se mostrará).")
    token = (getpass.getpass("Pega el token: ") or "").strip()
    if not token:
        print("No se introdujo token. Salida.", file=sys.stderr)
        sys.exit(1)
    if not validate_format(token):
        print("Formato inválido. Debe ser números:letras (ej: 123456789:ABCdef...).", file=sys.stderr)
        sys.exit(1)

    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key_path = str(KEY_FILE)
    key = get_or_create_key(key_path)
    encrypted = _encrypt_plaintext(token.encode("utf-8"), key)
    encrypted_b64 = base64.b64encode(encrypted).decode("ascii")

    print()
    print("=" * 60)
    print("1) Añade esta línea a .env.aws (y quita TELEGRAM_BOT_TOKEN):")
    print("=" * 60)
    print(f"{ENV_KEY_ENCRYPTED}={encrypted_b64}")
    print()
    print("2) Sube la clave a EC2 (no la subas a git):")
    print(f"   scp -i ~/.ssh/atp-rebuild-2026.pem {KEY_FILE} ubuntu@52.220.32.147:/home/ubuntu/crypto-2.0/secrets/telegram_key")
    print()
    print("3) En .env.aws de la instancia, asegura:")
    print("   TELEGRAM_KEY_FILE=/home/ubuntu/crypto-2.0/secrets/telegram_key")
    print("   (o la ruta donde hayas dejado el archivo)")
    print()
    print("4) Elimina TELEGRAM_BOT_TOKEN de .env.aws y de secrets/runtime.env en la instancia.")
    print("5) Reinicia el backend: docker compose --profile aws up -d backend-aws")
    print("=" * 60)
    print(f"Clave guardada en: {KEY_FILE}")
    print("(Añade secrets/telegram_key a .gitignore si no está.)")


if __name__ == "__main__":
    main()
