from __future__ import annotations

from collections import Counter

from ..schemas import (
    ActionCard,
    ActionImpactNode,
    ActionSimulationResult,
    LearningPathStep,
    RoleScorePreview,
    SimulatedBoost,
)
from .graph_loader import GraphData
from .inference_engine import InferenceEngine, NodeState
from .role_gap_analyzer import RoleGapAnalyzer


TOP_ROLE_LIMIT = 5
ACTIVATED_NODE_LIMIT = 6


class ActionSimulator:
    def __init__(
        self,
        graph: GraphData,
        engine: InferenceEngine,
        role_gap_analyzer: RoleGapAnalyzer,
    ) -> None:
        self.graph = graph
        self.engine = engine
        self.role_gap_analyzer = role_gap_analyzer

    def simulate(
        self,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
        learning_path: list[LearningPathStep],
        action_keys: list[str],
        template_ids: list[str],
    ) -> ActionSimulationResult:
        if target_role_id not in self.graph.role_ids:
            raise ValueError(f"unknown target role: {target_role_id}")
        if not action_keys and not template_ids:
            raise ValueError("action_keys or template_ids is required")

        applied_actions, boosts = self._resolve_actions_and_boosts(
            states=states,
            learning_path=learning_path,
            action_keys=action_keys,
            template_ids=template_ids,
        )

        simulated_scores = dict(score_map)
        for boost in boosts:
            simulated_scores[boost.node_id] = max(simulated_scores.get(boost.node_id, 0.0), boost.to_score)
        simulated_states = self.engine.run(self.graph, simulated_scores)

        current_score = round(states[target_role_id].score, 4)
        predicted_score = round(simulated_states[target_role_id].score, 4)
        delta_score = round(predicted_score - current_score, 4)
        before_rank = self._rank_of_role(states, target_role_id)
        after_rank = self._rank_of_role(simulated_states, target_role_id)
        overlap_node_ids, overlap_node_names = self._build_overlap_nodes(applied_actions)
        activated_nodes = self._build_activated_nodes(
            before_states=states,
            after_states=simulated_states,
            excluded_node_ids={boost.node_id for boost in boosts} | {target_role_id},
        )

        return ActionSimulationResult(
            target_role_id=target_role_id,
            target_role_name=self.graph.nodes[target_role_id].name,
            action_keys=[action.action_key for action in applied_actions],
            template_ids=[action.template_id for action in applied_actions],
            bundle_size=len(applied_actions),
            current_score=current_score,
            predicted_score=predicted_score,
            delta_score=delta_score,
            summary=self._build_summary(
                target_role_id=target_role_id,
                applied_actions=applied_actions,
                current_score=current_score,
                predicted_score=predicted_score,
                delta_score=delta_score,
                before_rank=before_rank,
                after_rank=after_rank,
                activated_nodes=activated_nodes,
            ),
            bundle_summary=self._build_bundle_summary(applied_actions, overlap_node_names, activated_nodes),
            overlap_node_ids=overlap_node_ids,
            overlap_node_names=overlap_node_names,
            applied_actions=applied_actions,
            injected_boosts=boosts,
            activated_nodes=activated_nodes,
            before_top_roles=self._build_top_roles(states),
            after_top_roles=self._build_top_roles(simulated_states),
            target_role_rank_before=before_rank,
            target_role_rank_after=after_rank,
        )

    def _resolve_actions_and_boosts(
        self,
        states: dict[str, NodeState],
        learning_path: list[LearningPathStep],
        action_keys: list[str],
        template_ids: list[str],
    ) -> tuple[list[ActionCard], list[SimulatedBoost]]:
        action_key_lookup: dict[str, tuple[LearningPathStep, ActionCard]] = {}
        template_lookup: dict[str, list[tuple[LearningPathStep, ActionCard]]] = {}
        for step in learning_path:
            for action in step.recommended_actions:
                if action.action_key:
                    action_key_lookup[action.action_key] = (step, action)
                template_lookup.setdefault(action.template_id, []).append((step, action))

        applied_actions: list[ActionCard] = []
        boosts: list[SimulatedBoost] = []
        used_node_ids: set[str] = set()
        selected_actions: list[tuple[LearningPathStep, ActionCard]] = []
        if action_keys:
            for action_key in action_keys:
                if action_key not in action_key_lookup:
                    raise ValueError(f"action_key is not available in current learning path: {action_key}")
                selected_actions.append(action_key_lookup[action_key])
        else:
            for template_id in template_ids:
                matches = template_lookup.get(template_id, [])
                if not matches:
                    raise ValueError(f"template_id is not available in current learning path: {template_id}")
                if len(matches) > 1:
                    raise ValueError(f"template_id appears in multiple learning path steps: {template_id}; use action_key instead")
                selected_actions.append(matches[0])

        for step, action in selected_actions:
            applied_actions.append(action)
            action_boosts = self.role_gap_analyzer.build_boosts_from_node_ids(
                states=states,
                node_ids=action.simulation_node_ids,
                relation=step.relation,
                tip=f"执行行动：{action.title}",
                exclude_node_ids=used_node_ids,
                max_boosts=4,
            )
            boosts.extend(action_boosts)
            used_node_ids.update(boost.node_id for boost in action_boosts)

        return applied_actions, boosts

    def _build_overlap_nodes(self, applied_actions: list[ActionCard]) -> tuple[list[str], list[str]]:
        if len(applied_actions) < 2:
            return [], []

        counts: Counter[str] = Counter()
        for action in applied_actions:
            counts.update(dict.fromkeys(action.simulation_node_ids, 1))

        overlap_node_ids = [node_id for node_id, count in counts.items() if count >= 2 and node_id in self.graph.nodes]
        overlap_node_names = [self.graph.nodes[node_id].name for node_id in overlap_node_ids]
        return overlap_node_ids, overlap_node_names

    def _build_top_roles(self, states: dict[str, NodeState], limit: int = TOP_ROLE_LIMIT) -> list[RoleScorePreview]:
        ranked_role_ids = self._sorted_role_ids(states)
        return [
            RoleScorePreview(
                job_id=role_id,
                job_name=self.graph.nodes[role_id].name,
                score=round(states[role_id].score, 4),
            )
            for role_id in ranked_role_ids[:limit]
        ]

    def _rank_of_role(self, states: dict[str, NodeState], role_id: str) -> int:
        ranked_role_ids = self._sorted_role_ids(states)
        try:
            return ranked_role_ids.index(role_id) + 1
        except ValueError:
            return len(ranked_role_ids) + 1

    def _sorted_role_ids(self, states: dict[str, NodeState]) -> list[str]:
        return sorted(
            self.graph.role_ids,
            key=lambda node_id: (states[node_id].score, self.graph.nodes[node_id].name),
            reverse=True,
        )

    def _build_activated_nodes(
        self,
        before_states: dict[str, NodeState],
        after_states: dict[str, NodeState],
        excluded_node_ids: set[str],
        limit: int = ACTIVATED_NODE_LIMIT,
    ) -> list[ActionImpactNode]:
        deltas: list[tuple[float, int, str]] = []
        for node_id, node in self.graph.nodes.items():
            if node_id in excluded_node_ids or node.layer == "evidence":
                continue
            before_score = round(before_states[node_id].score, 4)
            after_score = round(after_states[node_id].score, 4)
            delta_score = round(after_score - before_score, 4)
            if delta_score < 0.03:
                continue
            deltas.append((delta_score, self._layer_priority(node.layer), node_id))

        deltas.sort(key=lambda item: (item[0], item[1], self.graph.nodes[item[2]].name), reverse=True)
        return [
            ActionImpactNode(
                node_id=node_id,
                node_name=self.graph.nodes[node_id].name,
                layer=self.graph.nodes[node_id].layer,
                before_score=round(before_states[node_id].score, 4),
                after_score=round(after_states[node_id].score, 4),
                delta_score=delta_score,
            )
            for delta_score, _, node_id in deltas[:limit]
        ]

    @staticmethod
    def _layer_priority(layer: str) -> int:
        return {
            "ability": 0,
            "composite": 1,
            "direction": 2,
            "role": 3,
        }.get(layer, 0)

    def _build_summary(
        self,
        target_role_id: str,
        applied_actions: list[ActionCard],
        current_score: float,
        predicted_score: float,
        delta_score: float,
        before_rank: int,
        after_rank: int,
        activated_nodes: list[ActionImpactNode],
    ) -> str:
        role_name = self.graph.nodes[target_role_id].name
        action_label = "、".join(action.title for action in applied_actions[:2]) or "所选行动"
        rank_text = (
            f"岗位排序从第 {before_rank} 名提升到第 {after_rank} 名"
            if after_rank < before_rank
            else f"岗位排序维持在第 {after_rank} 名附近"
        )

        if delta_score <= 0:
            return f"执行 {action_label} 后，{role_name} 仍维持在 {predicted_score:.2f} 分附近，短期内更像巩固已有能力而不是拉升岗位得分。"

        activated_text = ""
        if activated_nodes:
            activated_text = f"，并带动 {'、'.join(node.node_name for node in activated_nodes[:3])}"
        return (
            f"执行 {action_label} 后，{role_name} 预计从 {current_score:.2f} 分提升到 {predicted_score:.2f} 分，"
            f"增益 {delta_score:.2f} 分，{rank_text}{activated_text}。"
        )

    def _build_bundle_summary(
        self,
        applied_actions: list[ActionCard],
        overlap_node_names: list[str],
        activated_nodes: list[ActionImpactNode],
    ) -> str:
        if not applied_actions:
            return ""
        if len(applied_actions) == 1:
            return "当前是单动作模拟，结果主要反映这一步单独执行后的图谱增益。"

        if overlap_node_names:
            overlap_text = f"两项动作都覆盖了 {'、'.join(overlap_node_names[:3])}"
            if activated_nodes:
                return f"{overlap_text}，组合收益更偏向巩固共用证据，同时新增带动 {'、'.join(node.node_name for node in activated_nodes[:2])}。"
            return f"{overlap_text}，说明两项动作存在重复覆盖，组合收益会更偏向巩固而不是纯新增。"

        if activated_nodes:
            return f"两项动作覆盖范围基本互补，并共同带动 {'、'.join(node.node_name for node in activated_nodes[:3])}。"
        return "两项动作覆盖范围基本互补，组合模拟主要体现联合补强后的目标岗位增益。"
