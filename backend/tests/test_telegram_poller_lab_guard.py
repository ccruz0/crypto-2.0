import importlib
from unittest.mock import patch


def _set_poller_env(monkeypatch, *, runtime_origin: str, run_poller: str = "true", allow_lab: str | None = None) -> None:
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", run_poller)
    monkeypatch.setenv("RUNTIME_ORIGIN", runtime_origin)
    monkeypatch.setenv("FORCE_TELEGRAM_TOKEN_PROMPT", "false")
    # Ensure poller guard can reach lock acquisition path in tests (no interactive prompt).
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_DEV", "dev-token-for-tests")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prod-token-for-tests")
    monkeypatch.setenv("TELEGRAM_ATP_CONTROL_BOT_TOKEN", "control-token-for-tests")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    if allow_lab is None:
        monkeypatch.delenv("ALLOW_LAB_TELEGRAM_POLLER", raising=False)
    else:
        monkeypatch.setenv("ALLOW_LAB_TELEGRAM_POLLER", allow_lab)


def test_process_telegram_commands_blocks_lab_by_default(monkeypatch, caplog):
    _set_poller_env(monkeypatch, runtime_origin="LAB", run_poller="true", allow_lab=None)
    import app.services.telegram_commands as tc
    tc = importlib.reload(tc)

    with patch.object(tc, "_acquire_poller_lock") as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert not acquire_lock.called
    assert "[TG][GUARD] Poller blocked in LAB runtime" in caplog.text


def test_process_telegram_commands_allows_lab_with_explicit_override(monkeypatch):
    _set_poller_env(monkeypatch, runtime_origin="LAB", run_poller="true", allow_lab="true")
    import app.services.telegram_commands as tc
    tc = importlib.reload(tc)

    with patch.object(tc, "_try_acquire_poller_flock", return_value=None), \
         patch.object(tc, "_acquire_poller_lock", return_value=False) as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert acquire_lock.called


def test_process_telegram_commands_does_not_block_aws(monkeypatch):
    _set_poller_env(monkeypatch, runtime_origin="AWS", run_poller="true", allow_lab=None)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("APP_ENV", "aws")
    import app.services.telegram_commands as tc
    tc = importlib.reload(tc)

    with patch.object(tc, "_try_acquire_poller_flock", return_value=None), \
         patch.object(tc, "_acquire_poller_lock", return_value=False) as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert acquire_lock.called
