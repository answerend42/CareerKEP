"""目标岗位差距分析。"""

from __future__ import annotations

from typing import Any

from .graph_loader import GraphData
from .inference_engine import InferenceResult


def analyze_role_gap(graph: GraphData, result: InferenceResult, role_id: str) -> dict[str, Any]:
    """找出目标岗位主要缺口。"""

    if role_id not in result.states:
        raise KeyError(f"不存在的岗位节点: {role_id}")

    state = result.states[role_id]
    incoming = graph.incoming.get(role_id, [])
    ranked_requirements: list[dict[str, Any]] = []

    for edge in incoming:
        parent = result.states.get(edge.source)
        if parent is None:
            continue
        if edge.relation not in {"requires", "supports", "prefers", "evidences"}:
            continue
        gap = max(0.0, 0.6 - parent.score) if edge.relation == "requires" else max(0.0, 0.4 - parent.score)
        ranked_requirements.append(
            {
                "node_id": edge.source,
                "label": parent.label,
                "relation": edge.relation,
                "score": round(parent.score, 6),
                "gap": round(gap, 6),
            }
        )

    ranked_requirements.sort(key=lambda item: (item["gap"], item["score"]), reverse=True)
    return {
        "role_id": role_id,
        "label": state.label,
        "score": round(state.score, 6),
        "requirements": ranked_requirements[:5],
    }


def suggest_bridge_nodes(graph: GraphData, result: InferenceResult, top_k: int = 4) -> list[dict[str, Any]]:
    """从中间层找桥接建议。"""

    bridge_layers = {"ability", "composite", "direction"}
    candidates = [
        state
        for state in result.states.values()
        if state.layer in bridge_layers and state.score > 0.12
    ]
    candidates.sort(key=lambda item: item.score, reverse=True)

    return [
        {
            "node_id": item.node_id,
            "label": item.label,
            "layer": item.layer,
            "score": round(item.score, 6),
            "path": [item.label],
        }
        for item in candidates[:top_k]
    ]

