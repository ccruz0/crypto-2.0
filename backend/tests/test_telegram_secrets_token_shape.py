"""Telegram token resolution rejects placeholders and bad ciphertext shape."""

from __future__ import annotations

import os

import pytest


def test_resolve_rejects_placeholder_plaintext(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_ENCRYPTED", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "YOUR_PRODUCTION_BOT_TOKEN")
    from app.core import telegram_secrets as ts

    assert ts.resolve_telegram_token_from_env() is None
    assert os.environ.get("TELEGRAM_BOT_TOKEN") is None


def test_resolve_accepts_valid_shape_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    tok = "123456789012345678:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_ENCRYPTED", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", tok)
    from app.core import telegram_secrets as ts

    assert ts.resolve_telegram_token_from_env() == tok
