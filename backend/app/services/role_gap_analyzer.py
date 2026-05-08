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

    path = build_explanation(graph, result, role_id)["path"]
    return {
        "role_id": role_id,
        "label": state.label,
        "score": round(state.score, 6),
        "path": path,
        "coverage_score": round(coverage_score, 6),
        "summary": f"已覆盖 {covered_count}/{total_requirements} 个关键前置条件",
        "requirements": ranked_requirements[:5],
        "strengths": strengths,
        "missing_requirements": missing_requirements[:5],
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
