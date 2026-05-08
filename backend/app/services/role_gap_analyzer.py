"""目标岗位差距分析。"""

from __future__ import annotations

from typing import Any

from .graph_loader import GraphData
from .explainer import build_explanation
from .inference_engine import InferenceResult


def _relation_expectation(relation: str) -> float:
    """根据关系类型给出更合理的期望分值。

    这里不是硬规则，只是让分析结果更贴近业务直觉：
    - `requires` 要求最高；
    - `supports` / `prefers` 次之；
    - `evidences` 更偏向辅助信号。
    """

    if relation == "requires":
        return 0.6
    if relation == "supports":
        return 0.5
    if relation == "prefers":
        return 0.45
    return 0.4


def _readiness_level(score: float, coverage_score: float, missing_count: int) -> str:
    """根据岗位分数、覆盖度和缺口数量给出准备度分级。

    这里不追求复杂模型，只给前端一个更容易解释的状态标签：
    - ``ready``：基本已经接近目标岗位；
    - ``close``：还差几项关键能力；
    - ``building``：仍处于补基础阶段；
    - ``early``：缺口比较多，需要先拉齐基础。
    """

    if score >= 0.8 and coverage_score >= 0.85 and missing_count == 0:
        return "ready"
    if score >= 0.55 and coverage_score >= 0.7 and missing_count <= 1:
        return "close"
    if score >= 0.35 or coverage_score >= 0.5:
        return "building"
    return "early"


def _requirement_priority(gap: float, relation: str) -> str:
    """把单条缺口映射成展示优先级。"""

    if relation == "requires" or gap >= 0.3:
        return "high"
    if relation == "supports" or gap >= 0.15:
        return "medium"
    return "low"


def analyze_role_gap(graph: GraphData, result: InferenceResult, role_id: str) -> dict[str, Any]:
    """找出目标岗位主要缺口。"""

    if role_id not in result.states:
        raise KeyError(f"不存在的岗位节点: {role_id}")

    state = result.states[role_id]
    incoming = graph.incoming.get(role_id, [])
    ranked_requirements: list[dict[str, Any]] = []
    total_gap = 0.0
    covered_count = 0

    for edge in incoming:
        parent = result.states.get(edge.source)
        if parent is None:
            continue
        if edge.relation not in {"requires", "supports", "prefers", "evidences"}:
            continue
        expected = _relation_expectation(edge.relation)
        gap = max(0.0, expected - parent.score)
        if gap <= 0:
            covered_count += 1
        total_gap += gap
        ranked_requirements.append(
            {
                "node_id": edge.source,
                "label": parent.label,
                "relation": edge.relation,
                "score": round(parent.score, 6),
                "gap": round(gap, 6),
                "expected": round(expected, 6),
                "status": "covered" if gap <= 0 else "needs_work",
            }
        )

    ranked_requirements.sort(key=lambda item: (item["gap"], item["score"], item["expected"]), reverse=True)
    strengths = [
        {
            "node_id": item["node_id"],
            "label": item["label"],
            "relation": item["relation"],
            "score": item["score"],
            "expected": item["expected"],
        }
        for item in ranked_requirements
        if item["status"] == "covered"
    ][:3]
    missing_requirements = [item for item in ranked_requirements if item["status"] == "needs_work"]
    total_requirements = len(ranked_requirements)
    coverage_score = 1.0
    if total_requirements:
        coverage_score = max(0.0, 1.0 - (total_gap / total_requirements))
    readiness_level = _readiness_level(state.score, coverage_score, len(missing_requirements))
    top_missing_requirement = missing_requirements[0] if missing_requirements else None
    focus_message = "当前画像已经比较接近目标岗位，可以继续巩固优势项。"
    if readiness_level == "close":
        focus_message = "已经接近目标岗位，优先补齐最重要的 1-2 项缺口。"
    elif readiness_level == "building":
        focus_message = "还需要继续补齐关键能力，建议先从高缺口项开始。"
    elif readiness_level == "early":
        focus_message = "当前更适合先打基础，再逐步靠近目标岗位。"

    priority_groups: dict[str, list[dict[str, Any]]] = {"high": [], "medium": [], "low": []}
    for item in missing_requirements:
        priority = _requirement_priority(float(item["gap"]), str(item["relation"]))
        priority_groups[priority].append(
            {
                "node_id": item["node_id"],
                "label": item["label"],
                "relation": item["relation"],
                "gap": item["gap"],
                "expected": item["expected"],
                "priority": priority,
            }
        )
    for bucket in priority_groups.values():
        bucket.sort(key=lambda item: (-float(item["gap"]), str(item["label"]).casefold(), str(item["node_id"]).casefold()))
    priority_groups = {key: value[:3] for key, value in priority_groups.items() if value}

    path = build_explanation(graph, result, role_id)["path"]
    return {
        "role_id": role_id,
        "label": state.label,
        "score": round(state.score, 6),
        "path": path,
        "coverage_score": round(coverage_score, 6),
        "readiness_level": readiness_level,
        "focus_message": focus_message,
        "summary": f"已覆盖 {covered_count}/{total_requirements} 个关键前置条件",
        "requirements": ranked_requirements[:5],
        "strengths": strengths,
        "missing_requirements": missing_requirements[:5],
        "priority_groups": priority_groups,
        "top_missing_requirement": top_missing_requirement,
    }


def suggest_bridge_nodes(graph: GraphData, result: InferenceResult, top_k: int = 4) -> list[dict[str, Any]]:
    """从中间层找桥接建议。"""

    bridge_layers = {"ability", "composite", "direction"}
    candidates = [
        state
        for state in result.states.values()
        if state.layer in bridge_layers and state.score > 0.12
    ]
    candidates.sort(key=lambda item: (-item.score, item.label.casefold(), item.node_id.casefold()))

    return [
        {
            "node_id": item.node_id,
            "label": item.label,
            "layer": item.layer,
            "score": round(item.score, 6),
            "path": build_explanation(graph, result, item.node_id)["path"],
        }
        for item in candidates[:top_k]
    ]
