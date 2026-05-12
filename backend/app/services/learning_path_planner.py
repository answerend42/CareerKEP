"""成长路径规划。"""

from __future__ import annotations

from typing import Any


def _priority_from_gap(gap: float, relation: str) -> str:
    """根据缺口大小和关系类型给出优先级。

    这里用非常轻量的规则把“缺口分析”转成“行动顺序”，方便前端直接展示。
    """

    if relation == "requires" or gap >= 0.3:
        return "high"
    if relation == "supports" or gap >= 0.15:
        return "medium"
    return "low"


def _effort_from_priority(priority: str) -> str:
    """把优先级映射成大致执行成本。"""

    if priority == "high":
        return "1-2周"
    if priority == "medium":
        return "3-5天"
    return "1-2天"


def build_learning_path(gap_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """把岗位缺口转换成可执行行动。

    这里会按照缺口大小和关系类型，输出带优先级的学习计划，便于前端直接做
    “先补什么、为什么先补”的展示。
    """

    plan: list[dict[str, Any]] = []
    for rank, item in enumerate(gap_analysis.get("requirements", [])[:4], start=1):
        label = item["label"]
        relation = item["relation"]
        gap = float(item.get("gap", 0.0))
        priority = _priority_from_gap(gap, relation)
        effort = _effort_from_priority(priority)
        # 已覆盖的要求不再写成“补齐”，否则行动建议会和实际缺口状态打架。
        if gap <= 0:
            if relation == "requires":
                reason = "这是目标岗位的基础要求，当前已经满足，建议继续巩固。"
                action = f"继续巩固 {label}，保持这项关键能力稳定。"
            elif relation == "supports":
                reason = "这是关键支撑能力，当前已经覆盖，建议继续巩固。"
                action = f"继续巩固 {label}，让相关能力保持稳定输出。"
            elif relation == "prefers":
                reason = "这是加分项，当前已经具备，继续保持即可。"
                action = f"继续保持 {label}，维持对目标岗位的适配度。"
            else:
                reason = "这是辅助信号，当前已经补齐，后续继续维持即可。"
                action = f"继续维持 {label}，让能力画像保持完整。"
        elif relation == "requires":
            reason = "这是目标岗位的硬门槛，优先级最高。"
            action = f"优先补齐 {label}，因为这是目标岗位的关键前置条件。"
        elif relation == "supports":
            reason = "这是关键支撑能力，能明显抬高整体适配度。"
            action = f"强化 {label}，让相关能力更稳定。"
        elif relation == "prefers":
            reason = "这是加分项，适合在基础能力补齐后继续增强。"
            action = f"适度提升 {label}，扩大对目标岗位的适配度。"
        else:
            reason = "这是辅助信号，能帮助补强整体画像。"
            action = f"补充 {label}，让能力画像更完整。"
        plan.append(
            {
                "rank": rank,
                "target": label,
                "relation": relation,
                "gap": round(gap, 6),
                "priority": priority,
                "estimated_effort": effort,
                "why_now": reason,
                "action": action,
            }
        )
    return plan
