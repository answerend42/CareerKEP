"""节点包：自动加节点时必须的 node + edges + aliases 原子单元。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from data_engine.proposers.candidate import Candidate


def _candidate_cls():
    from data_engine.proposers.candidate import Candidate

    return Candidate


@dataclass
class NodePackage:
    """一次可事务落地的扩图单元（走 apply_batch）。"""

    package_id: str
    node: Candidate
    edges: List[Candidate] = field(default_factory=list)
    aliases: List[Candidate] = field(default_factory=list)
    auto_eligible: bool = False
    reject_reason: str = ""
    source_proposer: str = "nodes_auto"

    def signatures(self) -> List[str]:
        sigs = [self.node.signature()]
        sigs.extend(e.signature() for e in self.edges)
        sigs.extend(a.signature() for a in self.aliases)
        return sigs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "package_id": self.package_id,
            "auto_eligible": self.auto_eligible,
            "reject_reason": self.reject_reason,
            "source_proposer": self.source_proposer,
            "node": self.node.to_dict(),
            "edges": [e.to_dict() for e in self.edges],
            "aliases": [a.to_dict() for a in self.aliases],
        }

    @classmethod
    def from_dict(cls, item: Dict[str, Any]) -> NodePackage:
        Candidate = _candidate_cls()

        def _cand(raw: Dict[str, Any]) -> Candidate:
            return Candidate(
                kind=raw["kind"],
                payload=raw["payload"],
                evidence=raw.get("evidence", []),
                confidence=float(raw.get("confidence", 0.0)),
                auto_apply_eligible=bool(raw.get("auto_apply_eligible", False)),
                source_proposer=raw.get("source_proposer", ""),
                reason=raw.get("reason", ""),
            )

        return cls(
            package_id=str(item["package_id"]),
            node=_cand(item["node"]),
            edges=[_cand(e) for e in item.get("edges", [])],
            aliases=[_cand(a) for a in item.get("aliases", [])],
            auto_eligible=bool(item.get("auto_eligible", False)),
            reject_reason=str(item.get("reject_reason", "")),
            source_proposer=str(item.get("source_proposer", "nodes_auto")),
        )
