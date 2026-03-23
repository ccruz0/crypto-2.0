"""Lightweight guards for app.services singleton vs submodule import behavior."""
import importlib


def test_telegram_notifier_importlib_is_module_not_instance():
    m = importlib.import_module("app.services.telegram_notifier")
    assert m.__name__ == "app.services.telegram_notifier"
    assert hasattr(m, "TelegramNotifier")
    inst = getattr(m, "telegram_notifier", None)
    assert inst is not None
    assert type(inst).__name__ == "TelegramNotifier"


def test_signal_monitor_importlib_is_module():
    m = importlib.import_module("app.services.signal_monitor")
    assert m.__name__ == "app.services.signal_monitor"
    assert hasattr(m, "SignalMonitorService")
    assert hasattr(m, "signal_monitor_service")


def test_from_app_services_telegram_notifier_is_shared_instance():
    from app.services import telegram_notifier as n
    from app.services.telegram_notifier import telegram_notifier as n2

    assert n is n2
