import importlib
import sys
from pathlib import Path
from unittest.mock import patch


def test_config_import_skips_runtime_env_when_testing_enabled(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")

    sys.modules.pop("app.core.config", None)
    sys.modules.pop("app.core.telegram_secrets", None)

    original_is_file = Path.is_file

    def guarded_is_file(self: Path) -> bool:
        text = str(self)
        if text.endswith("secrets/runtime.env"):
            raise AssertionError("runtime.env should not be touched when TESTING=1")
        return original_is_file(self)

    with patch("pathlib.Path.is_file", guarded_is_file):
        mod = importlib.import_module("app.core.config")
        assert mod.settings is not None
