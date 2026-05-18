from __future__ import annotations

from collections import defaultdict

from ..schemas import NormalizedSignal, SignalInput, clamp_score
from .graph_loader import GraphData


class InputNormalizer:
    def __init__(self, graph: GraphData, aliases: dict[str, list[str]]) -> None:
        self.graph = graph
        self.aliases = aliases
        self.alias_index = self._build_alias_index()

    def _build_alias_index(self) -> dict[str, str]:
        alias_index: dict[str, str] = {}
        for node_id, node in self.graph.nodes.items():
            alias_index[node_id.lower()] = node_id
            alias_index[node.name.lower()] = node_id
        for node_id, values in self.aliases.items():
            for value in values:
                alias_index[value.lower()] = node_id
        return alias_index

    def resolve_entity(self, entity: str) -> str | None:
        return self.alias_index.get(entity.strip().lower())

    def normalize_signals(self, signals: list[SignalInput]) -> tuple[list[NormalizedSignal], list[str]]:
        normalized: dict[str, NormalizedSignal] = {}
        unresolved: list[str] = []
        for signal in signals:
            if not signal.entity:
                continue
            node_id = self.resolve_entity(signal.entity)
            if not node_id:
                unresolved.append(signal.entity)
                continue
            node = self.graph.nodes[node_id]
            score = clamp_score(signal.score, default=0.7)
            current = normalized.get(node_id)
            if current is None or score > current.score:
                normalized[node_id] = NormalizedSignal(
                    node_id=node_id,
                    node_name=node.name,
                    score=score,
                    source="structured",
                )
        return sorted(normalized.values(), key=lambda item: (-item.score, item.node_id)), unresolved

    def merge_signals(
        self,
        parsed_signals: list[NormalizedSignal],
        structured_signals: list[NormalizedSignal],
    ) -> list[NormalizedSignal]:
        by_node: dict[str, NormalizedSignal] = {}
        for item in parsed_signals:
            by_node[item.node_id] = item
        for item in structured_signals:
            by_node[item.node_id] = item
        return sorted(by_node.values(), key=lambda item: (-item.score, item.node_id))

    @staticmethod
    def to_score_map(signals: list[NormalizedSignal]) -> dict[str, float]:
        score_map = defaultdict(float)
        for item in signals:
            score_map[item.node_id] = max(score_map[item.node_id], item.score)
        return dict(score_map)
