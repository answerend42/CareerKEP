"""推荐编排层。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..schemas import EvidenceInput, RecommendationItem, RecommendationRequest, RecommendationResponse
from ..services.action_simulator import simulate_actions
from ..services.explainer import build_explanation
from ..services.graph_loader import GraphData, load_graph_data
from ..services.inference_engine import infer
from ..services.input_normalizer import load_alias_map, merge_evidence_maps, normalize_alias_text, normalize_structured_input
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


def _normalize_identifier(value: str) -> str:
    """把输入字符串统一成便于匹配的形式。"""

    return normalize_alias_text(value)


def _state_sort_key(item: Any) -> tuple[float, str, str]:
    """给推荐结果排序用的稳定键。

    同分时按标签、再按节点 ID 排序，避免结果顺序受遍历顺序影响。
    """

    label = str(getattr(item, "label", "") or "").casefold()
    node_id = str(getattr(item, "node_id", "") or "").casefold()
    return (-float(getattr(item, "score", 0.0)), label, node_id)


def _resolve_target_role(graph: GraphData, alias_map: dict[str, list[str]], raw_target_role: str | None) -> str | None:
    """把目标岗位输入统一解析成图谱中的 role 节点 ID。

    这里同时支持三种输入方式：
    - 直接传节点 ID
    - 传中文/英文标签
    - 传词典别名

    这样前端既可以保留内部节点 ID，也可以直接让用户选中文岗位名。
    """

    if not raw_target_role:
        return None

    normalized_input = _normalize_identifier(raw_target_role)
    if not normalized_input:
        return None

    generic_terms = {
        "工程师",
        "开发",
        "岗位",
        "方向",
        "职业",
        "技术",
        "能力",
    }
    if normalized_input in generic_terms:
        return None

    exact_matches: list[tuple[str, str]] = []
    partial_matches: list[tuple[int, str, str]] = []

    def _consider(node_id: str, candidate: str, exact_score: str) -> None:
        candidate_norm = _normalize_identifier(candidate)
        if not candidate_norm:
            return
        if candidate_norm == normalized_input:
            exact_matches.append((exact_score, node_id))
            return
        if normalized_input in candidate_norm or candidate_norm in normalized_input:
            # 用长度差粗略区分“更像”的候选，短输入优先匹配更短的唯一目标。
            distance = abs(len(candidate_norm) - len(normalized_input))
            partial_matches.append((distance, candidate_norm, node_id))

    # 优先匹配节点 ID 和标签，避免别名误命中。
    for node_id, node in graph.nodes.items():
        if node.layer != "role":
            continue
        _consider(node_id, node_id, "id")
        _consider(node_id, node.label, "label")

    # 再匹配别名词典。
    for node_id, aliases in alias_map.items():
        node = graph.nodes.get(node_id)
        if node is None or node.layer != "role":
            continue
        for alias in aliases:
            _consider(node_id, alias, "alias")

    if exact_matches:
        # exact 匹配可能同时命中别名和标签，但都指向同一个节点时是安全的。
        matched_nodes = {node_id for _, node_id in exact_matches}
        if len(matched_nodes) == 1:
            return matched_nodes.pop()
        return None

    if not partial_matches:
        return None

    partial_matches.sort(key=lambda item: (item[0], item[1], item[2]))
    best_distance = partial_matches[0][0]
    best_candidates = [item for item in partial_matches if item[0] == best_distance]
    matched_nodes = {node_id for _, _, node_id in best_candidates}
    if len(matched_nodes) == 1:
        return matched_nodes.pop()
    return None


def _coerce_evidence_item(item: Any) -> EvidenceInput:
    """把单条证据对象归一成 `EvidenceInput`。

    这里故意只读取白名单字段，避免前端或脚本夹带额外元数据时触发构造异常。
    """

    if isinstance(item, EvidenceInput):
        return item
    if not isinstance(item, dict):
        # 列表里混入脏数据时直接跳过，保证推荐主链路还能继续跑。
        raise ValueError("证据列表中的元素不是有效的对象")

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


def _iter_evidence_payload(value: Any) -> list[Any]:
    """把 `evidence` 字段规范成可迭代列表。"""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    raise TypeError("evidence 必须是 list、dict 或 null")


def _build_request(payload: dict[str, Any]) -> RecommendationRequest:
    """把原始请求体转换成内部请求对象。"""

    evidence_payload = _iter_evidence_payload(payload.get("evidence"))
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
    explanation = build_explanation(graph, result, node_id)
    return RecommendationItem(
        node_id=node_id,
        label=state.label,
        layer=state.layer,
        score=state.score,
        reasons=reasons or [],
        path=explanation["path"],
        explanation=explanation,
    )


def _snapshot_roles(graph: GraphData, result, top_k: int = 10) -> list[dict[str, Any]]:
    role_states = [state for state in result.states.values() if state.layer == "role"]
    role_states.sort(key=_state_sort_key)
    return [build_explanation(graph, result, item.node_id) | {"layer": item.layer} for item in role_states[:top_k]]


def _build_result_summary(
    recommendations: list[RecommendationItem],
    near_miss_roles: list[RecommendationItem],
    bridge_recommendations: list[RecommendationItem],
    target_role_analysis: dict[str, Any],
    graph_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    """把本次推荐结果整理成给前端首页用的总览信息。"""

    top_recommendation = recommendations[0].to_dict() if recommendations else None
    top_bridge = bridge_recommendations[0].to_dict() if bridge_recommendations else None
    return {
        "recommendation_count": len(recommendations),
        "near_miss_count": len(near_miss_roles),
        "bridge_count": len(bridge_recommendations),
        "graph_snapshot_count": len(graph_snapshot),
        "has_target_role_analysis": bool(target_role_analysis),
        "resolved_target_role": target_role_analysis.get("resolved_target_role"),
        "readiness_level": target_role_analysis.get("readiness_level"),
        "top_recommendation": top_recommendation,
        "top_bridge": top_bridge,
    }


def recommend(payload: RecommendationRequest | dict[str, Any]) -> RecommendationResponse:
    """推荐主入口。"""

    if isinstance(payload, dict):
        request = _build_request(payload)
    else:
        request = payload
    top_k = _coerce_top_k(request.top_k)

    graph = _graph()
    alias_map = load_alias_map()
    resolved_target_role = _resolve_target_role(graph, alias_map, request.target_role)

    structured_evidence = normalize_structured_input(request.evidence)
    nl_evidence = parse_natural_language(request.text or "", alias_map) if request.text else {}
    evidence_map = merge_evidence_maps(structured_evidence, nl_evidence)
    result = infer(graph, evidence_map)
    input_trace = {
        "text": request.text,
        "target_role": request.target_role,
        "resolved_target_role": resolved_target_role,
        "top_k": top_k,
        # 这里把输入解析过程拆开返回，方便前端直接定位“为什么这个节点被命中”。
        "structured_evidence": [item.to_dict() for item in request.evidence],
        "structured_evidence_map": structured_evidence,
        "parsed_natural_language_evidence": nl_evidence,
        "merged_evidence": evidence_map,
    }

    role_states = [state for state in result.states.values() if state.layer == "role"]
    role_states.sort(key=_state_sort_key)

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
            bridge_explanation = build_explanation(graph, result, bridge["node_id"])
            bridge_recommendations.append(
                RecommendationItem(
                    node_id=bridge["node_id"],
                    label=bridge["label"],
                    layer=bridge["layer"],
                    score=bridge["score"],
                    reasons=["可作为成长桥接点"],
                    path=bridge["path"],
                    explanation=bridge_explanation | {"bridge_hint": bridge},
                )
            )

    target_role_analysis: dict[str, Any] = {}
    if resolved_target_role and resolved_target_role in result.states:
        target_role_analysis = analyze_role_gap(graph, result, resolved_target_role)
        target_role_analysis["matched_target_role"] = request.target_role
        target_role_analysis["resolved_target_role"] = resolved_target_role
        target_role_analysis["learning_path"] = build_learning_path(target_role_analysis)

    # 这里顺手准备一次轻量模拟，方便前端后续扩展“如果补强某项会怎样”。
    if resolved_target_role and resolved_target_role in result.states:
        gap_items = target_role_analysis.get("requirements", [])
        boost_plan = {item["node_id"]: min(0.2, max(0.05, item["gap"])) for item in gap_items[:3]}
        target_role_analysis["action_simulation"] = simulate_actions(evidence_map, boost_plan)

    graph_snapshot = _snapshot_roles(graph, result, top_k=8)
    result_summary = _build_result_summary(
        recommendations=recommendations[: top_k],
        near_miss_roles=near_miss_roles[: top_k],
        bridge_recommendations=bridge_recommendations[: top_k],
        target_role_analysis=target_role_analysis,
        graph_snapshot=graph_snapshot,
    )

    return RecommendationResponse(
        input_trace=input_trace,
        result_summary=result_summary,
        recommendations=recommendations[: top_k],
        near_miss_roles=near_miss_roles[: top_k],
        bridge_recommendations=bridge_recommendations[: top_k],
        target_role_analysis=target_role_analysis,
        propagation_snapshot=result.to_snapshot(top_k=12),
        graph_snapshot=graph_snapshot,
        raw_evidence=evidence_map,
    )
