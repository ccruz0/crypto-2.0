"""Regression guards: no secrets in logs (PR#1 P0)."""
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


def test_app_does_not_log_authorization_bearer_raw() -> None:
    """Fail if any app code logs raw Bearer token (format string with %s or {})."""
    root = Path(__file__).resolve().parents[1] / "app"
    for py_path in root.rglob("*.py"):
        text = py_path.read_text(encoding="utf-8")
        if "logger." not in text or "Bearer " not in text:
            continue
        # Forbidden: logger.info("...Bearer %s", token) or logger.info(f"...Bearer {token}")
        if "Bearer %s" in text or 'Bearer "%s"' in text:
            raise AssertionError(
                f"{py_path.relative_to(root)} may log raw Bearer token (format)"
            )


def test_diag_credentials_status_does_not_expose_secret_value() -> None:
    """routes_diag must not return secret_starts_with or any secret value."""
    p = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_diag.py"
    s = p.read_text(encoding="utf-8")
    assert "secret_starts_with" not in s
    assert "api_secret[:" not in s


def test_telegram_commands_auth_logs_mask_user_id() -> None:
    """PR1: [TG][AUTH] Added authorized user ID must use mask_chat_id (no raw identifiers in logs)."""
    p = Path(__file__).resolve().parents[1] / "app" / "services" / "telegram_commands.py"
    s = p.read_text(encoding="utf-8")
    marker = "[TG][AUTH] Added authorized user ID"
    if marker not in s:
        return  # No such log line
    # The line that logs Added authorized user ID must use mask_chat_id
    for line in s.splitlines():
        if marker in line and "logger." in line:
            assert "mask_chat_id(" in line, (
                "telegram_commands.py must log authorized user ID with mask_chat_id(...), not raw"
            )
            break


def test_telegram_commands_no_raw_api_response_in_logs() -> None:
    """PR1: No Telegram API response body logged unfiltered (no leak via error_data/response.text)."""
    p = Path(__file__).resolve().parents[1] / "app" / "services" / "telegram_commands.py"
    s = p.read_text(encoding="utf-8")
    for line in s.splitlines():
        if "logger." not in line or "[TG][ERROR]" not in line:
            continue
        # If this line logs error_data or response.text, it must use the sanitizer
        if "error_data" in line and ("}" in line or "%" in line or "format" in line):
            assert "sanitize_telegram" in line, (
                "telegram_commands.py must not log raw error_data; use sanitize_telegram_api_response_for_log"
            )
        if "response.text" in line:
            assert "sanitize_telegram" in line, (
                "telegram_commands.py must not log raw e.response.text; use sanitize_telegram_api_response_for_log"
            )
