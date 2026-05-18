from __future__ import annotations

from typing import Any

from ..schemas import GapSuggestion, SimulatedBoost, SimulationScenario, TargetRoleAnalysis
from .explainer import GraphExplainer
from .graph_loader import GraphData
from .inference_engine import InferenceEngine, NodeState


TARGET_PARENT_SCORE = 0.58
REQUIRED_SIMULATION_TARGET = 0.68
SUPPORT_SIMULATION_TARGET = 0.55


class RoleGapAnalyzer:
    def __init__(
        self,
        graph: GraphData,
        engine: InferenceEngine,
        explainer: GraphExplainer,
    ) -> None:
        self.graph = graph
        self.engine = engine
        self.explainer = explainer

    def analyze(
        self,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
        source_payload: dict[str, Any],
        scenario_limit: int = 3,
    ) -> TargetRoleAnalysis:
        if target_role_id not in self.graph.role_ids:
            raise ValueError(f"unknown target role: {target_role_id}")

        paths = self.explainer.top_paths(self.graph, states, target_role_id, limit=3)
        suggestions = self.build_gap_suggestions(states, target_role_id, limit=max(3, scenario_limit))
        scenario_list = self.build_what_if_scenarios(
            states=states,
            score_map=score_map,
            target_role_id=target_role_id,
            suggestions=suggestions,
            limit=scenario_limit,
        )
        state = states[target_role_id]
        return TargetRoleAnalysis(
            job_id=target_role_id,
            job_name=self.graph.nodes[target_role_id].name,
            current_score=state.score,
            gap_summary=self.explainer.summarize_gap(
                self.graph,
                states,
                target_role_id,
                paths,
                [item.node_name for item in suggestions],
            ),
            paths=paths,
            limitations=self.explainer.limitations(states, target_role_id),
            missing_requirements=list(state.diagnostics.get("missing_requirements", [])),
            priority_suggestions=suggestions,
            what_if_scenarios=scenario_list,
            **source_payload,
        )

    def build_gap_suggestions(
        self,
        states: dict[str, NodeState],
        role_id: str,
        limit: int = 3,
    ) -> list[GapSuggestion]:
        state = states[role_id]
        missing = set(str(name) for name in state.diagnostics.get("missing_requirements", []))
        grouped: dict[str, dict[str, Any]] = {}

        for contribution in state.parent_contributions:
            if contribution.relation not in {"requires", "supports"}:
                continue
            entry = grouped.setdefault(
                contribution.parent_id,
                {
                    "node_id": contribution.parent_id,
                    "node_name": contribution.parent_name,
                    "current_score": contribution.parent_score,
                    "support_value": 0.0,
                    "requires_value": 0.0,
                    "has_requires": False,
                },
            )
            if contribution.relation == "requires":
                entry["has_requires"] = True
                entry["requires_value"] = max(entry["requires_value"], contribution.value)
            else:
                entry["support_value"] = max(entry["support_value"], contribution.value)

        ranked: list[tuple[float, GapSuggestion]] = []
        for item in grouped.values():
            is_missing = item["node_name"] in missing
            current_score = float(item["current_score"] or 0.0)
            if current_score >= 0.72 and not is_missing:
                continue

            priority = item["requires_value"] * 2.2 + item["support_value"] * 1.3
            priority += max(0.0, TARGET_PARENT_SCORE - current_score)
            if is_missing:
                priority += 0.7
            if priority < 0.35:
                continue

            ranked.append(
                (
                    priority,
                    GapSuggestion(
                        node_id=str(item["node_id"]),
                        node_name=str(item["node_name"]),
                        relation="requires" if item["has_requires"] else "supports",
                        current_score=round(current_score, 4),
                        tip=self.build_gap_tip(
                            current_score=current_score,
                            is_missing=is_missing,
                            relation="requires" if item["has_requires"] else "supports",
                        ),
                    ),
                )
            )

        return [
            suggestion
            for _, suggestion in sorted(
                ranked,
                key=lambda item: (item[0], item[1].current_score, item[1].node_name),
                reverse=True,
            )[:limit]
        ]

    def build_what_if_scenarios(
        self,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
        suggestions: list[GapSuggestion],
        limit: int = 3,
    ) -> list[SimulationScenario]:
        if not suggestions:
            return []

        suggestion_pool = suggestions[: max(3, limit)]
        scenario_specs: list[tuple[str, list[GapSuggestion]]] = [
            (f"只补 {suggestion_pool[0].node_name}", suggestion_pool[:1]),
        ]
        if len(suggestion_pool) >= 2:
            scenario_specs.append(
                (
                    f"补强 {suggestion_pool[0].node_name} + {suggestion_pool[1].node_name}",
                    suggestion_pool[:2],
                )
            )
        if len(suggestion_pool) >= 3:
            scenario_specs.append(("集中补齐前三项", suggestion_pool[:3]))

        base_score = states[target_role_id].score
        scenarios: list[SimulationScenario] = []
        for title, boost_candidates in scenario_specs[:limit]:
            boosts = self.build_simulation_boosts(states, boost_candidates)
            scenario, _ = self.simulate_with_boosts(
                score_map=score_map,
                target_role_id=target_role_id,
                boosts=boosts,
                title=title,
                base_score=base_score,
            )
            if scenario is None:
                continue
            scenarios.append(scenario)

        scenarios.sort(key=lambda item: (item.delta_score, item.predicted_score, item.title), reverse=True)
        unique: list[SimulationScenario] = []
        seen_scores: set[tuple[float, float]] = set()
        for scenario in scenarios:
            key = (round(scenario.predicted_score, 3), round(scenario.delta_score, 3))
            if key in seen_scores:
                continue
            seen_scores.add(key)
            unique.append(scenario)
            if len(unique) >= limit:
                break
        return unique

    def build_simulation_boosts(
        self,
        states: dict[str, NodeState],
        suggestions: list[GapSuggestion],
        exclude_node_ids: set[str] | None = None,
        max_boosts: int = 4,
    ) -> list[SimulatedBoost]:
        exclude_node_ids = exclude_node_ids or set()
        boosts = self._build_boosts_for_suggestions(states, suggestions)
        filtered = [boost for boost in boosts if boost.node_id not in exclude_node_ids]
        return filtered[:max_boosts]

    def build_boosts_from_node_ids(
        self,
        states: dict[str, NodeState],
        node_ids: list[str],
        relation: str,
        tip: str,
        exclude_node_ids: set[str] | None = None,
        max_boosts: int = 4,
    ) -> list[SimulatedBoost]:
        exclude_node_ids = exclude_node_ids or set()
        boosts: list[SimulatedBoost] = []
        seen_node_ids = set(exclude_node_ids)

        for node_id in node_ids:
            if node_id in seen_node_ids or node_id not in self.graph.nodes:
                continue
            node = self.graph.nodes[node_id]
            if node.layer != "evidence":
                continue
            current_score = states[node_id].score
            target_score = self._simulation_target_score(current_score, relation)
            if target_score <= current_score + 0.01:
                continue

            boosts.append(
                SimulatedBoost(
                    node_id=node_id,
                    node_name=node.name,
                    from_score=round(current_score, 4),
                    to_score=round(target_score, 4),
                    tip=tip,
                )
            )
            seen_node_ids.add(node_id)
            if len(boosts) >= max_boosts:
                break

        return boosts

    def simulate_with_boosts(
        self,
        score_map: dict[str, float],
        target_role_id: str,
        boosts: list[SimulatedBoost],
        title: str,
        base_score: float,
    ) -> tuple[SimulationScenario | None, dict[str, NodeState]]:
        if not boosts:
            return None, self.engine.run(self.graph, score_map)

        simulated_scores = dict(score_map)
        for boost in boosts:
            simulated_scores[boost.node_id] = max(simulated_scores.get(boost.node_id, 0.0), boost.to_score)

        simulated_states = self.engine.run(self.graph, simulated_scores)
        predicted_score = simulated_states[target_role_id].score
        delta_score = round(predicted_score - base_score, 4)
        if delta_score <= 0:
            return None, simulated_states

        return (
            SimulationScenario(
                title=title,
                predicted_score=predicted_score,
                delta_score=delta_score,
                summary=self._build_scenario_summary(target_role_id, boosts, base_score, predicted_score),
                boosts=boosts,
            ),
            simulated_states,
        )

    def build_gap_tip(
        self,
        current_score: float,
        is_missing: bool,
        relation: str,
    ) -> str:
        if relation == "requires":
            if is_missing:
                if current_score <= 0.08:
                    return "补齐关键前置"
                return "继续补强关键前置"
            if current_score < 0.25:
                return "继续补强关键前置"
            return "继续巩固关键前置"
        if is_missing:
            if current_score <= 0.08:
                return "补齐关键前置"
            return "继续补强关键前置"
        if current_score < 0.25:
            return "补强核心支撑"
        return "继续巩固核心支撑"

    def _simulation_target_score(self, current_score: float, relation: str) -> float:
        baseline = REQUIRED_SIMULATION_TARGET if relation == "requires" else SUPPORT_SIMULATION_TARGET
        return round(min(1.0, max(baseline, current_score + 0.28)), 4)

    def _build_boosts_for_suggestions(
        self,
        states: dict[str, NodeState],
        suggestions: list[GapSuggestion],
    ) -> list[SimulatedBoost]:
        boosts: list[SimulatedBoost] = []
        seen_node_ids: set[str] = set()

        for suggestion in suggestions:
            candidates = self._select_boost_candidates(
                states,
                suggestion.node_id,
                suggestion.node_name,
                suggestion.relation,
                suggestion.tip,
            )
            if not candidates:
                candidates = [
                    {
                        "node_id": suggestion.node_id,
                        "node_name": suggestion.node_name,
                        "relation": suggestion.relation,
                        "tip": suggestion.tip,
                    }
                ]

            for candidate in candidates:
                if candidate["node_id"] in seen_node_ids:
                    continue
                current_score = states[candidate["node_id"]].score
                target_score = self._simulation_target_score(current_score, candidate["relation"])
                if target_score <= current_score + 0.01:
                    continue
                boosts.append(
                    SimulatedBoost(
                        node_id=str(candidate["node_id"]),
                        node_name=str(candidate["node_name"]),
                        from_score=round(current_score, 4),
                        to_score=round(target_score, 4),
                        tip=str(candidate["tip"]),
                    )
                )
                seen_node_ids.add(str(candidate["node_id"]))
                if len(boosts) >= 4:
                    return boosts

        return boosts

    def _select_boost_candidates(
        self,
        states: dict[str, NodeState],
        target_node_id: str,
        target_node_name: str,
        relation: str,
        tip: str,
    ) -> list[dict[str, Any]]:
        branch_limit = 3 if relation == "requires" else 2
        candidates = self._collect_evidence_candidates(states, target_node_id)
        if not candidates:
            return []

        ranked = sorted(
            candidates.values(),
            key=lambda item: (item["priority"], item["strength"], item["current_score"], item["node_name"]),
            reverse=True,
        )

        selected: list[dict[str, Any]] = []
        used_first_hops: set[str] = set()
        for item in ranked:
            if item["first_hop_id"] in used_first_hops:
                continue
            selected.append(
                {
                    "node_id": item["node_id"],
                    "node_name": item["node_name"],
                    "relation": relation,
                    "tip": f"{tip}（优先补 {target_node_name} 的证据项）",
                }
            )
            used_first_hops.add(item["first_hop_id"])
            if len(selected) >= branch_limit:
                return selected

        for item in ranked:
            if any(existing["node_id"] == item["node_id"] for existing in selected):
                continue
            selected.append(
                {
                    "node_id": item["node_id"],
                    "node_name": item["node_name"],
                    "relation": relation,
                    "tip": f"{tip}（优先补 {target_node_name} 的证据项）",
                }
            )
            if len(selected) >= branch_limit:
                break
        return selected

    def _collect_evidence_candidates(
        self,
        states: dict[str, NodeState],
        target_node_id: str,
        max_depth: int = 4,
    ) -> dict[str, dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for edge in self.graph.incoming.get(target_node_id, []):
            if edge.relation not in {"supports", "evidences", "requires"}:
                continue
            self._walk_positive_evidence(
                states=states,
                node_id=edge.source,
                first_hop_id=edge.source,
                strength=edge.weight,
                depth=1,
                max_depth=max_depth,
                out=candidates,
            )
        return candidates

    def _walk_positive_evidence(
        self,
        states: dict[str, NodeState],
        node_id: str,
        first_hop_id: str,
        strength: float,
        depth: int,
        max_depth: int,
        out: dict[str, dict[str, Any]],
    ) -> None:
        node = self.graph.nodes[node_id]
        if node.layer == "evidence":
            current_score = states[node_id].score
            priority = strength + max(0.0, 0.65 - current_score) * 0.35
            existing = out.get(node_id)
            if existing is None or priority > existing["priority"]:
                out[node_id] = {
                    "node_id": node_id,
                    "node_name": node.name,
                    "first_hop_id": first_hop_id,
                    "strength": round(strength, 4),
                    "current_score": round(current_score, 4),
                    "priority": round(priority, 4),
                }
            return

        if depth >= max_depth:
            return

        for edge in self.graph.incoming.get(node_id, []):
            if edge.relation not in {"supports", "evidences", "requires"}:
                continue
            self._walk_positive_evidence(
                states=states,
                node_id=edge.source,
                first_hop_id=first_hop_id,
                strength=strength * edge.weight,
                depth=depth + 1,
                max_depth=max_depth,
                out=out,
            )

    def _build_scenario_summary(
        self,
        target_role_id: str,
        boosts: list[SimulatedBoost],
        current_score: float,
        predicted_score: float,
    ) -> str:
        boosted_names = "、".join(item.node_name for item in boosts[:3])
        return (
            f"如果先把 {boosted_names} 补到中等偏上的水平，"
            f"{self.graph.nodes[target_role_id].name} 的预估分数会从 {round(current_score, 4):.2f} "
            f"提升到 {round(predicted_score, 4):.2f}。"
        )
