"""AWS polling token must prefer ATP Control bot so /task reaches backend-aws, not only trading bot."""

from __future__ import annotations

from unittest.mock import patch


def test_get_telegram_token_aws_prefers_atp_control_when_both_set():
    from app.utils import telegram_token_loader as ttl

    env = {
        "TELEGRAM_BOT_TOKEN": "111:AAA",
        "TELEGRAM_ATP_CONTROL_BOT_TOKEN": "222:BBB",
        "FORCE_TELEGRAM_TOKEN_PROMPT": "false",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=True):
            tok = ttl.get_telegram_token()
    assert tok == "222:BBB"


def test_get_telegram_token_source_aws_atp_first():
    from app.utils import telegram_token_loader as ttl

    env = {
        "TELEGRAM_BOT_TOKEN": "111:AAA",
        "TELEGRAM_ATP_CONTROL_BOT_TOKEN": "222:BBB",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=True):
            assert ttl.get_telegram_token_source() == "TELEGRAM_ATP_CONTROL_BOT_TOKEN"


def test_get_telegram_token_aws_missing_returns_none_no_interactive():
    from app.utils import telegram_token_loader as ttl

    env = {
        "FORCE_TELEGRAM_TOKEN_PROMPT": "false",
    }
    with patch.dict("os.environ", env, clear=True):
        with patch("app.core.runtime.is_aws_runtime", return_value=True):
            tok = ttl.get_telegram_token()
    assert tok is None


def test_get_telegram_token_source_aws_missing():
    from app.utils import telegram_token_loader as ttl

    with patch.dict("os.environ", {}, clear=True):
        with patch("app.core.runtime.is_aws_runtime", return_value=True):
            assert ttl.get_telegram_token_source() == "missing_aws_telegram_token"


def test_get_telegram_token_non_aws_still_prefers_primary_bot_token():
    from app.utils import telegram_token_loader as ttl

    env = {
        "TELEGRAM_BOT_TOKEN": "111:AAA",
        "TELEGRAM_ATP_CONTROL_BOT_TOKEN": "222:BBB",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("app.core.runtime.is_aws_runtime", return_value=False):
            tok = ttl.get_telegram_token()
    assert tok == "111:AAA"
