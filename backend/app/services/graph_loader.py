"""加载后端运行时图谱。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import json
from typing import Any


@dataclass(slots=True)
class GraphNode:
    """运行时图谱节点。"""

    id: str
    label: str
    layer: str
    aggregator: str = "weighted_sum_capped"
    cap: float = 1.0
    required_threshold: float = 0.0
    required_floor: float = 0.3
    penalty_floor: float = 0.35
    min_support_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "layer": self.layer,
            "aggregator": self.aggregator,
            "cap": self.cap,
            "required_threshold": self.required_threshold,
            "required_floor": self.required_floor,
            "penalty_floor": self.penalty_floor,
            "min_support_count": self.min_support_count,
        }


@dataclass(slots=True)
class GraphEdge:
    """运行时图谱边。"""

    source: str
    target: str
    relation: str
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "weight": self.weight,
        }


@dataclass(slots=True)
class GraphData:
    """完整图谱数据与邻接关系。"""

    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    incoming: dict[str, list[GraphEdge]] = field(default_factory=dict)
    outgoing: dict[str, list[GraphEdge]] = field(default_factory=dict)
    topo_order: list[str] = field(default_factory=list)

    def node(self, node_id: str) -> GraphNode:
        return self.nodes[node_id]


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_graph(nodes_payload: list[dict[str, Any]], edges_payload: list[dict[str, Any]]) -> GraphData:
    nodes = {
        item["id"]: GraphNode(
            id=item["id"],
            label=item.get("label", item["id"]),
            layer=item["layer"],
            aggregator=item.get("aggregator", "weighted_sum_capped"),
            cap=float(item.get("cap", 1.0)),
            required_threshold=float(item.get("required_threshold", 0.0)),
            required_floor=float(item.get("required_floor", 0.3)),
            penalty_floor=float(item.get("penalty_floor", 0.35)),
            min_support_count=int(item.get("min_support_count", 1)),
        )
        for item in nodes_payload
    }

    edges = [
        GraphEdge(
            source=item["source"],
            target=item["target"],
            relation=item["relation"],
            weight=float(item.get("weight", 1.0)),
        )
        for item in edges_payload
    ]

    incoming: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}

    for edge in edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError(f"边引用了不存在的节点: {edge}")
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)
        indegree[edge.target] += 1

    # 这里直接做一次拓扑排序，保证推理阶段按 DAG 顺序传播。
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    topo_order: list[str] = []
    while queue:
        current = queue.pop(0)
        topo_order.append(current)
        for edge in outgoing[current]:
            indegree[edge.target] -= 1
            if indegree[edge.target] == 0:
                queue.append(edge.target)

    if len(topo_order) != len(nodes):
        raise ValueError("图谱不是 DAG，无法进行拓扑推理")

    return GraphData(nodes=nodes, edges=edges, incoming=incoming, outgoing=outgoing, topo_order=topo_order)


@lru_cache(maxsize=1)
def load_graph_data() -> GraphData:
    """从 backend/data/seeds 目录加载图谱。"""

    seed_dir = _base_dir() / "data" / "seeds"
    nodes_path = seed_dir / "nodes.json"
    edges_path = seed_dir / "edges.json"
    nodes_payload = _load_json(nodes_path)
    edges_payload = _load_json(edges_path)
    return _build_graph(nodes_payload, edges_payload)

