"""成长路径规划。"""

from __future__ import annotations

from typing import Any


def build_learning_path(gap_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """把岗位缺口转换成可执行行动。"""

    plan: list[dict[str, Any]] = []
    for item in gap_analysis.get("requirements", [])[:4]:
        label = item["label"]
        relation = item["relation"]
        if relation == "requires":
            action = f"优先补齐 {label}，因为这是目标岗位的关键前置条件。"
        elif relation == "supports":
            action = f"强化 {label}，让相关能力更稳定。"
        else:
            action = f"适度提升 {label}，扩大对目标岗位的适配度。"
        plan.append(
            {
                "target": label,
                "relation": relation,
                "action": action,
            }
        )
    return plan

