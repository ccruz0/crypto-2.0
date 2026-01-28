from pathlib import Path


def test_crypto_com_trade_does_not_log_key_or_signature_fragments() -> None:
    """Static regression guard: ensure code doesn't emit key/signature fragments."""
    p = Path(__file__).resolve().parents[1] / "app" / "services" / "brokers" / "crypto_com_trade.py"
    s = p.read_text(encoding="utf-8")

    # No partial key previews
    assert "_preview_secret(self.api_key)" not in s
    assert "signature_preview" not in s

    # No formatted logging that would include api_key fragments
    assert "[CRYPTO_AUTH_DIAG] api_key=%s" not in s

    # In diag payload, api_key/sig must be placeholders only
    assert 'safe_payload["api_key"] = "<SET>"' in s
    assert 'safe_payload["sig"] = "<SET>"' in s
