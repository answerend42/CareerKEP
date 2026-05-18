"""Proposer 协议与注册表。"""

from __future__ import annotations

from typing import Dict, List, Protocol

from ..config import DataEngineConfig
from .candidate import Candidate


class BaseProposer(Protocol):
    """所有 proposer 的协议。

    name: 短名（"aliases" / "edges_cooccurrence" / "edges_roadmap" / "nodes"）
    kinds: 可能产出的 candidate.kind 集合
    propose(config) -> List[Candidate]
    """

    name: str
    kinds: tuple[str, ...]

    def propose(self, config: DataEngineConfig) -> List[Candidate]:
        ...


_REGISTRY: Dict[str, BaseProposer] = {}


def register(proposer: BaseProposer) -> BaseProposer:
    if proposer.name in _REGISTRY:
        raise ValueError(f"重复注册 proposer: {proposer.name!r}")
    _REGISTRY[proposer.name] = proposer
    return proposer


def get_proposer(name: str) -> BaseProposer | None:
    return _REGISTRY.get(name)


def all_proposers() -> Dict[str, BaseProposer]:
    return dict(_REGISTRY)
