from __future__ import annotations

from collections import Counter

from ..schemas import GapSuggestion, LearningPathStep, SimulatedBoost, SimulationScenario
from .graph_loader import GraphData
from .inference_engine import NodeState
from .role_gap_analyzer import RoleGapAnalyzer


MIN_STEP_DELTA = 0.03
MAX_ROADMAP_STEPS = 4
TARGET_READY_SCORE = 0.62

LAYER_PRIORITY = {
    "evidence": 0,
    "ability": 1,
    "composite": 2,
    "direction": 3,
    "role": 4,
}


class LearningPathPlanner:
    def __init__(self, graph: GraphData, role_gap_analyzer: RoleGapAnalyzer) -> None:
        self.graph = graph
        self.role_gap_analyzer = role_gap_analyzer

    def plan(
        self,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
        step_limit: int = MAX_ROADMAP_STEPS,
    ) -> list[LearningPathStep]:
        if target_role_id not in self.graph.role_ids:
            raise ValueError(f"unknown target role: {target_role_id}")

        working_states = states
        working_scores = dict(score_map)
        used_boost_node_ids: set[str] = set()
        focus_counts: Counter[str] = Counter()
        steps: list[LearningPathStep] = []

        for step_index in range(1, max(1, min(MAX_ROADMAP_STEPS, step_limit)) + 1):
            candidate = self._select_best_step(
                step_index=step_index,
                states=working_states,
                score_map=working_scores,
                target_role_id=target_role_id,
                used_boost_node_ids=used_boost_node_ids,
                focus_counts=focus_counts,
            )
            if candidate is None:
                break

            suggestion = candidate["suggestion"]
            scenario = candidate["scenario"]
            simulated_states = candidate["simulated_states"]
            boosts = candidate["boosts"]
            blocked_by = self._collect_blocked_by(working_states, target_role_id, suggestion)
            unlock_nodes = self._collect_unlock_nodes(
                before_states=working_states,
                after_states=simulated_states,
                focus_node_id=suggestion.node_id,
                target_role_id=target_role_id,
            )

            steps.append(
                LearningPathStep(
                    step=step_index,
                    focus_node_id=suggestion.node_id,
                    focus_node_name=suggestion.node_name,
                    relation=suggestion.relation,
                    title=self._build_step_title(step_index, suggestion),
                    summary=self._build_step_summary(
                        target_role_id=target_role_id,
                        suggestion=suggestion,
                        scenario=scenario,
                        blocked_by=blocked_by,
                        unlock_nodes=unlock_nodes,
                    ),
                    expected_score_delta=scenario.delta_score,
                    expected_total_score=scenario.predicted_score,
                    blocked_by=blocked_by,
                    unlock_nodes=unlock_nodes,
                    boosts=boosts,
                )
            )

            for boost in boosts:
                working_scores[boost.node_id] = max(working_scores.get(boost.node_id, 0.0), boost.to_score)
                used_boost_node_ids.add(boost.node_id)
            focus_counts[suggestion.node_id] += 1
            working_states = simulated_states

            target_state = working_states[target_role_id]
            if target_state.score >= TARGET_READY_SCORE and not target_state.diagnostics.get("missing_requirements"):
                break

        return steps

    def _select_best_step(
        self,
        step_index: int,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
        used_boost_node_ids: set[str],
        focus_counts: Counter[str],
    ) -> dict[str, object] | None:
        suggestions = self.role_gap_analyzer.build_gap_suggestions(states, target_role_id, limit=6)
        if not suggestions:
            return None

        target_state = states[target_role_id]
        best_candidate: dict[str, object] | None = None

        for suggestion in suggestions:
            if focus_counts[suggestion.node_id] >= 2:
                continue

            boosts = self.role_gap_analyzer.build_simulation_boosts(
                states,
                [suggestion],
                exclude_node_ids=used_boost_node_ids,
                max_boosts=4,
            )
            scenario, simulated_states = self.role_gap_analyzer.simulate_with_boosts(
                score_map=score_map,
                target_role_id=target_role_id,
                boosts=boosts,
                title=self._build_step_title(step_index, suggestion),
                base_score=target_state.score,
            )
            if scenario is None or scenario.delta_score < MIN_STEP_DELTA:
                continue

            unlock_nodes = self._collect_unlock_nodes(
                before_states=states,
                after_states=simulated_states,
                focus_node_id=suggestion.node_id,
                target_role_id=target_role_id,
            )
            blocked_by = self._collect_blocked_by(states, target_role_id, suggestion)
            rank = self._rank_candidate(
                suggestion=suggestion,
                scenario_delta=scenario.delta_score,
                unlock_count=len(unlock_nodes),
                blocked_count=len(blocked_by),
                focus_repeat=focus_counts[suggestion.node_id],
            )
            if best_candidate is None or rank > float(best_candidate["rank"]):
                best_candidate = {
                    "rank": rank,
                    "suggestion": suggestion,
                    "scenario": scenario,
                    "simulated_states": simulated_states,
                    "boosts": boosts,
                }

        return best_candidate

    def _rank_candidate(
        self,
        suggestion: GapSuggestion,
        scenario_delta: float,
        unlock_count: int,
        blocked_count: int,
        focus_repeat: int,
    ) -> float:
        relation_bonus = 0.8 if suggestion.relation == "requires" else 0.25
        return (
            scenario_delta * 4.0
            + relation_bonus
            + unlock_count * 0.06
            + blocked_count * 0.08
            - focus_repeat * 0.22
        )

    def _collect_blocked_by(
        self,
        states: dict[str, NodeState],
        target_role_id: str,
        suggestion: GapSuggestion,
    ) -> list[str]:
        blocked: list[str] = []
        target_missing = [str(item) for item in states[target_role_id].diagnostics.get("missing_requirements", [])]
        if suggestion.node_name in target_missing:
            blocked.append(suggestion.node_name)
        for item in target_missing:
            if item not in blocked:
                blocked.append(item)
            if len(blocked) >= 2:
                break
        if blocked:
            return blocked

        focus_missing = [str(item) for item in states[suggestion.node_id].diagnostics.get("missing_requirements", [])]
        return focus_missing[:2]

    def _collect_unlock_nodes(
        self,
        before_states: dict[str, NodeState],
        after_states: dict[str, NodeState],
        focus_node_id: str,
        target_role_id: str,
        limit: int = 3,
    ) -> list[str]:
        ranked: list[tuple[float, int, str]] = []
        for node_id, node in self.graph.nodes.items():
            if node.layer == "evidence" or node_id in {focus_node_id, target_role_id}:
                continue
            delta = round(after_states[node_id].score - before_states[node_id].score, 4)
            if delta < 0.035:
                continue
            ranked.append((delta, LAYER_PRIORITY.get(node.layer, 0), node.name))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def _build_step_title(self, step_index: int, suggestion: GapSuggestion) -> str:
        prefix = "先补" if suggestion.relation == "requires" and step_index == 1 else "补强"
        return f"第 {step_index} 步：{prefix} {suggestion.node_name}"

    def _build_step_summary(
        self,
        target_role_id: str,
        suggestion: GapSuggestion,
        scenario: SimulationScenario,
        blocked_by: list[str],
        unlock_nodes: list[str],
    ) -> str:
        predicted_score = float(scenario.predicted_score)
        delta_score = float(scenario.delta_score)
        target_role_name = self.graph.nodes[target_role_id].name
        blocker_text = f"当前主要被 {'、'.join(blocked_by)} 卡住，" if blocked_by else ""
        unlock_text = f" 并带动 {'、'.join(unlock_nodes)}。" if unlock_nodes else "。"
        return (
            f"{blocker_text}优先围绕 {suggestion.node_name} 安排补齐动作，"
            f"预计可把 {target_role_name} 再抬高 {delta_score:.2f} 分，"
            f"达到 {predicted_score:.2f} 分{unlock_text}"
        )
