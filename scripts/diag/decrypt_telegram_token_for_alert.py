#!/usr/bin/env python3
"""
Write decrypted TELEGRAM_BOT_TOKEN to a file (for health_snapshot_telegram_alert.sh).
Uses the same decrypt method as scripts/setup_telegram_token.py. Does not print secrets.
Usage: decrypt_telegram_token_for_alert.py <output_file>
Exit 0 and write token to output_file on success; exit 1 on failure (no write).
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def main() -> int:
    if len(sys.argv) != 2:
        return 1
    out_path = sys.argv[1]
    if not out_path or os.path.isdir(out_path):
        return 1

    # Reuse decrypt from setup_telegram_token (same repo)
    import importlib.util
    setup_path = os.path.join(REPO_ROOT, "scripts", "setup_telegram_token.py")
    if not os.path.isfile(setup_path):
        return 1
    spec = importlib.util.spec_from_file_location("setup_telegram_token", setup_path)
    if spec is None or spec.loader is None:
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    decrypt_token = getattr(mod, "decrypt_token", None)
    if decrypt_token is None:
        return 1

    key_path = os.environ.get("TELEGRAM_KEY_FILE") or os.path.join(REPO_ROOT, ".telegram_key")
    if not os.path.isfile(key_path):
        key_path = os.path.join(REPO_ROOT, "secrets", "telegram_key")
    if not os.path.isfile(key_path):
        return 1

    for env_name in (".env", ".env.aws", "secrets/runtime.env"):
        env_path = os.path.join(REPO_ROOT, env_name)
        token = decrypt_token(env_path=env_path, key_path=key_path)
        if token:
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(token)
                os.chmod(out_path, 0o600)
            except OSError:
                return 1
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
