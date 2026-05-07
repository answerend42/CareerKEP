"""图谱分数传播与推理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas import NodeState, clamp01
from .graph_loader import GraphData, GraphEdge


RELATION_FACTORS = {
    "supports": 1.0,
    "evidences": 0.92,
    "requires": 1.0,
    "prefers": 0.75,
    "inhibits": 1.0,
}

INHIBIT_FACTOR = 0.82


@dataclass
class InferenceResult:
    """一次推理的完整结果。"""

    states: dict[str, NodeState] = field(default_factory=dict)
    topo_order: list[str] = field(default_factory=list)

    def to_snapshot(self, top_k: int = 12) -> list[dict[str, Any]]:
        items = sorted(self.states.values(), key=lambda item: item.score, reverse=True)[:top_k]
        return [item.to_dict() for item in items]


def _contribution_parent_score(state: NodeState, edge: GraphEdge) -> float:
    return state.score * edge.weight * RELATION_FACTORS.get(edge.relation, 1.0)


def _propagate_root_evidence(parent: NodeState, edge: GraphEdge) -> dict[str, float]:
    propagated: dict[str, float] = {}
    for root_id, root_score in parent.evidence.items():
        contribution = root_score * edge.weight * RELATION_FACTORS.get(edge.relation, 1.0)
        propagated[root_id] = max(propagated.get(root_id, 0.0), contribution)
    return propagated


def _aggregated_by_relation(root_maps: dict[str, dict[str, float]]) -> dict[str, float]:
    return {relation: sum(values.values()) for relation, values in root_maps.items()}


def _gate_multiplier(value: float, threshold: float, floor: float) -> float:
    if threshold <= 0:
        return 1.0
    if value >= threshold:
        return 1.0
    ratio = value / threshold if threshold > 0 else 0.0
    return max(floor, ratio)


def _collect_root_maps(parent_maps: list[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {relation: {} for relation in RELATION_FACTORS}
    for relation_map in parent_maps:
        for relation, root_map in relation_map.items():
            relation_bucket = merged.setdefault(relation, {})
            for root_id, contribution in root_map.items():
                relation_bucket[root_id] = max(relation_bucket.get(root_id, 0.0), contribution)
    return merged


def infer(graph: GraphData, evidence_map: dict[str, float]) -> InferenceResult:
    """按拓扑序执行推理。"""

    states: dict[str, NodeState] = {}

    for node_id in graph.topo_order:
        node = graph.node(node_id)
        direct_input = clamp01(evidence_map.get(node_id, 0.0))

        if node.layer == "evidence":
            state = NodeState(
                node_id=node_id,
                label=node.label,
                layer=node.layer,
                score=direct_input,
                direct_input=direct_input,
                evidence={node_id: direct_input} if direct_input > 0 else {},
                parent_contributions=[],
                diagnostics={"base_positive": direct_input, "inhibit_total": 0.0},
                aggregator=node.aggregator,
            )
            states[node_id] = state
            continue

        parent_contributions: list[dict[str, Any]] = []
        parent_root_maps: list[dict[str, dict[str, float]]] = []
        parent_relation_contribs: list[float] = []

        for edge in graph.incoming.get(node_id, []):
            parent = states[edge.source]
            edge_contribution = _contribution_parent_score(parent, edge)
            parent_contributions.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.relation,
                    "weight": edge.weight,
                    "contribution": round(edge_contribution, 6),
                }
            )
            parent_relation_contribs.append(edge_contribution)
            propagated_root = _propagate_root_evidence(parent, edge)
            parent_root_maps.append({edge.relation: propagated_root})

        relation_root_maps = _collect_root_maps(parent_root_maps)
        relation_totals = _aggregated_by_relation(relation_root_maps)

        support_total = relation_totals.get("supports", 0.0) + 0.92 * relation_totals.get("evidences", 0.0)
        require_total = relation_totals.get("requires", 0.0)
        prefer_total = relation_totals.get("prefers", 0.0) * 0.75
        inhibit_total = relation_totals.get("inhibits", 0.0)
        base_positive = min(node.cap, support_total + require_total + prefer_total + direct_input)
        coverage = 0.0
        if node.min_support_count > 0:
            effective_support_count = sum(
                1
                for edge in graph.incoming.get(node_id, [])
                if edge.relation in {"supports", "evidences", "requires"}
                and (states[edge.source].score * edge.weight) >= 0.05
            )
            coverage = min(1.0, effective_support_count / node.min_support_count)

        if node.aggregator == "source":
            base_score = direct_input
        elif node.aggregator == "max_pool":
            best_parent = max(parent_relation_contribs, default=0.0)
            base_score = min(node.cap, best_parent + prefer_total * 0.45 + direct_input)
        elif node.aggregator == "soft_and":
            base_score = min(node.cap, base_positive * (0.45 + 0.55 * coverage))
        elif node.aggregator == "penalty_gate":
            gate = _gate_multiplier(require_total, node.required_threshold, node.penalty_floor)
            base_score = base_positive * gate
        elif node.aggregator == "hard_gate":
            if node.required_threshold > 0 and require_total < node.required_threshold:
                base_score = 0.0
            else:
                base_score = base_positive
        else:
            gate = 1.0
            if node.required_threshold > 0:
                gate = _gate_multiplier(require_total, node.required_threshold, node.required_floor)
            base_score = base_positive * gate

        final_score = min(node.cap, max(0.0, base_score - inhibit_total * INHIBIT_FACTOR))

        positive_root_maps: dict[str, float] = {}
        for relation in ("supports", "evidences", "requires", "prefers"):
            for root_id, contribution in relation_root_maps.get(relation, {}).items():
                positive_root_maps[root_id] = max(positive_root_maps.get(root_id, 0.0), contribution)
        if direct_input > 0:
            positive_root_maps[node_id] = max(positive_root_maps.get(node_id, 0.0), direct_input)

        evidence: dict[str, float] = {}
        positive_total = sum(positive_root_maps.values())
        if positive_total > 0 and final_score > 0:
            scale = final_score / positive_total
            for root_id, contribution in positive_root_maps.items():
                scaled = contribution * scale
                if scaled >= 0.01:
                    evidence[root_id] = round(scaled, 6)

        diagnostics = {
            "support_total": round(support_total, 6),
            "require_total": round(require_total, 6),
            "prefer_total": round(prefer_total, 6),
            "inhibit_total": round(inhibit_total, 6),
            "base_positive": round(base_positive, 6),
            "coverage": round(coverage, 6),
        }
        state = NodeState(
            node_id=node_id,
            label=node.label,
            layer=node.layer,
            score=round(final_score, 6),
            direct_input=direct_input,
            evidence=evidence,
            parent_contributions=parent_contributions,
            diagnostics=diagnostics,
            aggregator=node.aggregator,
        )
        states[node_id] = state

    return InferenceResult(states=states, topo_order=list(graph.topo_order))
