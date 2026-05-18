from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..schemas import (
    ActionSimulationRequest,
    BridgeRecommendationItem,
    BridgeRolePreview,
    GapSuggestion,
    LearningPathStep,
    NearMissItem,
    RecommendationItem,
    RecommendationRequest,
    RoleGapRequest,
)
from ..services.action_simulator import ActionSimulator
from ..services.action_template_matcher import ActionTemplateMatcher
from ..services.explainer import GraphExplainer
from ..services.graph_loader import GraphLoader
from ..services.inference_engine import InferenceEngine, NodeState
from ..services.input_normalizer import InputNormalizer
from ..services.learning_path_planner import LearningPathPlanner
from ..services.nl_parser import LightweightNLParser
from ..services.role_gap_analyzer import RoleGapAnalyzer


MIN_RECOMMENDATION_SCORE = 0.05
MIN_NEAR_MISS_SCORE = 0.05
MIN_BRIDGE_SCORE = 0.03
MAX_NEAR_MISS_ITEMS = 4
MAX_BRIDGE_ITEMS = 4
CONSTRAINT_BRIDGE_FALLBACKS = {
    "constraint_weak_english": [
        {
            "anchor_id": "dir_quality_assurance",
            "related_role_ids": ["role_test_development_engineer", "role_qa_platform_engineer"],
            "next_step_ids": ["language_english_reading", "knowledge_technical_documentation", "project_test_automation"],
            "summary": "当前主要识别到英语约束，还没有足够技能证据直接下岗位结论。可先从测试开发这类资料路径更清晰的方向起步，同时补技术英语与文档阅读。",
        },
        {
            "anchor_id": "dir_data_analytics",
            "related_role_ids": ["role_data_analyst", "role_bi_engineer"],
            "next_step_ids": ["language_english_reading", "skill_sql", "project_dashboard"],
            "summary": "如果你现在最担心的是英语门槛，可以先沿数据分析方向建立 SQL 和报表基础，再逐步补英文文档阅读能力。",
        },
        {
            "anchor_id": "dir_web_backend",
            "related_role_ids": ["role_backend_engineer", "role_python_backend_engineer"],
            "next_step_ids": ["language_english_reading", "knowledge_technical_documentation", "project_backend_api"],
            "summary": "后端依然可以作为中期目标，但当前更像桥接路径。先补技术英语和文档阅读，再通过一个 API 项目建立可迁移的正向证据。",
        },
    ]
}
DEMO_CASE_METADATA = {
    "sample_request": {
        "title": "系统示例：后端入门画像",
        "summary": "适合第一屏演示推荐、节点确认和传播图。",
        "tags": ["系统示例", "后端", "推荐演示"],
    },
    "backend_bundle_nl": {
        "title": "后端成长画像",
        "summary": "用自然语言直接演示后端目标岗位分析与双动作组合模拟。",
        "tags": ["自然语言", "后端", "组合模拟"],
    },
    "data_engineer_structured": {
        "title": "数据工程画像",
        "summary": "适合展示结构化信号如何触发数据工程成长路径。",
        "tags": ["结构化输入", "数据工程", "规划链路"],
    },
    "frontend_structured": {
        "title": "前端画像",
        "summary": "适合展示前端方向的推荐、差距分析和动作模板匹配。",
        "tags": ["结构化输入", "前端", "动作模板"],
    },
    "qa_nl": {
        "title": "质量保障画像",
        "summary": "适合演示 QA / 测试开发方向的差距分析与补齐建议。",
        "tags": ["自然语言", "QA", "补齐建议"],
    },
    "appsec_structured": {
        "title": "应用安全画像",
        "summary": "适合展示安全方向的前置能力和专项行动模板。",
        "tags": ["结构化输入", "安全", "前置能力"],
    },
    "devops_nl": {
        "title": "DevOps 画像",
        "summary": "适合演示基础能力补齐后如何重新拉动 DevOps 目标岗位。",
        "tags": ["自然语言", "DevOps", "规划回放"],
    },
}


