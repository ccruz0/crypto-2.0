"""Tests for shared Crypto.com credential hydration and trade_client bootstrap."""

from __future__ import annotations

from unittest.mock import patch

from app.utils.credential_resolver import (
    CREDENTIAL_PAIRS,
    ensure_trade_client_crypto_credentials,
    hydrate_crypto_env_from_runtime_file,
    resolve_crypto_credentials,
)


def test_hydrate_reads_exchange_custom_from_runtime_file(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "EXCHANGE_CUSTOM_API_KEY=test_key\nEXCHANGE_CUSTOM_API_SECRET=test_secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EXCHANGE_CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("EXCHANGE_CUSTOM_API_SECRET", raising=False)
    with patch("app.utils.credential_resolver.runtime_env_file_path", return_value=runtime):
        flags = hydrate_crypto_env_from_runtime_file()
    assert flags.get("EXCHANGE_CUSTOM_API_KEY") is True
    assert flags.get("EXCHANGE_CUSTOM_API_SECRET") is True
    key, secret, _, _ = resolve_crypto_credentials()
    assert key == "test_key"
    assert secret == "test_secret"


def test_ensure_trade_client_sets_same_singleton(monkeypatch):
    monkeypatch.setenv("EXCHANGE_CUSTOM_API_KEY", "k1")
    monkeypatch.setenv("EXCHANGE_CUSTOM_API_SECRET", "s1")
    meta = ensure_trade_client_crypto_credentials()
    from app.services.brokers.crypto_com_trade import trade_client

    assert meta["credentials_loaded"] is True
    assert trade_client.api_key == "k1"
    assert trade_client.api_secret == "s1"


def test_credential_pairs_include_exchange_custom_first():
    assert CREDENTIAL_PAIRS[0] == ("EXCHANGE_CUSTOM_API_KEY", "EXCHANGE_CUSTOM_API_SECRET")
