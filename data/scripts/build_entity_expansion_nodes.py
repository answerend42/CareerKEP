"""Build nodes.json-compatible file for the expanded 398-entity KG slice.

Entity set:
  - 365 nodes from `data/seeds/nodes.json`
  - 33 new candidates from `data/entity_expansion/entity_expansion_candidates.json`

Layers (five, same as runtime KG):
  evidence -> ability -> composite -> direction -> role

Output:
  - data/entity_expansion/entity_expansion_nodes.json
  - data/entity_expansion/entity_expansion_nodes.summary.json

Source/blame:
  - restored from sx commit 27867a8b6c42b367dc7da113262fb90d103744ab
    data/scripts/build_entity_expansion_nodes.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NODES = REPO_ROOT / "data" / "seeds" / "nodes.json"
DEFAULT_EXPANSION = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_candidates.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_nodes.json"

LAYER_ORDER = ("evidence", "ability", "composite", "direction", "role")

CATEGORY_TO_LAYER: dict[str, str] = {
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

CATEGORY_TO_NODE_TYPE: dict[str, str] = {
    "skill": "skill",
    "tool": "skill",
    "knowledge": "knowledge",
    "project": "project",
    "interest": "interest",
    "constraint": "constraint",
    "soft_skill": "soft_skill",
    "language": "language",
    "evidence": "skill",
    "ability": "ability_unit",
    "cap": "compound_capability",
    "dir": "career_direction",
    "role": "career_role",
}

LAYER_TO_AGGREGATOR: dict[str, str] = {
    "evidence": "source",
    "ability": "weighted_sum_capped",
    "composite": "soft_and",
    "direction": "penalty_gate",
    "role": "hard_gate",
}


def default_params(layer: str) -> dict[str, Any]:
    if layer == "evidence":
        return {}
    if layer == "ability":
        return {"cap": 1.0}
    if layer == "composite":
        return {"min_support_count": 2, "required_threshold": 0.06}
    if layer == "direction":
        return {"cap": 1.0, "required_threshold": 0.03, "penalty_floor": 0.45}
    if layer == "role":
        return {"cap": 1.0, "required_threshold": 0.025}
    return {}


def describe_node(label: str, category: str, layer: str) -> str:
    if layer == "evidence":
        templates = {
            "skill": f"{label} 编程技能。",
            "tool": f"{label} 工具或框架经验。",
            "knowledge": f"{label} 知识基础。",
            "project": f"{label} 项目经历。",
            "interest": f"{label} 兴趣偏好。",
            "constraint": f"{label} 约束或短板。",
            "soft_skill": f"{label} 软技能。",
            "language": f"{label} 语言能力。",
            "evidence": f"{label} 用户可输入证据。",
        }
        return templates.get(category, f"{label} 证据节点。")
    if layer == "ability":
        return f"{label} 基础能力单元。"
    if layer == "composite":
        return f"{label} 复合能力。"
    if layer == "direction":
        return f"{label} 岗位方向。"
    if layer == "role":
        return f"{label}，推荐岗位节点。"
    return f"{label}。"


def build_new_node(candidate: dict[str, Any]) -> dict[str, Any]:
    entity_id = candidate["proposed_id"]
    label = candidate.get("label") or entity_id
    category = candidate.get("category") or "evidence"
    layer = CATEGORY_TO_LAYER.get(category, "evidence")
    node_type = CATEGORY_TO_NODE_TYPE.get(category, "skill")

    metadata: dict[str, Any] = {
        "origin": "entity_expansion",
        "source_file": "entity_expansion_candidates.json",
        "category": category,
        "review_status": candidate.get("review_status"),
        "priority": candidate.get("priority"),
    }
    if candidate.get("aliases"):
        metadata["aliases"] = candidate["aliases"][:16]
    if candidate.get("source_records"):
        metadata["source_records"] = candidate["source_records"]

    return {
        "id": entity_id,
        "name": label,
        "layer": layer,
        "node_type": node_type,
        "aggregator": LAYER_TO_AGGREGATOR[layer],
        "description": describe_node(label, category, layer),
        "params": default_params(layer),
        "metadata": metadata,
    }


def build_nodes(nodes_path: Path, expansion_path: Path) -> list[dict[str, Any]]:
    existing_nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
    existing_ids = {node["id"] for node in existing_nodes}

    expansion = json.loads(expansion_path.read_text(encoding="utf-8"))
    new_nodes: list[dict[str, Any]] = []
    for candidate in expansion.get("new_entity_candidates", []):
        proposed_id = candidate["proposed_id"]
        if proposed_id in existing_ids:
            raise ValueError(f"duplicate node id in expansion candidates: {proposed_id}")
        new_nodes.append(build_new_node(candidate))

    new_nodes.sort(key=lambda node: (LAYER_ORDER.index(node["layer"]), node["id"]))
    return existing_nodes + new_nodes


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", default=str(DEFAULT_NODES))
    parser.add_argument("--expansion", default=str(DEFAULT_EXPANSION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes_path = Path(args.nodes)
    expansion_path = Path(args.expansion)
    output_path = Path(args.output)

    nodes = build_nodes(nodes_path, expansion_path)
    if len(nodes) != 398:
        raise SystemExit(f"expected 398 nodes, got {len(nodes)}")

    layer_counts = Counter(node["layer"] for node in nodes)
    node_type_counts = Counter(node["node_type"] for node in nodes)

    write_json(output_path, nodes)

    summary = {
        "schema": "career_kep.entity_expansion_nodes_build.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "node_count": len(nodes),
        "existing_nodes": 365,
        "new_nodes": 33,
        "output_path": str(output_path.relative_to(REPO_ROOT)),
        "layers": list(LAYER_ORDER),
        "by_layer": {layer: layer_counts[layer] for layer in LAYER_ORDER},
        "by_node_type": dict(sorted(node_type_counts.items())),
    }
    summary_path = output_path.with_suffix(".summary.json")
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
