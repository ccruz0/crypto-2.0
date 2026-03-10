#!/usr/bin/env python3
"""
Interactive setup for .env.aws and secrets/runtime.env.
Asks for each variable one by one; you can paste values at each prompt.
Output: .env.aws and (optionally) secrets/runtime.env in the repo root or a chosen dir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root (script lives in ops/)
REPO_ROOT = Path(__file__).resolve().parent.parent

# Width for the "window" around each prompt
WIDTH = 72


def sep(title: str = "", char: str = "=") -> None:
    if title:
        padding = (WIDTH - 4 - len(title)) // 2
        print(f"\n{char * WIDTH}")
        print(f"{char}  {' ' * max(0, padding)}{title}{' ' * max(0, WIDTH - 4 - padding - len(title))}  {char}")
        print(f"{char * WIDTH}\n")
    else:
        print(f"{char * WIDTH}\n")


def prompt_var(name: str, hint: str, default: str = "", secret: bool = False) -> str:
    """Show a clear block for one variable and read the value (paste-friendly)."""
    sep(f" {name} ", "-")
    print(f"  {hint}")
    if default:
        print(f"  (default: {default if not secret else '***'})")
    print()
    prompt = f"  Pegar valor para {name}: "
    try:
        value = input(prompt).strip()
    except EOFError:
        value = ""
    if not value and default:
        value = default
    return value


# Variables for .env.aws (name, hint, default, secret)
ENV_AWS_VARS = [
    ("POSTGRES_DB", "Base de datos PostgreSQL.", "atp", False),
    ("POSTGRES_USER", "Usuario PostgreSQL.", "trader", False),
    ("POSTGRES_PASSWORD", "Contraseña de PostgreSQL (generar segura).", "", True),
    ("SECRET_KEY", "Clave para sesiones/tokens (generar: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\" ).", "", True),
    ("ADMIN_ACTIONS_KEY", "Clave para acciones de administración.", "", True),
    ("DIAGNOSTICS_API_KEY", "Clave para endpoints de diagnóstico.", "", True),
    ("TELEGRAM_BOT_TOKEN_ENCRYPTED", "Token de Telegram cifrado (base64). Opcional si no usas Telegram.", "", True),
    ("TELEGRAM_CHAT_ID", "Chat ID de Telegram (número).", "", False),
    ("TELEGRAM_CHAT_ID_AWS", "Chat ID para AWS (mismo que TELEGRAM_CHAT_ID si es el mismo canal).", "", False),
    ("RUN_TELEGRAM", "Enviar alertas por Telegram (true/false).", "true", False),
    ("EXCHANGE_CUSTOM_BASE_URL", "URL base API Crypto.com.", "https://api.crypto.com/exchange/v1", False),
    ("CRYPTO_REST_BASE", "URL REST Crypto.com.", "https://api.crypto.com/exchange/v1", False),
    ("EXCHANGE_CUSTOM_API_KEY", "API Key de Crypto.com Exchange.", "", True),
    ("EXCHANGE_CUSTOM_API_SECRET", "API Secret de Crypto.com Exchange.", "", True),
    ("USE_CRYPTO_PROXY", "Usar proxy para Crypto (true/false). En EC2 directo: false.", "false", False),
    ("LIVE_TRADING", "Trading en vivo (true/false).", "true", False),
    ("AWS_INSTANCE_IP", "IP elástica de la instancia EC2 (para whitelist en Exchange).", "", False),
    ("ENVIRONMENT", "Entorno (aws/local).", "aws", False),
    ("APP_ENV", "Identificador de app (aws/local).", "aws", False),
    ("RUNTIME_ORIGIN", "Origen en runtime (AWS/LOCAL).", "AWS", False),
    ("API_BASE_URL", "URL base de la API (interno: http://backend-aws:8002).", "http://backend-aws:8002", False),
    ("FRONTEND_URL", "URL pública del frontend (ej: https://dashboard.hilovivo.com).", "https://dashboard.hilovivo.com", False),
    ("NEXT_PUBLIC_API_URL", "Path público de la API para el frontend.", "/api", False),
    ("NEXT_PUBLIC_ENVIRONMENT", "Entorno público (aws/local).", "aws", False),
    ("ENABLE_DIAGNOSTICS_ENDPOINTS", "Habilitar endpoints de diagnóstico (0/1).", "1", False),
    ("GRAFANA_ADMIN_USER", "Usuario admin Grafana (opcional).", "admin", False),
    ("GF_SECURITY_ADMIN_PASSWORD", "Contraseña admin Grafana (opcional).", "", True),
]

# Variables for secrets/runtime.env (sensitive only; can reuse from .env.aws)
RUNTIME_ENV_VARS = [
    ("TELEGRAM_BOT_TOKEN_ENCRYPTED", "Token Telegram cifrado (base64).", True),
    ("TELEGRAM_CHAT_ID", "Chat ID Telegram.", False),
    ("ADMIN_ACTIONS_KEY", "Clave acciones admin.", True),
    ("DIAGNOSTICS_API_KEY", "Clave diagnóstico API.", True),
]


def build_database_url(user: str, password: str, host: str, db: str) -> str:
    return f"postgresql://{user}:{password}@{host}:5432/{db}"


def main() -> None:
    out_dir = Path(os.environ.get("ATP_ENV_OUTPUT_DIR", str(REPO_ROOT)))
    out_dir.mkdir(parents=True, exist_ok=True)
    env_aws_path = out_dir / ".env.aws"
    runtime_env_path = out_dir / "secrets" / "runtime.env"

    sep(" Configuración .env.aws (uno por uno, pega y Enter) ", "=")
    print("  Deja vacío y Enter para usar el valor por defecto cuando exista.")
    print("  Escribe 's' o 'skip' para saltar el resto de opcionales (opcional).\n")

    values: dict[str, str] = {}
    for name, hint, default, secret in ENV_AWS_VARS:
        val = prompt_var(name, hint, default, secret)
        if val.lower() in ("s", "skip") and default:
            val = default
        values[name] = val

    # DATABASE_URL from POSTGRES_*
    if values.get("POSTGRES_PASSWORD"):
        values["DATABASE_URL"] = build_database_url(
            values.get("POSTGRES_USER", "trader"),
            values["POSTGRES_PASSWORD"],
            "db",
            values.get("POSTGRES_DB", "atp"),
        )
    else:
        values["DATABASE_URL"] = "postgresql://trader:CHANGE_ME@db:5432/atp"

    # Write .env.aws (grouped with comments)
    lines = [
        "# ATP production .env.aws - generated by ops/interactive_env_setup.py",
        "# Do NOT commit real values.",
        "",
        "# --- Database ---",
        f"POSTGRES_DB={values.get('POSTGRES_DB', 'atp')}",
        f"POSTGRES_USER={values.get('POSTGRES_USER', 'trader')}",
        f"POSTGRES_PASSWORD={values.get('POSTGRES_PASSWORD', '')}",
        f"DATABASE_URL={values['DATABASE_URL']}",
        "",
        "# --- App security ---",
        f"SECRET_KEY={values.get('SECRET_KEY', '')}",
        f"ADMIN_ACTIONS_KEY={values.get('ADMIN_ACTIONS_KEY', '')}",
        f"DIAGNOSTICS_API_KEY={values.get('DIAGNOSTICS_API_KEY', '')}",
        f"ENABLE_DIAGNOSTICS_ENDPOINTS={values.get('ENABLE_DIAGNOSTICS_ENDPOINTS', '1')}",
        "",
        "# --- Telegram ---",
        f"TELEGRAM_BOT_TOKEN_ENCRYPTED={values.get('TELEGRAM_BOT_TOKEN_ENCRYPTED', '')}",
        f"TELEGRAM_CHAT_ID={values.get('TELEGRAM_CHAT_ID', '')}",
        f"TELEGRAM_CHAT_ID_AWS={values.get('TELEGRAM_CHAT_ID_AWS', '')}",
        f"RUN_TELEGRAM={values.get('RUN_TELEGRAM', 'true')}",
        "",
        "# --- Crypto.com Exchange ---",
        f"EXCHANGE_CUSTOM_BASE_URL={values.get('EXCHANGE_CUSTOM_BASE_URL', 'https://api.crypto.com/exchange/v1')}",
        f"CRYPTO_REST_BASE={values.get('CRYPTO_REST_BASE', 'https://api.crypto.com/exchange/v1')}",
        f"EXCHANGE_CUSTOM_API_KEY={values.get('EXCHANGE_CUSTOM_API_KEY', '')}",
        f"EXCHANGE_CUSTOM_API_SECRET={values.get('EXCHANGE_CUSTOM_API_SECRET', '')}",
        f"USE_CRYPTO_PROXY={values.get('USE_CRYPTO_PROXY', 'false')}",
        f"LIVE_TRADING={values.get('LIVE_TRADING', 'true')}",
        f"AWS_INSTANCE_IP={values.get('AWS_INSTANCE_IP', '')}",
        "",
        "# --- URLs / identity ---",
        f"ENVIRONMENT={values.get('ENVIRONMENT', 'aws')}",
        f"APP_ENV={values.get('APP_ENV', 'aws')}",
        f"RUNTIME_ORIGIN={values.get('RUNTIME_ORIGIN', 'AWS')}",
        f"API_BASE_URL={values.get('API_BASE_URL', 'http://backend-aws:8002')}",
        f"FRONTEND_URL={values.get('FRONTEND_URL', 'https://dashboard.hilovivo.com')}",
        f"NEXT_PUBLIC_API_URL={values.get('NEXT_PUBLIC_API_URL', '/api')}",
        f"NEXT_PUBLIC_ENVIRONMENT={values.get('NEXT_PUBLIC_ENVIRONMENT', 'aws')}",
        "",
        "# --- Grafana (optional) ---",
        f"GRAFANA_ADMIN_USER={values.get('GRAFANA_ADMIN_USER', 'admin')}",
        f"GF_SECURITY_ADMIN_PASSWORD={values.get('GF_SECURITY_ADMIN_PASSWORD', '')}",
        "",
    ]

    env_aws_path.parent.mkdir(parents=True, exist_ok=True)
    env_aws_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Escrito: {env_aws_path}")

    # Optional: also write secrets/runtime.env
    sep(" secrets/runtime.env (solo sensibles) ", "=")
    try:
        write_runtime = input("  ¿Escribir también secrets/runtime.env con Telegram y keys? (s/n): ").strip().lower()
    except EOFError:
        write_runtime = "n"
    if write_runtime in ("s", "si", "y", "yes"):
        runtime_lines = [
            "# secrets/runtime.env - generated by ops/interactive_env_setup.py",
            "# Do NOT commit.",
            "",
        ]
        for name, hint, secret in RUNTIME_ENV_VARS:
            v = values.get(name, "")
            runtime_lines.append(f"{name}={v}")
        runtime_env_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_env_path.write_text("\n".join(runtime_lines), encoding="utf-8")
        print(f"  Escrito: {runtime_env_path}")
    else:
        print("  Omitido secrets/runtime.env.")

    sep(" Listo ", "=")
    print(f"  Revisa: {env_aws_path}")
    print("  Para subir a EC2: scp o pegar contenido en la instancia (nunca commitear).\n")


if __name__ == "__main__":
    main()
