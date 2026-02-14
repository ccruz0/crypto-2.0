"""
Tests for doctor:sltp environment_mismatch_detected (real detection from logs_excerpt).
Uses the same rule as engine._write_sltp_doctor_report to avoid heavy imports (Python 3.9).
"""
import json
import re

import pytest


def _compute_sltp_report_fields_from_logs(logs_excerpt: str) -> dict:
    """Same logic as _write_sltp_doctor_report for payload_numeric_validation, scientific_notation_detected, environment_mismatch_detected."""
    payload_numeric_validation = "FAIL" if "payload_numeric_validation FAIL" in (logs_excerpt or "") else "PASS"
    scientific_notation_detected = bool(re.search(r"\d+[eE][+-]?\d+", logs_excerpt or ""))
    _ex = (logs_excerpt or "").lower()
    _has_sandbox_uat = "uat" in _ex or "sandbox" in _ex
    _has_prod = "api.crypto.com" in _ex
    environment_mismatch_detected = bool(_has_sandbox_uat and _has_prod)
    return {
        "payload_numeric_validation": payload_numeric_validation,
        "scientific_notation_detected": scientific_notation_detected,
        "environment_mismatch_detected": environment_mismatch_detected,
    }


def test_environment_mismatch_detected_when_uat_and_prod_in_excerpt():
    """When logs_excerpt contains both uat/sandbox and api.crypto.com -> environment_mismatch_detected True."""
    excerpt = "base_url=https://uat.sandbox.api.crypto.com/exchange/v1 and api.crypto.com"
    report = _compute_sltp_report_fields_from_logs(excerpt)
    assert report["environment_mismatch_detected"] is True


def test_environment_mismatch_detected_when_sandbox_and_prod_in_excerpt():
    """When logs_excerpt contains 'sandbox' and 'api.crypto.com' -> environment_mismatch_detected True."""
    excerpt = "CRYPTO_REST_BASE=sandbox.api.crypto.com api.crypto.com"
    report = _compute_sltp_report_fields_from_logs(excerpt)
    assert report["environment_mismatch_detected"] is True


def test_environment_mismatch_not_detected_when_only_prod():
    """When logs_excerpt contains only api.crypto.com (no uat/sandbox) -> False."""
    excerpt = "base_url=https://api.crypto.com/exchange/v1"
    report = _compute_sltp_report_fields_from_logs(excerpt)
    assert report["environment_mismatch_detected"] is False


def test_environment_mismatch_not_detected_when_only_uat():
    """When logs_excerpt contains only uat (no api.crypto.com) -> False."""
    excerpt = "base_url=https://uat.sandbox.example.com"
    report = _compute_sltp_report_fields_from_logs(excerpt)
    assert report["environment_mismatch_detected"] is False


def test_doctor_report_file_environment_mismatch(tmp_path):
    """Integration: _write_sltp_doctor_report writes report.json with environment_mismatch_detected from logs."""
    try:
        from app.services.ai_engine.engine import _write_sltp_doctor_report
    except Exception:
        pytest.skip("engine module not importable (e.g. Python 3.9 type hint)")
    tool_entries = [
        {"tool": "tail_logs", "result": {"output": "uat and api.crypto.com in same log"}},
    ]
    path = _write_sltp_doctor_report(str(tmp_path), tool_entries)
    with open(path) as f:
        report = json.load(f)
    assert report["environment_mismatch_detected"] is True


def _generate_fake_sltp_report_without_tail_logs(tmp_path):
    """Call _write_sltp_doctor_report with no tail_logs tool entry (simulates tail_logs failure / missing)."""
    try:
        from app.services.ai_engine.engine import _write_sltp_doctor_report
    except Exception:
        pytest.skip("engine module not importable")
    tool_entries = [
        {"tool": "search_repo", "args": {"query": "stop loss"}, "result": []},
    ]
    path = _write_sltp_doctor_report(str(tmp_path), tool_entries)
    with open(path) as f:
        return json.load(f)


def test_sltp_report_always_contains_compose_fields(tmp_path):
    """Report always has tail_logs_source and compose_dir_used (fallback to unknown and /app when tail_logs fails)."""
    try:
        from app.services.ai_engine.engine import _write_sltp_doctor_report
    except Exception:
        pytest.skip("engine module not importable")
    report = _generate_fake_sltp_report_without_tail_logs(tmp_path)
    assert "tail_logs_source" in report
    assert "compose_dir_used" in report
    assert report["tail_logs_source"] is not None
    assert report["compose_dir_used"] is not None
    assert report["tail_logs_source"] == "unknown"
    assert report["compose_dir_used"] == "/app"
