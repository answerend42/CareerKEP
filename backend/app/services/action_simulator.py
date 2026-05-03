"""行动模拟。"""

from __future__ import annotations

from typing import Any

from ..schemas import clamp01


def simulate_actions(base_evidence: dict[str, float], boost_plan: dict[str, float]) -> dict[str, Any]:
    """模拟补强若干证据后的输入变化。"""

    simulated = dict(base_evidence)
    for node_id, delta in boost_plan.items():
        simulated[node_id] = clamp01(simulated.get(node_id, 0.0) + delta)
    return {
        "base_evidence": base_evidence,
        "boost_plan": boost_plan,
        "simulated_evidence": simulated,
    }

