"""Tests for scrub_for_llm: env-like / secret content must never reach the model."""

from __future__ import annotations

from app.jarvis.llm.scrub import REDACTION, scrub_for_llm


def test_env_assignment_value_redacted_key_preserved():
    out = scrub_for_llm("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    assert "wJalrXUtnFEMI" not in out
    assert "AWS_SECRET_ACCESS_KEY=" in out
    assert REDACTION in out


def test_export_form_redacted():
    out = scrub_for_llm("export TELEGRAM_BOT_TOKEN=123456:ABCDEF")
    assert "123456:ABCDEF" not in out
    assert "TELEGRAM_BOT_TOKEN=" in out


def test_aws_access_key_id_redacted_inline():
    out = scrub_for_llm("found key AKIAIOSFODNN7EXAMPLE in logs")
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert REDACTION in out


def test_pem_block_redacted():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBg\n-----END PRIVATE KEY-----"
    out = scrub_for_llm(f"key:\n{pem}\nend")
    assert "MIIBVgIBADANBg" not in out


def test_normal_disk_output_passes_through():
    df = "Filesystem      Size  Used Avail Use% Mounted on\n/dev/root        49G   24G   23G  52% /"
    out = scrub_for_llm(df)
    assert out == df


def test_empty_input():
    assert scrub_for_llm("") == ""
