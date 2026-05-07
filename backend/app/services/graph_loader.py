"""加载后端运行时图谱。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import math
from pathlib import Path
import json
import re
from typing import Any


VALID_LAYERS = frozenset({"evidence", "ability", "composite", "direction", "role"})
VALID_RELATIONS = frozenset({"supports", "evidences", "requires", "prefers", "inhibits"})
VALID_AGGREGATORS = frozenset({"source", "weighted_sum_capped", "max_pool", "soft_and", "penalty_gate", "hard_gate"})
LAYER_ORDER = {
    "evidence": 0,
    "ability": 1,
    "composite": 2,
    "direction": 3,
    "role": 4,
}
SCORE_FIELD_RANGES = {
    "cap": (0.0, 1.0),
    "required_threshold": (0.0, 1.0),
    "required_floor": (0.0, 1.0),
    "penalty_floor": (0.0, 1.0),
}
EDGE_WEIGHT_RANGE = (0.0, 1.0)
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
        aggregator_counts: dict[str, int] = {}
        for node in self.nodes.values():
            layer_counts[node.layer] = layer_counts.get(node.layer, 0) + 1
            aggregator_counts[node.aggregator] = aggregator_counts.get(node.aggregator, 0) + 1

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
            "aggregators": aggregator_counts,
            "validation": {
                "status": "ok",
                "warnings": [],
            },
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


def _coerce_finite_float(value: Any, location: str, errors: list[str]) -> float | None:
    if isinstance(value, bool):
        errors.append(f"{location}: 必须是有限数")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{location}: 必须是有限数")
        return None
    if not math.isfinite(number):
        errors.append(f"{location}: 必须是有限数")
        return None
    return number


def _validate_float_range(value: Any, location: str, min_value: float, max_value: float, errors: list[str]) -> None:
    number = _coerce_finite_float(value, location, errors)
    if number is None:
        return
    if number < min_value or number > max_value:
        errors.append(f"{location}: 必须位于 {min_value:g}..{max_value:g}")


def _validate_non_negative_int(value: Any, location: str, errors: list[str]) -> None:
    if isinstance(value, bool):
        errors.append(f"{location}: 必须是非负整数")
        return
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{location}: 必须是非负整数")
        return
    if number < 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        errors.append(f"{location}: 必须是非负整数")


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

        for field_name, (min_value, max_value) in SCORE_FIELD_RANGES.items():
            if field_name in item:
                _validate_float_range(item[field_name], f"{location}.{field_name}", min_value, max_value, errors)
        if "min_support_count" in item:
            _validate_non_negative_int(item["min_support_count"], f"{location}.min_support_count", errors)

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

        if "weight" in item:
            _validate_float_range(item["weight"], f"{location}.weight", *EDGE_WEIGHT_RANGE, errors)

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


def _raise_validation_errors(errors: list[str]) -> None:
    if errors:
        raise GraphValidationError("图谱校验失败:\n- " + "\n- ".join(errors))


def _validate_edge_topology(nodes: dict[str, GraphNode], edges: list[GraphEdge]) -> None:
    errors: list[str] = []

    for index, edge in enumerate(edges):
        location = f"edges[{index}]"
        source_node = nodes.get(edge.source)
        target_node = nodes.get(edge.target)
        if source_node is None or target_node is None:
            errors.append(f"{location}: 边引用了不存在的节点 {edge.source!r} -> {edge.target!r}")
            continue

        source_order = LAYER_ORDER[source_node.layer]
        target_order = LAYER_ORDER[target_node.layer]
        # 允许跳层是为了保留 seed 中 evidence 直接影响 direction/role 的业务捷径；
        # 但边必须严格向后流动，避免把推荐图谱变成难以解释的反馈网络。
        if source_order >= target_order:
            errors.append(
                f"{location}: 层级方向必须向后流动，"
                f"{edge.source}({source_node.layer}) -> {edge.target}({target_node.layer}) 不合法"
            )

    _raise_validation_errors(errors)


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

    _validate_edge_topology(nodes, edges)

    incoming: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}

    for edge in edges:
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


def build_graph_diagnostics(
    graph: GraphData,
    alias_map: dict[str, list[str]],
    alias_warnings: list[str],
) -> dict[str, Any]:
    """构造本地图谱诊断信息。

    诊断命令需要比线上元信息多一些本地检查细节，但仍复用同一份 summary，
    避免 API 和 CLI 对图谱规模的理解分叉。
    """

    summary = graph.summary()
    return {
        **summary,
        "alias_count": sum(len(aliases) for aliases in alias_map.values()),
        "alias_node_count": len(alias_map),
        "validation": {
            "status": "ok",
            "warnings": alias_warnings,
        },
    }
