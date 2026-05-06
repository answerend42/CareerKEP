"""推荐结果解释。"""

from __future__ import annotations

from typing import Any

from .graph_loader import GraphData
from .inference_engine import InferenceResult


def build_role_path(graph: GraphData, result: InferenceResult, node_id: str, max_depth: int = 4) -> list[str]:
    """向上回溯一条最强路径。"""

    path = [node_id]
    current = node_id
    depth = 0
    while depth < max_depth:
        parents = graph.incoming.get(current, [])
        if not parents:
            break
        best_edge = None
        best_score = -1.0
        for edge in parents:
            parent_state = result.states.get(edge.source)
            if parent_state is None:
                continue
            candidate = parent_state.score * edge.weight
            if candidate > best_score:
                best_score = candidate
                best_edge = edge
        if best_edge is None or best_score <= 0:
            break
        path.append(best_edge.source)
        current = best_edge.source
        depth += 1
    return list(reversed(path))


def summarize_contributions(result: InferenceResult, node_id: str, top_k: int = 3) -> list[str]:
    """把节点的证据贡献整理成可读摘要。"""

    state = result.states[node_id]
    items = sorted(state.evidence.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [f"{root_id}:{value:.2f}" for root_id, value in items]


def build_explanation(graph: GraphData, result: InferenceResult, node_id: str) -> dict[str, Any]:
    """构造单个节点的解释信息。"""

    state = result.states[node_id]
    return {
        "node_id": node_id,
        "label": state.label,
        "score": round(state.score, 6),
        "path": build_role_path(graph, result, node_id),
        "evidence": summarize_contributions(result, node_id),
        "diagnostics": state.diagnostics,
    }

