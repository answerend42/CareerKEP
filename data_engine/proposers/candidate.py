"""Candidate dataclass。

每个 proposer 输出一组 Candidate：声明类型、payload、证据、置信度，以及是否
满足"自动应用"条件。Applier 只看 auto_apply_eligible 字段决定走哪个通道。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class Candidate:
    kind: str                       # "alias" / "edge" / "node"
    payload: Dict[str, Any]         # 应用时实际写入的内容（schema 见各 proposer）
    evidence: List[Dict[str, Any]] = field(default_factory=list)  # 支持证据，供 review 展示
    confidence: float = 0.0
    auto_apply_eligible: bool = False
    source_proposer: str = ""       # 哪个 proposer 产出，用于审计
    reason: str = ""                # 简短说明（如"高置信无 collision"）

    def signature(self) -> str:
        """用于去重 + applied/rejected 黑白名单。"""

        if self.kind == "alias":
            return f"alias::{self.payload['entity_id']}::{self.payload['alias']}"
        if self.kind == "edge":
            return (
                f"edge::{self.payload['source']}::{self.payload['relation']}::"
                f"{self.payload['target']}"
            )
        if self.kind == "node":
            return f"node::{self.payload['id']}"
        raise ValueError(f"未知 candidate.kind: {self.kind!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
