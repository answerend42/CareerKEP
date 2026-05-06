"""加载后端运行时图谱。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import json
import re
from typing import Any


VALID_LAYERS = frozenset({"evidence", "ability", "composite", "direction", "role"})
VALID_RELATIONS = frozenset({"supports", "evidences", "requires", "prefers", "inhibits"})
VALID_AGGREGATORS = frozenset({"source", "weighted_sum_capped", "max_pool", "soft_and", "penalty_gate", "hard_gate"})
_NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class GraphValidationError(ValueError):
    """运行时图谱产物不满足后端契约。"""


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

    def summary(self) -> dict[str, Any]:
        """返回适合接口层输出的图谱概览。"""

        layer_counts: dict[str, int] = {}
        for node in self.nodes.values():
            layer_counts[node.layer] = layer_counts.get(node.layer, 0) + 1

        relation_counts: dict[str, int] = {}
        for edge in self.edges:
            relation_counts[edge.relation] = relation_counts.get(edge.relation, 0) + 1

        role_nodes = [
            node.to_dict()
            for node in self.nodes.values()
            if node.layer == "role"
        ]
        role_nodes.sort(key=lambda item: item["label"])

        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "layers": layer_counts,
            "relations": relation_counts,
            "role_nodes": role_nodes,
        }


def _base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_mapping(item: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        errors.append(f"{location}: 必须是 JSON 对象")
        return {}
    return item


def _validate_node_payloads(nodes_payload: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for index, raw_item in enumerate(nodes_payload):
        location = f"nodes[{index}]"
        item = _require_mapping(raw_item, location, errors)
        if not item:
            continue

        node_id = str(item.get("id") or "").strip()
        if not node_id:
            errors.append(f"{location}.id: 必须填写")
        elif not _NODE_ID_PATTERN.fullmatch(node_id):
            errors.append(f"{location}.id: 必须使用小写 snake_case，当前为 {node_id!r}")
        elif node_id in seen_ids:
            errors.append(f"{location}.id: 节点 ID 重复 {node_id!r}")
        else:
            seen_ids.add(node_id)

        layer = item.get("layer")
        if layer is None:
            errors.append(f"{location}.layer: 必须填写")
        elif str(layer) not in VALID_LAYERS:
            errors.append(f"{location}.layer: 未知层级 {layer!r}")

        aggregator = str(item.get("aggregator", "weighted_sum_capped"))
        if aggregator not in VALID_AGGREGATORS:
            errors.append(f"{location}.aggregator: 未知聚合器 {aggregator!r}")
        if aggregator == "source" and item.get("layer") != "evidence":
            errors.append(f"{location}.aggregator: source 聚合器只能用于 evidence 节点")

    return errors


def _validate_edge_payloads(edges_payload: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []

    for index, raw_item in enumerate(edges_payload):
        location = f"edges[{index}]"
        item = _require_mapping(raw_item, location, errors)
        if not item:
            continue

        for field_name in ("source", "target"):
            value = str(item.get(field_name) or "").strip()
            if not value:
                errors.append(f"{location}.{field_name}: 必须填写")

        relation = item.get("relation")
        if relation is None:
            errors.append(f"{location}.relation: 必须填写")
        elif str(relation) not in VALID_RELATIONS:
            errors.append(f"{location}.relation: 未知关系 {relation!r}")

    return errors


def _validate_graph_payloads(nodes_payload: Any, edges_payload: Any) -> None:
    errors: list[str] = []
    if not isinstance(nodes_payload, list):
        errors.append("nodes: 必须是 JSON 数组")
    if not isinstance(edges_payload, list):
        errors.append("edges: 必须是 JSON 数组")

    if not errors:
        errors.extend(_validate_node_payloads(nodes_payload))
        errors.extend(_validate_edge_payloads(edges_payload))

    if errors:
        raise GraphValidationError("图谱校验失败:\n- " + "\n- ".join(errors))


def _build_graph(nodes_payload: list[dict[str, Any]], edges_payload: list[dict[str, Any]]) -> GraphData:
    _validate_graph_payloads(nodes_payload, edges_payload)

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
            raise GraphValidationError(f"图谱校验失败:\n- 边引用了不存在的节点: {edge}")
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
        raise GraphValidationError("图谱校验失败:\n- 图谱不是 DAG，无法进行拓扑推理")

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


@lru_cache(maxsize=1)
def load_graph_summary() -> dict[str, Any]:
    """加载图谱概览，供 HTTP 元信息接口直接使用。"""

    return load_graph_data().summary()
