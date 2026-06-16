"""Tests for Jarvis investigation image attachments (evidence-only)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.routes_jarvis import router as jarvis_router
from app.database import ensure_jarvis_investigations_table
from app.jarvis.artifacts.images import MAX_IMAGE_BYTES, ImageValidationError
from app.jarvis.change_execution.config import phase5_safety_status
from app.jarvis.execution.safety import SafetyLevel, classify_text
from app.jarvis.investigations.investigation_attachments import (
    attachments_to_evidence,
    decode_attachment_payload,
)
from app.jarvis.investigations.investigation_runner import run_investigation

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
PNG_BYTES = base64.b64decode(PNG_B64)


@pytest.fixture()
def inv_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    ensure_jarvis_investigations_table(engine)
    monkeypatch.setattr("app.jarvis.investigations.persistence.engine", engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.jarvis.artifacts.storage._ARTIFACTS_DIR",
        tmp_path / "artifacts",
    )
    return engine


@pytest.fixture()
def jarvis_inv_client(inv_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def test_decode_valid_png_base64():
    data = decode_attachment_payload(PNG_B64)
    assert data == PNG_BYTES


def test_decode_rejects_invalid_base64():
    with pytest.raises(ImageValidationError, match="Invalid base64"):
        decode_attachment_payload("not-valid-base64!!!")


def test_attachments_to_evidence_stores_image(inv_db, tmp_path):
    evidence = attachments_to_evidence(
        "inv-test-1",
        [{"filename": "screenshot.png", "content_base64": PNG_B64, "caption": "Dashboard mismatch"}],
    )
    assert len(evidence) == 1
    item = evidence[0]
    assert item["source"] == "user"
    assert item["evidence_type"] == "image"
    assert item["is_direct"] is False
    assert item["detail"] == "Dashboard mismatch"
    assert item["content_url"].endswith("/content")
    assert item["artifact_id"]


def test_attachments_reject_oversized(inv_db):
    oversized_b64 = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ImageValidationError, match="exceeds"):
        attachments_to_evidence(
            "inv-test-2",
            [{"filename": "big.png", "content_base64": oversized_b64}],
        )


def test_attachments_reject_non_image(inv_db):
    with pytest.raises(ImageValidationError, match="not a valid|Unsupported file type"):
        attachments_to_evidence(
            "inv-test-3",
            [{"filename": "notes.txt", "content_base64": base64.b64encode(b"plain text").decode()}],
        )


def test_attachments_reject_unsupported_mime(inv_db):
    with pytest.raises(ImageValidationError, match="Unsupported content type"):
        attachments_to_evidence(
            "inv-test-4",
            [
                {
                    "filename": "shot.png",
                    "content_base64": PNG_B64,
                    "content_type": "application/pdf",
                }
            ],
        )


@patch("app.jarvis.investigations.investigation_runner.build_default_registry")
def test_run_investigation_merges_image_evidence(mock_registry_factory, inv_db):
    registry = MagicMock()
    registry.execute.return_value = MagicMock(
        ok=True,
        output={"tool": "inspect_health", "ok": True, "status": "ok", "matches": []},
    )
    mock_registry_factory.return_value = registry

    report = run_investigation(
        "Why are open orders empty?",
        persist=False,
        attachments=[{"filename": "ui.png", "content_base64": PNG_B64}],
    )
    image_items = [e for e in report.evidence if e.get("evidence_type") == "image"]
    assert len(image_items) == 1
    assert image_items[0]["source"] == "user"


@patch("app.jarvis.investigations.investigation_runner.build_default_registry")
def test_images_alone_do_not_complete_investigation(mock_registry_factory, inv_db):
    registry = MagicMock()
    registry.execute.return_value = MagicMock(
        ok=True,
        output={"tool": "inspect_health", "ok": True, "status": "ok", "matches": []},
    )
    mock_registry_factory.return_value = registry

    report = run_investigation(
        "Random unknown issue xyz",
        persist=False,
        attachments=[{"filename": "only.png", "content_base64": PNG_B64}],
    )
    assert report.status.value == "insufficient_evidence"


def test_api_accepts_image_attachment(jarvis_inv_client, inv_db):
    with patch("app.jarvis.investigations.investigation_runner.build_default_registry") as mock_factory:
        registry = MagicMock()
        registry.execute.return_value = MagicMock(
            ok=True,
            output={
                "tool": "diagnose_open_orders",
                "ok": True,
                "root_cause": "Exchange sync skipped rows during migration window",
                "evidence": [
                    {
                        "source": "database",
                        "reference": "exchange_orders",
                        "detail": "42 executed orders missing updated_at after migration",
                        "confidence": "high",
                    }
                ],
                "conclusion": "Missing orders are stale DB rows.",
            },
        )
        mock_factory.return_value = registry

        resp = jarvis_inv_client.post(
            "/api/jarvis/investigations/run",
            json={
                "objective": "Why are executed orders missing?",
                "attachments": [{"filename": "dash.png", "content_base64": PNG_B64}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    image_evidence = [e for e in body.get("evidence", []) if e.get("evidence_type") == "image"]
    assert len(image_evidence) == 1
    assert image_evidence[0]["source"] == "user"


def test_api_rejects_invalid_attachment(jarvis_inv_client):
    resp = jarvis_inv_client.post(
        "/api/jarvis/investigations/run",
        json={
            "objective": "Why are executed orders missing?",
            "attachments": [
                {"filename": "bad.txt", "content_base64": base64.b64encode(b"not an image").decode()}
            ],
        },
    )
    assert resp.status_code == 400


def test_api_blocks_forbidden_objective_with_images(jarvis_inv_client):
    objective = "Investigate and execute trade if missing orders are detected"
    assert classify_text(objective) == SafetyLevel.FORBIDDEN
    resp = jarvis_inv_client.post(
        "/api/jarvis/investigations/run",
        json={
            "objective": objective,
            "attachments": [{"filename": "shot.png", "content_base64": PNG_B64}],
        },
    )
    assert resp.status_code == 403


def test_phase5_write_gates_remain_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_PATCH_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_PR_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_WRITE_ENABLED", raising=False)
    status = phase5_safety_status()
    assert status["patch_apply_enabled"] is False
    assert status["pr_creation_enabled"] is False
    assert status["github_write_enabled"] is False


def test_attachment_content_endpoint(jarvis_inv_client, inv_db):
    evidence = attachments_to_evidence(
        "inv-content-1",
        [{"filename": "proof.png", "content_base64": PNG_B64}],
    )
    artifact_id = evidence[0]["artifact_id"]
    resp = jarvis_inv_client.get(
        f"/api/jarvis/investigations/inv-content-1/attachments/{artifact_id}/content"
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
