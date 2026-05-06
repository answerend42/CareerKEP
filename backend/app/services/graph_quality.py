"""运行时图谱质量检查。"""

from __future__ import annotations

from .graph_loader import GraphData, GraphValidationError


POSITIVE_RELATIONS = frozenset({"supports", "evidences", "requires", "prefers"})


def _positive_reachable_from(graph: GraphData, start_node_id: str) -> set[str]:
    reachable: set[str] = set()
    stack = [start_node_id]

    while stack:
        current = stack.pop()
        for edge in graph.outgoing.get(current, []):
            if edge.relation not in POSITIVE_RELATIONS:
                continue
            if edge.target in reachable:
                continue
            reachable.add(edge.target)
            stack.append(edge.target)
    return reachable


def validate_graph_quality(graph: GraphData) -> list[str]:
    """检查图谱是否足以支撑推荐解释。

    loader 负责“结构合法”，这里负责“推荐有用”：岗位要有正向入口，证据要能
    影响后续节点，负向证据只能通过 inhibits 表达惩罚。
    """

    errors: list[str] = []
    warnings: list[str] = []
    positive_reachability = {
        node_id: _positive_reachable_from(graph, node_id)
        for node_id, node in graph.nodes.items()
        if node.layer == "evidence"
    }

    for node_id, node in graph.nodes.items():
        if node.layer != "role":
            continue
        incoming = graph.incoming.get(node_id, [])
        if not any(edge.relation in {"requires", "supports"} for edge in incoming):
            errors.append(f"role {node_id!r}: 缺少 requires 或 supports 输入")
        if not any(node_id in reachable for reachable in positive_reachability.values()):
            errors.append(f"role {node_id!r}: 没有正向 evidence 路径可达")

    for node_id, node in graph.nodes.items():
        if node.layer != "evidence":
            continue
        outgoing = graph.outgoing.get(node_id, [])
        if not outgoing:
            errors.append(f"evidence {node_id!r}: 不能影响任何非 evidence 节点")
            continue
        if not any(graph.nodes[edge.target].layer != "evidence" for edge in outgoing):
            errors.append(f"evidence {node_id!r}: 不能影响任何非 evidence 节点")
        if node_id.startswith("weak_"):
            invalid_relations = sorted({edge.relation for edge in outgoing if edge.relation != "inhibits"})
            if invalid_relations:
                errors.append(f"negative evidence {node_id!r}: 只能通过 inhibits 产生影响，当前包含 {invalid_relations}")

    if errors:
        raise GraphValidationError("图谱质量校验失败:\n- " + "\n- ".join(errors))
    return warnings
