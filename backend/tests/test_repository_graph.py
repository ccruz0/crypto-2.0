"""Tests for Jarvis Phase 4 repository knowledge graph."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.jarvis.repository.graph import RepositoryGraph, build_repository_graph
from app.jarvis.repository.persistence import get_repository_metadata, refresh_repository_metadata, save_repository_metadata
from app.jarvis.repository.scanner import scan_repository


@pytest.fixture()
def sample_scan():
    return {
        "scanned_at": "2026-01-01T00:00:00Z",
        "file_count": 3,
        "modules": [
            {"path": "backend/app/jarvis/execution/service.py", "line_count": 100, "imports": ["app.jarvis.execution.lifecycle"]},
            {"path": "backend/app/api/routes_jarvis.py", "line_count": 200, "imports": ["fastapi"]},
        ],
        "api_endpoints": [
            {"path": "/api/jarvis/tasks/submit", "file": "backend/app/api/routes_jarvis.py"},
        ],
        "database_models": [{"name": "JarvisControlTask", "file": "backend/app/models/jarvis_control_models.py", "source": "sqlalchemy"}],
        "workflows": [{"file": ".github/workflows/deploy.yml", "name": "Deploy"}],
        "deployment_scripts": [{"path": "scripts/deploy.sh", "kind": "deployment_script"}],
        "read_only": True,
    }


def test_build_graph_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    assert graph.node_count >= 4


def test_build_graph_edges(sample_scan):
    graph = build_repository_graph(sample_scan)
    assert graph.edge_count >= 1


def test_graph_to_dict(sample_scan):
    data = build_repository_graph(sample_scan).to_dict()
    assert "nodes" in data
    assert "edges" in data
    assert data["node_count"] >= 1


def test_graph_find_related_modules(sample_scan):
    graph = build_repository_graph(sample_scan)
    matches = graph.find_related_modules("jarvis")
    assert len(matches) >= 1


def test_graph_find_affected_by_file(sample_scan):
    graph = build_repository_graph(sample_scan)
    affected = graph.find_affected_by_file("backend/app/api/routes_jarvis.py")
    assert isinstance(affected, list)


def test_scan_repository_read_only():
    report = scan_repository()
    assert report["read_only"] is True
    assert "modules" in report
    assert "api_endpoints" in report


def test_scan_repository_has_endpoints():
    report = scan_repository()
    assert isinstance(report["api_endpoints"], list)


def test_scan_repository_has_models():
    report = scan_repository()
    assert isinstance(report["database_models"], list)


def test_scan_repository_has_workflows():
    report = scan_repository()
    assert isinstance(report["workflows"], list)


def test_scan_repository_has_deployment_scripts():
    report = scan_repository()
    assert isinstance(report["deployment_scripts"], list)


def test_scan_incremental_delta(sample_scan):
    report = scan_repository(incremental=True, previous=sample_scan)
    assert report["incremental"] is True
    assert "delta" in report


def test_save_and_get_metadata(sample_scan, tmp_path, monkeypatch):
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_DIR", tmp_path)
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_FILE", tmp_path / "repository_metadata.json")
    saved = save_repository_metadata(sample_scan)
    assert saved["graph"]["node_count"] >= 1
    loaded = get_repository_metadata()
    assert loaded is not None
    assert loaded["report"]["file_count"] == 3


def test_refresh_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_DIR", tmp_path)
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_FILE", tmp_path / "repository_metadata.json")
    result = refresh_repository_metadata(incremental=False)
    assert "report" in result
    assert "graph" in result


def test_graph_module_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    module_nodes = [k for k, v in graph.nodes.items() if v.get("type") == "module"]
    assert len(module_nodes) >= 2


def test_graph_endpoint_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    ep_nodes = [k for k, v in graph.nodes.items() if v.get("type") == "api_endpoint"]
    assert len(ep_nodes) >= 1


def test_graph_model_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    model_nodes = [k for k, v in graph.nodes.items() if v.get("type") == "database_model"]
    assert len(model_nodes) >= 1


def test_graph_workflow_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    wf_nodes = [k for k, v in graph.nodes.items() if v.get("type") == "workflow"]
    assert len(wf_nodes) >= 1


def test_graph_deploy_nodes(sample_scan):
    graph = build_repository_graph(sample_scan)
    dep_nodes = [k for k, v in graph.nodes.items() if v.get("type") == "deployment"]
    assert len(dep_nodes) >= 1


def test_empty_scan_graph():
    graph = build_repository_graph({"modules": [], "api_endpoints": [], "database_models": [], "workflows": [], "deployment_scripts": []})
    assert graph.node_count == 0


def test_repository_graph_dataclass():
    g = RepositoryGraph(nodes={"a": {"type": "x"}}, edges=[])
    assert g.find_related_modules("a") == ["a"]


@pytest.mark.parametrize(
    "keyword",
    ["jarvis", "routes", "deploy", "workflow", "model"],
)
def test_find_related_keywords(sample_scan, keyword):
    graph = build_repository_graph(sample_scan)
    matches = graph.find_related_modules(keyword)
    assert isinstance(matches, list)


def test_scan_file_count_positive():
    report = scan_repository()
    assert report["file_count"] > 0


def test_scan_repo_root_present():
    report = scan_repository()
    assert report["repo_root"]


def test_get_metadata_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_FILE", tmp_path / "missing.json")
    assert get_repository_metadata() is None
