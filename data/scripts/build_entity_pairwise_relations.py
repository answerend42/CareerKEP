"""Build pairwise edges for the expanded 398-entity KG slice.

Entity set = 365 nodes from `data/seeds/nodes.json` + 33 accepted-new candidates
from `data/entity_expansion/entity_expansion_candidates.json`.

Relation types (four only):
  - support  (merges legacy supports / evidences)
  - requires
  - prefers
  - inhibits

Every unordered entity pair gets exactly one directed edge. Known semantics are
reused from `data/seeds/edges.json` when both endpoints exist; the rest use
layer/category heuristics aligned with the main KG.

Output (edges.json-compatible array):
  - data/entity_expansion/entity_expansion_pairwise_edges.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NODES = REPO_ROOT / "data" / "seeds" / "nodes.json"
DEFAULT_EXPANSION = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_candidates.json"
DEFAULT_SEED_EDGES = REPO_ROOT / "data" / "seeds" / "edges.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_pairwise_edges.json"

RELATION_ALIASES = {
    "supports": "support",
    "evidences": "support",
    "evidence": "support",
}

ALLOWED_RELATIONS = frozenset({"support", "requires", "prefers", "inhibits"})

DEFAULT_WEIGHTS = {
    "support": 0.2,
    "requires": 0.28,
    "prefers": 0.17,
    "inhibits": 0.3,
}

LAYER_RANK = {
    "evidence": 0,
    "ability": 1,
    "composite": 2,
    "direction": 3,
    "role": 4,
}

UPSTREAM_LAYERS = frozenset({"ability", "composite", "direction", "role"})


class EntityRecord:
    __slots__ = ("entity_id", "name", "layer", "category", "node_type")

    def __init__(
        self,
        entity_id: str,
        name: str,
        layer: str,
        category: str,
        node_type: str,
    ) -> None:
        self.entity_id = entity_id
        self.name = name
        self.layer = layer
        self.category = category
        self.node_type = node_type


def normalize_relation(relation: str) -> str:
    cleaned = (relation or "").strip().lower()
    return RELATION_ALIASES.get(cleaned, cleaned)


def pair_key(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def load_entities(nodes_path: Path, expansion_path: Path) -> dict[str, EntityRecord]:
    entities: dict[str, EntityRecord] = {}

    for node in json.loads(nodes_path.read_text(encoding="utf-8")):
        entity_id = node["id"]
        metadata = node.get("metadata") or {}
        entities[entity_id] = EntityRecord(
            entity_id=entity_id,
            name=node.get("name") or entity_id,
            layer=node.get("layer") or "evidence",
            category=metadata.get("category") or node.get("node_type") or "evidence",
            node_type=node.get("node_type") or "evidence",
        )

    expansion = json.loads(expansion_path.read_text(encoding="utf-8"))
    for row in expansion.get("new_entity_candidates", []):
        entity_id = row["proposed_id"]
        category = row.get("category") or "evidence"
        entities[entity_id] = EntityRecord(
            entity_id=entity_id,
            name=row.get("label") or entity_id,
            layer=_layer_for_new_category(category),
            category=category,
            node_type=category,
        )

    return entities


def _layer_for_new_category(category: str) -> str:
    mapping = {
        "ability": "ability",
        "cap": "composite",
        "dir": "direction",
        "role": "role",
        "constraint": "evidence",
        "interest": "evidence",
        "skill": "evidence",
        "tool": "evidence",
        "knowledge": "evidence",
        "project": "evidence",
        "soft_skill": "evidence",
        "language": "evidence",
        "evidence": "evidence",
    }
    return mapping.get(category, "evidence")


def load_seed_pair_edges(
    edges_path: Path,
    entity_ids: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    known: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in json.loads(edges_path.read_text(encoding="utf-8")):
        source = edge.get("source")
        target = edge.get("target")
        if source not in entity_ids or target not in entity_ids:
            continue
        relation = normalize_relation(edge.get("relation", ""))
        if relation not in ALLOWED_RELATIONS:
            continue
        key = pair_key(source, target)
        known[key] = edge
    return known


def infer_edge(left: EntityRecord, right: EntityRecord) -> tuple[str, str, str, str]:
    left_cat = left.category
    right_cat = right.category
    left_rank = LAYER_RANK.get(left.layer, 1)
    right_rank = LAYER_RANK.get(right.layer, 1)

    if left_cat == "constraint" and right_cat != "constraint":
        return left.entity_id, right.entity_id, "inhibits", "constraint_inhibits_positive"
    if right_cat == "constraint" and left_cat != "constraint":
        return right.entity_id, left.entity_id, "inhibits", "constraint_inhibits_positive"

    if left_cat == "interest" and right.layer in UPSTREAM_LAYERS:
        return left.entity_id, right.entity_id, "prefers", "interest_prefers_upstream"
    if right_cat == "interest" and left.layer in UPSTREAM_LAYERS:
        return right.entity_id, left.entity_id, "prefers", "interest_prefers_upstream"

    if left_cat == "knowledge" and right.layer in {"ability", "composite"}:
        return left.entity_id, right.entity_id, "requires", "knowledge_requires_upstream"
    if right_cat == "knowledge" and left.layer in {"ability", "composite"}:
        return right.entity_id, left.entity_id, "requires", "knowledge_requires_upstream"

    if left_rank < right_rank:
        return left.entity_id, right.entity_id, "support", "lower_layer_supports_higher"
    if right_rank < left_rank:
        return right.entity_id, left.entity_id, "support", "lower_layer_supports_higher"

    source, target = sorted((left.entity_id, right.entity_id))
    return source, target, "support", "same_layer_default_support"


def relation_note(relation: str, source_name: str, target_name: str) -> str:
    if relation == "support":
        return f"该节点正向支撑 {target_name}。"
    if relation == "requires":
        return f"{target_name} 依赖该关键前置。"
    if relation == "prefers":
        return f"该偏好会抬升 {target_name}。"
    if relation == "inhibits":
        return f"该约束会抑制 {target_name}。"
    return f"{source_name} -> {target_name}"


def seed_edge_to_output(edge: dict[str, Any]) -> dict[str, Any]:
    relation = normalize_relation(edge.get("relation", ""))
    metadata = dict(edge.get("metadata") or {})
    metadata["source_file"] = metadata.get("source_file") or "seeds/edges.json"
    metadata["relation_group"] = relation
    metadata["provenance"] = "seeds/edges.json"
    return {
        "source": edge["source"],
        "target": edge["target"],
        "relation": relation,
        "weight": edge.get("weight", DEFAULT_WEIGHTS[relation]),
        "note": edge.get("note") or relation_note(
            relation,
            edge["source"],
            edge["target"],
        ),
        "metadata": metadata,
    }


def heuristic_edge(
    source: str,
    target: str,
    relation: str,
    rule: str,
    entities: dict[str, EntityRecord],
) -> dict[str, Any]:
    source_name = entities[source].name
    target_name = entities[target].name
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "weight": DEFAULT_WEIGHTS[relation],
        "note": relation_note(relation, source_name, target_name),
        "metadata": {
            "source_file": "entity_expansion_pairwise_edges.json",
            "relation_group": relation,
            "provenance": "heuristic",
            "rule": rule,
        },
    }


def build_edges(
    entities: dict[str, EntityRecord],
    seed_pairs: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    entity_ids = sorted(entities)
    edges: list[dict[str, Any]] = []

    for left_id, right_id in combinations(entity_ids, 2):
        key = pair_key(left_id, right_id)
        if key in seed_pairs:
            edges.append(seed_edge_to_output(seed_pairs[key]))
            continue

        left = entities[left_id]
        right = entities[right_id]
        source, target, relation, rule = infer_edge(left, right)
        edges.append(heuristic_edge(source, target, relation, rule, entities))

    edges.sort(key=lambda row: (row["source"], row["target"]))
    return edges


def write_edges(path: Path, edges: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--expansion", default=str(DEFAULT_EXPANSION))
    parser.add_argument("--seed-edges", default=str(DEFAULT_SEED_EDGES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--summary-output",
        default="",
        help="Optional path for build summary JSON (counts only).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes_path = Path(args.nodes)
    expansion_path = Path(args.expansion)
    seed_edges_path = Path(args.seed_edges)
    output_path = Path(args.output)

    entities = load_entities(nodes_path, expansion_path)
    entity_ids = set(entities)
    if len(entities) != 398:
        raise SystemExit(f"expected 398 entities, got {len(entities)}")

    seed_pairs = load_seed_pair_edges(seed_edges_path, entity_ids)
    edges = build_edges(entities, seed_pairs)

    relation_counts = Counter(edge["relation"] for edge in edges)
    provenance_counts = Counter(
        "seed" if edge["metadata"].get("provenance") == "seeds/edges.json" else "heuristic"
        for edge in edges
    )

    write_edges(output_path, edges)

    summary = {
        "schema": "career_kep.entity_expansion_pairwise_edges_build.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entity_count": len(entities),
        "pairwise_edge_count": len(edges),
        "output_path": str(output_path.relative_to(REPO_ROOT)),
        "relation_types": sorted(ALLOWED_RELATIONS),
        "from_seed_edges": provenance_counts["seed"],
        "from_heuristics": provenance_counts["heuristic"],
        "by_relation": dict(sorted(relation_counts.items())),
    }

    summary_path = Path(args.summary_output) if args.summary_output else output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
