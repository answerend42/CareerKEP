from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    id: str
    name: str
    layer: str
    node_type: str
    aggregator: str
    description: str
    params: dict
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EdgeDefinition:
    source: str
    target: str
    relation: str
    weight: float
    note: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class GraphData:
    nodes: dict[str, NodeDefinition]
    edges: list[EdgeDefinition]
    incoming: dict[str, list[EdgeDefinition]]
    outgoing: dict[str, list[EdgeDefinition]]
    topological_order: list[str]

    @property
    def role_ids(self) -> list[str]:
        return [node_id for node_id, node in self.nodes.items() if node.layer == "role"]

    @property
    def evidence_ids(self) -> list[str]:
        return [node_id for node_id, node in self.nodes.items() if node.layer == "evidence"]


class GraphLoader:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or repo_root()

    def _load_json(self, relative_path: str) -> object:
        path = self.base_dir / relative_path
        return json.loads(path.read_text(encoding="utf-8"))

    def load_graph(self) -> GraphData:
        raw_nodes = self._load_json("data/seeds/nodes.json")
        raw_edges = self._load_json("data/seeds/edges.json")

        nodes = {
            item["id"]: NodeDefinition(
                id=item["id"],
                name=item["name"],
                layer=item["layer"],
                node_type=item["node_type"],
                aggregator=item["aggregator"],
                description=item["description"],
                params=item.get("params", {}),
                metadata=item.get("metadata", {}),
            )
            for item in raw_nodes
        }
        edges = [
            EdgeDefinition(
                source=item["source"],
                target=item["target"],
                relation=item["relation"],
                weight=float(item["weight"]),
                note=item["note"],
                metadata=item.get("metadata", {}),
            )
            for item in raw_edges
        ]

        incoming: dict[str, list[EdgeDefinition]] = defaultdict(list)
        outgoing: dict[str, list[EdgeDefinition]] = defaultdict(list)
        indegree = {node_id: 0 for node_id in nodes}
        for edge in edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError(f"invalid edge {edge.source}->{edge.target}")
            incoming[edge.target].append(edge)
            outgoing[edge.source].append(edge)
            indegree[edge.target] += 1

        queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
        topological_order: list[str] = []
        while queue:
            node_id = queue.popleft()
            topological_order.append(node_id)
            for edge in outgoing.get(node_id, []):
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    queue.append(edge.target)

        if len(topological_order) != len(nodes):
            raise ValueError("graph contains a cycle or disconnected indegree bookkeeping error")

        return GraphData(
            nodes=nodes,
            edges=edges,
            incoming=dict(incoming),
            outgoing=dict(outgoing),
            topological_order=topological_order,
        )

    def load_aliases(self) -> dict[str, list[str]]:
        return self._load_json("data/dictionaries/skill_aliases.json")  # type: ignore[return-value]

    def load_preference_patterns(self) -> dict[str, list[str]]:
        return self._load_json("data/dictionaries/preference_patterns.json")  # type: ignore[return-value]

    def load_parsing_patterns(self) -> dict:
        return self._load_json("data/dictionaries/parsing_patterns.json")  # type: ignore[return-value]

    def load_action_templates(self) -> list[dict[str, Any]]:
        return self._load_json("data/demo/action_templates.json")  # type: ignore[return-value]
