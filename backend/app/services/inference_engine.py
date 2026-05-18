from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .graph_loader import GraphData, NodeDefinition


POSITIVE_RELATIONS = {"supports", "evidences", "requires", "prefers"}
RELATION_FACTORS = {
    "supports": 1.0,
    "evidences": 0.92,
    "requires": 1.0,
    "prefers": 0.75,
    "inhibits": 1.0,
}
INHIBIT_FACTOR = 0.82


@dataclass(slots=True)
class ParentContribution:
    parent_id: str
    parent_name: str
    relation: str
    edge_weight: float
    parent_score: float
    value: float
    note: str


@dataclass(slots=True)
class NodeState:
    score: float
    direct_input: float
    evidence: dict[str, float] = field(default_factory=dict)
    parent_contributions: list[ParentContribution] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


class InferenceEngine:
    def run(self, graph: GraphData, user_scores: dict[str, float]) -> dict[str, NodeState]:
        states: dict[str, NodeState] = {}
        for node_id in graph.topological_order:
            node = graph.nodes[node_id]
            direct_input = max(0.0, min(1.0, user_scores.get(node_id, 0.0)))
            if node.layer == "evidence":
                evidence = {node_id: direct_input} if direct_input > 0 else {}
                states[node_id] = NodeState(
                    score=direct_input,
                    direct_input=direct_input,
                    evidence=evidence,
                    diagnostics={
                        "aggregator": "source",
                        "support_total": round(direct_input, 4),
                        "layer": node.layer,
                    },
                )
                continue

            incoming_edges = graph.incoming.get(node_id, [])
            relation_root_maps: dict[str, dict[str, float]] = {relation: {} for relation in RELATION_FACTORS}
            parent_contributions: list[ParentContribution] = []
            raw_required_scores: dict[str, float] = {}

            for edge in incoming_edges:
                parent_state = states[edge.source]
                contribution = parent_state.score * edge.weight * RELATION_FACTORS[edge.relation]
                parent_contributions.append(
                    ParentContribution(
                        parent_id=edge.source,
                        parent_name=graph.nodes[edge.source].name,
                        relation=edge.relation,
                        edge_weight=edge.weight,
                        parent_score=parent_state.score,
                        value=round(contribution, 4),
                        note=edge.note,
                    )
                )
                if edge.relation == "requires":
                    raw_required_scores[edge.source] = contribution

                if parent_state.score <= 0:
                    continue
                for root_id, root_value in parent_state.evidence.items():
                    scaled = root_value * edge.weight * RELATION_FACTORS[edge.relation]
                    current = relation_root_maps[edge.relation].get(root_id, 0.0)
                    if scaled > current:
                        relation_root_maps[edge.relation][root_id] = scaled

            score, evidence, diagnostics = self._aggregate_node(
                graph=graph,
                node=node,
                direct_input=direct_input,
                relation_root_maps=relation_root_maps,
                parent_contributions=parent_contributions,
                raw_required_scores=raw_required_scores,
            )
            states[node_id] = NodeState(
                score=score,
                direct_input=direct_input,
                evidence=evidence,
                parent_contributions=sorted(parent_contributions, key=lambda item: item.value, reverse=True),
                diagnostics=diagnostics,
            )

        return states

    def _aggregate_node(
        self,
        graph: GraphData,
        node: NodeDefinition,
        direct_input: float,
        relation_root_maps: dict[str, dict[str, float]],
        parent_contributions: list[ParentContribution],
        raw_required_scores: dict[str, float],
    ) -> tuple[float, dict[str, float], dict]:
        cap = float(node.params.get("cap", 1.0) or 1.0)
        required_threshold = float(node.params.get("required_threshold", 0.0) or 0.0)
        required_floor = float(node.params.get("required_floor", 0.0) or 0.0)
        penalty_floor = float(node.params.get("penalty_floor", 0.0) or 0.0)
        min_support_count = int(node.params.get("min_support_count", 1) or 1)

        positive_root_map = self._combine_positive_root_maps(relation_root_maps)
        prefer_root_map = {
            root_id: value * RELATION_FACTORS["prefers"]
            for root_id, value in relation_root_maps["prefers"].items()
        }
        for root_id, value in prefer_root_map.items():
            current = positive_root_map.get(root_id, 0.0)
            if value > current:
                positive_root_map[root_id] = value
        if direct_input > 0:
            positive_root_map[node.id] = max(positive_root_map.get(node.id, 0.0), direct_input)

        support_total = sum(relation_root_maps["supports"].values()) + sum(relation_root_maps["evidences"].values()) * 0.92
        require_total = sum(relation_root_maps["requires"].values())
        prefer_total = sum(prefer_root_map.values())
        inhibit_total = sum(relation_root_maps["inhibits"].values())
        base_positive = min(cap, support_total + require_total + prefer_total + direct_input)

        support_parent_count = len(
            {
                item.parent_id
                for item in parent_contributions
                if item.relation in {"supports", "evidences", "requires"} and item.value >= 0.05
            }
        )
        coverage = min(1.0, support_parent_count / max(1, min_support_count))
        base_score = base_positive
        has_required_inputs = bool(raw_required_scores)

        if node.aggregator == "max_pool":
            best_parent = max(
                [item.value for item in parent_contributions if item.relation in {"supports", "evidences", "requires"}] + [direct_input],
                default=0.0,
            )
            base_score = min(cap, best_parent + prefer_total * 0.45)
        elif node.aggregator == "soft_and":
            if support_parent_count == 0:
                base_score = 0.0
            else:
                base_score = min(cap, base_positive * (0.45 + 0.55 * coverage))

        gate_multiplier = 1.0
        hard_gate_closed = False
        if node.aggregator == "hard_gate":
            if has_required_inputs and required_threshold > 0 and require_total < required_threshold:
                hard_gate_closed = True
                base_score = 0.0
        elif node.aggregator == "penalty_gate":
            if has_required_inputs and required_threshold > 0:
                ratio = require_total / required_threshold if required_threshold else 1.0
                gate_multiplier = 1.0 if ratio >= 1.0 else max(penalty_floor, ratio)
                base_score *= gate_multiplier
        elif has_required_inputs and required_threshold > 0:
            ratio = require_total / required_threshold if required_threshold else 1.0
            gate_multiplier = 1.0 if ratio >= 1.0 else max(required_floor, ratio)
            base_score *= gate_multiplier

        final_score = min(cap, max(0.0, base_score - inhibit_total * INHIBIT_FACTOR))
        evidence = self._scale_evidence(positive_root_map, final_score)
        missing_requirements = self._missing_requirements(graph, raw_required_scores, node)
        diagnostics = {
            "aggregator": node.aggregator,
            "support_total": round(support_total, 4),
            "require_total": round(require_total, 4),
            "prefer_total": round(prefer_total, 4),
            "inhibit_total": round(inhibit_total, 4),
            "coverage": round(coverage, 4),
            "gate_multiplier": round(gate_multiplier, 4),
            "hard_gate_closed": hard_gate_closed,
            "missing_requirements": missing_requirements,
        }
        return round(final_score, 4), evidence, diagnostics

    @staticmethod
    def _combine_positive_root_maps(relation_root_maps: dict[str, dict[str, float]]) -> dict[str, float]:
        combined: dict[str, float] = {}
        for relation in ("supports", "evidences", "requires"):
            factor = 0.92 if relation == "evidences" else 1.0
            for root_id, value in relation_root_maps[relation].items():
                scaled = value * factor
                current = combined.get(root_id, 0.0)
                if scaled > current:
                    combined[root_id] = scaled
        return combined

    @staticmethod
    def _scale_evidence(positive_root_map: dict[str, float], final_score: float) -> dict[str, float]:
        if final_score <= 0 or not positive_root_map:
            return {}
        total = sum(positive_root_map.values())
        if total <= 0:
            return {}
        scale = final_score / total
        return {
            root_id: round(value * scale, 4)
            for root_id, value in sorted(positive_root_map.items(), key=lambda item: item[1], reverse=True)
            if value * scale >= 0.01
        }

    @staticmethod
    def _missing_requirements(graph: GraphData, raw_required_scores: dict[str, float], node: NodeDefinition) -> list[str]:
        if not raw_required_scores:
            return []
        threshold = float(node.params.get("required_threshold", 0.0) or 0.0)
        if threshold <= 0:
            floor = 0.12
        else:
            floor = min(0.18, threshold / max(1, len(raw_required_scores)))
        missing = [
            graph.nodes[parent_id].name
            for parent_id, value in raw_required_scores.items()
            if value < floor
        ]
        return sorted(missing)
