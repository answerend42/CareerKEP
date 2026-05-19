from __future__ import annotations

from dataclasses import dataclass, field
from math import prod

from .graph_loader import GraphData, NodeDefinition


POSITIVE_RELATIONS = {"supports", "requires", "prefers"}
RELATION_FACTORS = {
    "supports": 1.0,
    "requires": 1.0,
    "prefers": 0.75,
    "inhibits": 1.0,
}
INHIBIT_FACTOR = 0.82
CORE_REQUIRE_SCORE_FACTOR = 0.65
AUX_REQUIRE_FACTOR = 0.55
AUX_PREFERENCE_FACTOR = 0.45
AUX_NODE_CAP = 0.12
AUX_ROLE_CAP = 0.08
FORMAL_CORE_THRESHOLD = 0.05
SUPPORT_PARENT_THRESHOLD = 0.02


@dataclass(slots=True)
class ParentContribution:
    parent_id: str
    parent_name: str
    relation: str
    edge_weight: float
    parent_score: float
    value: float
    note: str
    channel: str = "core"
    scoring_policy: str = "positive_support"
    provenance: str = "curated"
    eligible_for_gate: bool = True
    eligible_for_formal_score: bool = True


@dataclass(slots=True)
class NodeState:
    score: float
    direct_input: float
    evidence: dict[str, float] = field(default_factory=dict)
    parent_contributions: list[ParentContribution] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    core_score: float = 0.0
    aux_score: float = 0.0
    gate_score: float = 1.0
    formal_eligible: bool = False
    core_evidence: dict[str, float] = field(default_factory=dict)
    aux_evidence: dict[str, float] = field(default_factory=dict)


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
                    core_score=direct_input,
                    aux_score=0.0,
                    gate_score=1.0,
                    formal_eligible=direct_input > 0,
                    core_evidence=evidence,
                    diagnostics={
                        "aggregator": "source",
                        "support_total": round(direct_input, 4),
                        "core_score": round(direct_input, 4),
                        "aux_score": 0.0,
                        "formal_eligible": direct_input > 0,
                        "layer": node.layer,
                    },
                )
                continue

            incoming_edges = graph.incoming.get(node_id, [])
            core_root_maps: dict[str, dict[str, float]] = {relation: {} for relation in RELATION_FACTORS}
            aux_root_maps: dict[str, dict[str, float]] = {relation: {} for relation in RELATION_FACTORS}
            parent_contributions: list[ParentContribution] = []
            raw_required_scores: dict[str, float] = {}

            for edge in incoming_edges:
                if edge.channel not in {"core", "aux"}:
                    continue
                if edge.relation not in RELATION_FACTORS:
                    continue

                parent_state = states[edge.source]
                parent_score = parent_state.core_score if edge.channel == "core" else parent_state.score
                contribution = parent_score * edge.weight * RELATION_FACTORS[edge.relation] * edge.trust
                parent_contributions.append(
                    ParentContribution(
                        parent_id=edge.source,
                        parent_name=graph.nodes[edge.source].name,
                        relation=edge.relation,
                        edge_weight=edge.weight,
                        parent_score=parent_score,
                        value=round(contribution, 4),
                        note=edge.note,
                        channel=edge.channel,
                        scoring_policy=edge.scoring_policy,
                        provenance=edge.provenance,
                        eligible_for_gate=edge.eligible_for_gate,
                        eligible_for_formal_score=edge.eligible_for_formal_score,
                    )
                )

                if edge.channel == "core" and edge.relation == "requires" and edge.eligible_for_gate:
                    raw_required_scores[edge.source] = contribution

                if parent_score <= 0:
                    continue

                root_maps = core_root_maps if edge.channel == "core" else aux_root_maps
                parent_evidence = parent_state.core_evidence if edge.channel == "core" else parent_state.evidence
                for root_id, root_value in parent_evidence.items():
                    scaled = root_value * edge.weight * RELATION_FACTORS[edge.relation] * edge.trust
                    current = root_maps[edge.relation].get(root_id, 0.0)
                    if scaled > current:
                        root_maps[edge.relation][root_id] = scaled

            score, core_score, aux_score, evidence, core_evidence, aux_evidence, diagnostics = self._aggregate_node(
                graph=graph,
                node=node,
                direct_input=direct_input,
                core_root_maps=core_root_maps,
                aux_root_maps=aux_root_maps,
                parent_contributions=parent_contributions,
                raw_required_scores=raw_required_scores,
            )
            states[node_id] = NodeState(
                score=score,
                direct_input=direct_input,
                evidence=evidence,
                core_score=core_score,
                aux_score=aux_score,
                gate_score=float(diagnostics.get("gate_multiplier", 1.0) or 1.0),
                formal_eligible=bool(diagnostics.get("formal_eligible", False)),
                core_evidence=core_evidence,
                aux_evidence=aux_evidence,
                parent_contributions=sorted(parent_contributions, key=lambda item: item.value, reverse=True),
                diagnostics=diagnostics,
            )

        return states

    def _aggregate_node(
        self,
        graph: GraphData,
        node: NodeDefinition,
        direct_input: float,
        core_root_maps: dict[str, dict[str, float]],
        aux_root_maps: dict[str, dict[str, float]],
        parent_contributions: list[ParentContribution],
        raw_required_scores: dict[str, float],
    ) -> tuple[float, float, float, dict[str, float], dict[str, float], dict[str, float], dict]:
        cap = float(node.params.get("cap", 1.0) or 1.0)
        required_threshold = float(node.params.get("required_threshold", 0.0) or 0.0)
        required_floor = float(node.params.get("required_floor", 0.0) or 0.0)
        penalty_floor = float(node.params.get("penalty_floor", 0.0) or 0.0)
        min_support_count = int(node.params.get("min_support_count", 1) or 1)

        core_support_total = self._noisy_or(core_root_maps["supports"].values())
        core_require_total = self._noisy_or(core_root_maps["requires"].values())
        core_prefer_total = self._noisy_or(core_root_maps["prefers"].values())
        core_inhibit_total = self._noisy_or(core_root_maps["inhibits"].values())

        aux_support_total = self._noisy_or(aux_root_maps["supports"].values())
        aux_require_total = self._noisy_or(aux_root_maps["requires"].values())
        aux_prefer_total = self._noisy_or(aux_root_maps["prefers"].values())
        aux_inhibit_total = self._noisy_or(aux_root_maps["inhibits"].values())

        support_total = core_support_total
        require_total = core_require_total
        prefer_total = core_prefer_total
        inhibit_total = core_inhibit_total
        core_positive_root_map = self._combine_root_maps(
            (
                (core_root_maps["supports"], 1.0),
                (core_root_maps["requires"], CORE_REQUIRE_SCORE_FACTOR),
                (core_root_maps["prefers"], 1.0),
            )
        )
        aux_positive_root_map = self._combine_root_maps(
            (
                (aux_root_maps["supports"], 1.0),
                (aux_root_maps["requires"], AUX_REQUIRE_FACTOR),
                (aux_root_maps["prefers"], AUX_PREFERENCE_FACTOR),
            )
        )
        if direct_input > 0:
            core_positive_root_map[node.id] = max(core_positive_root_map.get(node.id, 0.0), direct_input)

        core_base_positive = min(
            cap,
            core_support_total
            + core_require_total * CORE_REQUIRE_SCORE_FACTOR
            + core_prefer_total
            + direct_input,
        )

        support_parent_count = len(
            {
                item.parent_id
                for item in parent_contributions
                if item.channel == "core"
                and item.relation in {"supports", "requires"}
                and item.value >= SUPPORT_PARENT_THRESHOLD
            }
        )
        coverage = min(1.0, support_parent_count / max(1, min_support_count))
        core_base_score = core_base_positive
        has_required_inputs = bool(raw_required_scores)

        if node.aggregator == "max_pool":
            best_parent = max(
                [
                    item.value
                    for item in parent_contributions
                    if item.channel == "core" and item.relation in {"supports", "requires"}
                ]
                + [direct_input],
                default=0.0,
            )
            core_base_score = min(cap, best_parent + core_prefer_total * 0.45)
        elif node.aggregator == "soft_and":
            if support_parent_count == 0:
                core_base_score = 0.0
            else:
                core_base_score = min(cap, core_base_positive * (0.45 + 0.55 * coverage))

        gate_multiplier = 1.0
        hard_gate_closed = False
        if node.aggregator == "hard_gate":
            if has_required_inputs and required_threshold > 0 and core_require_total < required_threshold:
                hard_gate_closed = True
                core_base_score = 0.0
        elif node.aggregator == "penalty_gate":
            if has_required_inputs and required_threshold > 0:
                ratio = core_require_total / required_threshold if required_threshold else 1.0
                gate_multiplier = 1.0 if ratio >= 1.0 else max(penalty_floor, ratio)
                core_base_score *= gate_multiplier
        elif has_required_inputs and required_threshold > 0:
            ratio = core_require_total / required_threshold if required_threshold else 1.0
            gate_multiplier = 1.0 if ratio >= 1.0 else max(required_floor, ratio)
            core_base_score *= gate_multiplier

        core_score = min(cap, max(0.0, core_base_score - core_inhibit_total * INHIBIT_FACTOR))
        aux_cap = AUX_ROLE_CAP if node.layer == "role" else AUX_NODE_CAP
        aux_positive = (
            aux_support_total
            + aux_require_total * AUX_REQUIRE_FACTOR
            + aux_prefer_total * AUX_PREFERENCE_FACTOR
        )
        aux_score = min(aux_cap, aux_positive)
        final_score = min(cap, max(0.0, core_score + aux_score))

        core_evidence = self._scale_evidence(core_positive_root_map, core_score)
        aux_evidence = self._scale_evidence(aux_positive_root_map, aux_score)
        evidence = self._merge_evidence(core_evidence, aux_evidence, final_score)
        missing_requirements = self._missing_requirements(graph, raw_required_scores, node)
        formal_eligible = node.layer != "role" or core_score >= FORMAL_CORE_THRESHOLD
        diagnostics = {
            "aggregator": node.aggregator,
            "support_total": round(support_total, 4),
            "require_total": round(require_total, 4),
            "prefer_total": round(prefer_total, 4),
            "inhibit_total": round(inhibit_total, 4),
            "core_support_total": round(core_support_total, 4),
            "core_require_total": round(core_require_total, 4),
            "core_prefer_total": round(core_prefer_total, 4),
            "core_inhibit_total": round(core_inhibit_total, 4),
            "aux_support_total": round(aux_support_total, 4),
            "aux_require_total": round(aux_require_total, 4),
            "aux_prefer_total": round(aux_prefer_total, 4),
            "aux_inhibit_total": round(aux_inhibit_total, 4),
            "aux_cap": aux_cap,
            "core_score": round(core_score, 4),
            "aux_score": round(aux_score, 4),
            "coverage": round(coverage, 4),
            "gate_multiplier": round(gate_multiplier, 4),
            "hard_gate_closed": hard_gate_closed,
            "formal_eligible": formal_eligible,
            "missing_requirements": missing_requirements,
        }
        return (
            round(final_score, 4),
            round(core_score, 4),
            round(aux_score, 4),
            evidence,
            core_evidence,
            aux_evidence,
            diagnostics,
        )

    @staticmethod
    def _noisy_or(values: object) -> float:
        clipped = [max(0.0, min(0.95, float(value))) for value in values]
        if not clipped:
            return 0.0
        return 1.0 - prod(1.0 - value for value in clipped)

    @staticmethod
    def _combine_root_maps(root_maps: tuple[tuple[dict[str, float], float], ...]) -> dict[str, float]:
        combined: dict[str, float] = {}
        for root_map, factor in root_maps:
            for root_id, value in root_map.items():
                scaled = value * factor
                current = combined.get(root_id, 0.0)
                if scaled > current:
                    combined[root_id] = scaled
        return combined

    @staticmethod
    def _scale_evidence(positive_root_map: dict[str, float], score: float) -> dict[str, float]:
        if score <= 0 or not positive_root_map:
            return {}
        total = sum(positive_root_map.values())
        if total <= 0:
            return {}
        scale = score / total
        return {
            root_id: round(value * scale, 4)
            for root_id, value in sorted(positive_root_map.items(), key=lambda item: item[1], reverse=True)
            if value * scale >= 0.01
        }

    @staticmethod
    def _merge_evidence(core_evidence: dict[str, float], aux_evidence: dict[str, float], final_score: float) -> dict[str, float]:
        if final_score <= 0:
            return {}
        merged = dict(core_evidence)
        for root_id, value in aux_evidence.items():
            merged[root_id] = max(merged.get(root_id, 0.0), value)
        return dict(sorted(merged.items(), key=lambda item: item[1], reverse=True))

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
