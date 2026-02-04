import os


def _clear_telegram_env(monkeypatch) -> None:
    for k in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_BOT_TOKEN_AWS",
        "TELEGRAM_CHAT_ID_AWS",
        "TELEGRAM_BOT_TOKEN_LOCAL",
        "TELEGRAM_CHAT_ID_LOCAL",
        "TELEGRAM_AUTH_USER_ID",
        "TELEGRAM_AUTH_USER_ID_AWS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_refresh_config_aws_allows_when_fully_configured(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-aws")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-100123")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")
    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", lambda env: True)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["runtime_env"] == "aws"
    assert cfg["run_telegram"] is True
    assert cfg["kill_switch_enabled"] is True
    assert cfg["token_set"] is True
    assert cfg["chat_id_set"] is True
    assert cfg["enabled"] is True
    assert cfg["chat_id"] == "-100123"
    assert cfg["block_reasons"] == []
    assert notifier.enabled is True
    assert notifier.chat_id == "-100123"
    assert notifier.bot_token == "token-aws"


def test_refresh_config_blocks_when_kill_switch_disabled(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-aws")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-100123")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")
    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", lambda env: False)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["enabled"] is False
    assert "kill_switch_disabled" in cfg["block_reasons"]


def test_refresh_config_blocks_when_run_telegram_false(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-aws")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-100123")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")
    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", lambda env: True)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["run_telegram"] is False
    assert cfg["enabled"] is False
    assert "run_telegram_disabled" in cfg["block_reasons"]


def test_refresh_config_blocks_when_missing_credentials(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "true")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")
    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", lambda env: True)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["enabled"] is False
    assert "token_missing" in cfg["block_reasons"]
    assert "chat_id_missing" in cfg["block_reasons"]


def test_refresh_config_blocks_when_kill_switch_raises(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-aws")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-100123")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")

    def _raise(_env: str) -> bool:
        raise RuntimeError("db_down")

    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", _raise)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["enabled"] is False
    assert any(r.startswith("kill_switch_error:") for r in cfg["block_reasons"])


def test_refresh_config_aws_does_not_block_when_using_aws_creds_even_if_local_present(monkeypatch):
    from app.services import telegram_notifier as tg

    _clear_telegram_env(monkeypatch)
    monkeypatch.setenv("RUN_TELEGRAM", "true")
    # AWS creds present (should be selected)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_AWS", "token-aws")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_AWS", "-100123")
    # LOCAL creds also present (should NOT block if AWS creds are selected)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_LOCAL", "token-local")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_LOCAL", "-100999")

    monkeypatch.setattr(tg, "getRuntimeEnv", lambda: "aws")
    monkeypatch.setattr(tg, "_get_telegram_kill_switch_status", lambda env: True)

    notifier = tg.TelegramNotifier()
    cfg = notifier.refresh_config()

    assert cfg["enabled"] is True
    assert cfg["chat_id"] == "-100123"
    assert "aws_using_local_credentials" not in cfg["block_reasons"]

