"""推荐编排层。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..schemas import EvidenceInput, RecommendationItem, RecommendationRequest, RecommendationResponse
from ..services.action_simulator import simulate_actions
from ..services.explainer import build_explanation
from ..services.graph_loader import GraphData, load_graph_data
from ..services.inference_engine import infer
from ..services.input_normalizer import load_alias_map, merge_evidence_maps, normalize_structured_input
from ..services.learning_path_planner import build_learning_path
from ..services.nl_parser import parse_natural_language
from ..services.role_gap_analyzer import analyze_role_gap, suggest_bridge_nodes


@lru_cache(maxsize=1)
def _graph() -> GraphData:
    return load_graph_data()


def _coerce_top_k(value: Any, default: int = 5) -> int:
    """把前端传来的 `top_k` 尽量稳妥地转成整数。"""

    try:
        top_k = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, top_k)


def _coerce_evidence_item(item: Any) -> EvidenceInput:
    """把单条证据对象归一成 `EvidenceInput`。

    这里故意只读取白名单字段，避免前端或脚本夹带额外元数据时触发构造异常。
    """

    if isinstance(item, EvidenceInput):
        return item
    if not isinstance(item, dict):
        raise TypeError("证据列表中的元素必须是 dict 或 EvidenceInput")

    node_id = str(item.get("node_id") or item.get("id") or "").strip()
    if not node_id:
        # 空节点直接丢弃，和结构化归一阶段的行为保持一致。
        raise ValueError("证据项缺少有效的 node_id")

    return EvidenceInput(
        node_id=node_id,
        score=item.get("score", 1.0),
        source=item.get("source", "structured"),
        raw_text=item.get("raw_text"),
    )


def _build_request(payload: dict[str, Any]) -> RecommendationRequest:
    """把原始请求体转换成内部请求对象。"""

    evidence_payload = payload.get("evidence", [])
    evidence_items: list[EvidenceInput] = []
    for item in evidence_payload:
        try:
            evidence_items.append(_coerce_evidence_item(item))
        except ValueError:
            continue

    target_role = str(payload.get("target_role") or "").strip() or None
    text = payload.get("text")
    if text is not None:
        text = str(text)

    return RecommendationRequest(
        text=text,
        evidence=evidence_items,
        target_role=target_role,
        top_k=_coerce_top_k(payload.get("top_k"), default=5),
    )


def _build_recommendation_item(graph: GraphData, result, node_id: str, reasons: list[str] | None = None) -> RecommendationItem:
    state = result.states[node_id]
    path = build_explanation(graph, result, node_id)["path"]
    return RecommendationItem(
        node_id=node_id,
        label=state.label,
        layer=state.layer,
        score=state.score,
        reasons=reasons or [],
        path=path,
    )


def _snapshot_roles(graph: GraphData, result, top_k: int = 10) -> list[dict[str, Any]]:
    role_states = [state for state in result.states.values() if state.layer == "role"]
    role_states.sort(key=lambda item: item.score, reverse=True)
    return [build_explanation(graph, result, item.node_id) | {"layer": item.layer} for item in role_states[:top_k]]


def recommend(payload: RecommendationRequest | dict[str, Any]) -> RecommendationResponse:
    """推荐主入口。"""

    if isinstance(payload, dict):
        request = _build_request(payload)
    else:
        request = payload
    top_k = _coerce_top_k(request.top_k)

    graph = _graph()
    alias_map = load_alias_map()

    structured_evidence = normalize_structured_input(request.evidence)
    nl_evidence = parse_natural_language(request.text or "", alias_map) if request.text else {}
    evidence_map = merge_evidence_maps(structured_evidence, nl_evidence)
    result = infer(graph, evidence_map)

    role_states = [state for state in result.states.values() if state.layer == "role"]
    role_states.sort(key=lambda item: item.score, reverse=True)

    recommendations: list[RecommendationItem] = []
    near_miss_roles: list[RecommendationItem] = []
    for state in role_states:
        item = _build_recommendation_item(
            graph,
            result,
            state.node_id,
            reasons=[f"综合分数 {state.score:.2f}", f"证据数 {len(state.evidence)}"],
        )
        if state.score >= 0.55:
            recommendations.append(item)
        elif state.score >= 0.18:
            near_miss_roles.append(item)

    bridge_recommendations: list[RecommendationItem] = []
    if len(recommendations) < max(1, min(2, top_k)):
        for bridge in suggest_bridge_nodes(graph, result, top_k=top_k):
            bridge_recommendations.append(
                RecommendationItem(
                    node_id=bridge["node_id"],
                    label=bridge["label"],
                    layer=bridge["layer"],
                    score=bridge["score"],
                    reasons=["可作为成长桥接点"],
                    path=bridge["path"],
                )
            )

    target_role_analysis: dict[str, Any] = {}
    if request.target_role and request.target_role in result.states:
        target_role_analysis = analyze_role_gap(graph, result, request.target_role)
        target_role_analysis["learning_path"] = build_learning_path(target_role_analysis)

    # 这里顺手准备一次轻量模拟，方便前端后续扩展“如果补强某项会怎样”。
    if request.target_role and request.target_role in result.states:
        gap_items = target_role_analysis.get("requirements", [])
        boost_plan = {item["node_id"]: min(0.2, max(0.05, item["gap"])) for item in gap_items[:3]}
        target_role_analysis["action_simulation"] = simulate_actions(evidence_map, boost_plan)

    return RecommendationResponse(
        recommendations=recommendations[: top_k],
        near_miss_roles=near_miss_roles[: top_k],
        bridge_recommendations=bridge_recommendations[: top_k],
        target_role_analysis=target_role_analysis,
        propagation_snapshot=result.to_snapshot(top_k=12),
        graph_snapshot=_snapshot_roles(graph, result, top_k=8),
        raw_evidence=evidence_map,
    )
