"""后端请求与响应的数据结构。

这里尽量保持纯 Python + dataclass，方便在没有额外依赖的情况下直接运行。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


def clamp01(value: float | None) -> float:
    """把分值夹到 0 到 1 之间。

    这里对 ``None`` 做兜底，避免外部请求缺字段时直接把整条推荐链路打断。
    """

    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


@dataclass
class EvidenceInput:
    """一条结构化画像证据。"""

    node_id: str
    score: float = 1.0
    source: str = "structured"
    raw_text: str | None = None

    def normalized(self) -> "EvidenceInput":
        self.score = clamp01(self.score)
        # 节点 ID 需要做一次空值兜底，避免把 "None" 这种脏值写进图谱证据。
        self.node_id = str(self.node_id or "").strip()
        self.source = str(self.source or "structured").strip() or "structured"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecommendationRequest:
    """推荐请求。"""

    text: str | None = None
    evidence: list[EvidenceInput] = field(default_factory=list)
    target_role: str | None = None
    top_k: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "evidence": [item.to_dict() for item in self.evidence],
            "target_role": self.target_role,
            "top_k": self.top_k,
        }


@dataclass
class NodeState:
    """图中节点在一次推理里的状态。"""

    node_id: str
    label: str
    layer: str
    score: float = 0.0
    direct_input: float = 0.0
    evidence: dict[str, float] = field(default_factory=dict)
    parent_contributions: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, float] = field(default_factory=dict)
    aggregator: str = "weighted_sum_capped"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = round(float(self.score), 6)
        data["direct_input"] = round(float(self.direct_input), 6)
        return data


@dataclass
class RecommendationItem:
    """排序后的推荐条目。"""

    node_id: str
    label: str
    layer: str
    score: float
    reasons: list[str] = field(default_factory=list)
    path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "layer": self.layer,
            "score": round(float(self.score), 6),
            "reasons": list(self.reasons),
            "path": list(self.path),
        }


@dataclass
class RecommendationResponse:
    """推荐接口的统一响应。"""

    input_trace: dict[str, Any] = field(default_factory=dict)
    recommendations: list[RecommendationItem] = field(default_factory=list)
    near_miss_roles: list[RecommendationItem] = field(default_factory=list)
    bridge_recommendations: list[RecommendationItem] = field(default_factory=list)
    target_role_analysis: dict[str, Any] = field(default_factory=dict)
    propagation_snapshot: list[dict[str, Any]] = field(default_factory=list)
    graph_snapshot: list[dict[str, Any]] = field(default_factory=list)
    raw_evidence: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_trace": self.input_trace,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "near_miss_roles": [item.to_dict() for item in self.near_miss_roles],
            "bridge_recommendations": [item.to_dict() for item in self.bridge_recommendations],
            "target_role_analysis": self.target_role_analysis,
            "propagation_snapshot": self.propagation_snapshot,
            "graph_snapshot": self.graph_snapshot,
            "raw_evidence": self.raw_evidence,
        }
