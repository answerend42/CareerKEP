"""Build minimally screened LLM edge candidates for the expanded KG.

Strategy:
- keep all existing seed edges as preserved graph skeleton
- do not send old-old pairs to the LLM
- only generate unordered pairs where at least one endpoint is among the 33
  newly added expansion nodes
- emit JSONL candidate pairs plus a stable batch manifest for DeepSeek review

Outputs:
- data/entity_expansion/llm_edge_candidates.input.jsonl
- data/entity_expansion/llm_edge_batches.json
- data/entity_expansion/llm_edge_candidates.summary.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPANDED_NODES = (
    REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_nodes.json"
)
DEFAULT_EXPANSION = (
    REPO_ROOT / "data" / "entity_expansion" / "entity_expansion_candidates.json"
)
DEFAULT_ALIAS_DICT = REPO_ROOT / "data" / "dictionaries" / "skill_aliases.json"
DEFAULT_SEED_EDGES = REPO_ROOT / "data" / "seeds" / "edges.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.input.jsonl"
)
DEFAULT_BATCH_OUTPUT = REPO_ROOT / "data" / "entity_expansion" / "llm_edge_batches.json"
DEFAULT_SUMMARY_OUTPUT = (
    REPO_ROOT / "data" / "entity_expansion" / "llm_edge_candidates.summary.json"
)
LAYER_ORDER = {"evidence": 0, "ability": 1, "composite": 2, "direction": 3, "role": 4}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_node(
    node: dict[str, Any], aliases: dict[str, list[str]]
) -> dict[str, Any]:
    metadata = node.get("metadata") or {}
    alias_values = aliases.get(node["id"], [])
    return {
        "id": node["id"],
        "name": node.get("name") or node["id"],
        "layer": node.get("layer") or "evidence",
        "node_type": node.get("node_type") or "unknown",
        "category": metadata.get("category") or node.get("node_type") or "unknown",
        "description": node.get("description") or "",
        "aggregator": node.get("aggregator") or "",
        "aliases": alias_values[:12],
        "metadata": metadata,
    }


def prompt_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": node["id"],
        "name": node["name"],
        "layer": node["layer"],
        "category": node["category"],
        "node_type": node["node_type"],
    }
    if node["description"]:
        payload["description"] = node["description"]
    if node["aliases"]:
        payload["aliases"] = node["aliases"]

    source_records = node["metadata"].get("source_records") or []
    if source_records:
        payload["source_records"] = source_records[:6]
    review_status = node["metadata"].get("review_status")
    if review_status:
        payload["review_status"] = review_status
    priority = node["metadata"].get("priority")
    if priority:
        payload["priority"] = priority
    origin = node["metadata"].get("origin")
    if origin:
        payload["origin"] = origin
    return payload


def batch_key_for_pair(
    left: dict[str, Any], right: dict[str, Any], new_node_ids: set[str]
) -> str:
    left_new = left["id"] in new_node_ids
    right_new = right["id"] in new_node_ids

    if left_new and right_new:
        left_layer = left["layer"]
        right_layer = right["layer"]
        ordered_layers = sorted(
            (left_layer, right_layer),
            key=lambda item: (LAYER_ORDER.get(item, 99), item),
        )
        return f"new_new::{ordered_layers[0]}__{ordered_layers[1]}"

    new_node = left if left_new else right
    other_node = right if left_new else left
    return f"new_existing::{new_node['layer']}__{other_node['layer']}"


def build_candidate_record(
    left: dict[str, Any],
    right: dict[str, Any],
    new_node_ids: set[str],
) -> dict[str, Any]:
    pair_scope = (
        "new_new"
        if left["id"] in new_node_ids and right["id"] in new_node_ids
        else "new_existing"
    )
    pair_id = f"{left['id']}__{right['id']}"
    return {
        "pair_id": pair_id,
        "pair_key": [left["id"], right["id"]],
        "candidate_rule": "minimal_new_node_screen",
        "candidate_scope": pair_scope,
        "batch_key": batch_key_for_pair(left, right, new_node_ids),
        "new_endpoint_ids": sorted(
            node_id for node_id in (left["id"], right["id"]) if node_id in new_node_ids
        ),
        "node_a": prompt_node_payload(left),
        "node_b": prompt_node_payload(right),
    }


def build_candidates(
    expanded_nodes_path: Path,
    expansion_path: Path,
    alias_path: Path,
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    expanded_nodes = load_json(expanded_nodes_path)
    expansion = load_json(expansion_path)
    alias_values = load_json(alias_path)

    if not isinstance(expanded_nodes, list):
        raise ValueError("expanded nodes file must be a list")

    new_candidates = expansion.get("new_entity_candidates", [])
    new_node_ids = {row["proposed_id"] for row in new_candidates}
    if len(new_node_ids) != 33:
        raise ValueError(f"expected 33 new nodes, got {len(new_node_ids)}")

    nodes = [normalize_node(node, alias_values) for node in expanded_nodes]
    nodes_by_id = {node["id"]: node for node in nodes}
    if len(nodes_by_id) != 398:
        raise ValueError(f"expected 398 expanded nodes, got {len(nodes_by_id)}")

    missing_new_nodes = sorted(new_node_ids - set(nodes_by_id))
    if missing_new_nodes:
        raise ValueError(
            f"new node ids missing from expanded nodes: {missing_new_nodes}"
        )

    ordered_ids = sorted(nodes_by_id)
    candidates: list[dict[str, Any]] = []
    scope_counts = Counter()
    batch_key_counts = Counter()
    new_layer_counts = Counter(
        nodes_by_id[node_id]["layer"] for node_id in new_node_ids
    )

    for left_id, right_id in combinations(ordered_ids, 2):
        if left_id not in new_node_ids and right_id not in new_node_ids:
            continue
        left = nodes_by_id[left_id]
        right = nodes_by_id[right_id]
        candidate = build_candidate_record(left, right, new_node_ids)
        candidates.append(candidate)
        scope_counts[candidate["candidate_scope"]] += 1
        batch_key_counts[candidate["batch_key"]] += 1

    candidates.sort(key=lambda item: (item["batch_key"], item["pair_id"]))
    stats = {
        "expanded_node_count": len(nodes_by_id),
        "new_node_count": len(new_node_ids),
        "new_node_layers": dict(sorted(new_layer_counts.items())),
        "candidate_pair_count": len(candidates),
        "candidate_scope_counts": dict(sorted(scope_counts.items())),
        "candidate_batch_key_counts": dict(sorted(batch_key_counts.items())),
    }
    return candidates, new_node_ids, stats


def build_batches(
    candidates: list[dict[str, Any]], batch_size: int
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["batch_key"]].append(candidate)

    batches: list[dict[str, Any]] = []
    next_line = 1
    batch_index = 1
    for batch_key in sorted(grouped):
        records = grouped[batch_key]
        for start in range(0, len(records), batch_size):
            chunk = records[start : start + batch_size]
            scope = chunk[0]["candidate_scope"] if chunk else "unknown"
            batches.append(
                {
                    "batch_id": f"batch_{batch_index:04d}",
                    "batch_key": batch_key,
                    "candidate_scope": scope,
                    "pair_count": len(chunk),
                    "line_start": next_line,
                    "line_end": next_line + len(chunk) - 1,
                    "pair_ids": [item["pair_id"] for item in chunk],
                }
            )
            next_line += len(chunk)
            batch_index += 1
    return batches


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expanded-nodes", default=str(DEFAULT_EXPANDED_NODES))
    parser.add_argument("--expansion", default=str(DEFAULT_EXPANSION))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIAS_DICT))
    parser.add_argument("--seed-edges", default=str(DEFAULT_SEED_EDGES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--batch-output", default=str(DEFAULT_BATCH_OUTPUT))
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT))
    parser.add_argument("--batch-size", type=int, default=40)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates, new_node_ids, stats = build_candidates(
        expanded_nodes_path=Path(args.expanded_nodes),
        expansion_path=Path(args.expansion),
        alias_path=Path(args.aliases),
    )
    batches = build_batches(candidates, batch_size=args.batch_size)
    preserved_seed_edges = load_json(Path(args.seed_edges))

    write_jsonl(Path(args.output), candidates)
    write_json(
        Path(args.batch_output),
        {
            "schema": "career_kep.llm_edge_batches.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "screening_strategy": "minimal_new_node_pairs_only",
            "model": "deepseek-v4-flash",
            "batch_size": args.batch_size,
            "candidate_input_path": str(Path(args.output).relative_to(REPO_ROOT)),
            "preserved_seed_edge_count": len(preserved_seed_edges),
            "candidate_pair_count": len(candidates),
            "new_node_count": len(new_node_ids),
            "batch_count": len(batches),
            "batches": batches,
        },
    )
    write_json(
        Path(args.summary_output),
        {
            "schema": "career_kep.llm_edge_candidates_build.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "screening_strategy": "minimal_new_node_pairs_only",
            "preserved_seed_edge_count": len(preserved_seed_edges),
            **stats,
            "batch_count": len(batches),
            "batch_size": args.batch_size,
            "output_path": str(Path(args.output).relative_to(REPO_ROOT)),
            "batch_output_path": str(Path(args.batch_output).relative_to(REPO_ROOT)),
        },
    )

    print(
        json.dumps(
            {
                "candidate_pair_count": len(candidates),
                "new_node_count": len(new_node_ids),
                "preserved_seed_edge_count": len(preserved_seed_edges),
                "batch_count": len(batches),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
