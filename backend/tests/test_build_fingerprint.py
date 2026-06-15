"""Tests for backend build fingerprint resolution and health headers."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.build_fingerprint as build_fingerprint
from app.factory import create_app


@pytest.fixture(autouse=True)
def clear_fingerprint_cache():
    build_fingerprint.resolve_git_sha.cache_clear()
    build_fingerprint.resolve_build_time.cache_clear()
    yield
    build_fingerprint.resolve_git_sha.cache_clear()
    build_fingerprint.resolve_build_time.cache_clear()


def test_resolve_git_sha_prefers_env(monkeypatch):
    monkeypatch.setenv("ATP_GIT_SHA", "abc123def456")
    assert build_fingerprint.resolve_git_sha() == "abc123def456"


def test_resolve_git_sha_falls_back_to_git_sha_env(monkeypatch):
    monkeypatch.delenv("ATP_GIT_SHA", raising=False)
    monkeypatch.setenv("GIT_SHA", "deadbeef")
    assert build_fingerprint.resolve_git_sha() == "deadbeef"


def test_resolve_git_sha_reads_baked_file_when_env_unknown(monkeypatch, tmp_path: Path):
    sha_file = tmp_path / ".git_sha"
    sha_file.write_text("61bbdc4180bb533ac373b88c931e4d7db5aebdd0\n", encoding="utf-8")
    monkeypatch.setenv("ATP_GIT_SHA", "unknown")
    monkeypatch.setattr(build_fingerprint, "_GIT_SHA_FILE", sha_file)
    assert build_fingerprint.resolve_git_sha() == "61bbdc4180bb533ac373b88c931e4d7db5aebdd0"


def test_resolve_git_sha_returns_unknown_when_unset(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ATP_GIT_SHA", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setattr(build_fingerprint, "_GIT_SHA_FILE", tmp_path / "missing")
    assert build_fingerprint.resolve_git_sha() == "unknown"


def test_resolve_build_time_reads_baked_file(monkeypatch, tmp_path: Path):
    time_file = tmp_path / ".build_time"
    time_file.write_text("2026-06-15T11:47:20Z\n", encoding="utf-8")
    monkeypatch.setenv("ATP_BUILD_TIME", "unknown")
    monkeypatch.setattr(build_fingerprint, "_BUILD_TIME_FILE", time_file)
    assert build_fingerprint.resolve_build_time() == "2026-06-15T11:47:20Z"


def test_health_endpoint_exposes_backend_commit_header(monkeypatch):
    monkeypatch.setenv("ATP_GIT_SHA", "61bbdc4180bb533ac373b88c931e4d7db5aebdd0")
    monkeypatch.setenv("ATP_BUILD_TIME", "2026-06-15T11:47:20Z")
    import app.factory as factory_mod

    importlib.reload(build_fingerprint)
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-ATP-Backend-Commit") == "61bbdc4180bb533ac373b88c931e4d7db5aebdd0"
    assert response.headers.get("X-ATP-Backend-BuildTime") == "2026-06-15T11:47:20Z"
