"""Unit tests for scripts/aws_runtime_verify.py (no AWS network)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MODULE_PATH = Path(__file__).resolve().parent / "aws_runtime_verify.py"
SPEC = importlib.util.spec_from_file_location("aws_runtime_verify", MODULE_PATH)
assert SPEC and SPEC.loader
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def test_parse_remote_extracts_runtime_checks() -> None:
    stdout = """
BACKEND_AWS=OK line=crypto-20-backend-aws-1 Up 2 days
DISK_USAGE=OK pct=42 threshold=80
EXPOSED_PORTS=OK
TELEGRAM_POLLER=OK count=1
SCHEDULER_OK=OK http=200
VIOLATIONS=0
WARNINGS=0
"""
    parsed = verify._parse_remote(stdout)
    assert parsed["backend_aws"].startswith("OK")
    assert parsed["disk_usage"].startswith("OK")
    assert verify._check_ok(parsed, "backend_aws") is True
    assert verify._disk_pct(parsed) == 42


def test_parse_remote_disk_fail() -> None:
    parsed = verify._parse_remote("DISK_USAGE=FAIL pct=91 threshold=80")
    assert verify._check_ok(parsed, "disk_usage") is False
    assert verify._disk_pct(parsed) == 91


def test_classification_exit_codes() -> None:
    assert verify._classification(0) == "PRODUCTION_SAFE"
    assert verify._classification(1) == "PRODUCTION_AT_RISK"
    assert verify._classification(2) == "CRITICAL_RUNTIME_VIOLATION"


def test_compose_ports_ok_requires_localhost_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        'services:\n  backend:\n    ports:\n      - "127.0.0.1:8002:8002"\n'
        '  frontend:\n    ports:\n      - "127.0.0.1:3000:3000"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(verify, "COMPOSE_FILE", compose)
    assert verify._compose_ports_ok() is True

    compose.write_text('ports:\n  - "0.0.0.0:8002:8002"\n', encoding="utf-8")
    assert verify._compose_ports_ok() is False


def test_remote_check_script_prod_check_makes_health_a_violation() -> None:
    script = verify._remote_check_script("prod-check")
    assert "SCHEDULER_OK=FAIL" in script
    assert f"threshold={verify.DISK_ALERT_PCT}" in script
    assert "BACKEND_AWS=FAIL" in script


def test_remote_check_script_sentinel_keeps_health_warning() -> None:
    script = verify._remote_check_script("sentinel")
    assert "SCHEDULER_OK=WARN" in script
    assert "SCHEDULER_OK=FAIL" not in script


def test_verification_mode_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_RUNTIME_VERIFY_MODE", "prod-check")
    assert verify._verification_mode() == "prod-check"
    monkeypatch.setenv("AWS_RUNTIME_VERIFY_MODE", "sentinel")
    assert verify._verification_mode() == "sentinel"


def test_quiet_success_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_RUNTIME_VERIFY_QUIET", "1")
    assert verify._quiet_success() is True
    monkeypatch.delenv("AWS_RUNTIME_VERIFY_QUIET")
    assert verify._quiet_success() is False


def test_main_prod_check_skips_compose_and_fails_ec2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "runtime-report.json"
    history_dir = tmp_path / "runtime-history"
    monkeypatch.setattr(verify, "REPORT_PATH", report_path)
    monkeypatch.setattr(verify, "HISTORY_DIR", history_dir)
    monkeypatch.setenv("AWS_RUNTIME_VERIFY_QUIET", "1")

    with patch.object(verify, "_ec2_instance_state", return_value=("failed", "stopped")):
        code = verify.main(["--mode", "prod-check"])

    assert code == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "prod-check"
    assert report["checks"]["ec2_instance_running"] is False
    assert "compose_ports_ok" not in report["checks"]


def test_main_sentinel_fails_on_compose_before_ec2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "runtime-report.json"
    history_dir = tmp_path / "runtime-history"
    compose = tmp_path / "docker-compose.yml"
    compose.write_text('ports:\n  - "0.0.0.0:8002:8002"\n', encoding="utf-8")
    monkeypatch.setattr(verify, "REPORT_PATH", report_path)
    monkeypatch.setattr(verify, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(verify, "COMPOSE_FILE", compose)

    ec2_mock = MagicMock(return_value=("ok", "running"))
    with patch.object(verify, "_ec2_instance_state", ec2_mock):
        code = verify.main(["--mode", "sentinel"])

    assert code == 2
    ec2_mock.assert_called_once()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["checks"]["compose_ports_ok"] is False


def test_main_prod_check_success_is_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "runtime-report.json"
    history_dir = tmp_path / "runtime-history"
    monkeypatch.setattr(verify, "REPORT_PATH", report_path)
    monkeypatch.setattr(verify, "HISTORY_DIR", history_dir)
    monkeypatch.setenv("AWS_RUNTIME_VERIFY_QUIET", "1")

    remote_stdout = "\n".join(
        [
            "BACKEND_AWS=OK line=backend Up",
            "DISK_USAGE=OK pct=50 threshold=80",
            "EXPOSED_PORTS=OK",
            "TELEGRAM_POLLER=OK count=1",
            "SCHEDULER_OK=OK http=200",
        ]
    )
    with (
        patch.object(verify, "_ec2_instance_state", return_value=("ok", "running")),
        patch.object(verify, "_curl_health", return_value=(200, "ok")),
        patch.object(verify, "_ssm_ping_status", return_value=("ok", "Online")),
        patch.object(verify, "_run_ssm_remote_check", return_value=(0, remote_stdout, "")),
    ):
        code = verify.main(["--mode", "prod-check"])

    assert code == 0
    assert capsys.readouterr().out == ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["classification"] == "PRODUCTION_SAFE"
    assert report["checks"]["disk_usage_pct"] == 50
