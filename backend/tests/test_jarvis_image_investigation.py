"""Tests for image-driven Jarvis investigations.

Covers: OCR + entity extraction, screenshot classification, image-aware routing,
the image_evidence pipeline, the supervisor evidence gate, the investigation
runner end-to-end, and the Telegram response summary.
"""

from __future__ import annotations

import base64
import io
from unittest.mock import MagicMock, patch

import pytest

from app.jarvis.investigations.evidence_model import EvidenceItem
from app.jarvis.investigations.image_classification import (
    ImageInvestigationType,
    build_effective_objective,
    classify_image_investigation,
    route_image_investigation,
)
from app.jarvis.investigations.image_evidence import build_image_evidence
from app.jarvis.investigations.investigation_report import (
    identify_missing_image_evidence,
    validate_investigation_report_fields,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.objective_classification import InvestigationObjectiveType
from app.jarvis.investigations.ocr import (
    extract_entities,
    extract_text_from_image,
    set_ocr_engine,
)


def _png_bytes(text_lines: list[str]) -> bytes:
    """Render text to a PNG so OCR has something to read (real or via fake engine)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 60 + 36 * len(text_lines)), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill="black")
        y += 36
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_b64(text_lines: list[str]) -> str:
    return base64.b64encode(_png_bytes(text_lines)).decode("ascii")


@pytest.fixture()
def fake_ocr():
    """Inject a deterministic OCR engine keyed on bytes->text via a closure mapping."""
    mapping: dict[bytes, str] = {}

    def engine(data: bytes) -> str:
        return mapping.get(data, "")

    set_ocr_engine(engine)
    try:
        yield mapping
    finally:
        set_ocr_engine(None)


@pytest.fixture()
def artifact_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.jarvis.artifacts.storage._ARTIFACTS_DIR",
        tmp_path / "artifacts",
    )
    return tmp_path


# --- OCR + entity extraction -------------------------------------------------


class TestEntityExtraction:
    def test_extracts_error_codes_and_urls(self):
        ents = extract_entities("Crypto.com error code: 40101 see https://crypto.com/api HTTP 503")
        assert "40101" in ents.error_codes
        assert "503" in ents.error_codes
        assert any("crypto.com/api" in u for u in ents.urls)

    def test_extracts_timestamps_and_commit(self):
        ents = extract_entities("2024-06-20T10:00:00Z deployed commit a1b2c3d4e5")
        assert ents.timestamps
        assert "a1b2c3d4e5" in ents.commit_hashes

    def test_extracts_github_run_and_order_id(self):
        ents = extract_entities("workflow actions/runs/123456789 failed; order id 998877665544")
        assert "123456789" in ents.github_run_ids
        assert "998877665544" in ents.order_ids

    def test_extracts_alert_name_and_container(self):
        ents = extract_entities("[FIRING] ContainerRestartsHigh on container: crypto-backend")
        assert "ContainerRestartsHigh" in ents.alert_names
        assert any("crypto-backend" in c for c in ents.container_names)

    def test_extract_text_returns_empty_on_garbage_bytes(self):
        # No engine override here; garbage bytes must degrade to empty, not raise.
        set_ocr_engine(None)
        assert extract_text_from_image(b"not-an-image") == ""


# --- Screenshot classification ----------------------------------------------


class TestScreenshotClassification:
    def test_exchange_40101(self):
        text = "Crypto.com\ncode: 40101\nAuthentication failure"
        it = classify_image_investigation(text, extract_entities(text))
        assert it == ImageInvestigationType.EXCHANGE_ERROR

    def test_alert_name_only(self):
        text = "ContainerRestartsHigh"
        it = classify_image_investigation(text, extract_entities(text))
        assert it == ImageInvestigationType.ALERT_INVESTIGATION

    def test_github_actions_failed(self):
        text = "GitHub Actions failed\nbuild failed"
        it = classify_image_investigation(text, extract_entities(text))
        assert it == ImageInvestigationType.GITHUB_ACTIONS_FAILURE

    def test_deployment_failure(self):
        text = "docker compose\ncrypto-backend exited (1) CrashLoopBackOff"
        it = classify_image_investigation(text, extract_entities(text))
        assert it == ImageInvestigationType.DEPLOYMENT_FAILURE

    def test_order_reconciliation(self):
        text = "Open orders mismatch dashboard vs exchange"
        it = classify_image_investigation(text, extract_entities(text))
        assert it == ImageInvestigationType.ORDER_RECONCILIATION

    def test_unknown(self):
        it = classify_image_investigation("hello world", extract_entities("hello world"))
        assert it == ImageInvestigationType.UNKNOWN


# --- Routing -----------------------------------------------------------------


class TestImageRouting:
    def test_40101_routes_to_exchange_auth(self):
        text = "Crypto.com 40101"
        ents = extract_entities(text)
        it = classify_image_investigation(text, ents)
        routed = route_image_investigation(objective="", image_type=it, ocr_text=text, entities=ents)
        assert routed == InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION

    def test_container_alert_routes_to_alert_investigation(self):
        text = "ContainerRestartsHigh"
        ents = extract_entities(text)
        it = classify_image_investigation(text, ents)
        routed = route_image_investigation(objective="", image_type=it, ocr_text=text, entities=ents)
        assert routed == InvestigationObjectiveType.ALERT_INVESTIGATION

    def test_github_actions_routes_to_deployment(self):
        text = "GitHub Actions failed"
        ents = extract_entities(text)
        it = classify_image_investigation(text, ents)
        routed = route_image_investigation(objective="", image_type=it, ocr_text=text, entities=ents)
        assert routed == InvestigationObjectiveType.DEPLOYMENT_HEALTH

    def test_explicit_objective_overrides_image(self):
        # User explicitly asks about open orders even though image is an alert.
        text = "ContainerRestartsHigh"
        ents = extract_entities(text)
        it = classify_image_investigation(text, ents)
        routed = route_image_investigation(
            objective="why are my open orders missing from crypto.com",
            image_type=it,
            ocr_text=text,
            entities=ents,
        )
        assert routed == InvestigationObjectiveType.ORDER_RECONCILIATION

    def test_effective_objective_carries_hints(self):
        ents = extract_entities("40101")
        eff = build_effective_objective(
            objective="what is happening here",
            routed_type=InvestigationObjectiveType.EXCHANGE_AUTH_INVESTIGATION,
            ocr_text="40101",
            entities=ents,
        )
        assert "what is happening here" in eff
        assert "auth" in eff.lower()


# --- Image evidence pipeline -------------------------------------------------


class TestImageEvidencePipeline:
    def test_builds_image_ocr_and_entity_evidence(self, fake_ocr, artifact_dir):
        data = _png_bytes(["x"])
        fake_ocr[data] = "Crypto.com\ncode: 40101\nAuthentication failure"
        b64 = base64.b64encode(data).decode("ascii")
        result = build_image_evidence(
            "inv-img-1",
            [{"filename": "err.png", "content_base64": b64, "caption": "why failing?"}],
            source="dashboard",
        )
        types = {e.get("evidence_type") for e in result.evidence_items}
        assert "image" in types
        assert "ocr" in types
        assert "image_entities" in types
        assert result.image_investigation_type == ImageInvestigationType.EXCHANGE_ERROR
        assert "40101" in result.combined_entities.error_codes
        # The image evidence record stores id, timestamp, source, caption, ocr, entities.
        img = result.images[0]
        assert img.image_id
        assert img.uploaded_at
        assert img.source == "dashboard"
        assert img.caption == "why failing?"
        assert "40101" in img.ocr_text


# --- Supervisor evidence gate ------------------------------------------------


def _ocr_only_evidence() -> list[EvidenceItem]:
    return [
        {
            "source": "user",
            "reference": "art-1",
            "detail": "User-provided screenshot: err.png",
            "confidence": "medium",
            "evidence_type": "image",
        },
        {
            "source": "ocr",
            "reference": "art-1",
            "detail": "OCR text: Crypto.com 40101 authentication failure detected here",
            "confidence": "medium",
            "evidence_type": "ocr",
        },
    ]


class TestSupervisorGate:
    def test_ocr_only_cannot_complete(self):
        evidence = _ocr_only_evidence()
        gaps = identify_missing_image_evidence(evidence)
        assert any("domain evidence" in g for g in gaps)
        status = validate_investigation_report_fields(
            root_cause="Crypto.com API authentication failing with 40101 due to bad credentials",
            evidence=evidence,
            confidence=80.0,
            recommended_fix="Rotate API credentials",
            is_image_investigation=True,
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_with_domain_evidence_can_complete(self):
        evidence = _ocr_only_evidence() + [
            {
                "source": "authentication",
                "reference": "credential_diagnostics",
                "detail": "Exchange sync_status=failed_auth; 40101 returned by Crypto.com private API",
                "confidence": "high",
                "evidence_type": "authentication",
                "is_direct": True,
            },
            {
                "source": "logs",
                "reference": "exchange_sync",
                "detail": "[2024-06-20] Authentication failed 40101 repeated in exchange_sync logs",
                "confidence": "medium",
                "evidence_type": "log",
            },
        ]
        assert identify_missing_image_evidence(evidence) == []
        status = validate_investigation_report_fields(
            root_cause="Crypto.com API authentication failing with 40101 due to bad credentials",
            evidence=evidence,
            confidence=80.0,
            recommended_fix="Rotate API credentials and remove duplicate secret",
            is_image_investigation=True,
        )
        assert status == InvestigationStatus.COMPLETED

    def test_missing_image_evidence_flagged(self):
        # Domain-only (no image/ocr) for an image investigation -> flagged.
        evidence = [
            {
                "source": "logs",
                "reference": "x",
                "detail": "Authentication failed 40101 repeated in exchange_sync logs here",
                "confidence": "medium",
                "evidence_type": "log",
            }
        ]
        gaps = identify_missing_image_evidence(evidence)
        assert any("image evidence" in g for g in gaps)
        assert any("OCR evidence" in g for g in gaps)


# --- Runner end-to-end (DB-free, mocked collectors) -------------------------


class TestRunnerRouting:
    def test_image_influences_collection_objective(self, fake_ocr, artifact_dir):
        from app.jarvis.investigations import investigation_runner as runner

        data = _png_bytes(["x"])
        fake_ocr[data] = "Crypto.com\ncode: 40101\nAuthentication failure\nINVALID_API_KEY"
        b64 = base64.b64encode(data).decode("ascii")

        captured = {}

        def fake_collect(objective, **kwargs):
            captured["objective"] = objective
            domain = [
                {
                    "source": "authentication",
                    "reference": "credential_diagnostics",
                    "detail": "Exchange sync_status=failed_auth; 40101 from Crypto.com private API",
                    "confidence": "high",
                    "evidence_type": "authentication",
                    "is_direct": True,
                }
            ]
            tool_outputs = [{"tool": "reconcile_crypto_com_open_orders", "ok": True, "sync_status": "failed_auth"}]
            return domain, tool_outputs, "authentication", "exchange_auth", None, []

        with patch.object(runner, "collect_evidence", side_effect=fake_collect):
            report = runner.run_investigation(
                "What is happening here?",
                persist=False,
                attachments=[{"filename": "err.png", "content_base64": b64}],
                attachment_source="dashboard",
            )

        # Image classification recorded.
        assert report.image_investigation_type == "exchange_error"
        assert report.is_image_investigation is True
        # Effective objective used for collection carries auth routing hints.
        assert "auth" in captured["objective"].lower() or "40101" in captured["objective"]
        # Domain evidence present -> not blocked by image gate.
        assert report.status in (
            InvestigationStatus.COMPLETED,
            InvestigationStatus.INSUFFICIENT_EVIDENCE,
        )

    def test_ocr_only_no_domain_evidence_blocks_completion(self, fake_ocr, artifact_dir):
        from app.jarvis.investigations import investigation_runner as runner

        data = _png_bytes(["x"])
        fake_ocr[data] = "Crypto.com 40101 authentication failure"
        b64 = base64.b64encode(data).decode("ascii")

        def empty_collect(objective, **kwargs):
            return [], [], "authentication", "exchange_auth", None, []

        with patch.object(runner, "collect_evidence", side_effect=empty_collect):
            report = runner.run_investigation(
                "What is happening here?",
                persist=False,
                attachments=[{"filename": "err.png", "content_base64": b64}],
            )
        assert report.status == InvestigationStatus.INSUFFICIENT_EVIDENCE


# --- Telegram response summary ----------------------------------------------


class TestTelegramSummary:
    def test_summary_contains_required_sections(self):
        from app.jarvis.telegram_control import _format_image_investigation_summary

        report = {
            "investigation_id": "abc123",
            "status": "completed",
            "image_investigation_type": "exchange_error",
            "objective": "why is this failing",
            "root_cause": "Crypto.com auth failure 40101",
            "confidence": 82.0,
            "next_action": "Rotate credentials",
            "extracted_entities": {"error_codes": ["40101"]},
            "evidence": [
                {"source": "authentication", "evidence_type": "authentication", "detail": "failed_auth 40101"},
                {"source": "ocr", "evidence_type": "ocr", "detail": "ocr text"},
            ],
        }
        msg = _format_image_investigation_summary(report)
        assert "Issue" in msg
        assert "Evidence" in msg
        assert "Root cause" in msg
        assert "Confidence" in msg
        assert "Next action" in msg
        assert "40101" in msg
