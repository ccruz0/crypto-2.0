def test_signal_monitor_uses_refreshed_telegram_runtime_config(monkeypatch):
    from app.services import signal_monitor as sm

    class DummyTelegramNotifier:
        def __init__(self):
            self.calls = 0

        def refresh_config(self):
            self.calls += 1
            return {
                "runtime_env": "aws",
                "run_telegram": True,
                "kill_switch_enabled": True,
                "token_set": True,
                "chat_id_set": True,
                "enabled": True,
                "chat_id": "-100999",
                "block_reasons": [],
            }

    dummy = DummyTelegramNotifier()
    monkeypatch.setattr(sm, "telegram_notifier", dummy)

    svc = sm.SignalMonitorService()
    # Seed stale state to prove refresh=True overwrites it.
    svc._telegram_runtime_config = {
        "runtime_env": "aws",
        "run_telegram": False,
        "kill_switch_enabled": False,
        "token_set": False,
        "chat_id_set": False,
        "enabled": False,
        "chat_id": None,
        "block_reasons": ["stale_seed"],
    }

    cfg = svc._get_telegram_runtime_config(refresh=True)
    assert dummy.calls == 1
    assert cfg["enabled"] is True
    assert cfg["chat_id"] == "-100999"
    assert svc._telegram_chat_id() == "-100999"
    assert svc._telegram_send_enabled() is True

    # Subsequent read uses cached config without refreshing.
    cfg2 = svc._get_telegram_runtime_config(refresh=False)
    assert cfg2["chat_id"] == "-100999"
    assert dummy.calls == 1
