"""Tests for app.utils.redact: masking and safe logging (PR#1 P0 secrets audit)."""
import pytest
from app.utils.redact import (
    mask_token,
    mask_chat_id,
    redact_headers,
    safe_str,
    mask_sequence_of_ids,
    redact_secrets,
    sanitize_telegram_api_response_for_log,
)


class TestMaskToken:
    def test_empty_or_none_returns_not_set(self):
        assert mask_token(None) == "<NOT_SET>"
        assert mask_token("") == "<NOT_SET>"

    def test_short_string_returns_stars(self):
        assert mask_token("ab") == "***"
        assert mask_token("abcdef") == "***"

    def test_long_string_keeps_first_and_last_six(self):
        s = "abcdefghijklmnopqrstuvwxyz"
        assert mask_token(s) == "abcdef...uvwxyz"
        assert mask_token(s, first=4, last=4) == "abcd...wxyz"

    def test_whitespace_stripped(self):
        assert mask_token("  abcdefghijklmnopqrstuvwxyz  ") == "abcdef...uvwxyz"


class TestMaskChatId:
    def test_none_returns_not_set(self):
        assert mask_chat_id(None) == "<NOT_SET>"

    def test_empty_returns_stars(self):
        assert mask_chat_id("") == "***"

    def test_keeps_last_four(self):
        assert mask_chat_id("12345678") == "****5678"
        assert mask_chat_id(12345678) == "****5678"

    def test_short_id_masked_fully(self):
        assert mask_chat_id("12") == "***"


class TestRedactHeaders:
    def test_authorization_redacted(self):
        h = {"Authorization": "Bearer sk-xxx", "Content-Type": "application/json"}
        out = redact_headers(h)
        assert out["Authorization"] == "<REDACTED>"
        assert out["Content-Type"] == "application/json"

    def test_x_api_key_redacted(self):
        h = {"X-API-Key": "secret-key-123"}
        assert redact_headers(h)["X-API-Key"] == "<REDACTED>"

    def test_empty_or_none(self):
        assert redact_headers(None) == {}
        assert redact_headers({}) == {}


class TestSafeStr:
    def test_none(self):
        assert safe_str(None) == "None"

    def test_primitives(self):
        assert safe_str(True) == "True"
        assert safe_str(42) == "42"
        assert safe_str(3.14) == "3.14"

    def test_long_string_truncated(self):
        s = "a" * 300
        assert len(safe_str(s)) <= 203  # 200 + "..."

    def test_dict_shows_keys_only(self):
        assert "keys=" in safe_str({"a": 1, "b": 2})
        assert "dict" in safe_str({"secret": "x"})

    def test_list_shows_len_only(self):
        assert "len=3" in safe_str([1, 2, 3])


class TestMaskSequenceOfIds:
    def test_empty_or_none(self):
        assert mask_sequence_of_ids(None) == "none"
        assert mask_sequence_of_ids([]) == "none"

    def test_masks_each_id(self):
        out = mask_sequence_of_ids(["12345678", "87654321"])
        assert "5678" in out
        assert "4321" in out
        assert "12345678" not in out


class TestSanitizeTelegramApiResponseForLog:
    """PR1: No raw Telegram API response in logs."""

    def test_dict_redacts_chat_id_and_result(self):
        d = {"ok": False, "description": "Bad Request: chat not found", "chat_id": "12345678", "result": {"message_id": 99}}
        out = sanitize_telegram_api_response_for_log(d)
        assert "<REDACTED>" in out
        assert "12345678" not in out
        assert "description" in out

    def test_str_returns_body_len_only(self):
        out = sanitize_telegram_api_response_for_log('{"chat_id": 123}')
        assert "body len=" in out
        assert "123" not in out


class TestRedactSecrets:
    def test_dict_redacts_sensitive_keys(self):
        d = {"api_key": "sk-xxx", "name": "alice"}
        out = redact_secrets(d)
        assert out["api_key"] == "***REDACTED***"
        assert out["name"] == "alice"

    def test_nested_dict(self):
        d = {"payload": {"token": "secret", "count": 1}}
        out = redact_secrets(d)
        assert out["payload"]["token"] == "***REDACTED***"
        assert out["payload"]["count"] == 1
