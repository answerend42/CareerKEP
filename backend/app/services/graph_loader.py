from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUNTIME_RELATIONS = {"supports", "requires", "prefers", "inhibits"}
REVIEW_RELATIONS = RUNTIME_RELATIONS | {"related_to"}
RELATION_ALIASES = {
    "support": "supports",
    "supports": "supports",
    "evidence": "supports",
    "evidences": "supports",
    "requires": "requires",
    "prefers": "prefers",
    "inhibits": "inhibits",
    "related_to": "related_to",
    "related": "related_to",
}
LAYER_RANK = {"evidence": 0, "ability": 1, "composite": 2, "direction": 3, "role": 4}
LLM_DEFAULT_WEIGHTS = {
    "supports": 0.18,
    "requires": 0.26,
    "prefers": 0.14,
    "inhibits": 0.24,
}
PROVENANCE_TRUST = {
    "curated": 1.0,
    "promoted_runtime": 0.8,
    "llm_reviewed": 0.35,
    "llm_unreviewed": 0.15,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    id: str
    name: str
    layer: str
    node_type: str
    aggregator: str
    description: str
    params: dict
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EdgeDefinition:
    source: str
    target: str
    relation: str
    weight: float
    note: str
    metadata: dict[str, Any]
    scoring_policy: str = "positive_support"
    provenance: str = "curated"
    trust: float = 1.0
    eligible_for_gate: bool = True
    eligible_for_formal_score: bool = True
    channel: str = "core"


@dataclass(slots=True)
class GraphData:
    nodes: dict[str, NodeDefinition]
    edges: list[EdgeDefinition]
    incoming: dict[str, list[EdgeDefinition]]
    outgoing: dict[str, list[EdgeDefinition]]
    topological_order: list[str]
    aux_edges: list[EdgeDefinition] = field(default_factory=list)

    @property
    def role_ids(self) -> list[str]:
        return [node_id for node_id, node in self.nodes.items() if node.layer == "role"]

    @property
    def evidence_ids(self) -> list[str]:
        return [node_id for node_id, node in self.nodes.items() if node.layer == "evidence"]

    @property
    def all_edges(self) -> list[EdgeDefinition]:
        return [*self.edges, *self.aux_edges]


class GraphLoader:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or repo_root()
        self.graph_bundle_path = os.getenv("CAREER_KEP_GRAPH_BUNDLE")

    def _load_json(self, relative_path: str) -> object:
        path = self.base_dir / relative_path
        return json.loads(path.read_text(encoding="utf-8"))

    def load_graph(self) -> GraphData:
        if self.graph_bundle_path:
            raw_graph = self._load_graph_bundle(self.graph_bundle_path)
            raw_nodes = raw_graph["nodes"]
            raw_edges, raw_aux_edges = self._compile_runtime_edges(raw_graph["edges"], raw_nodes)
        else:
            raw_nodes = self._load_json("data/seeds/nodes.json")
            raw_edges, raw_aux_edges = self._compile_runtime_edges(self._load_json("data/seeds/edges.json"), raw_nodes)

        nodes = {
            item["id"]: NodeDefinition(
                id=item["id"],
                name=item["name"],
                layer=item["layer"],
                node_type=item["node_type"],
                aggregator=item["aggregator"],
                description=item["description"],
                params=item.get("params", {}),
                metadata=item.get("metadata", {}),
            )
            for item in raw_nodes
        }
        edges = [self._build_edge_definition(item) for item in raw_edges]
        aux_edges = [self._build_edge_definition(item) for item in raw_aux_edges]

        incoming: dict[str, list[EdgeDefinition]] = defaultdict(list)
        outgoing: dict[str, list[EdgeDefinition]] = defaultdict(list)
        indegree = {node_id: 0 for node_id in nodes}
        for edge in edges:
            if edge.source not in nodes or edge.target not in nodes:
                raise ValueError(f"invalid edge {edge.source}->{edge.target}")
            incoming[edge.target].append(edge)
            outgoing[edge.source].append(edge)
            indegree[edge.target] += 1

        queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
        topological_order: list[str] = []
        while queue:
            node_id = queue.popleft()
            topological_order.append(node_id)
            for edge in outgoing.get(node_id, []):
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    queue.append(edge.target)

        if len(topological_order) != len(nodes):
            raise ValueError("graph contains a cycle or disconnected indegree bookkeeping error")

        return GraphData(
            nodes=nodes,
            edges=edges,
            incoming=dict(incoming),
            outgoing=dict(outgoing),
            topological_order=topological_order,
            aux_edges=aux_edges,
        )

    def _build_edge_definition(self, item: dict[str, Any]) -> EdgeDefinition:
        return EdgeDefinition(
            source=item["source"],
            target=item["target"],
            relation=item["relation"],
            weight=float(item["weight"]),
            note=item["note"],
            metadata=item.get("metadata", {}),
            scoring_policy=item.get("scoring_policy", "positive_support"),
            provenance=item.get("provenance", "curated"),
            trust=float(item.get("trust", 1.0)),
            eligible_for_gate=bool(item.get("eligible_for_gate", True)),
            eligible_for_formal_score=bool(item.get("eligible_for_formal_score", True)),
            channel=item.get("channel", "core"),
        )

    def _load_graph_bundle(self, graph_bundle_path: str) -> dict[str, Any]:
        path = Path(graph_bundle_path)
        if not path.is_absolute():
            path = self.base_dir / path
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
            raise ValueError(f"invalid graph bundle: {path}")
        return payload

    def _compile_runtime_edges(
        self,
        raw_edges: list[dict[str, Any]],
        raw_nodes: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        raw_node_by_id = {node["id"]: node for node in raw_nodes}
        runtime_edges = []
        aux_edges = []
        for edge in raw_edges:
            normalized = self._normalize_runtime_edge(edge, raw_node_by_id)
            if normalized is None:
                continue
            if normalized.get("channel") in {"aux", "similarity"} and normalized.get("scoring_policy") == "similarity_only":
                aux_edges.append(normalized)
            elif normalized.get("channel") == "explain":
                aux_edges.append(normalized)
            else:
                runtime_edges.append(normalized)
        return runtime_edges, aux_edges

    def _normalize_runtime_edge(self, edge: dict[str, Any], raw_node_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        relation = RELATION_ALIASES.get(str(edge.get("relation") or "").strip().lower())
        if relation not in REVIEW_RELATIONS:
            return None

        source = edge["source"]
        target = edge["target"]
        status = edge.get("status")
        is_review_edge = status not in {None, "", "preserved_seed"}
        was_reversed = False
        channel = "core"
        scoring_policy = self._core_scoring_policy(relation, raw_node_by_id.get(target, {}))
        provenance = "curated"
        eligible_for_gate = relation == "requires"
        eligible_for_formal_score = True

        if is_review_edge:
            source_rank = LAYER_RANK.get(raw_node_by_id.get(source, {}).get("layer", ""))
            target_rank = LAYER_RANK.get(raw_node_by_id.get(target, {}).get("layer", ""))
            if source_rank is None or target_rank is None:
                return None
            if source_rank == target_rank:
                relation = "related_to"
                channel = "similarity"
                scoring_policy = "similarity_only"
                provenance = "llm_unreviewed"
                eligible_for_gate = False
                eligible_for_formal_score = False
            elif source_rank > target_rank:
                if relation != "requires":
                    relation = "related_to"
                    channel = "similarity"
                    scoring_policy = "similarity_only"
                    provenance = "llm_unreviewed"
                    eligible_for_gate = False
                    eligible_for_formal_score = False
                else:
                    was_reversed = True
                    channel = "aux"
                    scoring_policy = "soft_requirement"
                    provenance = "llm_unreviewed"
                    eligible_for_gate = False
                    eligible_for_formal_score = True
                    source, target = target, source
            else:
                channel = "aux"
                scoring_policy = self._llm_scoring_policy(relation)
                provenance = "llm_unreviewed"
                eligible_for_gate = False
                eligible_for_formal_score = relation != "inhibits"
                if relation == "inhibits":
                    channel = "explain"
                    scoring_policy = "explain_only"

        weight = edge.get("weight")
        if weight is None:
            confidence = float(edge.get("confidence") or 0.0)
            weight_relation = "supports" if relation == "related_to" else relation
            weight = round(LLM_DEFAULT_WEIGHTS[weight_relation] * max(0.5, min(1.0, confidence)), 4)

        metadata = dict(edge.get("metadata") or {})
        original_relation = str(edge.get("relation") or "").strip().lower()
        if original_relation and original_relation != relation:
            metadata.setdefault("original_relation", original_relation)
            metadata.setdefault("runtime_relation", relation)
        if is_review_edge:
            metadata.setdefault("runtime_weight_policy", "default_by_relation_times_confidence")
            metadata.setdefault("runtime_relation", relation)
            metadata.setdefault("channel", channel)
            metadata.setdefault("scoring_policy", scoring_policy)
            metadata.setdefault("eligible_for_gate", eligible_for_gate)
            metadata.setdefault("eligible_for_formal_score", eligible_for_formal_score)
            metadata.setdefault("provenance", provenance)
            if was_reversed:
                metadata.setdefault("converted_by_policy", "reverse_requires_to_layer_order")

        return {
            "source": source,
            "target": target,
            "relation": relation,
            "weight": weight,
            "note": edge.get("note") or "",
            "metadata": metadata,
            "scoring_policy": scoring_policy,
            "provenance": provenance,
            "trust": PROVENANCE_TRUST[provenance],
            "eligible_for_gate": eligible_for_gate,
            "eligible_for_formal_score": eligible_for_formal_score,
            "channel": channel,
        }

    def _core_scoring_policy(self, relation: str, target_node: dict[str, Any]) -> str:
        if relation == "requires":
            return "hard_requirement" if target_node.get("layer") == "role" else "soft_requirement"
        if relation == "prefers":
            return "preference_boost"
        if relation == "inhibits":
            return "negative_penalty"
        return "positive_support"

    def _llm_scoring_policy(self, relation: str) -> str:
        if relation == "requires":
            return "soft_requirement"
        if relation == "prefers":
            return "aux_preference"
        if relation == "inhibits":
            return "explain_only"
        return "soft_support"

    def load_aliases(self) -> dict[str, list[str]]:
        return self._load_json("data/dictionaries/skill_aliases.json")  # type: ignore[return-value]

    def load_preference_patterns(self) -> dict[str, list[str]]:
        return self._load_json("data/dictionaries/preference_patterns.json")  # type: ignore[return-value]

    def load_parsing_patterns(self) -> dict:
        return self._load_json("data/dictionaries/parsing_patterns.json")  # type: ignore[return-value]

    def load_action_templates(self) -> list[dict[str, Any]]:
        return self._load_json("data/demo/action_templates.json")  # type: ignore[return-value]