class RecommendationService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.loader = GraphLoader(base_dir=base_dir)
        self.graph = self.loader.load_graph()
        self.aliases = self.loader.load_aliases()
        self.preference_patterns = self.loader.load_preference_patterns()
        self.parsing_patterns = self.loader.load_parsing_patterns()
        self.action_templates = self.loader.load_action_templates()
        self.normalizer = InputNormalizer(self.graph, self.aliases)
        self.nl_parser = LightweightNLParser(self.graph, self.aliases, self.preference_patterns, self.parsing_patterns)
        self.engine = InferenceEngine()
        self.explainer = GraphExplainer()
        self.role_gap_analyzer = RoleGapAnalyzer(self.graph, self.engine, self.explainer)
        self.learning_path_planner = LearningPathPlanner(self.graph, self.role_gap_analyzer)
        self.action_template_matcher = ActionTemplateMatcher(self.graph, self.action_templates)
        self.action_simulator = ActionSimulator(self.graph, self.engine, self.role_gap_analyzer)
        self.sample_request_path = self.loader.base_dir / "data" / "demo" / "sample_request.json"
        self.planning_benchmark_path = self.loader.base_dir / "data" / "demo" / "planning_benchmark.json"
        self.provenance_summary = self._build_provenance_summary()

    def recommend(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        request = RecommendationRequest.from_payload(payload)
        merged_signals, unresolved, parse_result, score_map, states = self._resolve_request_context(
            request.text,
            request.signals,
        )
        active_signal_ids = {item.node_id for item in merged_signals}
        ranked_roles = sorted(
            self.graph.role_ids,
            key=lambda node_id: (states[node_id].score, self.graph.nodes[node_id].name),
            reverse=True,
        )
        ranked_roles = [role_id for role_id in ranked_roles if states[role_id].score >= MIN_RECOMMENDATION_SCORE]
        selected_role_ids = ranked_roles[: request.top_k]

        recommendations: list[RecommendationItem] = []
        for role_id in selected_role_ids:
            recommendations.append(self._build_recommendation_item(states, role_id))

        near_miss_roles = self._build_near_miss_items(
            states,
            excluded_role_ids=set(selected_role_ids),
            limit=min(MAX_NEAR_MISS_ITEMS, max(2, request.top_k)),
        )
        bridge_recommendations = self._build_bridge_items(
            states,
            excluded_role_ids=set(selected_role_ids)
            | {item.job_id for item in near_miss_roles},
            active_signal_ids=active_signal_ids,
            limit=min(MAX_BRIDGE_ITEMS, max(2, request.top_k)),
        )

        return {
            "normalized_inputs": [item.as_dict() for item in merged_signals],
            "recommendations": [item.as_dict() for item in recommendations],
            "near_miss_roles": [item.as_dict() for item in near_miss_roles],
            "bridge_recommendations": [item.as_dict() for item in bridge_recommendations],
            "empty_result_reason": self._build_empty_result_reason(
                merged_signals=merged_signals,
                recommendations=recommendations,
                near_miss_roles=near_miss_roles,
                bridge_recommendations=bridge_recommendations,
            ),
            "propagation_snapshot": self._build_snapshot(states) if request.include_snapshot else None,
            "parsing_notes": parse_result.notes[:30],
            "parsing_debug": parse_result.debug,
            "unresolved_entities": unresolved,
            "graph_stats": {
                "node_count": len(self.graph.nodes),
                "edge_count": len(self.graph.edges),
                "activated_node_count": sum(1 for state in states.values() if state.score >= 0.05),
                **self.provenance_summary,
            },
        }

    def role_gap(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        request = RoleGapRequest.from_payload(payload)
        if not request.target_role_id:
            raise ValueError("target_role_id is required")
        if request.target_role_id not in self.graph.role_ids:
            raise ValueError(f"unknown target role: {request.target_role_id}")

        merged_signals, unresolved, parse_result, score_map, states = self._resolve_request_context(
            request.text,
            request.signals,
        )
        analysis = self.role_gap_analyzer.analyze(
            states=states,
            score_map=score_map,
            target_role_id=request.target_role_id,
            source_payload=self._role_source_payload(request.target_role_id),
            scenario_limit=request.scenario_limit,
        )
        analysis.learning_path = self._build_learning_path(states, score_map, request.target_role_id)
        return {
            "target_role": analysis.as_dict(),
            "normalized_inputs": [item.as_dict() for item in merged_signals],
            "parsing_notes": parse_result.notes[:30],
            "parsing_debug": parse_result.debug,
            "unresolved_entities": unresolved,
        }

    def action_simulate(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        request = ActionSimulationRequest.from_payload(payload)
        if not request.target_role_id:
            raise ValueError("target_role_id is required")
        if request.target_role_id not in self.graph.role_ids:
            raise ValueError(f"unknown target role: {request.target_role_id}")
        if not request.action_keys and not request.template_ids:
            raise ValueError("action_keys or template_ids is required")

        merged_signals, unresolved, parse_result, score_map, states = self._resolve_request_context(
            request.text,
            request.signals,
        )
        learning_path = self._build_learning_path(states, score_map, request.target_role_id)
        simulation = self.action_simulator.simulate(
            states=states,
            score_map=score_map,
            target_role_id=request.target_role_id,
            learning_path=learning_path,
            action_keys=request.action_keys,
            template_ids=request.template_ids,
        )
        return {
            "simulation": simulation.as_dict(),
            "normalized_inputs": [item.as_dict() for item in merged_signals],
            "parsing_notes": parse_result.notes[:30],
            "parsing_debug": parse_result.debug,
            "unresolved_entities": unresolved,
        }

    def _build_recommendation_item(self, states: dict[str, NodeState], role_id: str) -> RecommendationItem:
        paths = self.explainer.top_paths(self.graph, states, role_id, limit=3)
        source_payload = self._role_source_payload(role_id)
        return RecommendationItem(
            job_id=role_id,
            job_name=self.graph.nodes[role_id].name,
            score=states[role_id].score,
            reason=self.explainer.summarize_reason(self.graph, states, role_id, paths),
            paths=paths,
            limitations=self.explainer.limitations(states, role_id),
            **source_payload,
        )

    def _build_near_miss_items(
        self,
        states: dict[str, NodeState],
        excluded_role_ids: set[str],
        limit: int,
    ) -> list[NearMissItem]:
        candidates: list[tuple[float, float, str]] = []
        for role_id in self.graph.role_ids:
            if role_id in excluded_role_ids:
                continue
            near_miss_score = self._estimate_near_miss_score(states[role_id])
            if near_miss_score < MIN_NEAR_MISS_SCORE:
                continue
            candidates.append((near_miss_score, states[role_id].score, role_id))

        selected: list[NearMissItem] = []
        for near_miss_score, _, role_id in sorted(
            candidates,
            key=lambda item: (item[0], item[1], self.graph.nodes[item[2]].name),
            reverse=True,
        )[:limit]:
            suggestions = self.role_gap_analyzer.build_gap_suggestions(states, role_id)
            paths = self.explainer.top_paths(self.graph, states, role_id, limit=2)
            source_payload = self._role_source_payload(role_id)
            selected.append(
                NearMissItem(
                    job_id=role_id,
                    job_name=self.graph.nodes[role_id].name,
                    near_miss_score=near_miss_score,
                    score=states[role_id].score,
                    gap_summary=self.explainer.summarize_gap(
                        self.graph,
                        states,
                        role_id,
                        paths,
                        [item.node_name for item in suggestions],
                    ),
                    paths=paths,
                    limitations=self.explainer.limitations(states, role_id),
                    missing_requirements=list(states[role_id].diagnostics.get("missing_requirements", [])),
                    suggestions=suggestions,
                    **source_payload,
                )
            )
        return selected

    def _estimate_near_miss_score(self, state: NodeState) -> float:
        diagnostics = state.diagnostics
        support_total = float(diagnostics.get("support_total", 0.0) or 0.0)
        require_total = float(diagnostics.get("require_total", 0.0) or 0.0)
        prefer_total = float(diagnostics.get("prefer_total", 0.0) or 0.0)
        inhibit_total = float(diagnostics.get("inhibit_total", 0.0) or 0.0)
        near_miss_score = max(
            state.score,
            support_total + require_total + prefer_total * 0.6 - inhibit_total * 0.25,
        )
        if diagnostics.get("missing_requirements"):
            near_miss_score += 0.015
        return round(max(0.0, min(1.0, near_miss_score)), 4)

    def _estimate_bridge_score(self, state: NodeState) -> float:
        bridge_score = self._latent_signal(state)
        if state.diagnostics.get("missing_requirements"):
            bridge_score += 0.01
        if state.diagnostics.get("hard_gate_closed"):
            bridge_score += 0.005
        return round(max(0.0, min(1.0, bridge_score)), 4)

    def _latent_signal(self, state: NodeState) -> float:
        diagnostics = state.diagnostics
        support_total = float(diagnostics.get("support_total", 0.0) or 0.0)
        require_total = float(diagnostics.get("require_total", 0.0) or 0.0)
        prefer_total = float(diagnostics.get("prefer_total", 0.0) or 0.0)
        inhibit_total = float(diagnostics.get("inhibit_total", 0.0) or 0.0)
        return max(
            state.score,
            support_total + require_total + prefer_total * 0.55 - inhibit_total * 0.2,
        )

    def _build_bridge_items(
        self,
        states: dict[str, NodeState],
        excluded_role_ids: set[str],
        active_signal_ids: set[str],
        limit: int,
    ) -> list[BridgeRecommendationItem]:
        candidates: list[tuple[float, float, str, str]] = []
        for node_id, node in self.graph.nodes.items():
            if node.layer not in {"role", "direction", "composite"}:
                continue
            if node.layer == "role" and node_id in excluded_role_ids:
                continue
            bridge_score = self._estimate_bridge_score(states[node_id])
            if bridge_score < MIN_BRIDGE_SCORE:
                continue
            candidates.append((bridge_score, states[node_id].score, node.layer, node_id))

        selected: list[BridgeRecommendationItem] = []
        seen_role_signatures: set[tuple[str, ...]] = set()
        for bridge_score, _, layer, node_id in sorted(
            candidates,
            key=lambda item: (
                item[1] >= MIN_BRIDGE_SCORE,
                item[1],
                item[0],
                item[2] == "role",
                self.graph.nodes[item[3]].name,
            ),
            reverse=True,
        ):
            suggestions = self._build_bridge_gap_suggestions(states, node_id)
            related_roles = self._bridge_related_roles(node_id, states)
            if layer != "role" and not related_roles:
                continue
            role_signature = tuple(role.job_id for role in related_roles[:2]) or (node_id,)
            if role_signature in seen_role_signatures:
                continue
            seen_role_signatures.add(role_signature)
            paths = self.explainer.top_paths(self.graph, states, node_id, limit=2)
            source_payload = self._node_source_payload(node_id)
            selected.append(
                BridgeRecommendationItem(
                    anchor_id=node_id,
                    anchor_name=self.graph.nodes[node_id].name,
                    anchor_type=layer,
                    bridge_score=bridge_score,
                    score=states[node_id].score,
                    summary=self._summarize_bridge(node_id, states, paths, suggestions, related_roles),
                    paths=paths,
                    limitations=self._node_limitations(states, node_id),
                    next_steps=suggestions,
                    related_roles=related_roles,
                    **source_payload,
                )
            )
            if len(selected) >= limit:
                break

        if selected:
            return selected
        return self._build_constraint_fallback_bridges(states, active_signal_ids, limit)

    def _build_bridge_gap_suggestions(
        self,
        states: dict[str, NodeState],
        node_id: str,
        limit: int = 3,
    ) -> list[GapSuggestion]:
        state = states[node_id]
        missing = set(str(name) for name in state.diagnostics.get("missing_requirements", []))
        grouped: dict[str, dict[str, Any]] = {}

        for contribution in state.parent_contributions:
            if contribution.relation not in {"requires", "supports", "evidences"}:
                continue
            entry = grouped.setdefault(
                contribution.parent_id,
                {
                    "node_id": contribution.parent_id,
                    "node_name": contribution.parent_name,
                    "current_score": states[contribution.parent_id].score,
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
            priority = item["requires_value"] * 2.2 + item["support_value"] * 1.15
            priority += max(0.0, 0.58 - current_score)
            if is_missing:
                priority += 0.6
            if priority < 0.22:
                continue
            relation = "requires" if item["has_requires"] else "supports"
            ranked.append(
                (
                    priority,
                    GapSuggestion(
                        node_id=str(item["node_id"]),
                        node_name=str(item["node_name"]),
                        relation=relation,
                        current_score=round(current_score, 4),
                        tip=self.role_gap_analyzer.build_gap_tip(
                            current_score=current_score,
                            is_missing=is_missing,
                            relation=relation,
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

    def _bridge_related_roles(
        self,
        node_id: str,
        states: dict[str, NodeState],
        limit: int = 3,
    ) -> list[BridgeRolePreview]:
        node = self.graph.nodes[node_id]
        if node.layer == "role":
            return [
                BridgeRolePreview(
                    job_id=node_id,
                    job_name=node.name,
                    score=states[node_id].score,
                )
            ]

        discovered: set[str] = set()
        queue: list[tuple[str, int]] = [(node_id, 0)]
        while queue:
            current_id, depth = queue.pop(0)
            for edge in self.graph.outgoing.get(current_id, []):
                target = edge.target
                target_node = self.graph.nodes[target]
                if target_node.layer == "role":
                    discovered.add(target)
                    continue
                if depth < 1 and target_node.layer in {"direction", "composite"}:
                    queue.append((target, depth + 1))

        return [
            BridgeRolePreview(
                job_id=role_id,
                job_name=self.graph.nodes[role_id].name,
                score=states[role_id].score,
            )
            for role_id in sorted(
                discovered,
                key=lambda item: (
                    self._latent_signal(states[item]),
                    states[item].score,
                    self.graph.nodes[item].name,
                ),
                reverse=True,
            )[:limit]
        ]

    def _summarize_bridge(
        self,
        node_id: str,
        states: dict[str, NodeState],
        paths: list[Any],
        suggestions: list[GapSuggestion],
        related_roles: list[BridgeRolePreview],
    ) -> str:
        node = self.graph.nodes[node_id]
        roots = list(dict.fromkeys(path.labels[0] for path in paths if path.labels))
        driver_text = "、".join(roots[:3]) if roots else "现有信号"
        next_step = suggestions[0].node_name if suggestions else "一组更明确的技能或项目证据"
        role_text = "、".join(role.job_name for role in related_roles[:2])

        if node.layer == "role":
            return f"{driver_text} 已经把你推到 {node.name} 的桥接区间，但还需要先补 {next_step}。"
        if related_roles:
            return f"{driver_text} 已形成 {node.name} 的入门信号，可先朝 {role_text} 靠近，优先补 {next_step}。"
        return f"{driver_text} 已形成 {node.name} 的桥接信号，优先补 {next_step} 后更容易进入正式推荐。"

    def _node_limitations(
        self,
        states: dict[str, NodeState],
        node_id: str,
    ) -> list[str]:
        state = states[node_id]
        messages: list[str] = []
        missing = state.diagnostics.get("missing_requirements", [])
        if missing:
            messages.append(f"当前关键短板: {'、'.join(missing[:3])}")
        inhibitions = [
            contribution.parent_name
            for contribution in state.parent_contributions
            if contribution.relation == "inhibits" and contribution.value >= 0.05
        ]
        if inhibitions:
            messages.append(f"当前抑制因素: {'、'.join(list(dict.fromkeys(inhibitions))[:3])}")
        if state.diagnostics.get("hard_gate_closed"):
            messages.append("当前仍未穿透正式岗位门槛。")
        return messages

    def _build_constraint_fallback_bridges(
        self,
        states: dict[str, NodeState],
        active_signal_ids: set[str],
        limit: int,
    ) -> list[BridgeRecommendationItem]:
        selected: list[BridgeRecommendationItem] = []
        for constraint_id, specs in CONSTRAINT_BRIDGE_FALLBACKS.items():
            if constraint_id not in active_signal_ids:
                continue
            for spec in specs:
                anchor_id = spec["anchor_id"]
                if anchor_id not in self.graph.nodes:
                    continue
                related_roles = [
                    BridgeRolePreview(
                        job_id=role_id,
                        job_name=self.graph.nodes[role_id].name,
                        score=states.get(role_id, NodeState(score=0.0, direct_input=0.0)).score if role_id in states else 0.0,
                    )
                    for role_id in spec.get("related_role_ids", [])
                    if role_id in self.graph.nodes
                ]
                selected.append(
                    BridgeRecommendationItem(
                        anchor_id=anchor_id,
                        anchor_name=self.graph.nodes[anchor_id].name,
                        anchor_type=self.graph.nodes[anchor_id].layer,
                        bridge_score=0.06,
                        score=states[anchor_id].score if anchor_id in states else 0.0,
                        summary=spec["summary"],
                        paths=[],
                        limitations=["当前只识别到约束信息，缺少技能或项目证据。"],
                        next_steps=self._fallback_step_suggestions(states, spec.get("next_step_ids", [])),
                        related_roles=related_roles[:3],
                        **self._node_source_payload(anchor_id),
                    )
                )
                if len(selected) >= limit:
                    return selected
        return selected[:limit]

    def _fallback_step_suggestions(
        self,
        states: dict[str, NodeState],
        node_ids: list[str],
    ) -> list[GapSuggestion]:
        suggestions: list[GapSuggestion] = []
        for node_id in node_ids:
            node = self.graph.nodes.get(node_id)
            if node is None:
                continue
            tip = "先补技术英语" if node.node_type == "language" else "优先补齐基础证据"
            suggestions.append(
                GapSuggestion(
                    node_id=node_id,
                    node_name=node.name,
                    relation="supports",
                    current_score=round(states.get(node_id, NodeState(score=0.0, direct_input=0.0)).score if node_id in states else 0.0, 4),
                    tip=tip,
                )
            )
        return suggestions

    def _build_empty_result_reason(
        self,
        merged_signals: list[Any],
        recommendations: list[RecommendationItem],
        near_miss_roles: list[NearMissItem],
        bridge_recommendations: list[BridgeRecommendationItem],
    ) -> str | None:
        if recommendations:
            return None
        if near_miss_roles or bridge_recommendations:
            return "当前输入还不足以形成正式岗位推荐，已降级展示 near miss / bridge 结果。"
        if not merged_signals:
            return "当前输入没有解析出稳定的图谱信号。"
        if all(self.graph.nodes[item.node_id].node_type == "constraint" for item in merged_signals if item.node_id in self.graph.nodes):
            return "当前只识别到约束，没有技能、项目或方向偏好证据。"
        return "当前信号过于稀疏，还没有穿透岗位门槛。"

    def _node_source_payload(self, node_id: str) -> dict[str, Any]:
        return {
            "provenance_count": int(self.graph.nodes[node_id].metadata.get("provenance_count", 0) or 0),
            "source_type_count": int(self.graph.nodes[node_id].metadata.get("source_type_count", 0) or 0),
            "source_types": [
                str(source_type)
                for source_type in self.graph.nodes[node_id].metadata.get("source_types", [])
                if str(source_type).strip()
            ],
            "source_refs": self._normalize_source_refs(self.graph.nodes[node_id].metadata.get("source_refs", [])),
        }

    def _role_source_payload(self, role_id: str) -> dict[str, Any]:
        return self._node_source_payload(role_id)

    def catalog(self) -> dict[str, Any]:
        evidence_nodes = [
            {
                "id": node_id,
                "name": node.name,
                "node_type": node.node_type,
                "description": node.description,
                "aliases": self.aliases.get(node_id, []),
            }
            for node_id, node in sorted(
                self.graph.nodes.items(),
                key=lambda item: (item[1].layer, item[1].node_type, item[1].name),
            )
            if node.layer == "evidence"
        ]
        role_nodes = [
            {
                "id": node_id,
                "name": node.name,
                "node_type": node.node_type,
                "description": node.description,
            }
            for node_id, node in sorted(
                self.graph.nodes.items(),
                key=lambda item: item[1].name,
            )
            if node.layer == "role"
        ]
        return {
            "evidence_nodes": evidence_nodes,
            "role_nodes": role_nodes,
            "graph_stats": {
                "node_count": len(self.graph.nodes),
                "edge_count": len(self.graph.edges),
                "evidence_node_count": len(self.graph.evidence_ids),
                "role_count": len(self.graph.role_ids),
                **self.provenance_summary,
            },
            "sample_request": self.sample_request(),
            "demo_cases": self.demo_cases(),
        }

    def sample_request(self) -> dict[str, Any]:
        return json.loads(self.sample_request_path.read_text(encoding="utf-8"))

    def demo_cases(self) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        sample_request = self.sample_request()
        cases.append(
            self._build_demo_case_payload(
                case_id="sample_request",
                text=str(sample_request.get("text", "") or ""),
                signals=sample_request.get("signals", []),
                target_role_id="role_backend_engineer",
                source="sample_request",
            )
        )

        if not self.planning_benchmark_path.exists():
            return cases

        for raw_case in json.loads(self.planning_benchmark_path.read_text(encoding="utf-8")):
            if not isinstance(raw_case, dict):
                continue
            target_role_id = str(raw_case.get("target_role_id", "") or "").strip()
            if not target_role_id or target_role_id not in self.graph.role_ids:
                continue
            cases.append(
                self._build_demo_case_payload(
                    case_id=str(raw_case.get("id", "") or "").strip() or target_role_id,
                    text=str(raw_case.get("text", "") or ""),
                    signals=raw_case.get("signals", []),
                    target_role_id=target_role_id,
                    source="planning_benchmark",
                )
            )
        return cases

    def _resolve_request_context(
        self,
        text: str,
        signals: list[Any],
    ) -> tuple[list[Any], list[str], Any, dict[str, float], dict[str, NodeState]]:
        structured_signals, unresolved = self.normalizer.normalize_signals(signals)
        parse_result = self.nl_parser.parse_detailed(text)
        merged_signals = self.normalizer.merge_signals(parse_result.signals, structured_signals)
        score_map = self.normalizer.to_score_map(merged_signals)
        states = self.engine.run(self.graph, score_map)
        return merged_signals, unresolved, parse_result, score_map, states

    def _build_learning_path(
        self,
        states: dict[str, NodeState],
        score_map: dict[str, float],
        target_role_id: str,
    ) -> list[LearningPathStep]:
        steps = self.learning_path_planner.plan(
            states=states,
            score_map=score_map,
            target_role_id=target_role_id,
        )
        return self.action_template_matcher.attach_actions(
            steps=steps,
            target_role_id=target_role_id,
        )

    def _build_provenance_summary(self) -> dict[str, Any]:
        unique_profiles: dict[str, dict[str, Any]] = {}
        nodes_with_provenance = 0
        latest_snapshot_date = ""

        for node in self.graph.nodes.values():
            refs = self._normalize_source_refs(node.metadata.get("source_refs", []))
            if refs:
                nodes_with_provenance += 1
            for ref in refs:
                profile_key = ref["profile_id"] or f"{ref['source_type']}::{ref['source_id']}"
                unique_profiles.setdefault(profile_key, ref)
                if ref["snapshot_date"] and ref["snapshot_date"] > latest_snapshot_date:
                    latest_snapshot_date = ref["snapshot_date"]

        source_profile_count_by_type: dict[str, int] = {}
        for ref in unique_profiles.values():
            if ref["source_type"]:
                source_profile_count_by_type[ref["source_type"]] = source_profile_count_by_type.get(ref["source_type"], 0) + 1

        return {
            "source_profile_count": len(unique_profiles),
            "nodes_with_provenance": nodes_with_provenance,
            "source_types": sorted(source_profile_count_by_type),
            "source_type_count": len(source_profile_count_by_type),
            "source_profile_count_by_type": {
                source_type: source_profile_count_by_type[source_type]
                for source_type in sorted(source_profile_count_by_type)
            },
            "latest_snapshot_date": latest_snapshot_date,
        }

    def _normalize_source_refs(self, raw_refs: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_refs, list):
            return []

        refs: list[dict[str, Any]] = []
        for ref in raw_refs:
            if not isinstance(ref, dict):
                continue
            sample_job_titles = ref.get("sample_job_titles", [])
            refs.append(
                {
                    "profile_id": str(ref.get("profile_id", "")),
                    "source_type": str(ref.get("source_type", "")),
                    "source_id": str(ref.get("source_id", "")),
                    "source_title": str(ref.get("source_title", "")),
                    "source_url": str(ref.get("source_url", "")),
                    "snapshot_date": str(ref.get("snapshot_date", "")),
                    "evidence_snippet": str(ref.get("evidence_snippet", "")),
                    "sample_job_titles": [
                        str(title)
                        for title in sample_job_titles
                        if str(title).strip()
                    ][:6],
                }
            )

        refs.sort(key=lambda item: (item["source_type"], item["source_title"], item["profile_id"]))
        return refs

    def _build_demo_case_payload(
        self,
        case_id: str,
        text: str,
        signals: Any,
        target_role_id: str,
        source: str,
    ) -> dict[str, Any]:
        normalized_signals: list[dict[str, Any]] = []
        if isinstance(signals, list):
            for signal in signals:
                if not isinstance(signal, dict):
                    continue
                entity = str(signal.get("entity", "") or "").strip()
                if not entity:
                    continue
                normalized_signals.append(
                    {
                        "entity": entity,
                        "score": float(signal.get("score", 0.7) or 0.7),
                    }
                )

        metadata = DEMO_CASE_METADATA.get(case_id, {})
        target_role_name = self.graph.nodes[target_role_id].name if target_role_id in self.graph.role_ids else target_role_id
        preview = text.strip()
        if not preview and normalized_signals:
            preview = "结构化信号：" + "、".join(
                f"{item['entity']} {item['score']:.2f}"
                for item in normalized_signals[:3]
            )
        if len(preview) > 88:
            preview = preview[:85].rstrip() + "..."

        return {
            "id": case_id,
            "title": metadata.get("title", target_role_name),
            "summary": metadata.get("summary", f"目标岗位：{target_role_name}"),
            "tags": metadata.get("tags", [source, target_role_name])[:4],
            "source": source,
            "text": text,
            "signals": normalized_signals,
            "signal_count": len(normalized_signals),
            "target_role_id": target_role_id,
            "target_role_name": target_role_name,
            "preview": preview,
        }

    def _serialize_node_metadata(self, node_id: str) -> dict[str, Any]:
        node = self.graph.nodes[node_id]
        metadata = dict(node.metadata)
        metadata["source_refs"] = self._normalize_source_refs(metadata.get("source_refs", []))
        metadata["provenance_count"] = int(metadata.get("provenance_count", len(metadata["source_refs"])) or 0)
        metadata["source_types"] = [
            str(source_type)
            for source_type in metadata.get("source_types", [])
            if str(source_type).strip()
        ]
        metadata["source_type_count"] = int(metadata.get("source_type_count", len(metadata["source_types"])) or 0)
        metadata["latest_snapshot_date"] = str(metadata.get("latest_snapshot_date", ""))
        return metadata

    def _build_snapshot(self, states: dict[str, Any]) -> dict[str, Any]:
        root_node_ids = {
            node_id
            for node_id, state in states.items()
            if state.direct_input > 0 and self.graph.nodes[node_id].layer == "evidence"
        }
        visible_node_ids = set(root_node_ids)
        for node_id in self.graph.topological_order:
            if node_id in visible_node_ids:
                continue
            state = states[node_id]
            if any(
                contribution.parent_id in visible_node_ids and contribution.value > 0
                for contribution in state.parent_contributions
            ):
                visible_node_ids.add(node_id)

        nodes = [
            {
                "id": node_id,
                "name": self.graph.nodes[node_id].name,
                "layer": self.graph.nodes[node_id].layer,
                "node_type": self.graph.nodes[node_id].node_type,
                "description": self.graph.nodes[node_id].description,
                "score": state.score,
                "aggregator": self.graph.nodes[node_id].aggregator,
                "metadata": self._serialize_node_metadata(node_id),
                "diagnostics": state.diagnostics,
            }
            for node_id, state in sorted(
                states.items(),
                key=lambda item: (item[1].score, item[0]),
                reverse=True,
            )
            if node_id in visible_node_ids
        ]

        edges = []
        for target_id, state in states.items():
            if target_id not in visible_node_ids:
                continue
            for contribution in state.parent_contributions:
                if contribution.parent_id not in visible_node_ids or contribution.value <= 0:
                    continue
                edges.append(
                    {
                        "source": contribution.parent_id,
                        "target": target_id,
                        "relation": contribution.relation,
                        "value": contribution.value,
                        "note": contribution.note,
                    }
                )
        edges.sort(key=lambda item: item["value"], reverse=True)
        return {"nodes": nodes, "edges": edges}


def recommend_from_payload(payload: dict[str, Any] | None, base_dir: Path | None = None) -> dict[str, Any]:
    service = RecommendationService(base_dir=base_dir)
    return service.recommend(payload)
