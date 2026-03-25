"""
Explicit secret → filesystem / Docker targets for Apply and Verify.

Do not infer env var names from secret names elsewhere; add entries here.
"""

from __future__ import annotations

from typing import Any, TypedDict


class EnvFileEntry(TypedDict):
    path: str
    key: str


class HealthcheckSpec(TypedDict, total=False):
    """Optional post-restart checks. If ``exec`` is set, run inside the compose service."""

    exec: list[str]


class DeployTarget(TypedDict, total=False):
    project_path: str
    profile: str
    service: str
    env_files: list[EnvFileEntry]
    verify_env_vars: list[str]
    healthcheck: HealthcheckSpec


SECRET_TARGETS: dict[str, dict[str, DeployTarget]] = {
    "telegram.atp_control.bot_token": {
        "prod": {
            "project_path": "/home/ubuntu/automated-trading-platform",
            "profile": "aws",
            "service": "backend-aws",
            "env_files": [
                {
                    "path": ".env.aws",
                    "key": "TELEGRAM_ATP_CONTROL_BOT_TOKEN",
                },
                {
                    "path": "secrets/runtime.env",
                    "key": "TELEGRAM_BOT_TOKEN",
                },
            ],
            "verify_env_vars": [
                "TELEGRAM_ATP_CONTROL_BOT_TOKEN",
                "TELEGRAM_BOT_TOKEN",
            ],
            "healthcheck": {
                "exec": [
                    "python3",
                    "-c",
                    (
                        "import os, urllib.request; "
                        "t = os.environ.get('TELEGRAM_ATP_CONTROL_BOT_TOKEN', ''); "
                        "assert t; "
                        "urllib.request.urlopen("
                        "'https://api.telegram.org/bot' + t + '/getMe', timeout=25"
                        ").read()"
                    ),
                ],
            },
        }
    }
}


def get_deploy_target(secret_name: str, environment: str) -> DeployTarget | None:
    env = environment.strip().lower()
    t = SECRET_TARGETS.get(secret_name, {}).get(env)
    return t
