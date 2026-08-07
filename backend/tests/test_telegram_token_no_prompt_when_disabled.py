"""When RUN_TELEGRAM is explicitly disabled, never block startup on an interactive token prompt."""

from __future__ import annotations

from unittest.mock import patch


def test_get_telegram_token_skips_interactive_prompt_when_run_telegram_false():
    from app.utils import telegram_token_loader as ttl

    env = {
        "FORCE_TELEGRAM_TOKEN_PROMPT": "false",
        "RUN_TELEGRAM": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_BOT_TOKEN_DEV": "",
        "TELEGRAM_ATP_CONTROL_BOT_TOKEN": "",
        "TELEGRAM_CLAW_BOT_TOKEN": "",
        "TELEGRAM_BOT_TOKEN_AWS": "",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            with patch.object(ttl, "_get_token_interactive") as interactive:
                tok = ttl.get_telegram_token()
    assert tok is None
    interactive.assert_not_called()


def test_get_telegram_token_force_prompt_still_works_when_run_telegram_false():
    from app.utils import telegram_token_loader as ttl

    env = {
        "FORCE_TELEGRAM_TOKEN_PROMPT": "true",
        "RUN_TELEGRAM": "false",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch.object(ttl, "_get_token_interactive", return_value="999:FORCED") as interactive:
            tok = ttl.get_telegram_token()
    assert tok == "999:FORCED"
    interactive.assert_called_once()
