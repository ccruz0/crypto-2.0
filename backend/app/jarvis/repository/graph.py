"""Dependency graph builder for repository knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
        target = file_path.replace("\\", "/")
        affected: list[str] = []
        for edge in self.edges:
            if edge.get("target") == target or edge.get("source") == target:
                affected.append(edge.get("source", ""))
                affected.append(edge.get("target", ""))
        return list(dict.fromkeys(a for a in affected if a))


def build_repository_graph(scan_report: dict[str, Any]) -> RepositoryGraph:
    """Build a dependency graph from a repository scan report."""
    graph = RepositoryGraph(metadata={"scanned_at": scan_report.get("scanned_at")})

    for module in scan_report.get("modules", []):
        path = module.get("path", "")
        if not path:
            continue
        node_id = f"module:{path}"
        graph.nodes[node_id] = {
            "type": "module",
            "label": path,
            "line_count": module.get("line_count", 0),
        }
        for imp in module.get("imports", []):
            edge_target = f"import:{imp}"
            if edge_target not in graph.nodes:
                graph.nodes[edge_target] = {"type": "import", "label": imp}
            graph.edges.append({"source": node_id, "target": edge_target, "kind": "imports"})

    for endpoint in scan_report.get("api_endpoints", []):
        node_id = f"endpoint:{endpoint.get('path', '')}"
        graph.nodes[node_id] = {
            "type": "api_endpoint",
            "label": endpoint.get("path", ""),
            "file": endpoint.get("file", ""),
        }
        file_node = f"module:{endpoint.get('file', '')}"
        if file_node in graph.nodes:
            graph.edges.append({"source": file_node, "target": node_id, "kind": "defines"})

    for model in scan_report.get("database_models", []):
        node_id = f"model:{model.get('name', '')}"
        graph.nodes[node_id] = {
            "type": "database_model",
            "label": model.get("name", ""),
            "file": model.get("file", ""),
        }

    for wf in scan_report.get("workflows", []):
        node_id = f"workflow:{wf.get('name', wf.get('file', ''))}"
        graph.nodes[node_id] = {"type": "workflow", "label": wf.get("name", ""), "file": wf.get("file", "")}

    for script in scan_report.get("deployment_scripts", []):
        node_id = f"deploy:{script.get('path', '')}"
        graph.nodes[node_id] = {"type": "deployment", "label": script.get("path", "")}

    return graph
