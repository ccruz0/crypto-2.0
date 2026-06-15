"""Dependency graph builder for repository knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _module_node_id(path: str) -> str:
    return f"module:{path.replace(chr(92), '/')}"


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


@dataclass
class RepositoryGraph:
    """In-memory dependency graph derived from scan metadata."""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "metadata": self.metadata,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    def find_related_modules(self, keyword: str, *, limit: int = 10) -> list[str]:
        key = keyword.lower()
        matches: list[str] = []
        for node_id, data in self.nodes.items():
            hay = f"{node_id} {data.get('label', '')}".lower()
            if key in hay:
                matches.append(node_id)
            if len(matches) >= limit:
                break
        return matches

    def find_affected_by_file(self, file_path: str) -> list[str]:
        """Return node IDs connected to a file path (impact analysis)."""
        target = _normalize_path(file_path)
        module_id = _module_node_id(target)
        affected: list[str] = []
        for edge in self.edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            src_path = src.removeprefix("module:")
            tgt_path = tgt.removeprefix("module:")
            if target in (src_path, tgt_path) or module_id in (src, tgt):
                affected.extend([src, tgt])
        for node_id, data in self.nodes.items():
            if data.get("file") == target or data.get("label") == target:
                affected.append(node_id)
        return list(dict.fromkeys(a for a in affected if a))


def build_repository_graph(scan_report: dict[str, Any]) -> RepositoryGraph:
    """Build a dependency graph from a repository scan report."""
    graph = RepositoryGraph(
        metadata={
            "scanned_at": scan_report.get("scanned_at"),
            "index_summary": scan_report.get("index_summary", {}),
        }
    )

    _MODULE_KIND_TO_TYPE = {
        "python_module": "backend_module",
        "frontend_module": "frontend_module",
        "test": "test",
    }

    for module in scan_report.get("modules", []):
        path = _normalize_path(module.get("path", ""))
        if not path:
            continue
        node_id = _module_node_id(path)
        kind = module.get("kind", "python_module")
        graph.nodes[node_id] = {
            "type": _MODULE_KIND_TO_TYPE.get(kind, "module"),
            "label": path,
            "line_count": module.get("line_count", 0),
            "kind": kind,
        }
        for imp in module.get("imports", []):
            edge_target = f"import:{imp}"
            if edge_target not in graph.nodes:
                graph.nodes[edge_target] = {"type": "import", "label": imp}
            graph.edges.append({"source": node_id, "target": edge_target, "kind": "imports"})

    for endpoint in scan_report.get("api_endpoints", []):
        node_id = f"endpoint:{endpoint.get('path', '')}"
        file_path = _normalize_path(endpoint.get("file", ""))
        graph.nodes[node_id] = {
            "type": "api_endpoint",
            "label": endpoint.get("path", ""),
            "file": file_path,
        }
        file_node = _module_node_id(file_path)
        if file_node in graph.nodes:
            graph.edges.append({"source": file_node, "target": node_id, "kind": "defines"})
        elif file_path:
            graph.edges.append({"source": f"file:{file_path}", "target": node_id, "kind": "defines"})

    for model in scan_report.get("database_models", []):
        node_id = f"model:{model.get('name', '')}"
        file_path = _normalize_path(model.get("file", ""))
        graph.nodes[node_id] = {
            "type": "database_model",
            "label": model.get("name", ""),
            "file": file_path,
        }
        file_node = _module_node_id(file_path)
        if file_node in graph.nodes:
            graph.edges.append({"source": file_node, "target": node_id, "kind": "defines"})

    for wf in scan_report.get("workflows", []):
        wf_file = _normalize_path(wf.get("file", ""))
        node_id = f"workflow:{wf.get('name', wf_file)}"
        graph.nodes[node_id] = {
            "type": "workflow",
            "label": wf.get("name", ""),
            "file": wf_file,
        }
        file_node = _module_node_id(wf_file)
        if file_node in graph.nodes:
            graph.edges.append({"source": file_node, "target": node_id, "kind": "defines"})

    for script in scan_report.get("deployment_scripts", []):
        script_path = _normalize_path(script.get("path", ""))
        node_id = f"deploy:{script_path}"
        graph.nodes[node_id] = {
            "type": "deployment",
            "label": script_path,
            "kind": script.get("kind", "deployment_script"),
        }

    for script in scan_report.get("scripts", []):
        script_path = _normalize_path(script.get("path", ""))
        node_id = f"script:{script_path}"
        graph.nodes[node_id] = {"type": "script", "label": script_path}

    return graph
