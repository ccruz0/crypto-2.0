from unittest.mock import patch


def _set_poller_env(monkeypatch, *, runtime_origin: str, run_poller: str = "true", allow_lab: str | None = None) -> None:
    monkeypatch.setenv("RUN_TELEGRAM_POLLER", run_poller)
    monkeypatch.setenv("RUNTIME_ORIGIN", runtime_origin)
    if allow_lab is None:
        monkeypatch.delenv("ALLOW_LAB_TELEGRAM_POLLER", raising=False)
    else:
        monkeypatch.setenv("ALLOW_LAB_TELEGRAM_POLLER", allow_lab)


def test_process_telegram_commands_blocks_lab_by_default(monkeypatch, caplog):
    import app.services.telegram_commands as tc

    _set_poller_env(monkeypatch, runtime_origin="LAB", run_poller="true", allow_lab=None)

    with patch.object(tc, "_acquire_poller_lock") as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert not acquire_lock.called
    assert "[TG][GUARD] Poller blocked in LAB runtime" in caplog.text


def test_process_telegram_commands_allows_lab_with_explicit_override(monkeypatch):
    import app.services.telegram_commands as tc

    _set_poller_env(monkeypatch, runtime_origin="LAB", run_poller="true", allow_lab="true")

    with patch.object(tc, "_acquire_poller_lock", return_value=False) as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert acquire_lock.called


def test_process_telegram_commands_does_not_block_aws(monkeypatch):
    import app.services.telegram_commands as tc

    _set_poller_env(monkeypatch, runtime_origin="AWS", run_poller="true", allow_lab=None)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("APP_ENV", "aws")

    with patch.object(tc, "_acquire_poller_lock", return_value=False) as acquire_lock:
        tc.process_telegram_commands(db=object())

    assert acquire_lock.called
